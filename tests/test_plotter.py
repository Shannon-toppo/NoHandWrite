"""Serial streaming to a GRBL plotter — everything that can be checked
without a machine on the other end of the cable."""
import importlib
import os
import threading
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from nohandwrite.export import GCodeOptions, strokes_to_gcode
from server import plotter as plotter_mod
from server.plotter import Plotter, PlotterError, extent, prepare


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from nohandwrite.store import Store
    import server.main as main
    importlib.reload(main)
    monkeypatch.setattr(main, "store", Store(tmp_path))
    return TestClient(main.app)


def test_prepare_strips_comments_and_blanks():
    lines = prepare("; header\nG21 ; mm\n\n; char 木\nG0 X1.00 Y2.00 F3000\n")
    assert lines == ["G21", "G0 X1.00 Y2.00 F3000"]
    # per-character comments are the only non-ASCII in the file, and they go
    assert all(l.isascii() for l in lines)


def test_prepare_rejects_nothing_to_send():
    assert prepare("; only comments\n\n") == []
    with pytest.raises(PlotterError):
        Plotter().start("; nothing here", port="/dev/null")


def test_ports_endpoint(client):
    body = client.get("/api/plot/ports").json()
    assert isinstance(body["ports"], list)
    assert all({"device", "description"} <= set(p) for p in body["ports"])


def test_plot_rejects_unknown_port(client):
    """Only ports the machine actually reports may be opened."""
    res = client.post("/api/plot", json={"writer": "taro", "text": "木",
                                         "port": "/dev/definitely-not-a-plotter"})
    assert res.status_code == 400
    assert "ポートが見つかりません" in res.json()["detail"]


def test_status_starts_idle(client):
    s = client.get("/api/plot/status").json()
    assert s["state"] == "idle" and s["sent"] == 0


# --- streaming against a fake GRBL on a pty ---------------------------------

BANNER_OK = b"\r\nGrbl 1.1h ['$' for help]\r\n"
BANNER_ALARM = BANNER_OK + b"['$H'|'$X' to unlock]\r\n"


class FakeGrbl(threading.Thread):
    """Answers 'ok' per line and records how much the sender kept in flight,
    which is what the character-counting protocol is supposed to manage."""

    STATUS = b"<Idle,MPos:0.000,0.000,0.000,WPos:0.000,0.000,0.000>\r\n"

    def __init__(self, fd, banner=BANNER_OK, delay=0.0):
        super().__init__(daemon=True)
        self.fd, self.banner, self.delay = fd, banner, delay
        self.lines: list[str] = []
        self.max_inflight = 0
        self.realtime = b""            # '!' feed hold, '\x18' soft reset
        self.alive = True

    def run(self):
        time.sleep(0.05)               # a real board resets on open, then greets
        os.write(self.fd, self.banner)
        buf = b""
        while self.alive:
            try:
                chunk = os.read(self.fd, 4096)
            except OSError:
                return
            if not chunk:
                return
            for byte in (b"!", b"\x18"):
                if byte in chunk:
                    self.realtime += byte
            if b"?" in chunk:          # real-time status query, no 'ok'
                os.write(self.fd, self.STATUS)
            self.max_inflight = max(self.max_inflight, len(buf) + len(chunk))
            for byte in (b"!", b"\x18", b"?"):
                chunk = chunk.replace(byte, b"")
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.strip():
                    self.lines.append(line.strip().decode())
                    if self.delay:
                        time.sleep(self.delay)
                    os.write(self.fd, b"ok\r\n")


@pytest.fixture()
def fake_grbl(monkeypatch):
    monkeypatch.setattr(plotter_mod, "WAKE_WAIT_S", 0.3)
    opened = []

    def start(gcode, banner=BANNER_OK, delay=0.0, **kw):
        master, slave = os.openpty()
        opened.append((master, slave))
        grbl = FakeGrbl(master, banner, delay)
        grbl.start()
        p = Plotter()
        p.start(gcode, os.ttyname(slave), **kw)
        return p, grbl

    yield start
    for master, slave in opened:
        os.close(slave)
        os.close(master)


def wait(p, timeout=20.0):
    deadline = time.monotonic() + timeout
    while p.running() and time.monotonic() < deadline:
        time.sleep(0.05)
    return p.status()


def sample_gcode(n_strokes=12, paper=(210.0, 297.0)):
    strokes = [np.array([[i * 30, 0], [500, 400 + i * 20], [900, 900]], float)
               for i in range(n_strokes)]
    paper_w, paper_h = paper if paper else (None, None)
    return strokes_to_gcode([{"char": "木", "strokes": strokes}],
                            GCodeOptions(paper_w_mm=paper_w, paper_h_mm=paper_h))


def test_streams_whole_job_without_overrunning_the_buffer(fake_grbl):
    p, grbl = fake_grbl(sample_gcode(), delay=0.002)
    s = wait(p)
    assert s["state"] == "done" and s["sent"] == s["total"] > 40
    assert s["start_report"].startswith("<Idle")        # asked where it was
    assert grbl.max_inflight <= plotter_mod.RX_BUFFER   # never overflows GRBL
    assert grbl.max_inflight > plotter_mod.RX_BUFFER / 2  # but does stay full
    assert grbl.lines[-1] == "G4 P0.1"                  # end-of-job sync
    assert "M3 S90" in grbl.lines and "G4 P0.25" in grbl.lines
    assert all(line.isascii() for line in grbl.lines)


def test_refuses_to_move_while_grbl_is_in_alarm(fake_grbl):
    p, grbl = fake_grbl(sample_gcode(), banner=BANNER_ALARM)
    s = wait(p)
    assert s["state"] == "error" and "アラーム" in s["message"]
    assert not any(l.startswith("G") for l in grbl.lines)


def test_unlock_option_clears_the_alarm_first(fake_grbl):
    p, grbl = fake_grbl(sample_gcode(), banner=BANNER_ALARM, unlock=True)
    s = wait(p)
    assert s["state"] == "done"
    assert grbl.lines[0] == "$X"


def test_stop_halts_and_parks_the_pen(fake_grbl):
    p, grbl = fake_grbl(sample_gcode(40), delay=0.02)
    while p.status()["sent"] == 0 and p.running():
        time.sleep(0.05)
    s = p.stop()
    assert s["state"] == "stopped" and 0 < s["sent"] < s["total"]
    assert grbl.realtime == b"!\x18"                   # feed hold, then reset
    assert grbl.lines[-2:] == ["$X", "M3 S40"]         # alarm cleared, pen up


def test_parks_the_origin_on_the_pen_before_drawing(fake_grbl):
    """The UI tells the user to put the pen on the paper's corner; the job
    has to tell the machine that too, or the absolute moves land in
    whatever coordinate system GRBL happened to be holding."""
    p, grbl = fake_grbl(sample_gcode())
    assert wait(p)["state"] == "done"
    assert grbl.lines[0] == "G92 X0 Y0"
    assert grbl.lines.index("G92 X0 Y0") < grbl.lines.index("G21")


def test_origin_can_be_left_to_the_machine(fake_grbl):
    p, grbl = fake_grbl(sample_gcode(), set_origin=False)
    assert wait(p)["state"] == "done"
    assert "G92 X0 Y0" not in grbl.lines


def test_extent_reads_how_far_the_job_reaches():
    lines = prepare("G0 X10.00 Y284.80 F3000\nG1 X120.50 Y12.00 F750\nG4 P0.25\n")
    assert extent(lines) == (120.5, 284.8)
    assert extent(["M3 S90", "G4 P0.25"]) == (0.0, 0.0)   # no axis words


def test_refuses_a_job_that_exceeds_the_work_area():
    """GRBL without soft limits grinds against the end stop instead of
    stopping, so this has to be caught before the port is even opened."""
    gcode = strokes_to_gcode([{"char": "木", "strokes": [
        np.array([[0, 0], [500, 500], [1000, 1000]], float)]}],
        GCodeOptions(paper_w_mm=210, paper_h_mm=297))
    with pytest.raises(PlotterError, match="可動範囲"):
        Plotter().start(gcode, port="/dev/null", travel_x_mm=200, travel_y_mm=200)


def test_work_area_check_passes_within_range(fake_grbl):
    """Same job unanchored fits in 200x200 and goes through."""
    p, grbl = fake_grbl(sample_gcode(2, paper=None),
                        travel_x_mm=200, travel_y_mm=200)
    assert wait(p)["state"] == "done"
