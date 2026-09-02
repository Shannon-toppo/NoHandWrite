import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from nohandwrite.rendercache import RenderCache
    from nohandwrite.store import Store
    import server.main as main
    importlib.reload(main)
    monkeypatch.setattr(main, "store", Store(tmp_path / "data"))
    monkeypatch.setattr(main, "render_cache", RenderCache(tmp_path / "cache"))
    return TestClient(main.app)


def sample_body(writer="taro", char="木"):
    return {
        "writer": writer, "char": char, "device": "test", "canvas": [450, 450],
        "strokes": [[{"x": 1, "y": 2, "t": 0, "p": 0.5}, {"x": 3, "y": 4, "t": 10, "p": 0.4}]],
    }


def test_prompts(client):
    sets = client.get("/api/prompts").json()
    assert "style" in sets and "hiragana" in sets and "alnum" in sets
    assert len(sets["hiragana"]["chars"]) == 71
    assert len(sets["alnum"]["chars"]) == 62
    assert len(sets["style_alnum"]["chars"]) == 87
    assert list(sets)[0] == "style_alnum"      # default set in the capture UI
    assert "、" in sets["symbols"]["chars"] and "「" in sets["symbols"]["chars"]
    assert len(sets["style"]["chars"]) == 25
    # extra style sets: 25 kanji each, no overlap across style 1–5
    style_keys = ["style", "style2", "style3", "style4", "style5"]
    for k in style_keys[1:]:
        assert len(sets[k]["chars"]) == 25
    all_style = "".join(sets[k]["chars"] for k in style_keys)
    assert len(set(all_style)) == len(all_style) == 125
    # extra sets come right after the basic style set, in order
    keys = list(sets)
    assert keys[keys.index("style"):keys.index("style") + 5] == style_keys


def test_typeset_layout(client):
    for _ in range(2):
        client.post("/api/samples", json=sample_body(char="木"))
    body = {
        "writer": "taro", "text": "木木\n木", "smooth": True, "jitter": 0,
        "char_size_mm": 10, "char_gap_mm": 2, "line_gap_mm": 5,
        "max_width_mm": 100, "margin_mm": 5,
    }
    r = client.post("/api/typeset", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["modes"]["木"] == "average"
    assert len(data["strokes"]) == 3           # one stroke per 木 sample here
    ys = [min(p[1] for p in s["points"]) for s in data["strokes"]]
    assert max(ys) >= min(ys) + 15             # second line is size+gap lower
    w, h = data["page"]
    assert w > 20 and h > 25


def test_typeset_line_guides(client):
    for _ in range(2):
        client.post("/api/samples", json=sample_body(char="木"))
    body = {
        "writer": "taro", "text": "木木\n木", "smooth": True, "jitter": 0,
        "char_size_mm": 10, "char_gap_mm": 2, "line_gap_mm": 5,
        "max_width_mm": 100, "margin_mm": 5,
    }
    data = client.post("/api/typeset", json=body).json()
    w, _ = data["page"]
    # two text lines -> two horizontal rules at the bottom of each 10mm cell
    assert data["guides"] == [[[5, 15], [round(w - 5, 2), 15]],
                              [[5, 30], [round(w - 5, 2), 30]]]

    data = client.post("/api/typeset", json={**body, "vertical": True}).json()
    _, h = data["page"]
    # vertical: one rule at the left edge of each of the two columns
    assert data["guides"] == [[[5, 5], [5, round(h - 5, 2)]],
                              [[20, 5], [20, round(h - 5, 2)]]]


def test_delete_character(client):
    for _ in range(2):
        client.post("/api/samples", json=sample_body(char="木"))
    client.post("/api/samples", json=sample_body(char="林"))
    r = client.delete("/api/writers/taro/chars/木")
    assert r.status_code == 200
    assert r.json() == {"char": "木", "deleted": True}
    assert client.get("/api/writers/taro/summary").json()["chars"] == {"林": 1}
    assert client.delete("/api/writers/taro/chars/木").status_code == 404
    assert client.delete("/api/writers/x!y/chars/木").status_code == 422


def test_typeset_repeated_chars_vary(client):
    for _ in range(2):
        client.post("/api/samples", json=sample_body(char="木"))
    body = {"writer": "taro", "text": "木木", "char_gap_mm": 0}
    data = client.post("/api/typeset", json=body).json()
    first, second = (s["points"] for s in data["strokes"][:2])
    # align the second occurrence back onto the first cell (15mm default step)
    shifted = [[x - 15, y] for x, y, *_ in second]
    assert shifted != [[x, y] for x, y, *_ in first]


def test_typeset_negative_char_gap(client):
    for _ in range(2):
        client.post("/api/samples", json=sample_body(char="木"))
    body = {"writer": "taro", "text": "木木", "jitter": 0, "char_gap_mm": -5,
            "proportional": False}
    r = client.post("/api/typeset", json=body)
    assert r.status_code == 200
    a, b = (s["points"] for s in r.json()["strokes"][:2])
    assert b[0][0] - a[0][0] == 10           # step = 15 (size) - 5 (gap)


def test_typeset_vertical(client):
    for _ in range(2):
        client.post("/api/samples", json=sample_body(char="木"))
    body = {"writer": "taro", "text": "木木", "jitter": 0, "char_gap_mm": 0,
            "proportional": False, "vertical": True}
    data = client.post("/api/typeset", json=body).json()
    a, b = (s["points"] for s in data["strokes"][:2])
    assert abs(b[0][0] - a[0][0]) < 1e-6           # same column
    assert b[0][1] - a[0][1] == 15                 # second char one cell below


def test_typeset_per_category_jitter(client):
    for char in ("木", "A"):
        for _ in range(2):
            client.post("/api/samples", json=sample_body(char=char))
    body = {"writer": "taro", "text": "木木AA", "char_gap_mm": 0,
            "proportional": False, "jitter": {"kanji": 1.0, "alnum": 0}}
    data = client.post("/api/typeset", json=body).json()
    by_char = {}
    for s in data["strokes"]:
        by_char.setdefault(s["char"], []).append(s["points"])
    kanji_a, kanji_b = by_char["木"]
    alnum_a, alnum_b = by_char["A"]
    step = 15  # default char_size_mm, gap 0
    assert ([[x - step, y] for x, y, *_ in kanji_b]
            != [[x, y] for x, y, *_ in kanji_a])                # kanji varies
    # alnum jitter 0 -> both A occurrences identical modulo layout offset
    shifted = [[round(x - step, 3), round(y, 3)] for x, y, *_ in alnum_b]
    assert shifted == [[round(x, 3), round(y, 3)] for x, y, *_ in alnum_a]


def test_export_gcode_custom_pen(client):
    client.post("/api/samples", json=sample_body(char="木"))
    body = {
        "writer": "taro", "text": "木", "format": "gcode",
        "pen_up_cmd": "M3 S40", "pen_down_cmd": "M3 S90",
        "feed_draw": 800, "flip_y": False,
    }
    r = client.post("/api/export", json=body)
    assert r.status_code == 200
    g = r.text
    assert "M3 S90" in g and "M3 S40" in g and "F800" in g


def test_export_pressure_options(client):
    client.post("/api/samples", json=sample_body(char="木"))   # p 0.5 / 0.4
    base = {"writer": "taro", "text": "木", "jitter": 0}
    g = client.post("/api/export", json={**base, "format": "gcode",
                                         "pressure_z": True,
                                         "z_light": 0.0, "z_heavy": -1.0}).text
    assert " Z-0." in g                       # modulated depth on draw moves
    assert "G1 Z0.0 F300" not in g
    svg = client.post("/api/export", json={**base, "format": "svg",
                                           "pressure_width": True}).text
    assert '<path' in svg and 'stroke-width="0.' in svg
    # per-path width attributes only appear in pressure mode
    plain = client.post("/api/export", json={**base, "format": "svg"}).text
    assert plain.count("stroke-width") == 1   # just the group default


def test_save_and_fetch(client):
    r = client.post("/api/samples", json=sample_body())
    assert r.status_code == 200
    assert r.json() == {"char": "木", "count": 1}
    r = client.post("/api/samples", json=sample_body())
    assert r.json()["count"] == 2

    r = client.get("/api/writers/taro/summary")
    assert r.json()["chars"] == {"木": 2}

    r = client.get("/api/writers/taro/chars/木")
    assert r.status_code == 200
    body = r.json()
    assert body["codepoint"] == "U+6728"
    assert len(body["samples"]) == 2

    r = client.post("/api/samples/undo", json={"writer": "taro", "char": "木"})
    assert r.json()["count"] == 1


class StubGenerator:
    """Stands in for SDT: 竹 comes out clean, 鬱 truncated, 鹵 and ： are
    unsupported, and 龘 is supported but decodes to nothing.

    `calls` records every batch it was asked for, which is how the cache
    tests see work being skipped.
    """

    available = True
    device = "cpu"
    UNSUPPORTED = "鹵："

    def __init__(self):
        self.calls = []

    def supports(self, char):
        return char not in self.UNSUPPORTED

    def generate(self, style_strokes, chars, **kw):
        import numpy as np
        from nohandwrite.generate import Generated
        self.calls.append(chars)
        strokes = [np.array([[0.0, 0.0], [1000.0, 1000.0]])]
        made = {
            "竹": Generated("竹", strokes, True, 0.9, 6, 6),
            "鬱": Generated("鬱", strokes, False, 0.8, 24, 29),
            "(": Generated("(", strokes, True, 0.9, 2, 2),
            ":": Generated(":", strokes, True, 0.9, 2, 2),
        }
        return {c: g for c, g in made.items() if c in chars}


@pytest.fixture()
def stub_generator(client, monkeypatch):
    import server.main as main
    monkeypatch.setattr(main, "generator", StubGenerator())
    client.post("/api/samples", json=sample_body(char="木"))   # style reference
    return client


def gen(client, text, **kw):
    """POST /api/generate with jitter off (so strokes compare equal)."""
    r = client.post("/api/generate", json={"writer": "taro", "text": text,
                                           "jitter": 0, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def stub(client):
    import server.main as main
    return main.generator


def test_generate_reports_each_failure_separately(stub_generator):
    r = stub_generator.post("/api/generate",
                            json={"writer": "taro", "text": "竹鬱鹵龘", "jitter": 0})
    assert r.status_code == 200
    by_char = {e["char"]: e for e in r.json()["chars"]}

    assert by_char["竹"]["mode"] == "generated"
    assert "reason" not in by_char["竹"]
    assert by_char["竹"]["quality"] == {"completed": True, "score": 0.9,
                                        "n_strokes": 6, "expected_strokes": 6}

    # truncated: still drawable, but flagged so the UI can warn
    assert by_char["鬱"]["mode"] == "generated_weak"
    assert by_char["鬱"]["reason_code"] == "truncated"
    assert by_char["鬱"]["strokes"]

    # "SDT has never heard of it" vs "SDT tried and produced nothing"
    assert by_char["鹵"]["mode"] == "unavailable"
    assert by_char["鹵"]["reason_code"] == "unsupported"
    assert by_char["龘"]["mode"] == "unavailable"
    assert by_char["龘"]["reason_code"] == "decode_failed"
    assert by_char["鹵"]["reason"] != by_char["龘"]["reason"]


def test_generate_model_missing_reason(client, monkeypatch):
    import server.main as main

    class Missing(StubGenerator):
        available = False

    monkeypatch.setattr(main, "generator", Missing())
    client.post("/api/samples", json=sample_body(char="木"))
    data = client.post("/api/generate", json={"writer": "taro", "text": "竹"}).json()
    entry = data["chars"][0]
    assert entry["mode"] == "unavailable" and entry["reason_code"] == "model_missing"


def test_typeset_marks_weak_generations(stub_generator):
    data = stub_generator.post("/api/typeset",
                               json={"writer": "taro", "text": "木竹鬱"}).json()
    assert data["modes"] == {"木": "smooth", "竹": "generated",
                             "鬱": "generated_weak"}


def test_validation(client):
    bad = sample_body(char="木木")
    assert client.post("/api/samples", json=bad).status_code == 422
    bad = sample_body(writer="../x")
    assert client.post("/api/samples", json=bad).status_code == 422
    assert client.get("/api/writers/taro/chars/未").status_code == 404


# --- rendering cache ------------------------------------------------------

def test_generation_is_cached_across_requests(stub_generator):
    """Editing a text must not re-generate the characters that did not
    change: only the new one reaches the model."""
    g = stub(stub_generator)
    first = gen(stub_generator, "竹")
    assert g.calls == ["竹"] and first["cache"] == {"hit": 0, "miss": 1}

    second = gen(stub_generator, "竹鬱")
    assert g.calls == ["竹", "鬱"]                  # 竹 came from the cache
    assert second["cache"] == {"hit": 1, "miss": 1}
    def strokes_of(data, char):
        return next(e["strokes"] for e in data["chars"] if e["char"] == char)
    assert strokes_of(second, "竹") == strokes_of(first, "竹")

    assert gen(stub_generator, "竹鬱")["cache"] == {"hit": 2, "miss": 0}
    assert g.calls == ["竹", "鬱"]


def test_beautified_characters_are_cached_until_rewritten(stub_generator):
    """A hand-written character is re-averaged only after its samples change."""
    assert gen(stub_generator, "木")["cache"] == {"hit": 0, "miss": 1}
    assert gen(stub_generator, "木")["cache"] == {"hit": 1, "miss": 0}
    stub_generator.post("/api/samples", json=sample_body(char="木"))
    assert gen(stub_generator, "木")["cache"] == {"hit": 0, "miss": 1}


def test_new_style_samples_invalidate_generated_characters(stub_generator):
    """SDT draws its style references from the writer's samples, so adding
    samples must not leave stale generated glyphs behind."""
    g = stub(stub_generator)
    gen(stub_generator, "竹")
    stub_generator.post("/api/samples", json=sample_body(char="木"))
    assert gen(stub_generator, "竹")["cache"] == {"hit": 0, "miss": 1}
    assert g.calls == ["竹", "竹"]


def test_refresh_bypasses_the_cache(stub_generator):
    """What the 再生成 button sends: draw this character again regardless."""
    g = stub(stub_generator)
    gen(stub_generator, "竹")
    assert gen(stub_generator, "竹", refresh=True)["cache"] == {"hit": 0, "miss": 1}
    assert g.calls == ["竹", "竹"]
    assert gen(stub_generator, "竹")["cache"] == {"hit": 1, "miss": 0}   # refilled


def test_smooth_flag_is_part_of_the_cache_key(stub_generator):
    gen(stub_generator, "竹", smooth=True)
    assert gen(stub_generator, "竹", smooth=False)["cache"] == {"hit": 0, "miss": 1}


def test_cache_clear_endpoint(stub_generator):
    gen(stub_generator, "竹")
    assert stub_generator.post("/api/cache/clear").json()["removed"] >= 1
    assert gen(stub_generator, "竹")["cache"] == {"hit": 0, "miss": 1}


# --- reporting characters that could not be drawn -------------------------

def test_typeset_reports_unrenderable_characters(stub_generator):
    data = stub_generator.post("/api/typeset", json={
        "writer": "taro", "text": "木竹鬱鹵", "width_fallback": False}).json()
    assert data["missing"] == ["鹵"]
    issues = {i["char"]: i for i in data["issues"]}
    assert set(issues) == {"鬱", "鹵"}              # 木 and 竹 came out fine
    assert issues["鹵"]["mode"] == "unavailable"
    assert issues["鹵"]["reason_code"] == "unsupported"
    assert issues["鬱"]["mode"] == "generated_weak"
    assert issues["鬱"]["reason"]                   # a sentence for the user
    assert data["issues"][0]["char"] == "鬱"        # reported in text order


def test_export_header_names_missing_characters(stub_generator):
    import urllib.parse
    r = stub_generator.post("/api/export", json={
        "writer": "taro", "text": "木鹵", "format": "gcode",
        "width_fallback": False})
    assert r.status_code == 200
    assert urllib.parse.unquote(r.headers["X-Missing-Chars"]) == "鹵"
    clean = stub_generator.post("/api/export", json={
        "writer": "taro", "text": "木", "format": "gcode"})
    assert clean.headers["X-Missing-Chars"] == ""


# --- full-width / half-width substitution ---------------------------------

def test_substitutes_the_width_the_writer_actually_wrote(stub_generator):
    """（ is on file, ( is not — draw the writer's own hand rather than let
    SDT invent a half-width one."""
    stub_generator.post("/api/samples", json=sample_body(char="（"))
    entry = gen(stub_generator, "(")["chars"][0]
    assert entry["char"] == "("                     # what the user typed
    assert entry["substitute"] == "（"               # what gets drawn
    assert entry["mode"] in ("smooth", "average")


def test_substitutes_a_generatable_width_when_neither_is_written(stub_generator):
    """： is outside the generation dictionary but : is inside it."""
    entry = gen(stub_generator, "：")["chars"][0]
    assert entry["substitute"] == ":" and entry["mode"] == "generated"


def test_no_substitution_when_the_character_itself_is_fine(stub_generator):
    stub_generator.post("/api/samples", json=sample_body(char="（"))
    assert "substitute" not in gen(stub_generator, "（")["chars"][0]
    assert "substitute" not in gen(stub_generator, "木")["chars"][0]


def test_width_fallback_can_be_switched_off(stub_generator):
    stub_generator.post("/api/samples", json=sample_body(char="（"))
    entry = gen(stub_generator, "(", width_fallback=False)["chars"][0]
    assert "substitute" not in entry and entry["mode"] == "generated"


def test_typeset_lays_out_the_substituted_glyph(stub_generator):
    stub_generator.post("/api/samples", json=sample_body(char="（"))
    data = stub_generator.post("/api/typeset", json={
        "writer": "taro", "text": "(", "jitter": 0}).json()
    assert data["substitutions"] == [{"char": "(", "substitute": "（"}]
    assert data["strokes"][0]["char"] == "（"       # placed as the full-width form
    assert not data["missing"]


# --- progress reporting ---------------------------------------------------

def test_progress_is_visible_while_a_render_runs(client, monkeypatch):
    """The UI polls this endpoint during the blocking POST, so the numbers
    have to be readable from another request while generation is happening."""
    import threading
    import server.main as main

    seen = []
    released = threading.Event()

    class SlowGenerator(StubGenerator):
        def generate(self, style_strokes, chars, on_progress=None, **kw):
            on_progress("generate", 1, len(chars))
            seen.append(client.get("/api/render/progress/job1").json())
            released.set()
            return super().generate(style_strokes, chars, **kw)

    monkeypatch.setattr(main, "generator", SlowGenerator())
    client.post("/api/samples", json=sample_body(char="木"))
    data = gen(client, "竹鬱", job="job1")

    assert released.is_set()
    mid = seen[0]
    assert mid["stage"] == "generate" and mid["total"] == 2 and mid["done"] == 1
    assert not mid["finished"]
    assert data["chars"]                            # and the render still ran

    after = client.get("/api/render/progress/job1").json()
    assert after["finished"] and after["stage"] == "done"


def test_progress_of_an_unknown_job_is_empty_not_an_error(client):
    """The browser starts polling before its POST has reached the server."""
    r = client.get("/api/render/progress/never-started")
    assert r.status_code == 200 and r.json()["stage"] is None


def test_a_render_without_a_job_id_reports_nothing(stub_generator):
    gen(stub_generator, "竹")                       # no job= -> null reporter
    assert stub_generator.get("/api/render/progress/job1").json()["stage"] is None
