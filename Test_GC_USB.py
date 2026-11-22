import libusb_package
import usb.backend.libusb1
import usb.core

backend = usb.backend.libusb1.get_backend(
    find_library=libusb_package.find_library
)
for d in usb.core.find(find_all=True, backend=backend):
  try:
    prod = usb.util.get_string(d, d.iProduct) if d.iProduct else ""
  except Exception:
    prod = ""
  print(
      f"VID={hex(d.idVendor)} PID={hex(d.idProduct)} Prod='{prod}'"
  )