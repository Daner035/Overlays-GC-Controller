import tkinter as tk
from gc_backend import GameCubeUSBBackend, has_meaningful_change


class GameCubeOverlayApp:

  def __init__(self, root: tk.Tk):
    self.root = root
    self.root.title("GC Input Overlay")
    self.root.attributes("-topmost", True)
    self.root.overrideredirect(True)
    self.root.geometry("340x150+40+40")
    self.root.configure(bg="#141418")

    # Permitir arrastrar la ventana con clic izquierdo
    self._drag_x = 0
    self._drag_y = 0
    self.root.bind("<ButtonPress-1>", self._start_drag)
    self.root.bind("<B1-Motion>", self._do_drag)
    # Cerrar con Escape o doble clic derecho
    self.root.bind("<Escape>", lambda _e: self.on_close())

    self.status_var = tk.StringVar(value="Conectando WUP-028...")
    self.btns_var = tk.StringVar(value="Botones: -")
    self.sticks_var = tk.StringVar(
        value="Stick: (128, 128) | C: (128, 128)"
    )
    self.triggers_var = tk.StringVar(value="L/R: (0, 0)")

    header = tk.Frame(root, bg="#1e1e26")
    header.pack(fill="x", padx=6, pady=(6, 2))

    tk.Label(
        header,
        textvariable=self.status_var,
        fg="#9be7ff",
        bg="#1e1e26",
        font=("Consolas", 9, "bold"),
    ).pack(side="left", padx=4, pady=2)

    tk.Button(
        header,
        text="X",
        command=self.on_close,
        fg="#ffffff",
        bg="#8b2635",
        activebackground="#b33245",
        activeforeground="#ffffff",
        bd=0,
        width=2,
        font=("Consolas", 8, "bold"),
    ).pack(side="right", padx=4, pady=2)

    body = tk.Frame(root, bg="#141418")
    body.pack(fill="both", expand=True, padx=10, pady=4)

    tk.Label(
        body,
        textvariable=self.btns_var,
        fg="#f5f5f7",
        bg="#141418",
        font=("Consolas", 11, "bold"),
        anchor="w",
        justify="left",
        wraplength=315,
    ).pack(fill="x", pady=(2, 4))

    tk.Label(
        body,
        textvariable=self.sticks_var,
        fg="#a6f7b2",
        bg="#141418",
        font=("Consolas", 10),
        anchor="w",
    ).pack(fill="x", pady=2)

    tk.Label(
        body,
        textvariable=self.triggers_var,
        fg="#ffd166",
        bg="#141418",
        font=("Consolas", 9),
        anchor="w",
    ).pack(fill="x", pady=2)

    self.backend = GameCubeUSBBackend()
    self.last_state = None
    self._init_usb()
    self._poll_loop()

  def _start_drag(self, event):
    self._drag_x = event.x
    self._drag_y = event.y

  def _do_drag(self, event):
    x = self.root.winfo_x() + (event.x - self._drag_x)
    y = self.root.winfo_y() + (event.y - self._drag_y)
    self.root.geometry(f"+{x}+{y}")

  def _init_usb(self):
    try:
      self.backend.connect()
      self.status_var.set("WUP-028 conectado [Esc para salir]")
    except Exception as exc:
      self.status_var.set(f"Error USB: {exc}")

  def _poll_loop(self):
    if self.backend.claimed:
      try:
        parsed = self.backend.read_port1()
        if parsed and has_meaningful_change(
            self.last_state, parsed, deadzone=2
        ):
          self.last_state = parsed
          btns = ", ".join(parsed["botones"]) if parsed["botones"] else "-"
          sx, sy = parsed["stick"]
          cx, cy = parsed["c_stick"]
          self.btns_var.set(f"Botones: {btns}")
          self.sticks_var.set(f"Stick: ({sx}, {sy}) | C: ({cx}, {cy})")
          self.triggers_var.set(
              f"L/R Analógico: ({parsed['l_analog']}, {parsed['r_analog']})"
          )
      except Exception as exc:
        self.status_var.set(f"Lectura interrumpida: {exc}")
        self.backend.close()

    # ~120 Hz aprox. (8 ms) para baja latencia sin saturar la UI
    self.root.after(8, self._poll_loop)

  def on_close(self):
    self.backend.close()
    self.root.destroy()


if __name__ == "__main__":
  root = tk.Tk()
  app = GameCubeOverlayApp(root)
  root.mainloop()