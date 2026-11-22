import argparse
import ctypes
import json
import socket
import tkinter as tk

HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010


def clamp(val, low, high):
  return max(low, min(high, val))


class GameCubeSquareOverlay:

  def __init__(
      self,
      root: tk.Tk,
      player: int = 1,
      port: int = 49152,
      x: int = 40,
      y: int = 40,
  ):
    self.root = root
    self.player = player
    self.port = port

    self.root.title(f"GC Input Overlay P{player}")
    self.root.attributes("-topmost", True)
    self.root.overrideredirect(True)
    self.root.configure(bg="#000000")
    self.root.attributes("-transparentcolor", "#000000")

    self.width = 255
    self.height = 120
    self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")

    self._drag_x = 0
    self._drag_y = 0
    self._topmost_tick = 0
    self._last_raw = None
    self._last_state = None

    self.root.bind("<ButtonPress-1>", self._start_drag)
    self.root.bind("<B1-Motion>", self._do_drag)
    self.root.bind("<Button-3>", lambda _e: self.on_close())
    self.root.bind("<Escape>", lambda _e: self.on_close())

    self.canvas = tk.Canvas(
        root,
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

  def _force_topmost(self):
    self.root.attributes("-topmost", True)
    try:
      hwnd = (
          ctypes.windll.user32.GetParent(self.root.winfo_id())
          or self.root.winfo_id()
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
    x = self.root.winfo_x() + (event.x - self._drag_x)
    y = self.root.winfo_y() + (event.y - self._drag_y)
    self.root.geometry(f"+{x}+{y}")

  def _draw_layout(self):
    c = self.canvas

    c.create_rectangle(10, 8, 66, 15, outline="#ffffff", width=1)
    self.l_bar = c.create_rectangle(11, 9, 11, 14, fill="#ffffff", width=0)
    self.l_click = c.create_rectangle(60, 9, 65, 14, fill="", outline="")

    c.create_rectangle(78, 8, 134, 15, outline="#ffffff", width=1)
    self.r_bar = c.create_rectangle(133, 9, 133, 14, fill="#ffffff", width=0)
    self.r_click = c.create_rectangle(79, 9, 84, 14, fill="", outline="")

    self.ls_x0, self.ls_y0, self.ls_x1, self.ls_y1 = 10, 21, 66, 77
    c.create_rectangle(
        self.ls_x0, self.ls_y0, self.ls_x1, self.ls_y1, outline="#ffffff", width=2
    )
    self.ls_mid_x = (self.ls_x0 + self.ls_x1) // 2
    self.ls_mid_y = (self.ls_y0 + self.ls_y1) // 2
    self.max_ls = ((self.ls_x1 - self.ls_x0) // 2) - 5
    c.create_rectangle(
        self.ls_mid_x - 1,
        self.ls_mid_y - 1,
        self.ls_mid_x + 1,
        self.ls_mid_y + 1,
        fill="#888888",
        width=0,
    )
    self.ls_box = c.create_rectangle(
        self.ls_mid_x - 4,
        self.ls_mid_y - 4,
        self.ls_mid_x + 4,
        self.ls_mid_y + 4,
        fill="#ffffff",
        outline="#ffffff",
        width=1,
    )

    self.cs_x0, self.cs_y0, self.cs_x1, self.cs_y1 = 78, 25, 124, 71
    c.create_rectangle(
        self.cs_x0, self.cs_y0, self.cs_x1, self.cs_y1, outline="#ffe600", width=2
    )
    self.cs_mid_x = (self.cs_x0 + self.cs_x1) // 2
    self.cs_mid_y = (self.cs_y0 + self.cs_y1) // 2
    self.max_cs = ((self.cs_x1 - self.cs_x0) // 2) - 7
    self.cs_box = c.create_rectangle(
        self.cs_mid_x - 5,
        self.cs_mid_y - 5,
        self.cs_mid_x + 5,
        self.cs_mid_y + 5,
        fill="#ffe600",
        outline="#ffe600",
        width=1,
    )

    self.dpad_rects = {
        "D-Up": c.create_rectangle(62, 82, 73, 93, outline="#ffffff", fill="", width=1),
        "D-Down": c.create_rectangle(62, 104, 73, 115, outline="#ffffff", fill="", width=1),
        "D-Left": c.create_rectangle(51, 93, 62, 104, outline="#ffffff", fill="", width=1),
        "D-Right": c.create_rectangle(73, 93, 84, 104, outline="#ffffff", fill="", width=1),
    }

    self.btn_rects = {
        "Start": c.create_rectangle(144, 46, 155, 57, outline="#ffffff", fill="", width=1),
        "A": c.create_rectangle(166, 42, 198, 74, outline="#00e59b", fill="", width=2),
        "B": c.create_rectangle(136, 80, 158, 102, outline="#ff1e1e", fill="", width=2),
        "X": c.create_rectangle(208, 44, 226, 66, outline="#ffffff", fill="", width=1),
        "Y": c.create_rectangle(170, 20, 196, 36, outline="#ffffff", fill="", width=1),
        "Z": c.create_rectangle(206, 9, 234, 25, outline="#b86bff", fill="", width=1),
    }

    c.create_text(182, 58, text="A", fill="#00e59b", font=("Consolas", 8, "bold"))
    c.create_text(147, 91, text="B", fill="#ff1e1e", font=("Consolas", 7, "bold"))
    c.create_text(217, 55, text="X", fill="#ffffff", font=("Consolas", 7, "bold"))
    c.create_text(183, 28, text="Y", fill="#ffffff", font=("Consolas", 7, "bold"))
    c.create_text(220, 17, text="Z", fill="#b86bff", font=("Consolas", 7, "bold"))
    c.create_text(149, 51, text="S", fill="#ffffff", font=("Consolas", 6, "bold"))

    self.status_text = c.create_text(
        10,
        113,
        text=f"P{self.player} esperando UDP...",
        fill="#aaaaaa",
        font=("Consolas", 6),
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
    btns = set(key[0])

    sx, sy = key[1]
    nx = clamp((sx - 128) / 95.0, -1.0, 1.0)
    ny = clamp((128 - sy) / 95.0, -1.0, 1.0)
    cx_ls = self.ls_mid_x + nx * self.max_ls
    cy_ls = self.ls_mid_y + ny * self.max_ls
    c.coords(self.ls_box, cx_ls - 4, cy_ls - 4, cx_ls + 4, cy_ls + 4)

    cx_val, cy_val = key[2]
    cnx = clamp((cx_val - 128) / 80.0, -1.0, 1.0)
    cny = clamp((128 - cy_val) / 80.0, -1.0, 1.0)
    cx_cs = self.cs_mid_x + cnx * self.max_cs
    cy_cs = self.cs_mid_y + cny * self.max_cs
    c.coords(self.cs_box, cx_cs - 5, cy_cs - 5, cx_cs + 5, cy_cs + 5)

    l_ratio = clamp((key[3] - 35) / 185.0, 0.0, 1.0)
    r_ratio = clamp((key[4] - 35) / 185.0, 0.0, 1.0)
    c.coords(self.l_bar, 11, 9, 11 + int(47 * l_ratio), 14)
    c.coords(self.r_bar, 133 - int(47 * r_ratio), 9, 133, 14)
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

    self.root.after(16, self._poll_loop)

  def on_close(self):
    try:
      self.sock.close()
    except OSError:
      pass
    self.root.destroy()


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="GC Input Overlay")
  parser.add_argument("--player", type=int, default=1, help="Número de jugador (1 o 2)")
  parser.add_argument("--port", type=int, default=49152, help="Puerto UDP local")
  parser.add_argument("--x", type=int, default=40, help="Posición inicial X")
  parser.add_argument("--y", type=int, default=40, help="Posición inicial Y")
  args = parser.parse_args()

  root = tk.Tk()
  app = GameCubeSquareOverlay(
      root, player=args.player, port=args.port, x=args.x, y=args.y
  )
  root.mainloop()