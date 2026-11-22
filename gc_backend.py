import json
import socket
import time
import libusb_package
import usb.backend.libusb1
import usb.core
import usb.util

try:
  import vgamepad as vg

  HAS_VGAMEPAD = True
except Exception:
  vg = None
  HAS_VGAMEPAD = False

VID = 0x057E
PID = 0x0337
UDP_HOST = "127.0.0.1"
UDP_PORT_P1 = 49152
UDP_PORT_P2 = 49153

DEBUG_PORTS = False

TRIGGER_MIN = 35
TRIGGER_MAX = 220
TRIGGER_SPAN = max(1, TRIGGER_MAX - TRIGGER_MIN)

GC_TO_XUSB_BUTTONS = (
    ("A", "XUSB_GAMEPAD_B"),
    ("B", "XUSB_GAMEPAD_A"),
    ("X", "XUSB_GAMEPAD_Y"),
    ("Y", "XUSB_GAMEPAD_X"),
    ("Start", "XUSB_GAMEPAD_START"),
    ("Z", "XUSB_GAMEPAD_RIGHT_SHOULDER"),
    ("D-Up", "XUSB_GAMEPAD_DPAD_UP"),
    ("D-Down", "XUSB_GAMEPAD_DPAD_DOWN"),
    ("D-Left", "XUSB_GAMEPAD_DPAD_LEFT"),
    ("D-Right", "XUSB_GAMEPAD_DPAD_RIGHT"),
)


def clamp(val, low, high):
  return max(low, min(high, val))


def parse_gc_port(port_bytes):
  if len(port_bytes) < 9:
    return None

  status = port_bytes[0]
  if status == 0x00:
    return {
        "status": status,
        "botones": [],
        "stick": (128, 128),
        "c_stick": (128, 128),
        "l_analog": 0,
        "r_analog": 0,
    }

  b1 = port_bytes[1]
  b2 = port_bytes[2]

  botones = []
  if b1 & 0x01:
    botones.append("A")
  if b1 & 0x02:
    botones.append("B")
  if b1 & 0x04:
    botones.append("X")
  if b1 & 0x08:
    botones.append("Y")
  if b1 & 0x10:
    botones.append("D-Left")
  if b1 & 0x20:
    botones.append("D-Right")
  if b1 & 0x40:
    botones.append("D-Down")
  if b1 & 0x80:
    botones.append("D-Up")

  if b2 & 0x01:
    botones.append("Start")
  if b2 & 0x02:
    botones.append("Z")
  if b2 & 0x04:
    botones.append("R")
  if b2 & 0x08:
    botones.append("L")

  return {
      "status": status,
      "botones": botones,
      "stick": (port_bytes[3], port_bytes[4]),
      "c_stick": (port_bytes[5], port_bytes[6]),
      "l_analog": port_bytes[7],
      "r_analog": port_bytes[8],
  }


def has_meaningful_change(prev, curr, deadzone=1):
  if prev is None:
    return True
  if prev.get("status") != curr.get("status"):
    return True
  if prev["botones"] != curr["botones"]:
    return True
  if (
      abs(prev["stick"][0] - curr["stick"][0]) > deadzone
      or abs(prev["stick"][1] - curr["stick"][1]) > deadzone
  ):
    return True
  if (
      abs(prev["c_stick"][0] - curr["c_stick"][0]) > deadzone
      or abs(prev["c_stick"][1] - curr["c_stick"][1]) > deadzone
  ):
    return True
  if (
      abs(prev["l_analog"] - curr["l_analog"]) > deadzone
      or abs(prev["r_analog"] - curr["r_analog"]) > deadzone
  ):
    return True
  return False


class VirtualGamepadBridge:
  """Crea un mando virtual Xbox 360 temporal (ViGEmBus) mientras el proceso viva."""

  def __init__(self):
    self.enabled = HAS_VGAMEPAD
    self.pad = vg.VX360Gamepad() if HAS_VGAMEPAD else None
    self._button_map = (
        tuple(
            (gc_btn, getattr(vg.XUSB_BUTTON, x_btn_name))
            for gc_btn, x_btn_name in GC_TO_XUSB_BUTTONS
        )
        if HAS_VGAMEPAD
        else ()
    )

  def send_state(self, state):
    if not self.enabled or self.pad is None:
      return

    btns = set(state["botones"])

    for gc_btn, x_btn in self._button_map:
      if gc_btn in btns:
        self.pad.press_button(button=x_btn)
      else:
        self.pad.release_button(button=x_btn)

    sx, sy = state["stick"]
    lx = int(clamp((sx - 128) / 95.0, -1.0, 1.0) * 32767)
    ly = int(clamp((sy - 128) / 95.0, -1.0, 1.0) * 32767)
    self.pad.left_joystick(x_value=lx, y_value=ly)

    cx, cy = state["c_stick"]
    rx = int(clamp((cx - 128) / 80.0, -1.0, 1.0) * 32767)
    ry = int(clamp((cy - 128) / 80.0, -1.0, 1.0) * 32767)
    self.pad.right_joystick(x_value=rx, y_value=ry)

    l_val = int(
        clamp((state["l_analog"] - TRIGGER_MIN) / TRIGGER_SPAN, 0.0, 1.0) * 255
    )
    r_val = int(
        clamp((state["r_analog"] - TRIGGER_MIN) / TRIGGER_SPAN, 0.0, 1.0) * 255
    )

    if "L" in btns:
      l_val = 255
    if "R" in btns:
      r_val = 255

    self.pad.left_trigger(value=l_val)
    self.pad.right_trigger(value=r_val)

    self.pad.update()

  def close(self):
    if self.pad is not None:
      self.pad.reset()
      self.pad.update()
      self.pad = None


class GameCubeUSBBackend:

  def __init__(self, vid=VID, pid=PID, broadcast_udp=True):
    self.vid = vid
    self.pid = pid
    self.dev = None
    self.intf_num = None
    self.ep_out = None
    self.ep_in = None
    self.claimed = False

    self.vpad_p1 = VirtualGamepadBridge() if broadcast_udp else None
    self.vpad_p2 = VirtualGamepadBridge() if broadcast_udp else None

    self._udp_sock = None
    self._target_p1 = (UDP_HOST, UDP_PORT_P1)
    self._target_p2 = (UDP_HOST, UDP_PORT_P2)

    self._last_p1 = None
    self._last_p2 = None
    self._debug_tick = 0

    if broadcast_udp:
      self._udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

  def _find_endpoints(self):
    try:
      cfg = self.dev.get_active_configuration()
    except usb.core.USBError:
      self.dev.set_configuration()
      cfg = self.dev.get_active_configuration()

    for intf in cfg:
      ep_out = usb.util.find_descriptor(
          intf,
          custom_match=lambda e: (
              usb.util.endpoint_direction(e.bEndpointAddress)
              == usb.util.ENDPOINT_OUT
          ),
      )
      ep_in = usb.util.find_descriptor(
          intf,
          custom_match=lambda e: (
              usb.util.endpoint_direction(e.bEndpointAddress)
              == usb.util.ENDPOINT_IN
          ),
      )
      if ep_out is not None and ep_in is not None:
        return intf.bInterfaceNumber, ep_out, ep_in

    return None, None, None

  def connect(self):
    backend = usb.backend.libusb1.get_backend(
        find_library=libusb_package.find_library
    )
    if backend is None:
      raise RuntimeError("No se pudo cargar libusb.")

    self.dev = usb.core.find(
        idVendor=self.vid, idProduct=self.pid, backend=backend
    )
    if self.dev is None:
      raise RuntimeError("No se encontró el adaptador WUP-028 (057e:0337).")

    self.intf_num, self.ep_out, self.ep_in = self._find_endpoints()
    if (
        self.intf_num is None
        or self.ep_out is None
        or self.ep_in is None
    ):
      raise RuntimeError("No se encontraron endpoints IN/OUT válidos.")

    try:
      if self.dev.is_kernel_driver_active(self.intf_num):
        self.dev.detach_kernel_driver(self.intf_num)
    except (NotImplementedError, usb.core.USBError):
      pass

    usb.util.claim_interface(self.dev, self.intf_num)
    self.claimed = True
    self.ep_out.write([0x13], timeout=1000)

  def _process_player(self, raw_slice, player_num, last_state, vpad, target):
    parsed = parse_gc_port(raw_slice)
    if parsed and has_meaningful_change(last_state, parsed, deadzone=1):
      if vpad is not None:
        vpad.send_state(parsed)
      if self._udp_sock is not None:
        packet = {"player": player_num, **parsed}
        payload = json.dumps(packet).encode("utf-8")
        self._udp_sock.sendto(payload, target)
      return parsed
    return last_state

  def read_ports(self):
    if not self.claimed or self.ep_in is None:
      return
    try:
      data = self.ep_in.read(self.ep_in.wMaxPacketSize, timeout=15)
      if data and len(data) >= 19:
        if DEBUG_PORTS:
          self._debug_tick += 1
          if self._debug_tick % 60 == 0:
            print(
                f"len={len(data)} | P1={parse_gc_port(data[1:10])} | P2={parse_gc_port(data[10:19])}"
            )

        self._last_p1 = self._process_player(
            data[1:10], 1, self._last_p1, self.vpad_p1, self._target_p1
        )
        self._last_p2 = self._process_player(
            data[10:19], 2, self._last_p2, self.vpad_p2, self._target_p2
        )
    except usb.core.USBTimeoutError:
      pass

  def close(self):
    if self.claimed and self.dev is not None and self.intf_num is not None:
      try:
        usb.util.release_interface(self.dev, self.intf_num)
      except usb.core.USBError:
        pass
      self.claimed = False

  def shutdown(self):
    self.close()
    if self.vpad_p1 is not None:
      self.vpad_p1.close()
    if self.vpad_p2 is not None:
      self.vpad_p2.close()
    if self._udp_sock is not None:
      self._udp_sock.close()
      self._udp_sock = None


if __name__ == "__main__":
  bridge = GameCubeUSBBackend(broadcast_udp=True)
  print(f"Mandos virtuales activos: {bool(bridge.vpad_p1 and bridge.vpad_p1.enabled)}")
  try:
    bridge.connect()
    print("Leyendo WUP-028 (Puertos 1 y 2) y enviando a mandos virtuales + UDP...")
    while True:
      bridge.read_ports()
      time.sleep(0.006)
  except KeyboardInterrupt:
    pass
  finally:
    bridge.shutdown()