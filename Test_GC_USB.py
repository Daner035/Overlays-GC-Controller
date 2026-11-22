import libusb_package
import usb.backend.libusb1
import usb.core
import usb.util

VID = 0x057E
PID = 0x0337


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

    # Comando 0x13: activa el modo de lectura/polling del adaptador WUP-028
    ep_out.write([0x13], timeout=1000)
    print(
        f"Conectado a WUP-028 (Interfaz {intf_num}, EP IN"
        f" {hex(ep_in.bEndpointAddress)})."
    )
    print("Mueve el control en el Puerto 1 (Ctrl+C para salir)...")

    while True:
      try:
        data = ep_in.read(ep_in.wMaxPacketSize, timeout=100)
        # En el reporte del WUP-028: byte 0 = tipo de reporte; bytes 1..9 = Puerto 1
        if data and len(data) >= 10:
          p1 = list(data[1:10])
          # p1[0]: estado/tipo de mando | p1[1..2]: botones | p1[3..6]: sticks | p1[7..8]: gatillos analógicos
          print(
              f"P1 Raw: {p1} | StickL: ({p1[3]}, {p1[4]}) | C-Stick:"
              f" ({p1[5]}, {p1[6]})"
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