"""validate prints every error and warning as JSON, even when the scene is invalid."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def run_validate(deck_path):
    environment = dict(os.environ, DISPLAY="", OPENSLIDE_WISH="/nonexistent/no-gui-permitted")
    return subprocess.run([sys.executable, "-m", "openslide_tk", "validate", str(deck_path)], cwd=ROOT,
                          env=environment, capture_output=True, text=True, timeout=30)


def deck(**element):
    text = {"id": "a", "type": "text", "x": 0, "y": 0, "width": 100, "height": 10, "text": "a line of text that cannot fit"}
    text.update(element)
    return {"schema_version": 1, "id": "d", "title": "T", "width": 1920, "height": 1080,
            "slides": [{"id": "s1", "elements": [text]}]}


class ValidateCommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def check(self, scene):
        path = self.root / "deck.json"
        path.write_text(json.dumps(scene), encoding="utf-8")
        result = run_validate(path)
        self.assertNotIn("Traceback", result.stderr)
        return result.returncode, json.loads(result.stdout)

    def test_an_invalid_scene_lists_errors_and_warnings_with_exit_1(self):
        code, diagnostics = self.check(deck(color="red"))
        self.assertEqual(code, 1)
        self.assertEqual(sorted((d["severity"], d["code"]) for d in diagnostics),
                         [("error", "invalid_color"), ("warning", "text_overflow")])

    def test_warnings_alone_exit_0(self):
        code, diagnostics = self.check(deck())
        self.assertEqual(code, 0)
        self.assertEqual([d["code"] for d in diagnostics], ["text_overflow"])

    def test_broken_json_still_fails_without_json_output(self):
        path = self.root / "broken.json"
        path.write_text('{"schema_version": NaN}', encoding="utf-8")
        result = run_validate(path)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("Invalid deck JSON", result.stderr)


if __name__ == "__main__":
    unittest.main()
