"""GRBL machine probe: read the controller's settings, and optionally jog it.

Why: the G-code we emit is plain absolute mm, so when the machine goes
somewhere the file never asked for, the mismatch is in the controller —
kinematics, steps/mm, or a stale work offset. This asks the machine.

    uv run python scripts/grbl_probe.py                 # settings only, no motion
    uv run python scripts/grbl_probe.py --jog X 50      # move +50mm in X
    uv run python scripts/grbl_probe.py --jog Y 50      # move +50mm in Y

The jog is the CoreXY test. On a correctly configured machine "--jog X 50"
moves the pen 50mm to the right and nothing else. If it instead travels
diagonally at 45° (about 35mm right and 35mm back), the belts are wired
CoreXY but the firmware is a plain Cartesian build: every commanded
(x, y) comes out as ((x+y)/2, (x-y)/2).
"""
from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, ".")

import serial

from server.plotter import DEFAULT_BAUD, WAKE_WAIT_S, list_serial_ports

# Settings worth reading back on a pen plotter.
LABELS = {
    "$0": "ステップパルス幅 us", "$3": "方向反転マスク",
    "$20": "ソフトリミット", "$21": "ハードリミット", "$22": "ホーミング有効",
    "$30": "スピンドル最大S", "$31": "スピンドル最小S", "$32": "レーザーモード",
    "$100": "X steps/mm", "$101": "Y steps/mm", "$110": "X 最高速度 mm/min",
    "$111": "Y 最高速度 mm/min", "$120": "X 加速度", "$121": "Y 加速度",
    "$130": "X 可動範囲 mm", "$131": "Y 可動範囲 mm",
}


def talk(ser: serial.Serial, cmd: str, wait: float = 1.5) -> list[str]:
    ser.write((cmd + "\n").encode())
    deadline = time.monotonic() + wait
    out = []
    while time.monotonic() < deadline:
        line = ser.readline().decode("ascii", "replace").strip()
        if not line:
            continue
        if line.startswith("ok"):
            break
        if line.startswith("error"):
            out.append(line)
            break
        out.append(line)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port")
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    ap.add_argument("--jog", nargs=2, metavar=("AXIS", "MM"),
                    help="relative move, e.g. --jog X 50 (MOVES THE MACHINE)")
    args = ap.parse_args()

    port = args.port
    if not port:
        ports = list_serial_ports()
        if not ports:
            print("シリアルポートが見つかりません。USBを確認してください。")
            return 1
        port = ports[0]["device"]
        print(f"ポート: {port} ({ports[0]['description']})")

    with serial.Serial(port, args.baud, timeout=0.3) as ser:
        ser.write(b"\r\n\r\n")
        time.sleep(WAKE_WAIT_S)          # opening the port resets the board
        banner = ser.read_all().decode("ascii", "replace").strip()
        ser.reset_input_buffer()
        print(f"\n--- 接続 ---\n{banner}")

        print("\n--- ビルド情報 ($I) ---")
        for line in talk(ser, "$I"):
            print(f"  {line}")

        print("\n--- 設定 ($$) ---")
        for line in talk(ser, "$$", wait=3.0):
            key = line.split("=")[0]
            label = LABELS.get(key)
            print(f"  {line}" + (f"   ← {label}" if label else ""))

        print("\n--- 現在位置 (?) ---")
        ser.write(b"?")
        time.sleep(0.4)
        print(f"  {ser.read_all().decode('ascii', 'replace').strip()}")

        if args.jog:
            axis, mm = args.jog[0].upper(), float(args.jog[1])
            print(f"\n--- ジョグ: {axis} 方向に {mm}mm 動かします ---")
            input("  ペンを上げ、周囲の安全を確認したら Enter(中止は Ctrl-C): ")
            for cmd in ("G91", f"G0 {axis}{mm} F1000", "G90"):
                res = talk(ser, cmd, wait=20.0)
                print(f"  {cmd}" + (f" -> {res}" if res else " -> ok"))
            time.sleep(0.5)
            ser.write(b"?")
            time.sleep(0.4)
            print(f"  移動後: {ser.read_all().decode('ascii', 'replace').strip()}")
            print("\n  実際の動きは? 真横に50mm → 正常 / 斜め45°に約35mm →"
                  " CoreXY のキネマティクス不一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
