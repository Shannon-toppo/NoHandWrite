"""File-based store for handwriting data.

Layout: <root>/<writer>/u<hex codepoint>.json — one file per character,
holding every recorded sample of that character by that writer
(see CharacterData.to_json for the schema).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .strokes import CharacterData, Sample

_WRITER_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _check_writer(writer: str) -> str:
        if not _WRITER_RE.match(writer):
            raise ValueError(f"invalid writer id: {writer!r} (use A-Za-z0-9_-)")
        return writer

    def _char_path(self, writer: str, char: str) -> Path:
        return self.root / self._check_writer(writer) / f"u{ord(char):04x}.json"

    def add_sample(self, writer: str, char: str, sample: Sample) -> CharacterData:
        if len(char) != 1:
            raise ValueError("char must be a single character")
        data = self.load_character(writer, char) or CharacterData(char=char, writer=writer)
        data.samples.append(sample)
        path = self._char_path(writer, char)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data.to_json(), ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return data

    def load_character(self, writer: str, char: str) -> CharacterData | None:
        path = self._char_path(writer, char)
        if not path.exists():
            return None
        return CharacterData.from_json(json.loads(path.read_text(encoding="utf-8")))

    def delete_last_sample(self, writer: str, char: str) -> CharacterData | None:
        data = self.load_character(writer, char)
        if data is None or not data.samples:
            return data
        data.samples.pop()
        path = self._char_path(writer, char)
        if data.samples:
            path.write_text(json.dumps(data.to_json(), ensure_ascii=False), encoding="utf-8")
        else:
            path.unlink()
            return None
        return data

    def list_writers(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir()
                      if p.is_dir() and _WRITER_RE.match(p.name))

    def summary(self, writer: str) -> dict[str, int]:
        """Map of character -> number of samples for a writer."""
        wdir = self.root / self._check_writer(writer)
        result: dict[str, int] = {}
        if not wdir.exists():
            return result
        for path in sorted(wdir.glob("u*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                result[data["char"]] = len(data["samples"])
            except (json.JSONDecodeError, KeyError):
                continue
        return result
