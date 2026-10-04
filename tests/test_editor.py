"""Saved editor operations remain atomic, reversible and correctly targeted."""
import base64
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openslide_tk.__main__ import starter_deck
from openslide_tk.model import image_info, validate_deck
from openslide_tk.storage import save_deck
from openslide_tk.viewer import Viewer


class RecordingViewer(Viewer):
    def __init__(self, path):
        self.messages = []
        super().__init__(path)

    def send(self, command, *args):
        self.messages.append((command, args))


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "deck.json"
        self.deck = starter_deck()
        first = self.deck["slides"][0]
        first["elements"][0]["href"] = "#welcome"
        for index in (2, 3):
            slide = copy.deepcopy(first)
            slide["id"] = f"slide-{index}"
            slide["title"] = f"Page {index}"
            self.deck["slides"].append(slide)
        save_deck(self.path, self.deck)
        self.viewer = RecordingViewer(self.path)

    def tearDown(self):
        if self.viewer._raster_executor is not None:
            self.viewer._raster_executor.shutdown(wait=True, cancel_futures=True)
        self.temporary.cleanup()

    def disk(self):
        return json.loads(self.path.read_text())

    def form(self, *values):
        self.viewer.action("save_form", ["welcome", "title", *values])

    def test_form_save_unicode_styles_and_undo_redo_restore_disk(self):
        self.form("text", "新標題 [literal] $value\n下一行", "font_size", "90", "color", "#AA6633",
                  "x", "150.5", "width", "1500", "bold", "0", "align", "center")
        saved = copy.deepcopy(self.viewer.deck)
        element = saved["slides"][0]["elements"][0]
        self.assertEqual(element["text"], "新標題 [literal] $value\n下一行")
        self.assertEqual((element["font_size"], element["x"], element["bold"]), (90, 150.5, False))
        self.assertEqual(self.disk(), saved)
        self.assertEqual(len(self.viewer.undo_stack), 1)
        self.viewer.action("undo", [])
        self.assertEqual(self.disk(), self.deck)
        self.assertEqual(self.viewer.deck, self.deck)
        self.viewer.action("redo", [])
        self.assertEqual(self.disk(), saved)
        self.assertEqual(self.viewer.deck, saved)

    def test_invalid_edit_preserves_memory_file_selection_and_history(self):
        self.viewer.action("edit", ["title"])
        before = self.path.read_bytes()
        for values in (("font_size", "not a number"), ("color", "red"), ("width", "-10"),
                       ("x", "nan"), ("x", "inf"), ("id", "changed"), ("x", "1", "x", "2")):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.form(*values)
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(self.viewer.deck, self.deck)
            self.assertEqual(self.viewer.inspected, ("welcome", "title"))
            self.assertEqual(self.viewer.undo_stack, [])

    def test_failed_write_preserves_edit_and_undo_history(self):
        self.form("text", "Saved change")
        saved = copy.deepcopy(self.viewer.deck)
        history = copy.deepcopy(self.viewer.undo_stack)
        with patch("openslide_tk.viewer.save_deck", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.form("text", "Must not commit")
            with self.assertRaises(OSError):
                self.viewer.action("undo", [])
        self.assertEqual(self.viewer.deck, saved)
        self.assertEqual(self.disk(), saved)
        self.assertEqual(self.viewer.undo_stack, history)
        self.assertEqual(self.viewer.redo_stack, [])

    def test_new_edit_after_undo_discards_redo(self):
        self.form("text", "First edit")
        self.viewer.action("undo", [])
        self.assertEqual(len(self.viewer.redo_stack), 1)
        self.form("text", "Different edit")
        self.assertEqual(self.viewer.redo_stack, [])
        saved = copy.deepcopy(self.viewer.deck)
        self.viewer.action("redo", [])
        self.assertEqual(self.viewer.deck, saved)

    def test_duplicate_uses_unique_slide_and_element_ids_and_fixes_self_link(self):
        self.viewer.action("duplicate_slide", [])
        duplicate = self.viewer.deck["slides"][1]
        self.assertEqual(self.viewer.navigation.index, 1)
        self.assertEqual(duplicate["id"], "welcome-copy")
        self.assertEqual(duplicate["elements"][0]["href"], "#welcome-copy")
        originals = {e["id"] for s in self.deck["slides"] for e in s["elements"]}
        self.assertTrue(all(e["id"] not in originals for e in duplicate["elements"]))
        self.viewer.navigation = self.viewer._navigator(0)
        self.viewer.action("duplicate_slide", [])
        ids = [slide["id"] for slide in self.viewer.deck["slides"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("welcome-copy-2", ids)
        self.assertFalse([d for d in validate_deck(self.viewer.deck) if d["severity"] == "error"])

    def test_delete_cleans_links_and_undo_restores_them(self):
        self.viewer.action("delete_slide", [])
        self.assertEqual(len(self.viewer.deck["slides"]), 2)
        self.assertEqual(self.viewer.deck["slides"][0]["id"], "slide-2")
        self.assertTrue(all("href" not in s["elements"][0] for s in self.viewer.deck["slides"]))
        self.viewer.action("undo", [])
        self.assertEqual(self.viewer.deck, self.deck)
        self.assertEqual(self.viewer.navigation.index, 0)
        self.viewer.action("delete_slide", [])
        self.viewer.action("delete_slide", [])
        last = copy.deepcopy(self.viewer.deck)
        with self.assertRaisesRegex(ValueError, "至少"):
            self.viewer.action("delete_slide", [])
        self.assertEqual(self.viewer.deck, last)
        self.assertEqual(self.disk(), last)

    def test_move_preserves_active_slide_and_boundary_is_noop(self):
        self.viewer.action("move_slide", ["-1"])
        self.assertEqual(self.viewer.undo_stack, [])
        self.viewer.action("move_slide", ["1"])
        self.assertEqual([s["id"] for s in self.viewer.deck["slides"]], ["slide-2", "welcome", "slide-3"])
        self.assertEqual(self.viewer.navigation.index, 1)
        self.viewer.action("undo", [])
        self.assertEqual(self.viewer.deck, self.deck)
        self.assertEqual(self.viewer.navigation.index, 0)
        with self.assertRaises(ValueError):
            self.viewer.action("move_slide", ["20"])

    def test_delayed_form_event_targets_explicit_slide(self):
        self.viewer.navigation = self.viewer._navigator(2)
        self.form("text", "Edits the original page")
        self.assertEqual(self.viewer.deck["slides"][0]["elements"][0]["text"], "Edits the original page")
        self.assertEqual(self.viewer.deck["slides"][2]["elements"][0]["text"], self.deck["slides"][2]["elements"][0]["text"])
        self.viewer.action("delete_slide", [])
        with self.assertRaises(ValueError):
            self.form("text", "Deleted object")

    def test_external_change_is_not_overwritten_by_edit_or_undo(self):
        self.form("text", "Saved edit")
        external = copy.deepcopy(self.deck)
        external["title"] = "External update"
        save_deck(self.path, external)
        changed_time = self.viewer.modified + 1_000_000_000
        os.utime(self.path, ns=(changed_time, changed_time))
        with self.assertRaisesRegex(ValueError, "其他程式"):
            self.form("text", "Should not overwrite")
        with self.assertRaises(ValueError):
            self.viewer.action("undo", [])
        self.assertEqual(self.disk(), external)
        self.viewer.reload()
        self.assertEqual(self.viewer.deck, external)
        self.assertEqual(self.viewer.undo_stack, [])

    def test_png_preview_worker_resizes_caches_and_contains_asset_paths(self):
        try:
            from .test_model import png_bytes
        except ImportError:
            from test_model import png_bytes
        asset = self.path.parent / "pixel.png"
        asset.write_bytes(png_bytes())
        self.viewer.action("image_request", ["request-one", str(asset), "24", "18"])
        event, args = self.viewer.events.get(timeout=10)
        self.assertEqual(event, "_image_result")
        self.viewer.action(event, args)
        command, arguments = self.viewer.messages[-1]
        self.assertEqual(command, "::os::raster_ready")
        self.assertEqual(arguments[0], "request-one")
        self.assertEqual(image_info(base64.b64decode(arguments[1]))[1:], (24, 18))
        self.viewer.action("image_request", ["request-two", str(asset), "24", "18"])
        self.assertTrue(self.viewer.events.empty())
        self.assertEqual(self.viewer.messages[-1][0], "::os::raster_ready")
        self.assertEqual(self.viewer.messages[-1][1][0], "request-two")
        self.viewer.action("image_request", ["outside", "/etc/passwd", "20", "20"])
        self.assertEqual(self.viewer.messages[-1][0], "::os::raster_unavailable")
        self.assertEqual(self.viewer.messages[-1][1][1], "invalid")

    def test_advanced_json_rejects_duplicates_and_notes_are_reversible(self):
        raw = json.dumps(self.deck).replace('"schema_version": 1', '"schema_version": 1, "schema_version": 2')
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.viewer.action("save_source", [raw])
        self.viewer.action("notes", ["新的講者備註"])
        self.assertEqual(self.disk()["slides"][0]["notes"], "新的講者備註")
        self.viewer.action("undo", [])
        self.assertEqual(self.viewer.deck, self.deck)


class FormProbe(Viewer):
    def send(self, command, *args):
        if command != "::os::smoke":
            return super().send(command, *args)
        self.action("edit", [self.deck["slides"][0]["elements"][0]["id"]])
        script = r"""
proc ::os::form_probe {} {
    focus -force .body.inspector.tabs.content.text
    update
    ::os::shortcut next
    ::os::shortcut full
    set ::os::form(font_size) 82
    set ::os::form(color) #AABBCC
    .body.inspector.tabs.content.text delete 1.0 end
    .body.inspector.tabs.content.text insert 1.0 {表單已完成 Unicode edit}
    ::os::apply_inspector
    after 250 ::os::form_probe_result
}
proc ::os::form_probe_result {} {
    ::os::emit form_probe $::os::fullscreen [.body.inspector.tabs.content.text get 1.0 end-1c] [.toolbar.undo instate !disabled]
}
after 100 ::os::form_probe
"""
        super().send("eval", script)

    def action(self, action, args):
        if action == "form_probe":
            self.smoke_result = {"fullscreen": int(args[0]), "text": args[1], "undo_enabled": bool(int(args[2]))}
        else:
            super().action(action, args)


class InspectorLayoutProbe(Viewer):
    def send(self, command, *args):
        if command != "::os::smoke":
            return super().send(command, *args)
        self.action("edit", [self.deck["slides"][0]["elements"][0]["id"]])
        script = r"""
proc ::os::layout_probe {} {
    set rows {}
    foreach geometry {1440x900 1080x680} {
        wm geometry . $geometry
        update
        foreach tab {content geometry} {
            .body.inspector.tabs select .body.inspector.tabs.$tab
            update idletasks
            set panel .body.inspector
            set apply .body.inspector.apply
            set top [winfo rooty $panel]
            set bottom [expr {$top+[winfo height $panel]}]
            set button_top [winfo rooty $apply]
            set button_bottom [expr {$button_top+[winfo height $apply]}]
            set viewport .body.inspector.tabs.$tab.viewport
            set region [$viewport cget -scrollregion]
            set content_height [lindex $region 3]
            set viewport_height [winfo height $viewport]
            lappend rows [join [list $geometry $tab [winfo ismapped $apply] $top $bottom $button_top $button_bottom $content_height $viewport_height] ,]
            $viewport yview moveto 1
            update idletasks
            if {![winfo ismapped $apply]} {error "Apply disappeared after scrolling"}
        }
    }
    ::os::emit layout_probe [join $rows |]
}
after 100 ::os::layout_probe
"""
        super().send("eval", script)

    def action(self, action, args):
        if action == "layout_probe":
            self.smoke_result = {"rows": [row.split(",") for row in args[0].split("|")]}
        else:
            super().action(action, args)


@unittest.skipUnless(os.environ.get("OPENSLIDE_GUI_TEST") == "1", "Set OPENSLIDE_GUI_TEST=1 to exercise the real Tk form")
class GuiEditorTests(unittest.TestCase):
    def test_apply_stays_visible_and_tabs_scroll_at_minimum_window_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "layout.json"
            save_deck(path, starter_deck())
            result = InspectorLayoutProbe(path, smoke_test=True).run()
            self.assertEqual(len(result["rows"]), 4)
            for row in result["rows"]:
                geometry, tab, *values = row
                mapped, top, bottom, button_top, button_bottom, content_height, viewport_height = map(float, values)
                with self.subTest(geometry=geometry, tab=tab):
                    self.assertEqual(mapped, 1)
                    self.assertGreaterEqual(button_top, top)
                    self.assertLessEqual(button_bottom, bottom)
                    self.assertGreater(button_bottom - button_top, 20)
                    self.assertGreater(viewport_height, 50)
                    if geometry == "1080x680" and tab == "content":
                        self.assertGreater(content_height, viewport_height)

    def test_real_form_saves_and_editing_focus_blocks_navigation_shortcuts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "form.json"
            deck = starter_deck()
            second = copy.deepcopy(deck["slides"][0])
            second["id"] = "second"
            deck["slides"].append(second)
            save_deck(path, deck)
            viewer = FormProbe(path, smoke_test=True)
            result = viewer.run()
            self.assertEqual(result["fullscreen"], 0)
            self.assertEqual(viewer.navigation.index, 0)
            self.assertEqual(result["text"], "表單已完成 Unicode edit")
            self.assertTrue(result["undo_enabled"])
            saved = json.loads(path.read_text())
            first = saved["slides"][0]["elements"][0]
            self.assertEqual((first["text"], first["font_size"], first["color"]), ("表單已完成 Unicode edit", 82, "#AABBCC"))
            self.assertEqual(saved["slides"][1], second)


if __name__ == "__main__":
    unittest.main()
