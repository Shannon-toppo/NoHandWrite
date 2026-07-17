"""NoHandWrite API server: capture storage + static web UI.

Run:  uv run uvicorn server.main:app --host 0.0.0.0 --port 8765
Then open http://<this-machine>:8765/ (iPad: same LAN, Safari + Apple Pencil).
"""
from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nohandwrite.beautify import beautify
from nohandwrite.export import GCodeOptions, LayoutOptions, strokes_to_gcode, strokes_to_svg
from nohandwrite.fourier import smooth_stroke
from nohandwrite.generate import SDTGenerator
from nohandwrite.store import Store
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


@app.get("/api/writers/{writer}/chars/{char}/beautify")
def get_beautified(writer: str, char: str) -> dict:
    data = store.load_character(writer, char)
    if data is None:
        raise HTTPException(404, "no samples for this character")
    try:
        return beautify(data).to_json()
    except ValueError as e:
        raise HTTPException(422, str(e))


generator = SDTGenerator()


@app.get("/api/generate/status")
def generate_status() -> dict:
    return {"available": generator.available, "device": generator.device}


class GenerateIn(BaseModel):
    writer: str
    text: str = Field(min_length=1, max_length=200)
    smooth: bool = True


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
    return {"writer": body.writer, "size": STANDARD_SIZE,
            "chars": [{"char": c, **entries[c]} for c in chars]}


class ExportIn(BaseModel):
    writer: str
    text: str = Field(min_length=1, max_length=2000)
    smooth: bool = True
    format: str = Field(default="svg", pattern="^(svg|gcode)$")
    char_size_mm: float = Field(default=15.0, gt=0, le=200)
    max_width_mm: float = Field(default=180.0, gt=0, le=2000)


@app.post("/api/export")
def export_text(body: ExportIn) -> Response:
    chars = [c for c in dict.fromkeys(body.text) if not c.isspace()]
    charmap = _render_chars(body.writer, chars, body.smooth)
    entries = []
    for c in body.text:
        if c == "\n":
            entries.append({"char": "\n"})
        elif c.isspace():
            entries.append({"char": c, "strokes": None})
        else:
            entries.append({"char": c, "strokes": charmap[c].get("strokes")})
    layout = LayoutOptions(char_size_mm=body.char_size_mm, max_width_mm=body.max_width_mm)
    if body.format == "svg":
        content = strokes_to_svg(entries, layout)
        media, fname = "image/svg+xml", "nohandwrite.svg"
    else:
        content = strokes_to_gcode(entries, GCodeOptions(layout=layout))
        media, fname = "text/plain", "nohandwrite.gcode"
    return Response(content=content, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
