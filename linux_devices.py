"""Linux UAPI adapters for the Cardputer Zero's GPIO, LCD and keyboard."""

import ctypes
import errno
import fcntl
import mmap
import os
from pathlib import Path
import struct


GPIO22 = 22
GPIO_EVENT = struct.Struct("=QIIII6I")
GPIO_EVENT_BUFFER_SIZE = 1024
INPUT_EVENT = struct.Struct("@llHHi")
KEYBOARD = "/dev/input/by-path/platform-3f804000.i2c-event"
LCD_SIZE = (320, 170)


def gpio_ioctl(direction, number, size):
    return (direction << 30) | (size << 16) | (0xB4 << 8) | number


class PulseInput:
    def __init__(self, edge, bias):
        chip_ioctl = gpio_ioctl(2, 1, 68)  # GPIO_GET_CHIPINFO_IOCTL
        line_ioctl = gpio_ioctl(3, 7, 592)  # GPIO_V2_GET_LINE_IOCTL
        self.sequence = 0
        self.last_loss_ns = None
        last_error = None
        for path in sorted(Path("/dev").glob("gpiochip[0-9]*")):
            try:
                with path.open("rb", buffering=0) as chip:
                    info = bytearray(68)
                    fcntl.ioctl(chip, chip_ioctl, info)
                    _, label, lines = struct.unpack("=32s32sI", info)
                    if label.split(b"\0", 1)[0] != b"pinctrl-bcm2835" or lines <= GPIO22:
                        continue
                    request = bytearray(592)
                    struct.pack_into("=I", request, 0, GPIO22)
                    struct.pack_into("=32s", request, 256, b"geiger-counter")
                    flags = (1 << 2) | (1 << (5 if edge == "falling" else 4))
                    flags |= 1 << (8 if bias == "pull-up" else 10)
                    struct.pack_into("=Q", request, 288, flags)
                    struct.pack_into("=II", request, 560, 1, GPIO_EVENT_BUFFER_SIZE)
                    fcntl.ioctl(chip, line_ioctl, request)
                    self.fd, = struct.unpack_from("=i", request, 588)
            except OSError as error:
                last_error = error
                if error.errno != errno.EACCES:
                    raise
                continue
            try:
                os.set_blocking(self.fd, False)
            except OSError:
                self.close()
                raise
            return
        if last_error:
            raise last_error
        raise OSError(errno.ENODEV, "BCM2835 GPIO controller not found")

    def close(self):
        os.close(self.fd)

    def read(self):
        try:
            data = os.read(self.fd, GPIO_EVENT.size * GPIO_EVENT_BUFFER_SIZE)
        except BlockingIOError:
            return []
        if not data:
            raise OSError(errno.EIO, "GPIO event stream closed")
        timestamps = []
        for timestamp, _, _, _, sequence, *_ in GPIO_EVENT.iter_unpack(data):
            if sequence != ((self.sequence + 1) & 0xFFFFFFFF):
                self.last_loss_ns = timestamp
            self.sequence = sequence
            timestamps.append(timestamp)
        return timestamps


class FixedScreenInfo(ctypes.Structure):
    # struct fb_fix_screeninfo from linux/fb.h. unsigned long follows the host ABI.
    _fields_ = [
        ("id", ctypes.c_char * 16),
        ("smem_start", ctypes.c_ulong),
        ("smem_len", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("type_aux", ctypes.c_uint32),
        ("visual", ctypes.c_uint32),
        ("xpanstep", ctypes.c_uint16),
        ("ypanstep", ctypes.c_uint16),
        ("ywrapstep", ctypes.c_uint16),
        ("line_length", ctypes.c_uint32),
        ("mmio_start", ctypes.c_ulong),
        ("mmio_len", ctypes.c_uint32),
        ("accel", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint16),
        ("reserved", ctypes.c_uint16 * 2),
    ]


def framebuffer_path():
    for name in ("GEIGER_FB", "LV_LINUX_FBDEV_DEVICE"):
        if os.environ.get(name):
            return os.environ[name]
    candidates = []
    for sysfs in sorted(Path("/sys/class/graphics").glob("fb[0-9]*")):
        name = (sysfs / "name").read_text().strip().lower()
        if "st7789" in name:
            return f"/dev/{sysfs.name}"
        candidates.append(f"/dev/{sysfs.name}")
    if len(candidates) == 1:
        return candidates[0]
    raise OSError(errno.ENODEV, "LCD framebuffer not found (set GEIGER_FB)")


class Framebuffer:
    def __init__(self, path):
        with open(path, "r+b", buffering=0) as device:
            var = bytearray(160)
            fcntl.ioctl(device, 0x4600, var)  # FBIOGET_VSCREENINFO
            width, height, _, _, xoffset, yoffset, bpp, grayscale = struct.unpack_from("=8I", var)
            colors = struct.unpack_from("=9I", var, 32)
            alpha = struct.unpack_from("=3I", var, 68)
            fix = bytearray(ctypes.sizeof(FixedScreenInfo))
            fcntl.ioctl(device, 0x4602, fix)  # FBIOGET_FSCREENINFO
            fixed = FixedScreenInfo.from_buffer(fix)
            if (width, height) != LCD_SIZE or fixed.type != 0 or fixed.visual != 2 or grayscale:
                raise OSError(errno.ENOTSUP, f"Expected 320x170 true-color framebuffer: {path}")
            self.bpp = bpp
            if bpp == 16 and colors == (11, 5, 0, 5, 6, 0, 0, 5, 0):
                self.raw_mode = None
            elif bpp == 32 and colors == (16, 8, 0, 8, 8, 0, 0, 8, 0) and alpha[1] in (0, 8):
                self.raw_mode = "BGRA"
            else:
                raise OSError(errno.ENOTSUP, f"Unsupported {bpp}-bit framebuffer format: {path}")
            self.row_bytes = width * (bpp // 8)
            self.stride = fixed.line_length
            self.start = yoffset * self.stride + xoffset * (bpp // 8)
            end = self.start + (height - 1) * self.stride + self.row_bytes
            if end > fixed.smem_len or (xoffset + width) * (bpp // 8) > self.stride:
                raise OSError(errno.EINVAL, f"Invalid framebuffer bounds: {path}")
            self.memory = mmap.mmap(device.fileno(), fixed.smem_len, access=mmap.ACCESS_WRITE)

    def close(self):
        self.memory.close()

    def show(self, image):
        if self.raw_mode:
            pixels = image.convert("RGBA").tobytes("raw", self.raw_mode)
        else:
            pixels = rgb565(image.tobytes())
        for row in range(LCD_SIZE[1]):
            src = row * self.row_bytes
            dest = self.start + row * self.stride
            self.memory[dest : dest + self.row_bytes] = pixels[src : src + self.row_bytes]


def rgb565(rgb):
    pixels = bytearray(len(rgb) // 3 * 2)
    red = rgb[0::3]
    green = rgb[1::3]
    blue = rgb[2::3]
    pixels[0::2] = bytes(((g & 0x1C) << 3) | (b >> 3) for g, b in zip(green, blue))
    pixels[1::2] = bytes((r & 0xF8) | (g >> 5) for r, g in zip(red, green))
    return pixels


def open_keyboard():
    path = os.environ.get("LV_LINUX_KEYBOARD_DEVICE") or KEYBOARD
    return os.open(path, os.O_RDONLY | os.O_NONBLOCK)


def read_keys(fd):
    try:
        data = os.read(fd, INPUT_EVENT.size * 32)
    except BlockingIOError:
        return []
    if not data:
        raise OSError(errno.EIO, "Keyboard event stream closed")
    return [code for _, _, kind, code, value in INPUT_EVENT.iter_unpack(data)
            if kind == 1 and value == 1]
