"""Atomic outputs preserve private files and respect the caller's umask."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from openslide_tk.export import write_atomic
from openslide_tk.storage import atomic_write

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "posix", "POSIX mode/umask semantics are platform-specific")
class AtomicPermissionTests(unittest.TestCase):
    def test_all_export_formats_and_json_honor_umask_and_existing_modes(self):
        # Change umask only in an isolated child, never in the test runner or
        # the product. All public save/export paths must have the same policy.
        program = r'''
import json, os, stat, sys
from pathlib import Path
from openslide_tk.__main__ import starter_deck
from openslide_tk.storage import save_deck
from openslide_tk.export import export_html, export_svg
from openslide_tk.pptx import export_pptx
root=Path(sys.argv[1]); mask=int(sys.argv[2],8)
os.umask(mask)
deck=starter_deck()
writers={
 "deck.json":lambda p:save_deck(p,deck),
 "deck.pptx":lambda p:export_pptx(deck,p),
 "static.html":lambda p:export_html(deck,p),
 "player.html":lambda p:export_html(deck,p,interactive=True),
 "slide.svg":lambda p:export_svg(deck,0,p),
}
result={}
for name,write in writers.items():
 path=root/name
 write(path)
 expected=0o666 & ~mask
 assert stat.S_IMODE(path.stat().st_mode)==expected,(name,oct(mask),'new file mode')
 original=path.read_bytes()
 for existing in (0o600,0o640,0o664,0o444):
  os.chmod(path,existing)
  write(path)
  assert stat.S_IMODE(path.stat().st_mode)==existing,(name,oct(existing),'replacement mode')
  assert path.read_bytes()==original,(name,'content changed')
 result[name]=oct(expected)
assert not list(root.glob('.*.tmp'))
print(json.dumps(result))
'''
        for mask in ("022", "027", "077"):
            with self.subTest(umask=mask), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run([sys.executable, "-S", "-c", program, directory, mask], cwd=ROOT,
                                        text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(json.loads(result.stdout)), 5)

    def test_replace_failure_preserves_content_and_mode_for_both_entrypoints(self):
        for writer in (atomic_write, write_atomic):
            with self.subTest(writer=writer.__name__), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "private.data"
                path.write_bytes(b"original private content")
                path.chmod(0o600)
                with patch("openslide_tk.storage.os.replace", side_effect=OSError("replace refused")):
                    with self.assertRaisesRegex(OSError, "replace refused"):
                        writer(path, b"replacement")
                self.assertEqual(path.read_bytes(), b"original private content")
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(list(path.parent.iterdir()), [path])

    def test_failed_new_output_cleans_up_without_reading_or_changing_umask(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new.html"
            with patch("openslide_tk.storage.os.umask", side_effect=AssertionError("Never mutate global umask")):
                with patch("openslide_tk.storage.os.fsync", side_effect=OSError("disk failure")):
                    with self.assertRaisesRegex(OSError, "disk failure"):
                        write_atomic(path, "content")
                self.assertEqual(list(path.parent.iterdir()), [])
                write_atomic(path, "完整 UTF-8 content")
            self.assertEqual(path.read_text(), "完整 UTF-8 content")

    def test_invalid_payload_leaves_original_mode_and_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "output.json"
            path.write_text("old")
            path.chmod(0o640)
            with self.assertRaises(TypeError):
                atomic_write(path, object())
            self.assertEqual(path.read_text(), "old")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_temporary_file_is_owner_only_before_payload_is_written(self):
        real_fdopen = os.fdopen
        observed = []

        def inspect_before_write(fd, *args, **kwargs):
            observed.append(stat.S_IMODE(os.fstat(fd).st_mode))
            return real_fdopen(fd, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private.json"
            path.write_text("old")
            path.chmod(0o600)
            with patch("openslide_tk.storage.os.fdopen", side_effect=inspect_before_write):
                atomic_write(path, "replacement private content")
            self.assertEqual(observed, [0o600])
            self.assertEqual(path.read_text(), "replacement private content")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
