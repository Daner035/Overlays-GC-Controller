import libusb_package
import usb.backend.libusb1
import usb.core
import usb.util

VID = 0x057E
PID = 0x0337


def active_bits(byte_val):
  return [f"0x{1 << i:02x}" for i in range(8) if byte_val & (1 << i)]


def parse_gc_port(p1):
  if len(p1) < 9:
    return None

  b1 = p1[1]
  b2 = p1[2]

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
      "status": p1[0],
      "botones": botones,
      "b1_bits": active_bits(b1),
      "b2_bits": active_bits(b2),
      "stick": (p1[3], p1[4]),
      "c_stick": (p1[5], p1[6]),
      "l_analog": p1[7],
      "r_analog": p1[8],
  }


def has_meaningful_change(prev, curr, deadzone=2):
  if prev is None:
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


class GameCubeUSBBackend:

  def __init__(self, vid=VID, pid=PID):
    self.vid = vid
    self.pid = pid
    self.dev = None
    self.intf_num = None
    self.ep_out = None
    self.ep_in = None
    self.claimed = False

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

  def read_port1(self):
    if not self.claimed or self.ep_in is None:
      return None
    try:
      data = self.ep_in.read(self.ep_in.wMaxPacketSize, timeout=15)
      if data and len(data) >= 10:
        return parse_gc_port(list(data[1:10]))
    except usb.core.USBTimeoutError:
      pass
    return None

  def close(self):
    if self.claimed and self.dev is not None and self.intf_num is not None:
      try:
        usb.util.release_interface(self.dev, self.intf_num)
      except usb.core.USBError:
        pass
      self.claimed = False