import argparse
from pathlib import Path
import subprocess
import sys
import time

BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
if str(BASE_DIR) not in sys.path:
  sys.path.insert(0, str(BASE_DIR))


def run_backend():
  import gc_backend

  bridge = gc_backend.GameCubeUSBBackend(broadcast_udp=True)
  print(
      "Mandos virtuales activos:"
      f" {bool(bridge.vpad_p1 and bridge.vpad_p1.enabled)}"
  )
  try:
    while True:
      cycle_start = time.perf_counter()

      if not bridge.claimed:
        try:
          bridge.connect()
        except (RuntimeError, gc_backend.usb.core.USBError) as exc:
          if not bridge._waiting_logged:
            print(f"Esperando adaptador WUP-028: {exc}")
            bridge._waiting_logged = True
          time.sleep(gc_backend.RECONNECT_DELAY_SEC)
          continue

      ok = bridge.read_ports()
      if not ok:
        time.sleep(gc_backend.RECONNECT_DELAY_SEC)
        continue

      elapsed = time.perf_counter() - cycle_start
      remaining = gc_backend.LOOP_INTERVAL_SEC - elapsed
      if remaining > 0:
        time.sleep(remaining)
  except KeyboardInterrupt:
    pass
  finally:
    bridge.shutdown()


def run_overlay():
  import tkinter as tk
  import gc_overlay_ui

  root = tk.Tk()
  root.withdraw()

  saved_pos = gc_overlay_ui.load_saved_positions()
  overlays = []

  def shutdown_all():
    gc_overlay_ui.save_positions(overlays)
    for ov in overlays:
      ov.close()
    try:
      root.destroy()
    except tk.TclError:
      pass

  root.protocol("WM_DELETE_WINDOW", shutdown_all)

  p1_x, p1_y = gc_overlay_ui._resolve_pos(saved_pos, "1", 40, 40)
  fallback_p2_y = (
      p1_y
      + max(1, int(round(120 * gc_overlay_ui.SCALE)))
      + max(6, int(round(12 * gc_overlay_ui.SCALE)))
  )
  p2_x, p2_y = gc_overlay_ui._resolve_pos(saved_pos, "2", p1_x, fallback_p2_y)

  ov1 = gc_overlay_ui.GameCubeSquareOverlay(
      tk.Toplevel(root),
      root,
      player=1,
      port=49152,
      x=p1_x,
      y=p1_y,
      scale=gc_overlay_ui.SCALE,
      on_request_close=shutdown_all,
  )
  ov2 = gc_overlay_ui.GameCubeSquareOverlay(
      tk.Toplevel(root),
      root,
      player=2,
      port=49153,
      x=p2_x,
      y=p2_y,
      scale=gc_overlay_ui.SCALE,
      on_request_close=shutdown_all,
  )
  overlays.extend([ov1, ov2])

  try:
    root.mainloop()
  finally:
    gc_overlay_ui.save_positions(overlays)
    for ov in overlays:
      ov.close()


def _child_command(flag: str):
  if getattr(sys, "frozen", False):
    return [sys.executable, flag]
  return [sys.executable, str(Path(__file__).resolve()), flag]


def main():
  parser = argparse.ArgumentParser(add_help=False)
  parser.add_argument("--run-backend", action="store_true")
  parser.add_argument("--run-overlay", action="store_true")
  args, _ = parser.parse_known_args()

  if args.run_backend:
    run_backend()
    return
  if args.run_overlay:
    run_overlay()
    return

  backend_proc = subprocess.Popen(_child_command("--run-backend"))
  time.sleep(0.4)
  overlay_proc = subprocess.Popen(_child_command("--run-overlay"))

  try:
    while True:
      if overlay_proc.poll() is not None or backend_proc.poll() is not None:
        break
      time.sleep(0.25)
  except KeyboardInterrupt:
    pass
  finally:
    for proc in (overlay_proc, backend_proc):
      if proc.poll() is None:
        proc.terminate()
        try:
          proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
          proc.kill()


if __name__ == "__main__":
  main()