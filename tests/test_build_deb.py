import io
import tarfile
import unittest

from build_deb import tar_gz


class PackageArchiveTests(unittest.TestCase):
    def test_parent_directories_are_listed_before_files(self):
        data = tar_gz([
            ("usr/lib/geiger/app.py", b"app", 0o644),
            ("usr/lib/geiger/device.py", b"device", 0o644),
        ])
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            entries = archive.getmembers()
            self.assertEqual([entry.name for entry in entries],
                             ["usr", "usr/lib", "usr/lib/geiger",
                              "usr/lib/geiger/app.py", "usr/lib/geiger/device.py"])
            self.assertTrue(all(entry.isdir() and entry.mode == 0o755 for entry in entries[:3]))
