"""Build the platform-independent .deb on Windows or Linux."""

import gzip
import io
from pathlib import Path, PurePosixPath
import tarfile

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
LAUNCHER = "usr/share/APPLaunch"


def tar_gz(files):
    data = io.BytesIO()
    directories = set()
    with tarfile.open(fileobj=data, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for path, content, mode in files:
            for parent in reversed(PurePosixPath(path).parents):
                directory = parent.as_posix()
                if directory == "." or directory in directories:
                    continue
                entry = tarfile.TarInfo(directory)
                entry.type = tarfile.DIRTYPE
                entry.mode = 0o755
                entry.uname = entry.gname = "root"
                archive.addfile(entry)
                directories.add(directory)
            entry = tarfile.TarInfo(path)
            entry.size = len(content)
            entry.mode = mode
            entry.uname = entry.gname = "root"
            archive.addfile(entry, io.BytesIO(content))
    return gzip.compress(data.getvalue(), mtime=0)


def write_ar_member(output, name, content):
    header = f"{name + '/':16}{0:<12}{0:<6}{0:<6}{'100644':<8}{len(content):<10}\x60\n"
    output.write(header.encode("ascii"))
    output.write(content)
    if len(content) % 2:
        output.write(b"\n")


def icon():
    image = Image.new("RGBA", (96, 96))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((3, 3, 92, 92), radius=19, fill="#1a262d")
    draw.ellipse((17, 17, 79, 79), outline="#c6f65a", width=2)
    for start in (36, 156, 276):
        draw.pieslice((23, 23, 73, 73), start, start + 48, fill="#c6f65a")
    draw.ellipse((39, 39, 57, 57), fill="#1a262d")
    draw.ellipse((43, 43, 53, 53), fill="#c6f65a")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build():
    control = (ROOT / "packaging/control").read_bytes()
    fields = dict(line.split(": ", 1) for line in control.decode().splitlines()
                  if line and not line.startswith(" "))
    name = fields["Package"]
    lib = f"usr/lib/{name}"
    launcher = f'#!/bin/sh\nexec /usr/bin/python3 -B /{lib}/geiger.py "$@"\n'.encode()
    data = tar_gz([
        (f"usr/bin/{name}", launcher, 0o755),
        (f"{lib}/geiger.py", (ROOT / "geiger.py").read_bytes(), 0o644),
        (f"{lib}/linux_devices.py", (ROOT / "linux_devices.py").read_bytes(), 0o644),
        (f"{LAUNCHER}/applications/geiger-counter.desktop",
         (ROOT / "packaging/geiger-counter.desktop").read_bytes(), 0o644),
        (f"{LAUNCHER}/share/images/geiger-counter.png", icon(), 0o644),
    ])
    output = ROOT / "dist" / f'{name}_{fields["Version"]}_{fields["Architecture"]}.deb'
    output.parent.mkdir(exist_ok=True)
    with output.open("wb") as package:
        package.write(b"!<arch>\n")
        write_ar_member(package, "debian-binary", b"2.0\n")
        write_ar_member(package, "control.tar.gz", tar_gz([("control", control, 0o644)]))
        write_ar_member(package, "data.tar.gz", data)
    return output


if __name__ == "__main__":
    print(build())
