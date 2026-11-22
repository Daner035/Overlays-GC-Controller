import tkinter as tk
from gc_backend import GameCubeUSBBackend


def clamp(val, low, high):
  return max(low, min(high, val))


class GameCubeSquareOverlay:

  def __init__(self, root: tk.Tk):
    self.root = root
    self.root.title("GC Input Overlay")
    self.root.attributes("-topmost", True)
    self.root.overrideredirect(True)
    self.root.configure(bg="#000000")
    # Hace que el color #000000 sea totalmente transparente en Windows
    self.root.attributes("-transparentcolor", "#000000")

    self.width = 255
    self.height = 120
    self.root.geometry(f"{self.width}x{self.height}+40+40")

    # Arrastrar con clic izquierdo; cerrar con clic derecho o Esc
    self._drag_x = 0
    self._drag_y = 0
    for widget_or_canvas in (self.root,):
      widget_or_canvas.bind("<ButtonPress-1>", self._start_drag)
      widget_or_canvas.bind("<B1-Motion>", self._do_drag)
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

    self.backend = GameCubeUSBBackend()
    self._init_usb()
    self._poll_loop()

  def _start_drag(self, event):
    self._drag_x = event.x
    self._drag_y = event.y

  def _do_drag(self, event):
    x = self.root.winfo_x() + (event.x - self._drag_x)
    y = self.root.winfo_y() + (event.y - self._drag_y)
    self.root.geometry(f"+{x}+{y}")

  def _draw_layout(self):
    c = self.canvas

    # --- Gatillos L y R ---
    c.create_rectangle(10, 8, 66, 15, outline="#ffffff", width=1)
    self.l_bar = c.create_rectangle(11, 9, 11, 14, fill="#ffffff", width=0)
    self.l_click = c.create_rectangle(60, 9, 65, 14, fill="", outline="")

    c.create_rectangle(78, 8, 134, 15, outline="#ffffff", width=1)
    self.r_bar = c.create_rectangle(133, 9, 133, 14, fill="#ffffff", width=0)
    self.r_click = c.create_rectangle(79, 9, 84, 14, fill="", outline="")

    # --- Control Stick (cuadrado blanco) ---
    self.ls_x0, self.ls_y0, self.ls_x1, self.ls_y1 = 10, 21, 66, 77
    c.create_rectangle(
        self.ls_x0, self.ls_y0, self.ls_x1, self.ls_y1, outline="#ffffff", width=2
    )
    ls_mid_x = (self.ls_x0 + self.ls_x1) // 2
    ls_mid_y = (self.ls_y0 + self.ls_y1) // 2
    c.create_rectangle(
        ls_mid_x - 1, ls_mid_y - 1, ls_mid_x + 1, ls_mid_y + 1, fill="#888888", width=0
    )
    self.ls_box = c.create_rectangle(
        ls_mid_x - 4, ls_mid_y - 4, ls_mid_x + 4, ls_mid_y + 4,
        fill="#ffffff", outline="#ffffff", width=1
    )

    # --- C-Stick (cuadrado amarillo) ---
    self.cs_x0, self.cs_y0, self.cs_x1, self.cs_y1 = 78, 25, 124, 71
    c.create_rectangle(
        self.cs_x0, self.cs_y0, self.cs_x1, self.cs_y1, outline="#ffe600", width=2
    )
    cs_mid_x = (self.cs_x0 + self.cs_x1) // 2
    cs_mid_y = (self.cs_y0 + self.cs_y1) // 2
    self.cs_box = c.create_rectangle(
        cs_mid_x - 5, cs_mid_y - 5, cs_mid_x + 5, cs_mid_y + 5,
        fill="#ffe600", outline="#ffe600", width=1
    )

    # --- D-Pad (4 cuadrados compactos abajo) ---
    self.dpad_rects = {
        "D-Up": c.create_rectangle(62, 82, 73, 93, outline="#ffffff", fill="", width=1),
        "D-Down": c.create_rectangle(62, 104, 73, 115, outline="#ffffff", fill="", width=1),
        "D-Left": c.create_rectangle(51, 93, 62, 104, outline="#ffffff", fill="", width=1),
        "D-Right": c.create_rectangle(73, 93, 84, 104, outline="#ffffff", fill="", width=1),
    }

    # --- Botones principales (B separado de A) ---
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
        10, 113, text="Conectando...", fill="#aaaaaa", font=("Consolas", 6), anchor="w"
    )

  def _init_usb(self):
    try:
      self.backend.connect()
      self.canvas.itemconfig(self.status_text, text="P1")
    except Exception as exc:
      self.canvas.itemconfig(
          self.status_text, text=f"Error: {exc}", fill="#ff5555"
      )

  def _update_visuals(self, state):
    c = self.canvas
    btns = set(state["botones"])

    # 1. Control Stick
    sx, sy = state["stick"]
    nx = clamp((sx - 128) / 95.0, -1.0, 1.0)
    ny = clamp((128 - sy) / 95.0, -1.0, 1.0)
    max_ls = ((self.ls_x1 - self.ls_x0) // 2) - 5
    cx_ls = ((self.ls_x0 + self.ls_x1) // 2) + nx * max_ls
    cy_ls = ((self.ls_y0 + self.ls_y1) // 2) + ny * max_ls
    c.coords(self.ls_box, cx_ls - 4, cy_ls - 4, cx_ls + 4, cy_ls + 4)

    # 2. C-Stick
    cx_val, cy_val = state["c_stick"]
    cnx = clamp((cx_val - 128) / 95.0, -1.0, 1.0)
    cny = clamp((128 - cy_val) / 95.0, -1.0, 1.0)
    max_cs = ((self.cs_x1 - self.cs_x0) // 2) - 7
    cx_cs = ((self.cs_x0 + self.cs_x1) // 2) + cnx * max_cs
    cy_cs = ((self.cs_y0 + self.cs_y1) // 2) + cny * max_cs
    c.coords(self.cs_box, cx_cs - 5, cy_cs - 5, cx_cs + 5, cy_cs + 5)

    # 3. Gatillos L y R
    l_ratio = clamp((state["l_analog"] - 30) / 195.0, 0.0, 1.0)
    r_ratio = clamp((state["r_analog"] - 30) / 195.0, 0.0, 1.0)
    c.coords(self.l_bar, 11, 9, 11 + int(47 * l_ratio), 14)
    c.coords(self.r_bar, 133 - int(47 * r_ratio), 9, 133, 14)
    c.itemconfig(self.l_click, fill="#ffffff" if "L" in btns else "")
    c.itemconfig(self.r_click, fill="#ffffff" if "R" in btns else "")

    # 4. Botones principales
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

    # 5. D-Pad
    for direction, rect_id in self.dpad_rects.items():
      c.itemconfig(rect_id, fill="#00e59b" if direction in btns else "")

  def _poll_loop(self):
    if self.backend.claimed:
      try:
        parsed = self.backend.read_port1()
        if parsed:
          self._update_visuals(parsed)
      except Exception as exc:
        self.canvas.itemconfig(
            self.status_text, text=f"Error USB: {exc}", fill="#ff5555"
        )
        self.backend.close()

    self.root.after(8, self._poll_loop)

  def on_close(self):
    self.backend.close()
    self.root.destroy()


if __name__ == "__main__":
  root = tk.Tk()
  app = GameCubeSquareOverlay(root)
  root.mainloop()