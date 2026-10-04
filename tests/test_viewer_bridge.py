"""Exercise persistence, the real Tcl interpreter boundary, and headless CLI."""

import io
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

from openslide_tk.__main__ import main, starter_deck
from openslide_tk.storage import atomic_write, save_deck
from openslide_tk.viewer import Viewer, tcl_version, tcl_word


ROOT = Path(__file__).resolve().parents[1]
def modern_tclsh():
    """The first tclsh that is Tcl 8.6+ (tcl_word needs binary decode), and the reason when there is none."""
    seen = []
    for candidate in (shutil.which("tclsh"), "/opt/homebrew/bin/tclsh", "/usr/local/bin/tclsh", "/usr/bin/tclsh"):
        if candidate and os.path.isfile(candidate) and candidate not in seen:
            seen.append(candidate)
            version = tcl_version(candidate)
            if version and version >= (8, 6):
                return candidate, ""
    return None, "Tcl 8.6+ is required for bridge integration tests" + (f" (found only {', '.join(seen)})" if seen else "")


TCLSH, TCLSH_MISSING = modern_tclsh()


class ProcessDiagnosticTests(unittest.TestCase):
    diagnostic = "2026-10-03 16:52:02.475 wish[73095:20522884] Error received in message reply handler: Connection interrupted"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        path = Path(self.temporary.name) / "deck.json"
        save_deck(path, starter_deck())
        self.viewer = Viewer(path, smoke_test=True)

    def tearDown(self):
        self.temporary.cleanup()

    def test_cocoa_stderr_is_retained_without_becoming_a_bridge_failure(self):
        self.viewer.process = types.SimpleNamespace(stderr=io.StringIO(self.diagnostic + "\n"), returncode=0)
        self.viewer._read_stderr()
        self.assertEqual(list(self.viewer.stderr_lines), [self.diagnostic])
        action, args = self.viewer.events.get_nowait()
        self.assertEqual(action, "stderr")
        with patch("openslide_tk.viewer.sys.platform", "darwin"), patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.viewer.action(action, args)
        self.assertEqual(list(self.viewer.diagnostics), [self.diagnostic])
        self.assertIn(self.diagnostic, stderr.getvalue())

    def test_actual_protocol_and_unrecognized_stderr_errors_still_fail(self):
        with patch("openslide_tk.viewer.sys.platform", "darwin"):
            for action, text in (("error", self.diagnostic), ("stderr", "Error received in message reply handler: Connection interrupted"),
                                 ("stderr", 'invalid command name "missing"'), ("stderr", self.diagnostic + "; extra failure")):
                with self.subTest(action=action, text=text), self.assertRaises(RuntimeError):
                    self.viewer.action(action, [text])
        with patch("openslide_tk.viewer.sys.platform", "linux"), self.assertRaises(RuntimeError):
            self.viewer.action("stderr", [self.diagnostic])

    def test_abnormal_exit_and_late_protocol_error_cannot_pass_smoke(self):
        self.viewer.process = types.SimpleNamespace(returncode=9)
        self.viewer.stderr_lines.append(self.diagnostic)
        with self.assertRaisesRegex(RuntimeError, "status 9") as failed:
            self.viewer._check_process_exit([])
        self.assertIn(self.diagnostic, str(failed.exception))
        self.viewer.process.returncode = 0
        self.viewer.events.put(("error", ["late Tcl failure after smoke event"]))
        with self.assertRaisesRegex(RuntimeError, "late Tcl failure"):
            self.viewer._check_process_exit([])


class PersistenceTests(unittest.TestCase):
    def test_unicode_json_roundtrip_and_nested_directory_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "簡報.json"
            deck = starter_deck()
            save_deck(path, deck)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), deck)
            self.assertIn("我的簡報", path.read_text(encoding="utf-8"))
            self.assertFalse(list(path.parent.glob("*.tmp")))

    def test_replace_failure_preserves_previous_file_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "deck.json"
            path.write_text("old valid content", encoding="utf-8")
            with patch("openslide_tk.storage.os.replace", side_effect=OSError("simulated failure")):
                with self.assertRaises(OSError):
                    atomic_write(path, "replacement content")
            self.assertEqual(path.read_text(), "old valid content")
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_new_content_is_flushed_before_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "deck.json"
            path.write_text("old", encoding="utf-8")
            real_replace = os.replace
            events = []

            def sync(fd):
                events.append("fsync")

            def replace(source, destination):
                self.assertEqual(Path(source).parent, path.parent)
                self.assertEqual(Path(source).read_text(), "完整 replacement")
                self.assertEqual(path.read_text(), "old")
                self.assertEqual(events, ["fsync"])
                events.append("replace")
                return real_replace(source, destination)

            with patch("openslide_tk.storage.os.fsync", side_effect=sync), patch("openslide_tk.storage.os.replace", side_effect=replace):
                atomic_write(path, "完整 replacement")
            self.assertEqual(events, ["fsync", "replace"])
            self.assertEqual(path.read_text(), "完整 replacement")

    def test_invalid_open_preserves_active_document_and_save_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            active = Path(temporary) / "active.json"
            rejected = Path(temporary) / "invalid.json"
            save_deck(active, starter_deck())
            rejected.write_text("{broken JSON", encoding="utf-8")
            viewer = Viewer(active)
            with self.assertRaises(ValueError):
                viewer.action("open", [str(rejected)])
            self.assertEqual(viewer.path, active.resolve())
            self.assertEqual(viewer.deck, starter_deck())
            self.assertEqual(rejected.read_text(), "{broken JSON")

    def test_failed_new_preserves_active_document_and_save_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            active = Path(temporary) / "active.json"
            rejected = Path(temporary) / "unwritable.json"
            save_deck(active, starter_deck())
            viewer = Viewer(active)
            with patch("openslide_tk.viewer.save_deck", side_effect=OSError("simulated disk error")):
                with self.assertRaises(OSError):
                    viewer.action("new", [str(rejected)])
            self.assertEqual(viewer.path, active.resolve())
            self.assertEqual(viewer.deck, starter_deck())


@unittest.skipUnless(TCLSH, TCLSH_MISSING)
class TclBoundaryTests(unittest.TestCase):
    def test_tcl_word_roundtrips_inert_data_in_real_interpreter(self):
        samples = ["", "ordinary text", "繁體中文 🎞️", "[set injected 1]; set injected 1", "$injected {closing} \\ slash\nsecond line\tcolumn", '"; set injected 1; #']
        for sample in samples:
            with self.subTest(sample=sample):
                program = "set injected 0\nset result " + tcl_word(sample) + "\nputs [binary encode hex [encoding convertto utf-8 $result]]\nputs $injected\n"
                result = subprocess.run([TCLSH], input=program, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertEqual(result.stdout.splitlines(), [sample.encode("utf-8").hex(), "0"])

    def test_send_keeps_multiline_and_tcl_syntax_inside_one_argument(self):
        viewer = Viewer.__new__(Viewer)
        sink = io.StringIO()
        viewer.process = types.SimpleNamespace(stdin=sink)
        content = "[set injected 1];\nputs BAD; $injected {資料}"
        viewer.send("capture", content, "second argument")
        self.assertEqual(sink.getvalue().count("\n"), 1)
        program = "set injected 0\nproc capture {a b} {puts [binary encode hex [encoding convertto utf-8 $a]]; puts $b}\n" + sink.getvalue() + "puts $injected\n"
        result = subprocess.run([TCLSH], input=program, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout.splitlines(), [content.encode().hex(), "second argument", "0"])

    def test_incoming_events_decode_unicode_and_reject_malformed_hex(self):
        viewer = Viewer.__new__(Viewer)
        viewer.events = queue.Queue()
        viewer.process = types.SimpleNamespace(stdout=io.StringIO("notes\t" + "繁體\n備註".encode().hex() + "\nedit\tnot-hex\n"))
        viewer._read_events()
        self.assertEqual(viewer.events.get_nowait(), ("notes", ["繁體\n備註"]))
        self.assertEqual(viewer.events.get_nowait()[0], "error")


class HeadlessCliTests(unittest.TestCase):
    def run_cli(self, *arguments):
        environment = dict(os.environ, DISPLAY="", OPENSLIDE_WISH="/nonexistent/no-gui-permitted")
        return subprocess.run([sys.executable, "-m", "openslide_tk", *map(str, arguments)], cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30)

    def test_init_validate_and_native_pptx_export_without_display(self):
        with tempfile.TemporaryDirectory() as temporary:
            deck = Path(temporary) / "deck.json"
            output = Path(temporary) / "deck.pptx"
            for arguments in [("init", deck), ("validate", deck), ("export", deck, output)]:
                result = self.run_cli(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(output) as archive:
                self.assertIsNone(archive.testzip())
                self.assertIn("ppt/slides/slide1.xml", archive.namelist())
                self.assertIn("我的簡報", json.loads(deck.read_text())["title"])

    def test_init_does_not_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            deck = Path(temporary) / "deck.json"
            deck.write_text("existing content", encoding="utf-8")
            result = self.run_cli("init", deck)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(deck.read_text(), "existing content")

    def test_export_never_launches_a_child_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            deck = Path(temporary) / "deck.json"
            output = Path(temporary) / "deck.pptx"
            save_deck(deck, starter_deck())
            with patch("subprocess.Popen", side_effect=AssertionError("Headless export must not launch wish, Node or a browser")), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(main(["export", str(deck), str(output)]), 0)
            self.assertTrue(output.is_file())

    def test_svg_rejects_zero_or_out_of_range_slide_numbers(self):
        with tempfile.TemporaryDirectory() as temporary:
            deck = Path(temporary) / "deck.json"
            output = Path(temporary) / "deck.svg"
            save_deck(deck, starter_deck())
            for index in [0, -1, 2]:
                with self.subTest(index=index):
                    result = self.run_cli("export", deck, output, "--slide", index)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertFalse(output.exists())

    def test_validate_rejects_duplicate_json_keys_consistently_with_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            deck = Path(temporary) / "ambiguous.json"
            content = json.dumps(starter_deck(), ensure_ascii=False)
            deck.write_text(content.replace('"schema_version": 1', '"schema_version": 2, "schema_version": 1'), encoding="utf-8")
            for arguments in [("validate", deck), ("export", deck, Path(temporary) / "deck.pptx")]:
                with self.subTest(command=arguments[0]):
                    result = self.run_cli(*arguments)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertNotIn("Traceback", result.stderr)

    def test_malformed_json_has_a_clear_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            deck = Path(temporary) / "broken.json"
            deck.write_text("{not json", encoding="utf-8")
            result = self.run_cli("validate", deck)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Traceback", result.stderr)


class AllSlidesProbe(Viewer):
    """Only the test process adds this diagnostic; shipping Tcl stays unchanged."""

    def __init__(self, path):
        super().__init__(path, smoke_test=True)
        self.probes = []

    def send(self, command, *args):
        if command == "::os::smoke":
            diagnostic = r'''
proc ::os::probe {} {
    update idletasks
    set canvas .body.canvas
    set cw [winfo width $canvas]
    set ch [winfo height $canvas]
    set s [expr {min(double($cw)/$::os::width,double($ch)/$::os::height)}]
    set left [expr {($cw-$::os::width*$s)/2}]
    set top [expr {($ch-$::os::height*$s)/2}]
    set right [expr {$left+$::os::width*$s}]
    set bottom [expr {$top+$::os::height*$s}]
    set rows [list "$cw,$ch,$left,$top,$right,$bottom"]
    foreach e $::os::elements {
        set id [dict get $e id]
        set bounds [$canvas bbox "id:$id"]
        if {[llength $bounds] != 4} {
            lappend rows "$id|MISSING"
        } else {
            set declared [list [expr {$left+[dict get $e x]*$s}] [expr {$top+[dict get $e y]*$s}] [expr {$left+([dict get $e x]+[dict get $e width])*$s}] [expr {$top+([dict get $e y]+[dict get $e height])*$s}]]
            lappend rows "$id|[dict get $e type]|[join $bounds ,]|[join $declared ,]"
        }
    }
    ::os::emit probe [join $rows "\n"]
}
after 150 ::os::probe
'''
            super().send("eval", diagnostic)
        else:
            super().send(command, *args)

    def action(self, action, args):
        if action != "probe":
            return super().action(action, args)
        lines = args[0].splitlines()
        viewport = list(map(float, lines[0].split(",")))
        rows = []
        for line in lines[1:]:
            parts = line.split("|")
            rows.append({"id": parts[0], "missing": len(parts) == 2, **({"type": parts[1], "bbox": list(map(float, parts[2].split(","))), "declared_bbox": list(map(float, parts[3].split(",")))} if len(parts) == 4 else {})})
        self.probes.append({"slide_index": self.navigation.index, "viewport": viewport, "elements": rows})
        next_index = self.navigation.index + 1
        if next_index == len(self.deck["slides"]):
            self.smoke_result = {"ok": True, "slides": self.probes}
        else:
            self.navigation = self._navigator(next_index)
            self.render()
            super().send("after", 80, "::os::probe")


@unittest.skipUnless(os.environ.get("OPENSLIDE_GUI_TEST") == "1", "Set OPENSLIDE_GUI_TEST=1 to inspect every slide in a real Tk window")
class GuiBoundsTests(unittest.TestCase):
    probe_result = None

    def test_all_demo_slides_render_inside_their_canvas(self):
        probe = AllSlidesProbe(ROOT / "examples/demo.json")
        result = probe.run()
        type(self).probe_result = result
        self.assertEqual(len(result["slides"]), len(probe.deck["slides"]))
        failures = []
        for slide in result["slides"]:
            _, _, left, top, right, bottom = slide["viewport"]
            for element in slide["elements"]:
                if element["missing"]:
                    failures.append((slide["slide_index"], element["id"], "missing"))
                    continue
                x1, y1, x2, y2 = element["bbox"]
                if x1 < left - 2 or y1 < top - 2 or x2 > right + 2 or y2 > bottom + 2:
                    failures.append((slide["slide_index"], element["id"], "outside canvas", element["bbox"]))
                if element["type"] == "text":
                    dx1, dy1, dx2, dy2 = element["declared_bbox"]
                    if x1 < dx1 - 3 or y1 < dy1 - 3 or x2 > dx2 + 3 or y2 > dy2 + 3:
                        failures.append((slide["slide_index"], element["id"], "outside text box", element["bbox"], element["declared_bbox"]))
        self.assertEqual(failures, [], failures)


if __name__ == "__main__":
    unittest.main()
