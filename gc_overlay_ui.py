import argparse
import ctypes
import json
import socket
import tkinter as tk

HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010

# Ajusta este valor (ej. 0.85 = 85%, 0.80 = 80%, 0.90 = 90%)
SCALE = 0.75


def clamp(val, low, high):
  return max(low, min(high, val))


class GameCubeSquareOverlay:

  def __init__(
      self,
      win: tk.Misc,
      app_root: tk.Tk,
      player: int = 1,
      port: int = 49152,
      x: int = 40,
      y: int = 40,
      scale: float = SCALE,
  ):
    self.win = win
    self.app_root = app_root
    self.player = player
    self.port = port
    self.scale = scale

    self.win.title(f"GC Input Overlay P{player}")
    self.win.attributes("-topmost", True)
    self.win.overrideredirect(True)
    self.win.configure(bg="#000000")
    self.win.attributes("-transparentcolor", "#000000")

    self.width = self._s(255)
    self.height = self._s(120)
    self.win.geometry(f"{self.width}x{self.height}+{x}+{y}")

    self._drag_x = 0
    self._drag_y = 0
    self._topmost_tick = 0
    self._last_raw = None
    self._last_state = None
    self._closed = False

    self.win.bind("<ButtonPress-1>", self._start_drag)
    self.win.bind("<B1-Motion>", self._do_drag)
    self.win.bind("<Button-3>", lambda _e: self.app_root.destroy())
    self.win.bind("<Escape>", lambda _e: self.app_root.destroy())

    self.canvas = tk.Canvas(
        win,
        width=self.width,
        height=self.height,
        bg="#000000",
        highlightthickness=0,
    )
    self.canvas.pack(fill="both", expand=True)
    self.canvas.bind("<ButtonPress-1>", self._start_drag)
    self.canvas.bind("<B1-Motion>", self._do_drag)

    self._draw_layout()
    self._force_topmost()

    self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.sock.bind(("127.0.0.1", self.port))
    self.sock.setblocking(False)

    self._poll_loop()

  def _s(self, val: float) -> int:
    return max(1, int(round(val * self.scale)))

  def _font(self, size: int, bold: bool = False):
    fsize = max(5, int(round(size * self.scale)))
    return ("Consolas", fsize, "bold") if bold else ("Consolas", fsize)

  def _force_topmost(self):
    if self._closed:
      return
    self.win.attributes("-topmost", True)
    try:
      hwnd = (
          ctypes.windll.user32.GetParent(self.win.winfo_id())
          or self.win.winfo_id()
      )
      ctypes.windll.user32.SetWindowPos(
          hwnd,
          HWND_TOPMOST,
          0,
          0,
          0,
          0,
          SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
      )
    except Exception:
      pass

  def _start_drag(self, event):
    self._drag_x = event.x
    self._drag_y = event.y

  def _do_drag(self, event):
    x = self.win.winfo_x() + (event.x - self._drag_x)
    y = self.win.winfo_y() + (event.y - self._drag_y)
    self.win.geometry(f"+{x}+{y}")

  def _draw_layout(self):
    c = self.canvas
    s = self._s

    c.create_rectangle(s(10), s(8), s(66), s(15), outline="#ffffff", width=1)
    self.l_bar = c.create_rectangle(
        s(11), s(9), s(11), s(14), fill="#ffffff", width=0
    )
    self.l_click = c.create_rectangle(
        s(60), s(9), s(65), s(14), fill="", outline=""
    )

    c.create_rectangle(s(78), s(8), s(134), s(15), outline="#ffffff", width=1)
    self.r_bar = c.create_rectangle(
        s(133), s(9), s(133), s(14), fill="#ffffff", width=0
    )
    self.r_click = c.create_rectangle(
        s(79), s(9), s(84), s(14), fill="", outline=""
    )

    self.ls_x0, self.ls_y0, self.ls_x1, self.ls_y1 = (
        s(10),
        s(21),
        s(66),
        s(77),
    )
    c.create_rectangle(
        self.ls_x0, self.ls_y0, self.ls_x1, self.ls_y1, outline="#ffffff", width=2
    )
    self.ls_mid_x = (self.ls_x0 + self.ls_x1) // 2
    self.ls_mid_y = (self.ls_y0 + self.ls_y1) // 2
    self.max_ls = ((self.ls_x1 - self.ls_x0) // 2) - s(5)
    self.ls_half = s(4)
    c.create_rectangle(
        self.ls_mid_x - s(1),
        self.ls_mid_y - s(1),
        self.ls_mid_x + s(1),
        self.ls_mid_y + s(1),
        fill="#888888",
        width=0,
    )
    self.ls_box = c.create_rectangle(
        self.ls_mid_x - self.ls_half,
        self.ls_mid_y - self.ls_half,
        self.ls_mid_x + self.ls_half,
        self.ls_mid_y + self.ls_half,
        fill="#ffffff",
        outline="#ffffff",
        width=1,
    )

    self.cs_x0, self.cs_y0, self.cs_x1, self.cs_y1 = (
        s(78),
        s(25),
        s(124),
        s(71),
    )
    c.create_rectangle(
        self.cs_x0, self.cs_y0, self.cs_x1, self.cs_y1, outline="#ffe600", width=2
    )
    self.cs_mid_x = (self.cs_x0 + self.cs_x1) // 2
    self.cs_mid_y = (self.cs_y0 + self.cs_y1) // 2
    self.max_cs = ((self.cs_x1 - self.cs_x0) // 2) - s(7)
    self.cs_half = s(5)
    self.cs_box = c.create_rectangle(
        self.cs_mid_x - self.cs_half,
        self.cs_mid_y - self.cs_half,
        self.cs_mid_x + self.cs_half,
        self.cs_mid_y + self.cs_half,
        fill="#ffe600",
        outline="#ffe600",
        width=1,
    )

    self.dpad_rects = {
        "D-Up": c.create_rectangle(
            s(62), s(82), s(73), s(93), outline="#ffffff", fill="", width=1
        ),
        "D-Down": c.create_rectangle(
            s(62), s(104), s(73), s(115), outline="#ffffff", fill="", width=1
        ),
        "D-Left": c.create_rectangle(
            s(51), s(93), s(62), s(104), outline="#ffffff", fill="", width=1
        ),
        "D-Right": c.create_rectangle(
            s(73), s(93), s(84), s(104), outline="#ffffff", fill="", width=1
        ),
    }

    self.btn_rects = {
        "Start": c.create_rectangle(
            s(144), s(46), s(155), s(57), outline="#ffffff", fill="", width=1
        ),
        "A": c.create_rectangle(
            s(166), s(42), s(198), s(74), outline="#00e59b", fill="", width=2
        ),
        "B": c.create_rectangle(
            s(136), s(80), s(158), s(102), outline="#ff1e1e", fill="", width=2
        ),
        "X": c.create_rectangle(
            s(208), s(44), s(226), s(66), outline="#ffffff", fill="", width=1
        ),
        "Y": c.create_rectangle(
            s(170), s(20), s(196), s(36), outline="#ffffff", fill="", width=1
        ),
        "Z": c.create_rectangle(
            s(206), s(9), s(234), s(25), outline="#b86bff", fill="", width=1
        ),
    }

    c.create_text(
        s(182), s(58), text="A", fill="#00e59b", font=self._font(8, bold=True)
    )
    c.create_text(
        s(147), s(91), text="B", fill="#ff1e1e", font=self._font(7, bold=True)
    )
    c.create_text(
        s(217), s(55), text="X", fill="#ffffff", font=self._font(7, bold=True)
    )
    c.create_text(
        s(183), s(28), text="Y", fill="#ffffff", font=self._font(7, bold=True)
    )
    c.create_text(
        s(220), s(17), text="Z", fill="#b86bff", font=self._font(7, bold=True)
    )
    c.create_text(
        s(149), s(51), text="S", fill="#ffffff", font=self._font(6, bold=True)
    )

    self.status_text = c.create_text(
        s(10),
        s(113),
        text=f"P{self.player} esperando UDP...",
        fill="#aaaaaa",
        font=self._font(6),
        anchor="w",
    )

  def _update_visuals(self, state):
    key = (
        tuple(state.get("botones", ())),
        tuple(state.get("stick", (128, 128))),
        tuple(state.get("c_stick", (128, 128))),
        state.get("l_analog", 0),
        state.get("r_analog", 0),
    )
    if key == self._last_state:
      return
    self._last_state = key

    c = self.canvas
    s = self._s
    btns = set(key[0])

    sx, sy = key[1]
    nx = clamp((sx - 128) / 95.0, -1.0, 1.0)
    ny = clamp((128 - sy) / 95.0, -1.0, 1.0)
    cx_ls = self.ls_mid_x + nx * self.max_ls
    cy_ls = self.ls_mid_y + ny * self.max_ls
    c.coords(
        self.ls_box,
        cx_ls - self.ls_half,
        cy_ls - self.ls_half,
        cx_ls + self.ls_half,
        cy_ls + self.ls_half,
    )

    cx_val, cy_val = key[2]
    cnx = clamp((cx_val - 128) / 80.0, -1.0, 1.0)
    cny = clamp((128 - cy_val) / 80.0, -1.0, 1.0)
    cx_cs = self.cs_mid_x + cnx * self.max_cs
    cy_cs = self.cs_mid_y + cny * self.max_cs
    c.coords(
        self.cs_box,
        cx_cs - self.cs_half,
        cy_cs - self.cs_half,
        cx_cs + self.cs_half,
        cy_cs + self.cs_half,
    )

    l_ratio = clamp((key[3] - 35) / 185.0, 0.0, 1.0)
    r_ratio = clamp((key[4] - 35) / 185.0, 0.0, 1.0)
    c.coords(self.l_bar, s(11), s(9), s(11 + 47 * l_ratio), s(14))
    c.coords(self.r_bar, s(133 - 47 * r_ratio), s(9), s(133), s(14))
    c.itemconfig(self.l_click, fill="#ffffff" if "L" in btns else "")
    c.itemconfig(self.r_click, fill="#ffffff" if "R" in btns else "")

    colors = {
        "A": "#00e59b",
        "B": "#ff1e1e",
        "X": "#ffffff",
        "Y": "#ffffff",
        "Z": "#b86bff",
        "Start": "#ffffff",
    }
    for name, rect_id in self.btn_rects.items():
      c.itemconfig(rect_id, fill=colors[name] if name in btns else "")

    for direction, rect_id in self.dpad_rects.items():
      c.itemconfig(rect_id, fill="#00e59b" if direction in btns else "")

  def _poll_loop(self):
    if self._closed:
      return

    self._topmost_tick += 1
    if self._topmost_tick % 300 == 0:
      self._force_topmost()

    latest = None
    while True:
      try:
        raw, _addr = self.sock.recvfrom(4096)
        latest = raw
      except BlockingIOError:
        break
      except OSError:
        break

    if latest is not None and latest != self._last_raw:
      self._last_raw = latest
      try:
        state = json.loads(latest.decode("utf-8"))
        self.canvas.itemconfig(
            self.status_text, text=f"P{self.player} LIVE", fill="#00e59b"
        )
        self._update_visuals(state)
      except Exception:
        pass

    self.win.after(16, self._poll_loop)

  def close(self):
    self._closed = True
    try:
      self.sock.close()
    except OSError:
      pass


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="GC Input Overlay")
  parser.add_argument(
      "--player",
      type=int,
      default=0,
      help="0 = ambos (P1 y P2), 1 = solo P1, 2 = solo P2",
  )
  parser.add_argument("--port", type=int, default=0, help="Puerto UDP opcional")
  parser.add_argument("--x", type=int, default=40, help="Posición inicial X")
  parser.add_argument("--y", type=int, default=40, help="Posición inicial Y")
  parser.add_argument(
      "--scale",
      type=float,
      default=SCALE,
      help="Escala visual (ej. 0.85 para hacerlo más pequeño)",
  )
  args = parser.parse_args()

  root = tk.Tk()
  root.withdraw()

  overlays = []

  def shutdown_all():
    for ov in overlays:
      ov.close()
    try:
      root.destroy()
    except tk.TclError:
      pass

  root.protocol("WM_DELETE_WINDOW", shutdown_all)

  if args.player == 1:
    p1_port = args.port if args.port else 49152
    overlays.append(
        GameCubeSquareOverlay(
            root,
            root,
            player=1,
            port=p1_port,
            x=args.x,
            y=args.y,
            scale=args.scale,
        )
    )
  elif args.player == 2:
    p2_port = args.port if args.port else 49153
    overlays.append(
        GameCubeSquareOverlay(
            root,
            root,
            player=2,
            port=p2_port,
            x=args.x,
            y=args.y,
            scale=args.scale,
        )
    )
  else:
    ov1 = GameCubeSquareOverlay(
        tk.Toplevel(root),
        root,
        player=1,
        port=49152,
        x=args.x,
        y=args.y,
        scale=args.scale,
    )
    ov2 = GameCubeSquareOverlay(
        tk.Toplevel(root),
        root,
        player=2,
        port=49153,
        x=args.x,
        y=args.y + ov1.height + max(6, int(round(12 * args.scale))),
        scale=args.scale,
    )
    overlays.extend([ov1, ov2])

  try:
    root.mainloop()
  finally:
    for ov in overlays:
      ov.close()