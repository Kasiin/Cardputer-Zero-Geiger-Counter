import importlib
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch

import geiger
from geiger import Counts, Demo, SECOND, load_tube, readout, render, save_tube


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


class DoseTests(unittest.TestCase):
    def test_both_tube_profiles_and_all_units_at_100_cpm(self):
        history = [1] * 59 + [41]
        for tube, expected in {
            "J305": ("0.81", "7.096", "8.1e-05", "0.081", "81"),
            "M4011": ("0.65", "5.694", "6.5e-05", "0.065", "65"),
        }.items():
            self.assertEqual(readout(history, tube, "cpm"), ("CPM", 100))
            for unit, value in zip(("usv/h", "msv/y", "rad/h", "mrad/h", "urad/h"), expected):
                with self.subTest(tube=tube, unit=unit):
                    self.assertEqual(readout(history, tube, unit)[1], value)

    def test_dose_waits_for_full_window_and_is_hidden_on_event_loss(self):
        self.assertEqual(readout([1] * 59, "M4011", "usv/h"), ("uSv/h", "--"))
        self.assertEqual(readout([0] * 60, "M4011", "usv/h"), ("uSv/h", "0"))
        self.assertEqual(readout([1] * 60, "J305", "usv/h", "Kernel dropped 1 edge")[1], "--")
        self.assertEqual(readout([1] * 60, "J305", "cpm", "Kernel dropped 1 edge")[1], 60)

    def test_dose_recovers_after_a_loss_leaves_the_completed_window(self):
        counts = Counts(10)
        last_loss = 10 + SECOND + 1
        for now, expected in ((10 + 61 * SECOND, "--"), (10 + 62 * SECOND, "0")):
            history, _ = counts.sample(now)
            warning = "GPIO edge loss" if counts.has_recent_loss(now, last_loss) else None
            self.assertEqual(readout(history, "J305", "usv/h", warning)[1], expected)
        counts.reset(10 + 63 * SECOND)
        self.assertFalse(counts.has_recent_loss(10 + 63 * SECOND, last_loss))
        self.assertFalse(counts.has_recent_loss(10 + 63 * SECOND, None))

    def test_tube_selection_survives_restart(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config" / "tube"
            self.assertEqual(load_tube(path), "M4011")
            save_tube(path, "J305")
            self.assertEqual(load_tube(path), "J305")
            save_tube(path, "M4011")
            self.assertEqual(load_tube(path), "M4011")
            path.write_text("unknown", encoding="ascii")
            self.assertEqual(load_tube(path), "M4011")

    def test_t_and_u_update_the_running_display(self):
        select = MagicMock(POLLIN=1, POLLERR=8, POLLHUP=16, POLLNVAL=32)
        select.poll.return_value.poll.side_effect = [[], [(42, 1)], [(42, 1)]]
        framebuffer = MagicMock()
        linux = MagicMock(Framebuffer=MagicMock(return_value=framebuffer))
        linux.open_keyboard.return_value = 42
        linux.read_keys.side_effect = [[20, 22], [16]]
        with (
            patch.dict(sys.modules, {"select": select, "linux_devices": linux}),
            patch.object(geiger.os, "close"),
            patch.object(geiger.time, "monotonic_ns", side_effect=[0, 0, 0, 0, 60 * SECOND, 60 * SECOND]),
            patch.object(geiger, "render") as draw,
            patch.object(geiger, "save_tube") as save,
        ):
            self.assertEqual(geiger.main(["--demo"]), 0)
        first, switched = draw.call_args_list
        self.assertEqual(first.args[-2:], ("M4011", "cpm"))
        self.assertEqual(switched.args[-2:], ("J305", "usv/h"))
        self.assertEqual(len(switched.args[0]), 60)
        save.assert_not_called()


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
                self.assertEqual(struct.unpack_from("=II", payload, 560), (1, 1024))
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

    def test_gpio_timestamps_sequence_gap_without_flagging_wrap(self):
        source = object.__new__(devices.PulseInput)
        source.fd = 42
        source.sequence = 0xFFFFFFFE
        source.last_loss_ns = None
        payload = b"".join(devices.GPIO_EVENT.pack(time, 2, 22, seq, seq, *([0] * 6))
                           for time, seq in ((10, 0xFFFFFFFF), (20, 0), (40, 2), (50, 3)))
        split = 2 * devices.GPIO_EVENT.size
        with patch.object(devices.os, "read", side_effect=[payload[:split], payload[split:]]):
            self.assertEqual(source.read(), [10, 20])
            self.assertIsNone(source.last_loss_ns)
            self.assertEqual(source.read(), [40, 50])
        self.assertEqual(source.last_loss_ns, 40)

    def test_rgb565_primary_colors(self):
        rgb = bytes((255, 0, 0, 0, 255, 0, 0, 0, 255))
        self.assertEqual(devices.rgb565(rgb), bytes.fromhex("00f8 e007 1f00"))


if __name__ == "__main__":
    unittest.main()
