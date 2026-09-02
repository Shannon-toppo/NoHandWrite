"""Cache of rendered characters, keyed by what they were rendered from.

Typesetting a page re-renders every distinct character in the text, and the
SDT generation behind an unwritten character costs seconds — so editing one
word used to pay for the whole page again. Entries are therefore kept both
in memory and on disk (the disk copy is what makes the first preview after a
server restart instant, without loading the model at all).

Keys are built by the caller and must encode *everything* the rendering
depended on: which writer, which character, the options used, and a
fingerprint of the source samples (see `Store.char_stamp`). Nothing here
expires — a changed fingerprint simply produces a different key, and the
stale files are eventually evicted by size.
"""
from __future__ import annotations

import json
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path

_WRITER_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")


class RenderCache:
    """Two-level (memory + disk) cache of small JSON-able dicts.

    `memory_entries` bounds the in-process LRU; `disk_entries` bounds the
    files kept per writer, pruned oldest-first once the directory grows past
    it. Set `root` to None for a memory-only cache (used by the tests).
    """

    def __init__(self, root: str | Path | None, memory_entries: int = 2048,
                 disk_entries: int = 4000):
        self.root = Path(root) if root is not None else None
        self.memory_entries = memory_entries
        self.disk_entries = disk_entries
        self._mem: OrderedDict[tuple[str, str], dict] = OrderedDict()
        self._puts = 0
        # sync endpoints run on a threadpool, so two previews can touch the
        # LRU at once
        self._lock = threading.Lock()

    # -- paths ---------------------------------------------------------
    def _dir(self, writer: str) -> Path | None:
        if self.root is None or not _WRITER_RE.match(writer):
            return None
        return self.root / writer

    def _path(self, writer: str, key: str) -> Path | None:
        d = self._dir(writer)
        if d is None or not _KEY_RE.match(key):
            return None
        return d / f"{key}.json"

    # -- lookup --------------------------------------------------------
    def get(self, writer: str, key: str) -> dict | None:
        mem_key = (writer, key)
        with self._lock:
            entry = self._mem.get(mem_key)
            if entry is not None:
                self._mem.move_to_end(mem_key)
                return entry
        path = self._path(writer, key)
        if path is None or not path.exists():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        self._remember(mem_key, entry)
        return entry

    def put(self, writer: str, key: str, entry: dict) -> None:
        self._remember((writer, key), entry)
        path = self._path(writer, key)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # unique temp name: two threads may write the same key at once
            tmp = path.with_suffix(f".{os.getpid()}-{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            return                      # a cache is never worth failing over
        with self._lock:
            self._puts += 1
            due = self._puts % 64 == 0
        if due:
            self._prune(writer)

    def clear(self, writer: str | None = None) -> int:
        """Drop cached entries (one writer's, or all). Returns files removed."""
        with self._lock:
            if writer is None:
                self._mem.clear()
            else:
                for k in [k for k in self._mem if k[0] == writer]:
                    del self._mem[k]
        if self.root is None or not self.root.exists():
            return 0
        dirs = [self._dir(writer)] if writer else list(self.root.iterdir())
        removed = 0
        for d in dirs:
            if d is None or not d.is_dir():
                continue
            for f in d.glob("*.json"):
                f.unlink(missing_ok=True)
                removed += 1
        return removed

    # -- internals -----------------------------------------------------
    def _remember(self, mem_key: tuple[str, str], entry: dict) -> None:
        with self._lock:
            self._mem[mem_key] = entry
            self._mem.move_to_end(mem_key)
            while len(self._mem) > self.memory_entries:
                self._mem.popitem(last=False)

    def _prune(self, writer: str) -> None:
        d = self._dir(writer)
        if d is None or not d.is_dir():
            return
        try:
            files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime)
        except OSError:
            return
        for f in files[:max(0, len(files) - self.disk_entries)]:
            f.unlink(missing_ok=True)
