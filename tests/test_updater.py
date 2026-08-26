"""Tests for VNC-Menu-Updater.pyw.

safe_extract() is the only place in the project where a bug becomes a real
vulnerability: it unpacks an archive downloaded from the network. It is tested
here against traversal, absolute paths and symlink entries.
"""

import unittest
import zipfile
from pathlib import Path

import vncmenu_loader


class UpdaterTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # VNC-Menu-Updater.pyw may legitimately be absent (partial checkout, or
        # an overlay that only ships the changed files). Skip rather than error.
        if not vncmenu_loader.UPDATER_SCRIPT.is_file():
            raise unittest.SkipTest(
                f"{vncmenu_loader.UPDATER_SCRIPT.name} not present in this checkout"
            )
        cls.updater, cls.sandbox = vncmenu_loader.load_updater()

    @classmethod
    def tearDownClass(cls):
        vncmenu_loader.release_sandbox(getattr(cls, "sandbox", None))

    def _zip_with(self, entries, name):
        path = self.sandbox / name
        with zipfile.ZipFile(path, "w") as archive:
            for arcname, data in entries:
                archive.writestr(arcname, data)
        return path


class TestPreservedPaths(UpdaterTestCase):
    def test_user_data_is_preserved(self):
        for relative in (
            "data/hosts.json",
            "data/template.vnc",
            "data/realvnc/Setor_PC01.vnc",
            "logs/user.log",
            "_internal/hosts.json",
            "_internal/realvnc/x.vnc",
        ):
            self.assertTrue(
                self.updater.is_preserved(Path(relative)), relative
            )

    def test_application_files_are_not_preserved(self):
        for relative in ("VNC-Menu.pyw", "VNC-Menu-Updater.pyw", "_internal/base_library.zip"):
            self.assertFalse(self.updater.is_preserved(Path(relative)), relative)


class TestSafeExtract(UpdaterTestCase):
    def test_benign_archive_extracts(self):
        archive = self._zip_with(
            [("VNC-Menu.pyw", "print('hi')"), ("sub/dir/file.txt", "ok")], "benign.zip"
        )
        destination = self.sandbox / "out-benign"
        destination.mkdir()
        self.updater.safe_extract(archive, destination)
        self.assertTrue((destination / "VNC-Menu.pyw").is_file())
        self.assertTrue((destination / "sub" / "dir" / "file.txt").is_file())

    def test_parent_traversal_is_rejected(self):
        archive = self._zip_with([("../escaped.txt", "x")], "traversal.zip")
        destination = self.sandbox / "out-traversal"
        destination.mkdir()
        with self.assertRaises(RuntimeError):
            self.updater.safe_extract(archive, destination)
        self.assertFalse((self.sandbox / "escaped.txt").exists())

    def test_backslash_traversal_is_rejected(self):
        archive = self._zip_with([("..\\escaped-win.txt", "x")], "traversal-win.zip")
        destination = self.sandbox / "out-traversal-win"
        destination.mkdir()
        with self.assertRaises(RuntimeError):
            self.updater.safe_extract(archive, destination)

    def test_absolute_path_is_rejected(self):
        archive = self._zip_with([("/tmp/absolute-evil.txt", "x")], "absolute.zip")
        destination = self.sandbox / "out-absolute"
        destination.mkdir()
        with self.assertRaises(RuntimeError):
            self.updater.safe_extract(archive, destination)

    def test_symlink_entry_is_rejected(self):
        path = self.sandbox / "symlink.zip"
        with zipfile.ZipFile(path, "w") as archive:
            info = zipfile.ZipInfo("link")
            info.external_attr = (0o120777 << 16)  # S_IFLNK
            archive.writestr(info, "/etc/passwd")
        destination = self.sandbox / "out-symlink"
        destination.mkdir()
        with self.assertRaises(RuntimeError):
            self.updater.safe_extract(path, destination)

    def test_nothing_is_written_when_a_bad_entry_is_present(self):
        """Validation runs over every entry before extractall()."""
        archive = self._zip_with(
            [("good.txt", "ok"), ("../bad.txt", "evil")], "mixed.zip"
        )
        destination = self.sandbox / "out-mixed"
        destination.mkdir()
        with self.assertRaises(RuntimeError):
            self.updater.safe_extract(archive, destination)
        self.assertEqual(list(destination.iterdir()), [])


class TestFindPackageRoot(UpdaterTestCase):
    def test_finds_the_requested_entry_point(self):
        staging = self.sandbox / "staging-a"
        (staging / "VNC-Menu-v1.7.0").mkdir(parents=True)
        main = staging / "VNC-Menu-v1.7.0" / "VNC-Menu.pyw"
        main.write_text("x", encoding="utf-8")

        root, found = self.updater.find_package_root(staging, "VNC-Menu.pyw")
        self.assertEqual(found, main)
        self.assertEqual(root, main.parent)

    def test_prefers_the_shallowest_candidate(self):
        staging = self.sandbox / "staging-b"
        shallow = staging / "VNC-Menu.pyw"
        deep = staging / "a" / "b" / "VNC-Menu.pyw"
        deep.parent.mkdir(parents=True)
        shallow.write_text("x", encoding="utf-8")
        deep.write_text("x", encoding="utf-8")

        _root, found = self.updater.find_package_root(staging, "VNC-Menu.pyw")
        self.assertEqual(found, shallow)

    def test_raises_when_the_package_has_no_entry_point(self):
        staging = self.sandbox / "staging-c"
        staging.mkdir()
        (staging / "readme.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            self.updater.find_package_root(staging, "VNC-Menu.pyw")


if __name__ == "__main__":
    unittest.main()
