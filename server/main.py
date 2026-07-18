"""NoHandWrite API server: capture storage + static web UI.

Run:  uv run uvicorn server.main:app --host 0.0.0.0 --port 8765
Then open http://<this-machine>:8765/ (iPad: same LAN, Safari + Apple Pencil).
"""
from __future__ import annotations

import datetime
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
from nohandwrite.store import Store
from nohandwrite.variation import char_category, jitter_strokes
from nohandwrite.strokes import STANDARD_SIZE, Sample
from .prompts import PROMPT_SETS

ROOT = Path(__file__).resolve().parents[1]
store = Store(ROOT / "data")

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


class GenerateIn(BaseModel):
    writer: str
    text: str = Field(min_length=1, max_length=200)
    smooth: bool = True
    jitter: JitterSpec = 1.0


def _render_chars(writer: str, chars: list[str], smooth: bool) -> dict[str, dict]:
    """Per-character rendering map: written chars -> Fourier average,
    unwritten -> SDT generation. Values: {mode, strokes?|reason}."""
    try:
        summary = store.summary(writer)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not summary:
        raise HTTPException(422, "この書き手のサンプルがありません。先に入力ページで文字を書いてください。")

    entries: dict[str, dict] = {}
    to_generate = []
    for c in chars:
        if c in summary:
            data = store.load_character(writer, c)
            r = beautify(data)
            entries[c] = {"mode": r.mode, "strokes": [s.round(2).tolist() for s in r.strokes]}
        else:
            to_generate.append(c)

    if to_generate:
        if not generator.available:
            for c in to_generate:
                entries[c] = {"mode": "unavailable",
                              "reason": "SDTモデル/データが見つかりません(third_party/SDT)"}
        else:
            # style references: the writer's beautified characters (most-written first)
            style_chars = sorted(summary, key=summary.get, reverse=True)[:15]
            style_strokes = []
            for c in style_chars:
                data = store.load_character(writer, c)
                try:
                    style_strokes.append(beautify(data).strokes)
                except ValueError:
                    continue
            generated = generator.generate(style_strokes, "".join(to_generate))
            for c in to_generate:
                if c in generated:
                    strokes = generated[c]
                    if smooth:
                        strokes = [smooth_stroke(np.concatenate(
                            [s, np.zeros((len(s), 2))], axis=1)) for s in strokes]
                    entries[c] = {"mode": "generated",
                                  "strokes": [s.round(2).tolist() for s in strokes]}
                else:
                    entries[c] = {"mode": "unavailable",
                                  "reason": "生成辞書にない文字です"}
    return entries


@app.post("/api/generate")
def generate_text(body: GenerateIn) -> dict:
    """Render `text` in the writer's style: written characters use the Fourier
    average; unwritten ones are generated with SDT from the writer's samples."""
    chars = [c for c in dict.fromkeys(body.text) if not c.isspace()]
    entries = _render_chars(body.writer, chars, body.smooth)
    rng = np.random.default_rng()
    jitter = JitterIn.resolve(body.jitter)
    out = []
    for c in chars:
        e = dict(entries[c])
        if e.get("strokes"):
            e["strokes"] = [s.round(2).tolist() for s in
                            jitter_strokes(e["strokes"], rng, jitter.for_char(c))]
        out.append({"char": c, **e})
    return {"writer": body.writer, "size": STANDARD_SIZE, "chars": out}


class TypesetIn(BaseModel):
    """Text + layout parameters (millimeters) shared by preview and export."""
    writer: str
    text: str = Field(min_length=1, max_length=2000)
    smooth: bool = True
    jitter: JitterSpec = 1.0
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


def _layout_entries(body: TypesetIn) -> list[dict]:
    chars = [c for c in dict.fromkeys(body.text) if not c.isspace()]
    charmap = _render_chars(body.writer, chars, body.smooth)
    rng = np.random.default_rng()
    jitter = JitterIn.resolve(body.jitter)
    entries = []
    for c in body.text:
        if c == "\n":
            entries.append({"char": "\n"})
        elif c.isspace():
            entries.append({"char": c, "strokes": None})
        else:
            strokes = charmap[c].get("strokes")
            if strokes:
                # per-occurrence variation so repeated characters differ
                strokes = jitter_strokes(strokes, rng, jitter.for_char(c))
            entries.append({"char": c, "strokes": strokes,
                            "mode": charmap[c]["mode"]})
    return entries


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
    entries = _layout_entries(body)
    opts = body.layout_options()
    placed, (w, h) = layout_text(entries, opts)
    modes = {e["char"]: e.get("mode") for e in entries if e.get("mode")}
    return {
        "page": [round(w, 2), round(h, 2)],
        "strokes": [{"char": p.char, "points": p.points.round(3).tolist()} for p in placed],
        "guides": _line_guides(w, h, opts),
        "modes": modes,
    }


class ExportIn(TypesetIn):
    format: str = Field(default="gcode", pattern="^(svg|gcode)$")
    feed_draw: float = Field(default=1500.0, gt=0, le=20000)
    feed_travel: float = Field(default=3000.0, gt=0, le=20000)
    pen_up_cmd: str = Field(default="G0 Z5.0", max_length=100)
    pen_down_cmd: str = Field(default="G1 Z0.0 F300", max_length=100)
    flip_y: bool = True


@app.post("/api/export")
def export_text(body: ExportIn) -> Response:
    entries = _layout_entries(body)
    layout = body.layout_options()
    if body.format == "svg":
        content = strokes_to_svg(entries, layout)
        media, fname = "image/svg+xml", "nohandwrite.svg"
    else:
        content = strokes_to_gcode(entries, GCodeOptions(
            layout=layout, feed_draw=body.feed_draw, feed_travel=body.feed_travel,
            pen_up_cmd=body.pen_up_cmd, pen_down_cmd=body.pen_down_cmd,
            flip_y=body.flip_y))
        media, fname = "text/plain", "nohandwrite.gcode"
    return Response(content=content, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


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
