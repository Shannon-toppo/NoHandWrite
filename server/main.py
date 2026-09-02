"""NoHandWrite API server: capture storage + static web UI.

Run:  uv run uvicorn server.main:app --host 0.0.0.0 --port 8765
Then open http://<this-machine>:8765/ (iPad: same LAN, Safari + Apple Pencil).
"""
from __future__ import annotations

import datetime
import hashlib
import logging
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import numpy as np

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nohandwrite.beautify import beautify
from nohandwrite.export import (
    GCodeOptions, LayoutOptions, layout_text, strokes_to_gcode, strokes_to_svg,
)
from nohandwrite.fourier import smooth_stroke
from nohandwrite.generate import SDTGenerator
from nohandwrite.rendercache import RenderCache
from nohandwrite.store import Store
from nohandwrite.variation import char_category, jitter_strokes
from nohandwrite.strokes import STANDARD_SIZE, Sample
from nohandwrite.widths import width_variant
from .plotter import PlotterError, list_serial_ports, plotter
from .progress import NULL_REPORTER, ProgressBoard, Reporter
from .prompts import PROMPT_SETS

ROOT = Path(__file__).resolve().parents[1]
store = Store(ROOT / "data")
#: Rendered characters, so editing one word in a page of text does not pay
#: for generating the whole page again (see nohandwrite.rendercache).
render_cache = RenderCache(ROOT / "data" / ".render-cache")
#: What each in-flight render is doing, for the UI to poll (see progress.py)
progress_board = ProgressBoard()

# uvicorn only configures its own loggers; this is what surfaces the
# generation-quality lines (truncation rate, retries) in the server log
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="NoHandWrite")


class StrokePointIn(BaseModel):
    x: float
    y: float
    t: float = 0.0
    p: float = 0.0


class SampleIn(BaseModel):
    writer: str
    char: str = Field(min_length=1, max_length=1)
    device: str = "unknown"
    canvas: list[float] = Field(min_length=2, max_length=2)
    strokes: list[list[StrokePointIn]] = Field(min_length=1)


@app.get("/api/prompts")
def get_prompts() -> dict:
    return {
        key: {"label": v["label"], "chars": v["chars"], "description": v["description"]}
        for key, v in PROMPT_SETS.items()
    }


@app.post("/api/samples")
def post_sample(body: SampleIn) -> dict:
    if any(len(s) == 0 for s in body.strokes):
        raise HTTPException(422, "empty stroke")
    sample = Sample(
        strokes=[np.array([[p.x, p.y, p.t, p.p] for p in s])
                 for s in body.strokes],
        canvas=(body.canvas[0], body.canvas[1]),
        device=body.device,
        recorded_at=datetime.datetime.now().isoformat(timespec="seconds"),
    )
    try:
        data = store.add_sample(body.writer, body.char, sample)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"char": data.char, "count": len(data.samples)}


class UndoIn(BaseModel):
    writer: str
    char: str = Field(min_length=1, max_length=1)


@app.post("/api/samples/undo")
def undo_sample(body: UndoIn) -> dict:
    data = store.delete_last_sample(body.writer, body.char)
    return {"char": body.char, "count": len(data.samples) if data else 0}


@app.get("/api/writers")
def get_writers() -> dict:
    return {"writers": store.list_writers()}


@app.get("/api/writers/{writer}/summary")
def get_summary(writer: str) -> dict:
    try:
        return {"writer": writer, "chars": store.summary(writer)}
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/writers/{writer}/chars/{char}")
def get_character(writer: str, char: str) -> dict:
    data = store.load_character(writer, char)
    if data is None:
        raise HTTPException(404, "no samples for this character")
    return data.to_json()


@app.delete("/api/writers/{writer}/chars/{char}")
def delete_character(writer: str, char: str) -> dict:
    try:
        deleted = store.delete_character(writer, char)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not deleted:
        raise HTTPException(404, "no samples for this character")
    return {"char": char, "deleted": True}


@app.get("/api/writers/{writer}/chars/{char}/beautify")
def get_beautified(writer: str, char: str) -> dict:
    data = store.load_character(writer, char)
    if data is None:
        raise HTTPException(404, "no samples for this character")
    try:
        # field-relative (place=False): the library overlays this on the raw
        # samples, which are drawn field-relative in the browser
        return beautify(data, place=False).to_json()
    except ValueError as e:
        raise HTTPException(422, str(e))


generator = SDTGenerator()


@app.get("/api/generate/status")
def generate_status() -> dict:
    return {"available": generator.available, "device": generator.device}


class JitterIn(BaseModel):
    """Per-script jitter strengths (0 = identical every time, 1 = standard)."""
    hiragana: float = Field(default=1.0, ge=0, le=3)
    katakana: float = Field(default=1.0, ge=0, le=3)
    kanji: float = Field(default=1.0, ge=0, le=3)
    alnum: float = Field(default=1.0, ge=0, le=3)
    other: float = Field(default=1.0, ge=0, le=3)

    def for_char(self, c: str) -> float:
        return getattr(self, char_category(c))

    @classmethod
    def resolve(cls, jitter: "float | JitterIn") -> "JitterIn":
        if isinstance(jitter, cls):
            return jitter
        return cls(**{k: jitter for k in cls.model_fields})


#: Either one strength for every character or per-script strengths.
JitterSpec = Annotated[float, Field(ge=0, le=3)] | JitterIn


class RenderIn(BaseModel):
    """Options shared by every endpoint that turns text into strokes."""
    writer: str
    smooth: bool = True
    jitter: JitterSpec = 1.0
    #: substitute the other-width form of a character (（ for (, ; for ；…)
    #: when that form is better supported — see `_width_substitutions`
    width_fallback: bool = True
    #: ignore cached renderings and draw every character again
    refresh: bool = False
    #: client-generated id to report progress under; None = report nothing
    job: str | None = Field(default=None, max_length=64)


class GenerateIn(RenderIn):
    text: str = Field(min_length=1, max_length=200)


#: mode -> user-facing explanation for characters that produced no usable
#: strokes, or usable-but-suspect ones. `mode` is what the UI branches on;
#: `reason` is what it shows.
FAIL_REASON = {
    "model_missing": "SDTモデル/データが見つかりません(third_party/SDT)",
    "unsupported": "生成辞書にない文字です(SDTが対応していません)",
    "decode_failed": "生成に失敗しました(ストロークが得られませんでした)。再生成するか自分で書いてください。",
    "truncated": "生成が途中で打ち切られました(画数の多い字)。再生成するか自分で書いてください。",
    "few_strokes": "画数が足りない可能性があります。再生成するか自分で書いてください。",
    "low_score": "お手本との一致度が低い字です。再生成するか自分で書いてください。",
}

#: How many of the writer's characters SDT gets as style references.
STYLE_REFS = 15


def _style_chars(summary: dict[str, int]) -> list[str]:
    """The characters handed to SDT as style references, most-written first."""
    return sorted(summary, key=summary.get, reverse=True)[:STYLE_REFS]


def _fingerprint(writer: str, chars: list[str]) -> str:
    """Short hash of the sample files behind `chars`.

    This is the part of a cache key that makes an entry expire: rewriting,
    undoing or deleting a sample changes the file stamp, which changes the
    key, and the old rendering is simply never asked for again.
    """
    h = hashlib.sha1()
    for c in sorted(chars):
        h.update(f"{c}:{store.char_stamp(writer, c)}\n".encode())
    return h.hexdigest()[:16]


def _fail_entry(code: str) -> dict:
    return {"mode": "unavailable", "reason_code": code, "reason": FAIL_REASON[code]}


def _beautified(writer: str, char: str, stats: dict | None = None,
                refresh: bool = False) -> dict:
    """Cached Fourier average of a character the writer has written."""
    key = f"b-u{ord(char):04x}-{_fingerprint(writer, [char])}"
    entry = None if refresh else render_cache.get(writer, key)
    if entry is None:
        r = beautify(store.load_character(writer, char))
        entry = {"mode": r.mode, "strokes": [s.round(2).tolist() for s in r.strokes]}
        render_cache.put(writer, key, entry)
        if stats is not None:
            stats["miss"] += 1
    elif stats is not None:
        stats["hit"] += 1
    return entry


def _generated_entry(char: str, g, smooth: bool) -> dict:
    """Result entry for one SDT attempt (`g` is None when nothing came back)."""
    if g is None:
        # tell "SDT has never heard of this character" apart from "SDT tried
        # and produced nothing usable" — the first needs a dictionary entry,
        # the second just needs another go
        return _fail_entry("unsupported" if not generator.supports(char)
                           else "decode_failed")
    strokes = g.strokes
    if smooth:
        strokes = [smooth_stroke(np.concatenate(
            [s, np.zeros((len(s), 2))], axis=1)) for s in strokes]
    entry = {"mode": "generated" if g.ok else "generated_weak",
             "strokes": [s.round(2).tolist() for s in strokes],
             "quality": g.to_json()}
    if not g.ok:
        code = ("truncated" if not g.completed else
                "few_strokes" if not g.enough_strokes else "low_score")
        entry["reason_code"] = code
        entry["reason"] = FAIL_REASON[code]
    return entry


def _availability(summary: dict[str, int], char: str) -> int:
    """How well a character can be rendered: 2 = the writer wrote it,
    1 = SDT can generate it, 0 = neither."""
    if char in summary:
        return 2
    if generator.available and generator.supports(char):
        return 1
    return 0


def _width_substitutions(summary: dict[str, int],
                         chars: list[str]) -> dict[str, str]:
    """Characters to draw in their other width: requested -> substitute.

    Japanese text mixes （） with () and ；： with ;: , but a sample set
    normally holds only one of each pair. When the counterpart is better
    supported the counterpart is drawn: the writer's own （ beats an
    SDT-generated ( , and either beats a character we cannot draw at all.
    """
    subs = {}
    for c in chars:
        alt = width_variant(c)
        if alt and _availability(summary, alt) > _availability(summary, c):
            subs[c] = alt
    return subs


@dataclass
class Rendering:
    """Rendered characters keyed by the character the user actually typed."""
    charmap: dict[str, dict]
    cache: dict[str, int]          # {"hit": n, "miss": n} over text characters

    @property
    def issues(self) -> list[dict]:
        """Characters worth telling the user about, in text order: ones that
        could not be drawn, and ones drawn from a suspect generation."""
        return [{"char": c, **{k: v for k, v in e.items() if k != "strokes"}}
                for c, e in self.charmap.items() if e.get("reason_code")]

    @property
    def substitutions(self) -> list[dict]:
        return [{"char": c, "substitute": e["substitute"]}
                for c, e in self.charmap.items() if "substitute" in e]

    @property
    def missing(self) -> list[str]:
        """Characters that produce no ink at all (they come out as blanks)."""
        return [c for c, e in self.charmap.items() if not e.get("strokes")]


def _render_chars(writer: str, chars: list[str], smooth: bool,
                  width_fallback: bool = True, refresh: bool = False,
                  progress: Reporter = NULL_REPORTER) -> Rendering:
    """Render every distinct character of a text: written ones from the
    Fourier average, unwritten ones from SDT.

    Everything but the final per-instance jitter is cached (see
    `nohandwrite.rendercache`), so editing a few characters of a page only
    pays for the characters that changed. `refresh=True` redraws regardless
    — SDT resamples its style references each time, so it is a genuinely new
    attempt, which is what the UI's 再生成 button wants.
    """
    try:
        summary = store.summary(writer)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not summary:
        raise HTTPException(422, "この書き手のサンプルがありません。先に入力ページで文字を書いてください。")

    subs = _width_substitutions(summary, chars) if width_fallback else {}
    # the characters actually drawn, deduplicated
    wanted = list(dict.fromkeys(subs.get(c, c) for c in chars))

    stats = {"hit": 0, "miss": 0}
    entries: dict[str, dict] = {}
    to_generate: list[str] = []
    progress.stage("samples", len(wanted))
    for c in wanted:
        if c in summary:
            entries[c] = _beautified(writer, c, stats, refresh)
        else:
            to_generate.append(c)
        progress.advance()

    if to_generate and not generator.available:
        # a missing checkout is a setup problem, not a property of the
        # character, so it is never cached
        for c in to_generate:
            entries[c] = _fail_entry("model_missing")
        to_generate = []

    if to_generate:
        style_chars = _style_chars(summary)
        style_fp = _fingerprint(writer, style_chars)
        pending: list[tuple[str, str]] = []
        for c in to_generate:
            key = f"g{int(smooth)}-u{ord(c):04x}-{style_fp}"
            entry = None if refresh else render_cache.get(writer, key)
            if entry is None:
                stats["miss"] += 1
                pending.append((c, key))
            else:
                stats["hit"] += 1
                entries[c] = entry
        if pending:
            progress.stage("style", len(style_chars))
            style_strokes = []
            for c in style_chars:
                try:
                    style_strokes.append([np.asarray(s) for s in
                                          _beautified(writer, c)["strokes"]])
                except ValueError:
                    continue
                finally:
                    progress.advance()
            progress.stage("generate", len(pending))
            generated = generator.generate(style_strokes,
                                           "".join(c for c, _ in pending),
                                           on_progress=progress.on_generate)
            for c, key in pending:
                entry = _generated_entry(c, generated.get(c), smooth)
                render_cache.put(writer, key, entry)
                entries[c] = entry

    charmap = {}
    for c in chars:
        entry = dict(entries[subs.get(c, c)])
        if c in subs:
            entry["substitute"] = subs[c]
        charmap[c] = entry
    return Rendering(charmap=charmap, cache=stats)


@app.post("/api/generate")
def generate_text(body: GenerateIn) -> dict:
    """Render `text` in the writer's style: written characters use the Fourier
    average; unwritten ones are generated with SDT from the writer's samples."""
    chars = [c for c in dict.fromkeys(body.text) if not c.isspace()]
    progress = progress_board.reporter(body.job)
    r = _render_chars(body.writer, chars, body.smooth, body.width_fallback,
                      body.refresh, progress)
    progress.finish()
    rng = np.random.default_rng()
    jitter = JitterIn.resolve(body.jitter)
    out = []
    for c in chars:
        e = dict(r.charmap[c])
        if e.get("strokes"):
            e["strokes"] = [s.round(2).tolist() for s in jitter_strokes(
                e["strokes"], rng, jitter.for_char(e.get("substitute", c)))]
        out.append({"char": c, **e})
    return {"writer": body.writer, "size": STANDARD_SIZE, "chars": out,
            "cache": r.cache}


@app.get("/api/render/progress/{job}")
def render_progress(job: str) -> dict:
    """What the render started under `job` is doing. An unknown job (the
    request has not reached the server yet, or is long finished) reports an
    empty stage rather than an error — the browser polls this blind."""
    return progress_board.get(job) or {"stage": None, "done": 0, "total": 0,
                                       "finished": False, "elapsed_s": 0}


@app.post("/api/cache/clear")
def clear_cache(writer: str | None = None) -> dict:
    """Throw away cached renderings (one writer's, or every writer's)."""
    return {"removed": render_cache.clear(writer)}


class TypesetIn(RenderIn):
    """Text + layout parameters (millimeters) shared by preview and export."""
    text: str = Field(min_length=1, max_length=2000)
    char_size_mm: float = Field(default=15.0, gt=0, le=200)
    # negative gap lets characters overlap for tighter, more natural spacing
    char_gap_mm: float = Field(default=1.5, ge=-10, le=100)
    line_gap_mm: float = Field(default=4.0, ge=0, le=100)
    max_width_mm: float = Field(default=180.0, gt=0, le=2000)
    margin_mm: float = Field(default=10.0, ge=0, le=100)
    proportional: bool = True
    vertical: bool = False

    def layout_options(self) -> LayoutOptions:
        return LayoutOptions(char_size_mm=self.char_size_mm,
                             char_gap_mm=self.char_gap_mm,
                             line_gap_mm=self.line_gap_mm,
                             max_width_mm=self.max_width_mm,
                             margin_mm=self.margin_mm,
                             proportional=self.proportional,
                             vertical=self.vertical)


def _layout_entries(body: TypesetIn, progress: Reporter = NULL_REPORTER
                    ) -> tuple[list[dict], Rendering]:
    """One layout entry per character of `body.text`, plus what rendering them
    turned up. Entries carry the character actually drawn, so a width
    substitution gets the right glyph metrics, kinsoku class and vertical
    form."""
    chars = [c for c in dict.fromkeys(body.text) if not c.isspace()]
    r = _render_chars(body.writer, chars, body.smooth, body.width_fallback,
                      body.refresh, progress)
    progress.stage("layout")
    rng = np.random.default_rng()
    jitter = JitterIn.resolve(body.jitter)
    entries = []
    for c in body.text:
        if c == "\n":
            entries.append({"char": "\n"})
        elif c.isspace():
            entries.append({"char": c, "strokes": None})
        else:
            e = r.charmap[c]
            drawn = e.get("substitute", c)
            strokes = e.get("strokes")
            if strokes:
                # per-occurrence variation so repeated characters differ
                strokes = jitter_strokes(strokes, rng, jitter.for_char(drawn))
            entries.append({"char": drawn, "strokes": strokes,
                            "mode": e["mode"]})
    return entries, r


def _line_guides(w: float, h: float, opts: LayoutOptions) -> list[list[list[float]]]:
    """Ruled guide under each text line (left edge of each column when
    vertical), reconstructed from the page size. Preview only — never
    part of the exported G-code/SVG."""
    step = opts.char_size_mm + opts.line_gap_mm
    span = (w if opts.vertical else h) - 2 * opts.margin_mm - opts.char_size_mm
    n = max(round(span / step), 0) + 1
    if opts.vertical:
        return [[[round(opts.margin_mm + k * step, 2), round(opts.margin_mm, 2)],
                 [round(opts.margin_mm + k * step, 2), round(h - opts.margin_mm, 2)]]
                for k in range(n)]
    base = opts.margin_mm + opts.char_size_mm
    return [[[round(opts.margin_mm, 2), round(base + k * step, 2)],
             [round(w - opts.margin_mm, 2), round(base + k * step, 2)]]
            for k in range(n)]


@app.post("/api/typeset")
def typeset_preview(body: TypesetIn) -> dict:
    """Layout preview: placed strokes in absolute page millimeters."""
    progress = progress_board.reporter(body.job)
    entries, r = _layout_entries(body, progress)
    opts = body.layout_options()
    placed, (w, h) = layout_text(entries, opts)
    progress.finish()
    return {
        "page": [round(w, 2), round(h, 2)],
        "strokes": [{"char": p.char, "points": p.points.round(3).tolist()} for p in placed],
        "guides": _line_guides(w, h, opts),
        "modes": {c: e["mode"] for c, e in r.charmap.items()},
        "issues": r.issues,
        "substitutions": r.substitutions,
        "missing": r.missing,
        "cache": r.cache,
    }


class ExportIn(TypesetIn):
    format: str = Field(default="gcode", pattern="^(svg|gcode)$")
    feed_draw: float = Field(default=750.0, gt=0, le=20000)
    feed_travel: float = Field(default=3000.0, gt=0, le=20000)
    # servo pen lift by default (the usual GRBL kit); "G0 Z5.0" /
    # "G1 Z0.0 F300" for a machine with a real Z axis
    pen_up_cmd: str = Field(default="M3 S40", max_length=100)
    pen_down_cmd: str = Field(default="M3 S90", max_length=100)
    dwell_s: float = Field(default=0.25, ge=0, le=5)   # servo travel time
    flip_y: bool = True
    # paper size anchors the output to the sheet (machine zero = its
    # bottom-left corner); without it the origin is the text block, so the
    # position on the paper moves as the text grows
    paper_w_mm: float | None = Field(default=None, gt=0, le=2000)
    paper_h_mm: float | None = Field(default=None, gt=0, le=2000)
    # pen pressure: SVG variable stroke width / G-code Z-axis modulation
    # (leave pressure_z off for plotters without Z control)
    pressure_width: bool = False
    pressure_z: bool = False
    z_light: float = Field(default=0.0, ge=-20, le=20)
    z_heavy: float = Field(default=-0.4, ge=-20, le=20)

    def gcode_options(self) -> GCodeOptions:
        return GCodeOptions(
            layout=self.layout_options(), feed_draw=self.feed_draw,
            feed_travel=self.feed_travel, pen_up_cmd=self.pen_up_cmd,
            pen_down_cmd=self.pen_down_cmd, dwell_s=self.dwell_s,
            flip_y=self.flip_y, paper_w_mm=self.paper_w_mm,
            paper_h_mm=self.paper_h_mm, pressure_z=self.pressure_z,
            z_light=self.z_light, z_heavy=self.z_heavy)


#: Response header naming the characters a download came out missing, so the
#: browser can warn about silent gaps without a preview round-trip. Header
#: values are latin-1, so the characters are percent-encoded.
MISSING_HEADER = "X-Missing-Chars"


@app.post("/api/export")
def export_text(body: ExportIn) -> Response:
    progress = progress_board.reporter(body.job)
    entries, r = _layout_entries(body, progress)
    progress.stage("export")
    layout = body.layout_options()
    if body.format == "svg":
        content = strokes_to_svg(entries, layout,
                                 pressure_width=body.pressure_width)
        media, fname = "image/svg+xml", "nohandwrite.svg"
    else:
        content = strokes_to_gcode(entries, body.gcode_options())
        media, fname = "text/plain", "nohandwrite.gcode"
    progress.finish()
    return Response(content=content, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{fname}"',
        MISSING_HEADER: urllib.parse.quote("".join(r.missing)),
    })


# --- experimental: send straight to a GRBL plotter over USB ------------
# One job at a time; the UI polls /api/plot/status and can stop it.


class PlotIn(ExportIn):
    port: str = Field(min_length=1, max_length=200)
    baud: int = Field(default=115200, ge=1200, le=1000000)
    unlock: bool = False       # send $X first when GRBL boots into alarm
    set_origin: bool = True    # G92 X0 Y0: the parked pen is the origin
    # machine work area; 0 disables the check. Without soft limits GRBL
    # drives into the end stop and grinds, so refuse before moving.
    travel_x_mm: float = Field(default=0.0, ge=0, le=2000)
    travel_y_mm: float = Field(default=0.0, ge=0, le=2000)


@app.get("/api/plot/ports")
def plot_ports() -> dict:
    return {"ports": list_serial_ports()}


@app.post("/api/plot")
def plot_start(body: PlotIn) -> dict:
    if body.port not in {p["device"] for p in list_serial_ports()}:
        raise HTTPException(400, f"ポートが見つかりません: {body.port}")
    progress = progress_board.reporter(body.job)
    entries, r = _layout_entries(body, progress)
    progress.stage("export")
    gcode = strokes_to_gcode(entries, body.gcode_options())
    progress.finish()
    try:
        status = plotter.start(gcode, body.port, body.baud, body.unlock,
                               body.pen_up_cmd, body.set_origin,
                               body.travel_x_mm, body.travel_y_mm)
    except PlotterError as exc:
        raise HTTPException(409, str(exc))
    # the plotter draws blanks for these; say so before the pen is moving
    return {**status, "missing": r.missing}


@app.get("/api/plot/status")
def plot_status() -> dict:
    return plotter.status()


@app.post("/api/plot/stop")
def plot_stop() -> dict:
    return plotter.stop()


@app.middleware("http")
async def static_cache_headers(request, call_next):
    """App assets revalidate on every load (ETag 304s keep it fast) so UI
    changes show up immediately; the large font may cache for 30 days."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/fonts/"):
        response.headers.setdefault("Cache-Control", "public, max-age=2592000")
    elif path == "/" or path.endswith((".html", ".css", ".js")):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
