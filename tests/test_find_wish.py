"""find_wish skips Tcl/Tk older than 8.6 (macOS ships 8.5 in /usr/bin) and says what it found."""
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from openslide_tk import viewer


def fake(directory, name, script):
    path = Path(directory) / name
    path.write_text("#!/bin/sh\n" + script + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


@unittest.skipIf(os.name == "nt", "POSIX shell scripts stand in for Tcl")
class FindWishTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.old = self.install("old", "8.5.9")
        self.new = self.install("new", "9.0.4")
        environment = mock.patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop("OPENSLIDE_WISH", None)

    def install(self, name, version, with_tclsh=True):
        directory = self.root / name
        directory.mkdir()
        if with_tclsh:
            fake(directory, "tclsh", f"read line; echo {version}")  # answers 'puts [info patchlevel]'
        return fake(directory, "wish", "exit 1")  # find_wish must never start it

    def find(self, which, locations):
        with mock.patch.object(viewer.shutil, "which", return_value=which), \
                mock.patch.object(viewer, "WISH_LOCATIONS", tuple(locations)):
            return viewer.find_wish()

    def test_tcl_version_reads_the_patchlevel(self):
        self.assertEqual(viewer.tcl_version(str(Path(self.old).with_name("tclsh"))), (8, 5))
        self.assertEqual(viewer.tcl_version(str(Path(self.new).with_name("tclsh"))), (9, 0))
        self.assertIsNone(viewer.tcl_version(str(self.root / "missing" / "tclsh")))
        self.assertIsNone(viewer.tcl_version(fake(self.root, "silent", "true")))

    def test_an_old_wish_on_path_is_skipped_for_a_newer_one(self):
        self.assertEqual(self.find(self.old, [self.old, self.new]), self.new)

    def test_only_old_wish_says_what_was_found(self):
        with self.assertRaises(RuntimeError) as caught:
            self.find(self.old, [self.old])
        message = str(caught.exception)
        self.assertIn(f"Found only {self.old} (Tcl/Tk 8.5).", message)
        self.assertTrue(message.startswith("Tcl/Tk 8.6+ is required for the viewer."), message)

    def test_nothing_found_keeps_the_install_hint(self):
        with self.assertRaises(RuntimeError) as caught:
            self.find(None, [str(self.root / "none" / "wish")])
        self.assertNotIn("Found only", str(caught.exception))
        self.assertIn("OPENSLIDE_WISH", str(caught.exception))

    def test_configured_wish_is_used_as_given(self):
        os.environ["OPENSLIDE_WISH"] = self.old
        self.assertEqual(self.find(None, []), self.old)
        os.environ["OPENSLIDE_WISH"] = str(self.root / "nowhere" / "wish")
        self.assertEqual(self.find(None, [self.new]), self.new)  # a missing configured path falls back to detection

    def test_a_wish_without_tclsh_beside_it_is_accepted(self):
        bare = self.install("bare", "", with_tclsh=False)
        self.assertEqual(self.find(bare, [self.old]), bare)


if __name__ == "__main__":
    unittest.main()
