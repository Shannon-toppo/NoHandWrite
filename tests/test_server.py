import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from nohandwrite.store import Store
    import server.main as main
    importlib.reload(main)
    monkeypatch.setattr(main, "store", Store(tmp_path))
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
    """Stands in for SDT: 竹 comes out clean, 鬱 truncated, 鹵 unsupported,
    and 龘 is supported but decodes to nothing."""

    available = True
    device = "cpu"

    def supports(self, char):
        return char != "鹵"

    def generate(self, style_strokes, chars, **kw):
        import numpy as np
        from nohandwrite.generate import Generated
        strokes = [np.array([[0.0, 0.0], [1000.0, 1000.0]])]
        return {
            "竹": Generated("竹", strokes, True, 0.9, 6, 6),
            "鬱": Generated("鬱", strokes, False, 0.8, 24, 29),
        }


@pytest.fixture()
def stub_generator(client, monkeypatch):
    import server.main as main
    monkeypatch.setattr(main, "generator", StubGenerator())
    client.post("/api/samples", json=sample_body(char="木"))   # style reference
    return client


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
