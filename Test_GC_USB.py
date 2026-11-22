import msvcrt
import libusb_package
import usb.backend.libusb1
import usb.core
import usb.util

VID = 0x057E
PID = 0x0337
STOP_KEY = b"q"  # Cambia a b"\x1b" si prefieres Esc


def get_endpoints(dev):
  try:
    cfg = dev.get_active_configuration()
  except usb.core.USBError:
    dev.set_configuration()
    cfg = dev.get_active_configuration()

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


def active_bits(byte_val):
  """Devuelve las máscaras de bits (0x01..0x80) encendidas en un byte."""
  return [f"0x{1 << i:02x}" for i in range(8) if byte_val & (1 << i)]


def parse_gc_port(p1):
  if len(p1) < 9:
    return None

  b1 = p1[1]
  b2 = p1[2]

  botones = []
  # Ajusta estas máscaras según lo que veas al pulsar cada botón en tu control
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
  if b2 & 0x10:
    botones.append("Z")
  if b2 & 0x20:
    botones.append("R")
  if b2 & 0x40:
    botones.append("L")
  if b2 & 0x80:
    botones.append("b2_0x80")

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
  if prev["b1_bits"] != curr["b1_bits"] or prev["b2_bits"] != curr["b2_bits"]:
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


def main():
  backend = usb.backend.libusb1.get_backend(
      find_library=libusb_package.find_library
  )
  if backend is None:
    print("No se pudo cargar libusb.")
    raise SystemExit(1)

  dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
  if dev is None:
    print("No se encontró el adaptador WUP-028 (057e:0337).")
    raise SystemExit(1)

  intf_num, ep_out, ep_in = get_endpoints(dev)
  if intf_num is None or ep_out is None or ep_in is None:
    print("No se encontraron endpoints IN/OUT válidos en el adaptador.")
    raise SystemExit(1)

  claimed = False
  try:
    try:
      if dev.is_kernel_driver_active(intf_num):
        dev.detach_kernel_driver(intf_num)
    except (NotImplementedError, usb.core.USBError):
      pass

    usb.util.claim_interface(dev, intf_num)
    claimed = True

    ep_out.write([0x13], timeout=1000)
    print(
        f"Conectado a WUP-028 (Interfaz {intf_num}, EP IN"
        f" {hex(ep_in.bEndpointAddress)})."
    )
    print(
        "Pulsa un botón a la vez para ver qué bit enciende. Presiona 'q' para"
        " salir..."
    )

    last_state = None
    while True:
      if msvcrt.kbhit():
        key = msvcrt.getch()
        if key.lower() == STOP_KEY:
          print("\nDeteniendo lectura por tecla 'q'...")
          break

      try:
        data = ep_in.read(ep_in.wMaxPacketSize, timeout=100)
        if data and len(data) >= 10:
          parsed = parse_gc_port(list(data[1:10]))
          if parsed and has_meaningful_change(last_state, parsed, deadzone=2):
            last_state = parsed
            btns = ", ".join(parsed["botones"]) if parsed["botones"] else "-"
            print(
                f"Botones: [{btns}] | b1={parsed['b1_bits']}"
                f" b2={parsed['b2_bits']} | StickL: {parsed['stick']} |"
                f" C-Stick: {parsed['c_stick']} | L/R:"
                f" ({parsed['l_analog']}, {parsed['r_analog']})"
            )
      except usb.core.USBTimeoutError:
        pass
  except usb.core.USBError as exc:
    print(f"Error USB al operar con WUP-028: {exc}")
    print(
        "Revisa que Dolphin/Eden esté cerrado y que el adaptador use WinUSB o"
        " libusbK en Zadig."
    )
  finally:
    if claimed:
      try:
        usb.util.release_interface(dev, intf_num)
      except usb.core.USBError:
        pass


if __name__ == "__main__":
  main()