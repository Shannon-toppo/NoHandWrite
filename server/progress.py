"""Progress of in-flight render jobs, so the UI can show more than a spinner.

Laying out a page is one blocking POST that can run for a minute — loading
the SDT checkpoint alone takes tens of seconds, and every unwritten
character is an autoregressive decode after that. A status line that says
nothing for that long reads as a hang.

So the request carries a client-generated job id, the rendering code reports
what it is doing under that id, and the browser polls
`GET /api/render/progress/<job>` while it waits. Entries are tiny and the
board keeps only the most recent ones, so a browser that walks away
mid-render leaves nothing to clean up.
"""
from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

#: Job ids come from the browser and become dict keys, so keep them boring.
JOB_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass
class _Job:
    stage: str = "starting"
    done: int = 0
    total: int = 0                 # 0 = no count to show, just the stage
    started: float = field(default_factory=time.monotonic)
    finished: bool = False

    def to_json(self) -> dict:
        return {"stage": self.stage, "done": self.done, "total": self.total,
                "finished": self.finished,
                "elapsed_s": round(time.monotonic() - self.started, 1)}


class Reporter:
    """Handed to the rendering code to say where it has got to.

    A reporter with no job behind it does nothing, so callers never have to
    branch on whether anybody is watching.
    """

    def __init__(self, job: _Job | None = None):
        self._job = job

    def stage(self, stage: str, total: int = 0) -> None:
        if self._job is None:
            return
        self._job.stage = stage
        self._job.done = 0
        self._job.total = total

    def advance(self, n: int = 1) -> None:
        if self._job is not None:
            self._job.done += n

    def finish(self) -> None:
        if self._job is not None:
            self._job.stage = "done"
            self._job.finished = True

    def on_generate(self, stage: str, done: int, total: int) -> None:
        """Callback shape `SDTGenerator.generate` reports through."""
        if self._job is None:
            return
        self._job.stage = stage
        self._job.done = done
        self._job.total = total


#: For callers that render without a UI watching (tests, scripts).
NULL_REPORTER = Reporter()


class ProgressBoard:
    """The most recent `keep` jobs' progress, oldest dropped."""

    def __init__(self, keep: int = 32):
        self.keep = keep
        self._jobs: OrderedDict[str, _Job] = OrderedDict()
        self._lock = threading.Lock()

    def reporter(self, job: str | None) -> Reporter:
        """Start (or restart) `job` and return the reporter that feeds it."""
        if not job or not JOB_RE.match(job):
            return NULL_REPORTER
        entry = _Job()
        with self._lock:
            self._jobs[job] = entry
            self._jobs.move_to_end(job)
            while len(self._jobs) > self.keep:
                self._jobs.popitem(last=False)
        return Reporter(entry)

    def get(self, job: str) -> dict | None:
        with self._lock:
            entry = self._jobs.get(job)
        return entry.to_json() if entry else None
