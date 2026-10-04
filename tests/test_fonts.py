"""Document font semantics, safe serialization and real Tk bridge selection."""
import copy
from html.parser import HTMLParser
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from openslide_tk.export import export_html, svg_markup
from openslide_tk.fonts import canvas_font, document_fonts
from openslide_tk.pptx import export_pptx
from openslide_tk.storage import save_deck
from openslide_tk.viewer import Viewer
try:
    from .test_model import sample_deck
except ImportError:
    from test_model import sample_deck

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
ROOT = Path(__file__).resolve().parents[1]


class FontTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.deck = sample_deck()
        self.text = self.deck["slides"][0]["elements"][0]
        self.text["east_asian_font"] = "PingFang TC"

    def tearDown(self):
        self.temporary.cleanup()

    def test_uniform_cjk_face_reaches_runs_both_themes_and_notes(self):
        path = export_pptx(self.deck, self.root / "font.pptx")
        with zipfile.ZipFile(path) as archive:
            for name in ("ppt/slides/slide1.xml", "ppt/theme/theme1.xml", "ppt/theme/theme2.xml", "ppt/notesSlides/notesSlide1.xml"):
                xml = archive.read(name)
                parsed = ET.fromstring(xml)
                if "/theme/" not in name:
                    self.assertNotIn(b"Microsoft JhengHei", xml, name)
                self.assertTrue(list(parsed.iter(A + "ea")))
                self.assertTrue(all(e.attrib["typeface"] == "PingFang TC" for e in parsed.iter(A + "ea")))
                self.assertTrue(all(e.attrib["typeface"] == "Arial" for e in parsed.iter(A + "latin")))
                if "/theme/" in name:
                    hant = [e.attrib["typeface"] for e in parsed.iter(A + "font") if e.get("script") == "Hant"]
                    self.assertEqual(hant, ["Microsoft JhengHei"] * 2)
        for interactive in (False, True):
            html = export_html(self.deck, self.root / "font.html", interactive=interactive).read_text()
            self.assertIn('font-family: "Arial", "PingFang TC",', html)

    def test_windows_theme_hint_does_not_override_other_explicit_faces(self):
        self.text["east_asian_font"] = "Custom Hant Face"
        with zipfile.ZipFile(export_pptx(self.deck, self.root / "custom.pptx")) as archive:
            for name in ("ppt/theme/theme1.xml", "ppt/theme/theme2.xml"):
                theme = ET.fromstring(archive.read(name))
                self.assertEqual([e.get("typeface") for e in theme.iter(A + "font")
                                  if e.get("script") == "Hant"], ["Custom Hant Face"] * 2)

    def test_mixed_fallback_is_per_script_order_independent_and_not_metadata(self):
        second = copy.deepcopy(self.text)
        second.update(id="second", font_family="Cambria")
        self.deck["slides"][0]["elements"].append(second)
        self.deck["metadata"] = {"east_asian_font": "UNTRUSTED_METADATA_FACE"}
        self.assertEqual(document_fonts(self.deck), ("Arial", "PingFang TC"))
        self.deck["slides"][0]["elements"].reverse()
        self.assertEqual(document_fonts(self.deck), ("Arial", "PingFang TC"))
        second["east_asian_font"] = "Heiti TC"
        self.assertEqual(document_fonts(self.deck), ("Arial", "Microsoft JhengHei"))
        with zipfile.ZipFile(export_pptx(self.deck, self.root / "mixed.pptx")) as archive:
            slide = ET.fromstring(archive.read("ppt/slides/slide1.xml"))
            self.assertEqual({e.attrib["typeface"] for e in slide.iter(A + "ea")}, {"PingFang TC", "Heiti TC"})
            theme = ET.fromstring(archive.read("ppt/theme/theme1.xml"))
            self.assertEqual({e.attrib["typeface"] for e in theme.iter(A + "ea")}, {"Microsoft JhengHei"})
        del second["east_asian_font"]
        self.assertEqual(document_fonts(self.deck), ("Arial", "Microsoft JhengHei"))
        self.deck["slides"][0]["elements"] = []
        self.assertEqual(document_fonts(self.deck), ("Arial", "Microsoft JhengHei"))

    def test_font_css_cannot_terminate_style_or_inject_script(self):
        attack = 'TC </style><script>alert(1)</script> "&'
        self.text["east_asian_font"] = attack
        class Tags(HTMLParser):
            def __init__(self): super().__init__(); self.tags = []
            def handle_starttag(self, tag, attrs): self.tags.append(tag)
        for interactive in (False, True):
            html = export_html(self.deck, self.root / "safe.html", interactive=interactive).read_text()
            parsed = Tags(); parsed.feed(html)
            self.assertEqual(parsed.tags.count("script"), int(interactive))
            self.assertEqual(parsed.tags.count("style"), 1)
            self.assertNotIn(attack, html)
        with zipfile.ZipFile(export_pptx(self.deck, self.root / "safe.pptx")) as archive:
            theme = ET.fromstring(archive.read("ppt/theme/theme1.xml"))
            self.assertEqual({e.attrib["typeface"] for e in theme.iter(A + "ea")}, {attack})

    def test_canvas_selects_explicit_ea_for_cjk_but_preserves_ascii_and_legacy(self):
        for value in ("中文", "Mix 英文 123", "かな", "한글", "\U00020000", "ＡＢＣ"):
            self.assertEqual(canvas_font({**self.text, "text": value}), "PingFang TC", value)
        for value in ("Latin123", "🎞️", ""):
            self.assertEqual(canvas_font({**self.text, "text": value}), "Arial", value)
        legacy = {**self.text, "text": "中文", "font_family": "Custom Legacy"}
        del legacy["east_asian_font"]
        self.assertEqual(canvas_font(legacy), "Custom Legacy")
        viewer = Viewer.__new__(Viewer); calls = []; viewer.send = lambda command, *args: calls.append((command, args))
        before = copy.deepcopy(self.text)
        viewer.send_element("::os::element", self.text)
        sent = dict(zip(calls[0][1][::2], calls[0][1][1::2]))
        self.assertEqual(sent["_display_font_family"], "PingFang TC")
        self.assertEqual(self.text, before, "Bridge-only family must not enter scene JSON")

    def test_editor_can_set_and_clear_ea_face_atomically(self):
        path = self.root / "deck.json"; save_deck(path, self.deck)
        viewer = Viewer(path); viewer.send = lambda *args: None
        sid = self.deck["slides"][0]["id"]; eid = self.text["id"]
        viewer.action("save_form", [sid, eid, "east_asian_font", "Heiti TC"])
        self.assertEqual(viewer.deck["slides"][0]["elements"][0]["east_asian_font"], "Heiti TC")
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            viewer.action("save_form", [sid, eid, "east_asian_font", "PingFang TC, sans-serif"])
        self.assertEqual(path.read_bytes(), before)
        viewer.action("save_form", [sid, eid, "east_asian_font", ""])
        self.assertNotIn("east_asian_font", viewer.deck["slides"][0]["elements"][0])
        viewer.action("undo", [])
        self.assertEqual(viewer.deck["slides"][0]["elements"][0]["east_asian_font"], "Heiti TC")

    def test_custom_fonts_export_with_no_site_packages_and_repeat_bytes(self):
        source = self.root / "deck.json"; save_deck(source, self.deck)
        for suffix in ("pptx", "html"):
            targets = [self.root / (name + "." + suffix) for name in ("first", "second")]
            for target in targets:
                run = subprocess.run([sys.executable, "-S", "-m", "openslide_tk", "export", str(source), str(target)], cwd=ROOT, text=True, capture_output=True)
                self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(targets[0].read_bytes(), targets[1].read_bytes())


class FontProbe(Viewer):
    def send(self, command, *args):
        if command != "::os::smoke":
            return super().send(command, *args)
        super().send("eval", r'''
proc ::os::font_probe {} {
    update idletasks
    ::os::presenter
    ::os::presenter_render
    set cjk [.body.canvas itemcget [lindex [.body.canvas find withtag id:cjk] 0] -font]
    set latin [.body.canvas itemcget [lindex [.body.canvas find withtag id:latin] 0] -font]
    ::os::emit font_probe [lindex $cjk 0] [lindex $latin 0] [lindex [.presenter.notes cget -font] 0] [font actual $cjk -family] [expr {[lsearch -exact [font families] "PingFang TC"] >= 0}]
}
after 200 ::os::font_probe
''')

    def action(self, action, args):
        if action != "font_probe":
            return super().action(action, args)
        self.smoke_result = dict(zip(("cjk", "latin", "notes", "actual_cjk", "installed"), args))


@unittest.skipUnless(os.environ.get("OPENSLIDE_GUI_TEST") == "1", "Set OPENSLIDE_GUI_TEST=1 for real Tk font selection")
class GuiFontTests(unittest.TestCase):
    def test_real_canvas_and_presenter_apply_ea_family(self):
        with tempfile.TemporaryDirectory() as temporary:
            deck = sample_deck(); slide = deck["slides"][0]
            first = slide["elements"][0]; first.update(id="cjk", east_asian_font="PingFang TC", text="晶片 Chip123", font_size=60, width=1600)
            second = copy.deepcopy(first); second.update(id="latin", text="Latin123", y=450)
            slide["elements"].append(second)
            path = Path(temporary) / "deck.json"; save_deck(path, deck)
            result = FontProbe(path, smoke_test=True).run()
            self.assertEqual((result["cjk"], result["latin"], result["notes"]), ("PingFang TC", "Arial", "PingFang TC"))
            if result["installed"] == "1":
                self.assertEqual(result["actual_cjk"], "PingFang TC")


if __name__ == "__main__":
    unittest.main()
