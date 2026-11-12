#!/usr/bin/python3
"""A 320x170 Geiger counter for the Cardputer Zero."""

import argparse
from contextlib import ExitStack
from functools import lru_cache
import random
import sys
import time

from PIL import Image, ImageDraw, ImageFont


SECOND = 1_000_000_000
WINDOW = 60
SIZE = (320, 170)
BACKGROUND = "#10171b"
PANEL = "#1a262d"
INK = "#edf5f7"
MUTED = "#a9bcc5"
LIME = "#c6f65a"
TEAL = "#66e1cf"
AMBER = "#ffcc76"


class Counts:
    def __init__(self, start):
        self.reset(start)

    def reset(self, start):
        self.start = start
        self.buckets = {}
        self.total = 0

    def add(self, timestamp):
        if timestamp >= self.start:
            second = (timestamp - self.start) // SECOND
            self.buckets[second] = self.buckets.get(second, 0) + 1
            self.total += 1

    def sample(self, now):
        completed = (now - self.start) // SECOND
        oldest = max(0, completed - WINDOW)
        self.buckets = {second: count for second, count in self.buckets.items() if second >= oldest}
        history = [self.buckets.get(second, 0) for second in range(oldest, completed)]
        return history, self.total


@lru_cache(maxsize=None)
def font(size):
    return ImageFont.load_default(size=size)


def render(history, total, status, problem=None):
    image = Image.new("RGB", SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)

    def text(x, y, value, size=12, color=INK, anchor="lt"):
        draw.text((x, y), str(value), fill=color, font=font(size), anchor=anchor)

    def metric(x, label, value, color):
        draw.rounded_rectangle((x, 29, x + 95, 80), radius=5, fill=PANEL)
        text(x + 9, 35, label, 11, MUTED)
        value = str(value)
        size = next((size for size in (25, 20, 15, 11) if font(size).getlength(value) <= 80), 8)
        text(x + 9, 49, value, size, color)

    text(11, 8, "GEIGER COUNTER", 15)
    text(309, 10, status, 12, AMBER if problem else TEAL, "rt")
    metric(10, "CPS", history[-1] if history else "--", LIME)
    metric(112, "CPM", sum(history) if len(history) == WINDOW else "--", TEAL)
    metric(214, "TOTAL", total, INK)
    if problem:
        text(11, 91, problem, 12, AMBER)
    else:
        text(11, 91, "LAST 60 S", 11, MUTED)
        if len(history) < WINDOW:
            text(309, 91, f"CPM warm-up {len(history)}/60 s", 11, MUTED, "rt")
        else:
            text(309, 91, f"PEAK {max(history)} CPS", 11, MUTED, "rt")
    baseline = 143
    for y in (111, 127, baseline):
        draw.line((10, y, 309, y), fill="#293740")
    scale = max(1, max(history, default=0))
    for index, count in enumerate(history, start=WINDOW - len(history)):
        x = 10 + index * 5
        if count:
            height = max(1, round(32 * count / scale))
            draw.rectangle((x, baseline - height, x + 3, baseline - 1), fill=LIME)
    text(11, 152, "R  Reset", 12, MUTED)
    text(309, 152, "ESC / Q  Exit", 12, MUTED, "rt")
    return image


class Demo:
    def __init__(self, start):
        self.random = random.Random(22)
        self.next_second = start + SECOND

    def update(self, now, counts):
        while now >= self.next_second:
            counts_this_second = self.random.choices((0, 1, 2, 3, 4), (4, 8, 5, 2, 1))[0]
            for _ in range(counts_this_second):
                counts.add(self.next_second - 1)
            self.next_second += SECOND


def run(args):
    import os
    import select

    from linux_devices import Framebuffer, PulseInput, framebuffer_path, open_keyboard, read_keys

    with ExitStack() as stack:
        framebuffer = Framebuffer(framebuffer_path())
        stack.callback(framebuffer.close)
        keyboard = open_keyboard()
        stack.callback(os.close, keyboard)
        poller = select.poll()
        poller.register(keyboard, select.POLLIN)
        pulse = None
        problem = None
        if not args.demo:
            try:
                pulse = PulseInput(args.edge, args.bias)
                stack.callback(pulse.close)
                poller.register(pulse.fd, select.POLLIN)
            except OSError as error:
                print(f"G22: {error}", file=sys.stderr)
                problem = "G22 unavailable. Check access or pin use."
        start = time.monotonic_ns()
        counts = Counts(start)
        demo = Demo(start) if args.demo else None
        title = "SIMULATION" if demo else "G22 " + args.edge.upper()
        previous = None
        lost_at_reset = 0
        next_frame = start
        while True:
            now = time.monotonic_ns()
            timeout = max(0, (next_frame - now + 999_999) // 1_000_000)
            keys = []
            for fd, flags in poller.poll(timeout):
                if fd == keyboard:
                    if flags & (select.POLLERR | select.POLLHUP | select.POLLNVAL):
                        raise OSError("Keyboard event stream stopped")
                    keys.extend(read_keys(fd))
                elif pulse and fd == pulse.fd:
                    try:
                        if flags & (select.POLLERR | select.POLLHUP | select.POLLNVAL):
                            raise OSError("GPIO event stream stopped")
                        for timestamp in pulse.read():
                            counts.add(timestamp)
                    except OSError as error:
                        print(f"G22: {error}", file=sys.stderr)
                        poller.unregister(fd)
                        pulse = None
                        problem = "G22 event stream stopped."
            if 1 in keys or 16 in keys:  # KEY_ESC / KEY_Q
                return 1 if problem else 0
            now = time.monotonic_ns()
            if 19 in keys:  # KEY_R
                counts.reset(now)
                if demo:
                    demo = Demo(now)
                if pulse:
                    lost_at_reset = pulse.lost
            if demo:
                demo.update(now, counts)
            history, total = counts.sample(now)
            loss = pulse.lost - lost_at_reset if pulse else 0
            status = "INPUT ERROR" if problem else "MISSED PULSES" if loss else title
            warning = problem or (f"Kernel dropped {loss} edges" if loss else None)
            frame = ([], "--", status, warning) if problem else (history, total, status, warning)
            if frame != previous and (now >= next_frame or keys):
                framebuffer.show(render(*frame))
                previous = frame
            if now >= next_frame:
                next_frame = now + 100_000_000


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true", help="simulate counts on the device")
    mode.add_argument("--preview", metavar="PNG", help="render a simulated dashboard to a PNG")
    parser.add_argument("--edge", choices=("falling", "rising"), default="falling")
    parser.add_argument("--bias", choices=("pull-up", "disabled"), default="pull-up")
    args = parser.parse_args(argv)
    if args.preview:
        counts = Counts(0)
        Demo(0).update(WINDOW * SECOND, counts)
        render(*counts.sample(WINDOW * SECOND), "SIMULATION").save(args.preview)
        return 0
    try:
        return run(args)
    except (ImportError, OSError) as error:
        print(f"Geiger Counter: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
