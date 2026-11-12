import importlib
import struct
import sys
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch

from geiger import Counts, Demo, SECOND, render


if sys.platform == "win32":
    # Windows can exercise the UAPI payloads without opening a device.
    fcntl_stub = ModuleType("fcntl")
    fcntl_stub.ioctl = MagicMock()
    with patch.dict(sys.modules, {"fcntl": fcntl_stub}):
        devices = importlib.import_module("linux_devices")
else:
    devices = importlib.import_module("linux_devices")


class CountTests(unittest.TestCase):
    def test_second_boundary_and_late_delivery(self):
        counts = Counts(10)
        counts.add(10 + SECOND)
        self.assertEqual(counts.sample(10 + SECOND), ([0], 1))
        counts.add(10 + SECOND - 1)
        self.assertEqual(counts.sample(10 + 2 * SECOND), ([1, 1], 2))

    def test_rolling_window_and_idle_seconds(self):
        counts = Counts(0)
        counts.add(0)
        counts.add(59 * SECOND)
        self.assertEqual(counts.sample(60 * SECOND), ([1] + [0] * 58 + [1], 2))
        self.assertEqual(counts.sample(61 * SECOND), ([0] * 58 + [1, 0], 2))
        self.assertEqual(counts.sample(120 * SECOND), ([0] * 60, 2))

    def test_reset_ignores_queued_old_edges(self):
        counts = Counts(0)
        counts.add(0)
        counts.reset(SECOND)
        counts.add(SECOND - 1)
        counts.add(SECOND)
        self.assertEqual(counts.sample(2 * SECOND), ([1], 1))

    def test_demo_renders_full_dashboard(self):
        counts = Counts(0)
        Demo(0).update(60 * SECOND, counts)
        history, total = counts.sample(60 * SECOND)
        self.assertEqual(len(history), 60)
        self.assertEqual(sum(history), total)
        self.assertGreater(total, 0)
        self.assertEqual(render(history, total, "SIMULATION").size, (320, 170))


class LinuxDeviceTests(unittest.TestCase):
    def test_request_is_g22_input_with_falling_edge_and_pull_up(self):
        chip = MagicMock()

        def ioctl(fd, operation, payload):
            if operation == 0x8044B401:
                struct.pack_into("=32s32sI", payload, 0, b"gpiochip0", b"pinctrl-bcm2835", 54)
            else:
                self.assertEqual(operation, 0xC250B407)
                self.assertEqual(len(payload), 592)
                self.assertEqual(struct.unpack_from("=I", payload), (22,))
                self.assertEqual(struct.unpack_from("=Q", payload, 288), (0x124,))
                self.assertEqual(struct.unpack_from("=II", payload, 560), (1, 256))
                struct.pack_into("=i", payload, 588, 42)

        with (
            patch.object(devices.Path, "glob", return_value=[chip]),
            patch.object(devices.fcntl, "ioctl", side_effect=ioctl),
            patch.object(devices.os, "set_blocking") as nonblock,
            patch.object(devices.os, "close") as close,
        ):
            source = devices.PulseInput("falling", "pull-up")
            nonblock.assert_called_once_with(42, False)
            source.close()
            close.assert_called_once_with(42)

    def test_gpio_counts_lost_edges_and_wraps_sequence(self):
        source = object.__new__(devices.PulseInput)
        source.fd = 42
        source.sequence = 0xFFFFFFFE
        source.lost = 0
        payload = b"".join(devices.GPIO_EVENT.pack(time, 2, 22, seq, seq, *([0] * 6))
                           for time, seq in ((10, 0xFFFFFFFF), (20, 0), (40, 2)))
        with patch.object(devices.os, "read", return_value=payload):
            self.assertEqual(source.read(), [10, 20, 40])
        self.assertEqual(source.lost, 1)

    def test_rgb565_primary_colors(self):
        rgb = bytes((255, 0, 0, 0, 255, 0, 0, 0, 255))
        self.assertEqual(devices.rgb565(rgb), bytes.fromhex("00f8 e007 1f00"))


if __name__ == "__main__":
    unittest.main()
