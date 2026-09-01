"""Experimental: stream G-code to a GRBL controller over USB serial.

One job at a time, run on a background thread; the web UI polls `status()`
and can `stop()`. Lines are sent with GRBL's character-counting protocol
(keep at most RX_BUFFER bytes in flight, one 'ok' per line) rather than
send-and-wait, so the planner never starves — handwriting is thousands of
short segments and send-and-wait would make the machine stutter at every
one of them.

Comments are stripped before sending: they cost buffer space and the
per-character ones are not ASCII.

The G-code is absolute (G90), so a job only lands where you want it if the
controller agrees on where zero is. Machines like these have no homing
switches and GRBL keeps whatever position it had from earlier work, so
`set_origin` sends `G92 X0 Y0` first: wherever the pen is parked becomes
the origin the file is written against. Without it the first move is
"go to X10 Y285 in some coordinate system you never set", which is how a
job ends up jumping across the bed before drawing correctly.
"""
from __future__ import annotations

import logging
import platform
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass

import serial
from serial.tools import list_ports

log = logging.getLogger(__name__)

RX_BUFFER = 128           # GRBL's serial receive buffer, bytes
DEFAULT_BAUD = 115200
WAKE_WAIT_S = 2.0         # opening the port resets the controller board
REPLY_TIMEOUT_S = 120.0   # no 'ok' for this long = something is wrong

# Never a plotter on macOS.
_SKIP = ("Bluetooth-Incoming-Port", "debug-console", "wlan-debug")


class PlotterError(RuntimeError):
    pass


class _Stopped(Exception):
    pass


def list_serial_ports() -> list[dict]:
    """Candidate USB serial ports. On macOS only the /dev/cu.* names are
    offered: opening /dev/tty.* blocks waiting for carrier detect."""
    out = []
    for p in list_ports.comports():
        if any(s in p.device for s in _SKIP):
            continue
        if platform.system() == "Darwin" and not p.device.startswith("/dev/cu."):
            continue
        out.append({"device": p.device, "description": p.description or "",
                    "hwid": p.hwid or ""})
    return out


def extent(lines: list[str]) -> tuple[float, float]:
    """Furthest X and Y the job asks for. The file is absolute mm from the
    origin we just set, so this is exactly how far the head has to travel."""
    max_x = max_y = 0.0
    for line in lines:
        for word in line.split():
            if word[:1] in ("X", "Y"):
                try:
                    value = float(word[1:])
                except ValueError:
                    continue
                if word[0] == "X":
                    max_x = max(max_x, value)
                else:
                    max_y = max(max_y, value)
    return max_x, max_y


def prepare(gcode: str) -> list[str]:
    """G-code text -> the ASCII lines actually worth sending."""
    lines = []
    for raw in gcode.splitlines():
        line = raw.split(";", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


@dataclass
class JobState:
    state: str = "idle"       # idle | running | done | error | stopped
    sent: int = 0
    total: int = 0
    port: str = ""
    message: str = ""
    elapsed_s: float = 0.0
    start_report: str = ""    # GRBL's '?' report before the first move


class Plotter:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._started = 0.0
        self.job = JobState()

    # -- public API ------------------------------------------------------
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict:
        s = asdict(self.job)
        if self.running():
            s["elapsed_s"] = round(time.monotonic() - self._started, 1)
        return s

    def start(self, gcode: str, port: str, baud: int = DEFAULT_BAUD,
              unlock: bool = False, pen_up_cmd: str = "M3 S40",
              set_origin: bool = True, travel_x_mm: float = 0.0,
              travel_y_mm: float = 0.0) -> dict:
        if self.running():
            raise PlotterError("すでに送信中です。停止してから開始してください。")
        lines = prepare(gcode)
        if not lines:
            raise PlotterError("送信できる行がありません。")
        # GRBL without soft limits happily drives into the end stop and
        # grinds there, so refuse before anything moves.
        need_x, need_y = extent(lines)
        over = ((travel_x_mm and need_x > travel_x_mm)
                or (travel_y_mm and need_y > travel_y_mm))
        if over:
            raise PlotterError(
                f"このジョブは X{need_x:.0f} / Y{need_y:.0f} mm まで動きますが、"
                f"可動範囲は X{travel_x_mm:.0f} / Y{travel_y_mm:.0f} mm です。"
                "「用紙の左下を機械原点にする」をオフにするか、"
                "文字サイズ・余白・用紙を小さくしてください。")
        self._stop.clear()
        self._started = time.monotonic()
        self.job = JobState(state="running", total=len(lines), port=port,
                            message="接続中…")
        self.job.message = f"接続中…(最大 X{need_x:.0f} / Y{need_y:.0f} mm)"
        self._thread = threading.Thread(
            target=self._run,
            args=(lines, port, baud, unlock, pen_up_cmd, set_origin),
            daemon=True)
        self._thread.start()
        return self.status()

    def stop(self) -> dict:
        """Feed hold + soft reset. The machine ends up in alarm with its
        position lost, so the caller has to re-zero before the next job."""
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=8.0)
        return self.status()

    # -- worker ----------------------------------------------------------
    def _run(self, lines: list[str], port: str, baud: int, unlock: bool,
             pen_up_cmd: str, set_origin: bool) -> None:
        ser = None
        try:
            ser = serial.Serial(port, baud, timeout=0.2)
        except Exception as exc:
            self._finish("error", f"ポートを開けません: {exc}")
            return
        try:
            self._wake(ser, unlock)
            if set_origin:
                ser.write(b"G92 X0 Y0\n")        # the pen is parked on zero
                self._pump(ser, deque(), timeout=5.0)
            self.job.message = "描画中…"
            self._stream(ser, lines)
            self._sync(ser)                      # wait for the last move
            self._finish("done", "描画が完了しました。")
        except _Stopped:
            self._abort(ser, pen_up_cmd)
            self._finish("stopped", "停止しました。位置が失われているので、"
                                    "原点を合わせ直してください。")
        except PlotterError as exc:
            self._abort(ser, pen_up_cmd)
            self._finish("error", str(exc))
        except Exception as exc:                 # unexpected: still park the pen
            log.exception("plot job failed")
            self._abort(ser, pen_up_cmd)
            self._finish("error", f"送信に失敗しました: {exc}")
        finally:
            try:
                ser.close()
            except Exception:
                pass

    def _finish(self, state: str, message: str) -> None:
        self.job.elapsed_s = round(time.monotonic() - self._started, 1)
        self.job.state = state
        self.job.message = message

    def _wake(self, ser: serial.Serial, unlock: bool) -> None:
        ser.write(b"\r\n\r\n")
        time.sleep(WAKE_WAIT_S)
        banner = ser.read_all().decode("ascii", "replace")
        ser.reset_input_buffer()
        log.info("GRBL banner: %s", banner.strip().replace("\r\n", " | "))
        if "ALARM" in banner or "unlock" in banner:
            if not unlock:
                raise PlotterError(
                    "GRBLがアラーム状態です。ホーミング($H)を済ませるか、"
                    "「$Xでアンロック」にチェックを入れて再送信してください。")
            ser.write(b"$X\n")
            self._pump(ser, deque(), timeout=5.0)
        self.job.start_report = self._report(ser)
        log.info("GRBL position before start: %s", self.job.start_report)

    def _report(self, ser: serial.Serial) -> str:
        """'?' is a real-time command: GRBL answers with <...> and no 'ok'."""
        ser.reset_input_buffer()
        ser.write(b"?")
        time.sleep(0.3)
        raw = ser.read_all().decode("ascii", "replace")
        return next((l.strip() for l in raw.splitlines()
                     if l.strip().startswith("<")), raw.strip())

    def _stream(self, ser: serial.Serial, lines: list[str]) -> None:
        pending: deque[int] = deque()            # byte lengths awaiting 'ok'
        for i, line in enumerate(lines):
            if self._stop.is_set():
                raise _Stopped()
            data = (line + "\n").encode("ascii", "replace")
            while sum(pending) + len(data) >= RX_BUFFER:
                self._pump(ser, pending)
            ser.write(data)
            pending.append(len(data))
            self.job.sent = i + 1
        while pending:
            self._pump(ser, pending)

    def _sync(self, ser: serial.Serial) -> None:
        """'ok' means parsed, not drawn. A dwell blocks until the planner
        is empty, so its 'ok' is the real end of the job."""
        ser.write(b"G4 P0.1\n")
        self._pump(ser, deque(), timeout=REPLY_TIMEOUT_S)

    def _pump(self, ser: serial.Serial, pending: deque[int],
              timeout: float = REPLY_TIMEOUT_S) -> None:
        """Consume responses until one 'ok' arrives (or GRBL complains)."""
        deadline = time.monotonic() + timeout
        while True:
            if self._stop.is_set():
                raise _Stopped()
            line = ser.readline().decode("ascii", "replace").strip()
            if not line:
                if time.monotonic() > deadline:
                    raise PlotterError("GRBLから応答がありません(タイムアウト)。"
                                       "ボーレートと配線を確認してください。")
                continue
            if line.startswith("ok"):
                if pending:
                    pending.popleft()
                return
            if line.startswith("error") or "ALARM" in line:
                raise PlotterError(f"GRBLがエラーを返しました: {line}")
            log.info("GRBL: %s", line)           # [MSG:...], <status>, ...

    def _abort(self, ser: serial.Serial, pen_up_cmd: str) -> None:
        """Best effort: halt, clear the queue, and get the pen off the paper."""
        try:
            ser.write(b"!")                      # feed hold
            time.sleep(0.4)
            ser.write(b"\x18")                   # soft reset: drops the queue
            time.sleep(1.0)
            ser.reset_input_buffer()
            ser.write(b"$X\n")                   # clear the reset's alarm
            time.sleep(0.3)
            ser.write((pen_up_cmd + "\n").encode("ascii", "replace"))
            time.sleep(0.3)
        except Exception:
            log.exception("abort cleanup failed")


plotter = Plotter()
