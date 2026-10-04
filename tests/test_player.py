"""Offline player contract and state tests; Node is an optional QA interpreter."""
import copy
import base64
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from openslide_tk.export import export_html, svg_markup
from openslide_tk.model import validate_deck
from openslide_tk.pptx import export_pptx
try:
    from .test_model import png_bytes, sample_deck
except ImportError:
    from test_model import png_bytes, sample_deck

ROOT = Path(__file__).resolve().parents[1]
PLAYER = ROOT / "openslide_tk" / "web" / "player.js"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
S = "{http://www.w3.org/2000/svg}"


class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nodes = []
        self.script_text = []
        self.in_script = False

    def handle_starttag(self, tag, attributes):
        self.nodes.append((tag, dict(attributes)))
        if tag == "script":
            self.in_script = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False

    def handle_data(self, data):
        if self.in_script:
            self.script_text.append(data)


class PlayerExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.deck = sample_deck()
        self.deck["slides"][0]["elements"][0]["step"] = 3
        self.deck["slides"].append({"id": "two", "title": "第二頁", "elements": []})

    def tearDown(self):
        self.temporary.cleanup()

    def test_interactive_is_embedded_progressively_enhanced_and_reproducible(self):
        before = copy.deepcopy(self.deck)
        first = export_html(self.deck, self.root / "first.html", interactive=True).read_text()
        second = export_html(self.deck, self.root / "second.html", interactive=True).read_text()
        self.assertEqual(first, second)
        self.assertEqual(self.deck, before)
        parsed = Document()
        parsed.feed(first)
        scripts = [attrs for tag, attrs in parsed.nodes if tag == "script"]
        self.assertEqual(scripts, [{}])
        self.assertEqual("".join(parsed.script_text), PLAYER.read_text())
        policy = next(attrs["content"] for tag, attrs in parsed.nodes if tag == "meta" and attrs.get("http-equiv") == "Content-Security-Policy")
        for tag in ("style", "script"):
            content = re.search("<" + tag + ">(.*?)</" + tag + ">", first, re.S).group(1)
            digest = base64.b64encode(hashlib.sha256(content.encode()).digest()).decode()
            self.assertIn(tag + "-src 'sha256-" + digest + "'", policy)
        self.assertNotIn("unsafe-inline", policy)
        self.assertNotIn("unsafe-eval", policy)
        slides = [attrs for _, attrs in parsed.nodes if "data-os-slide" in attrs]
        self.assertEqual([s["data-os-slide"] for s in slides], ["1", "2"])
        self.assertTrue(all("hidden" not in s for s in slides), "No-JS must expose every slide")
        self.assertEqual([a["data-os-step"] for _, a in parsed.nodes if "data-os-step" in a], ["3"])
        self.assertNotIn('class="os-step-hidden"', first)
        self.assertEqual(sum(tag == "svg" for tag, _ in parsed.nodes), 2, "No serialized thumbnail copies")
        ids = [a["id"] for _, a in parsed.nodes if "id" in a]
        self.assertEqual(len(ids), len(set(ids)))
        for name in ("os-prev", "os-next", "os-page", "os-progress", "os-directory", "os-notes-toggle", "os-fullscreen", "os-timer", "os-full-toggle"):
            self.assertIn(name, ids)
        self.assertIn("@media print", first)
        self.assertIn(".os-enhanced .os-step-hidden { visibility: visible; }", first)
        self.assertIn("prefers-reduced-motion: reduce", first)
        self.assertFalse(any(tag in ("script", "link", "iframe") and ("src" in a or "href" in a) for tag, a in parsed.nodes))

    def test_scene_and_notes_cannot_terminate_script_or_create_dom_handlers(self):
        attack = '</script><script>globalThis.COMPROMISED=1</script><img src=x onerror="alert(1)"> & "'
        self.deck["title"] = attack
        slide = self.deck["slides"][0]
        slide["title"] = attack
        slide["notes"] = attack
        slide["elements"][0]["text"] = attack
        slide["elements"][0]["alt"] = attack
        slide["elements"][0]["font_family"] = 'Custom";fill:red;/*'
        html = export_html(self.deck, self.root / "safe.html", interactive=True).read_text()
        parsed = Document()
        parsed.feed(html)
        self.assertEqual(sum(tag == "script" for tag, _ in parsed.nodes), 1)
        self.assertFalse(any(tag == "img" for tag, _ in parsed.nodes))
        self.assertFalse(any(key.lower().startswith("on") for _, attrs in parsed.nodes for key in attrs))
        self.assertNotIn("COMPROMISED", "".join(parsed.script_text))
        self.assertIn("&lt;/script&gt;", html)
        self.assertNotRegex(PLAYER.read_text(), r"\.innerHTML\s*=|\.outerHTML\s*=|insertAdjacentHTML|\beval\s*\(")

    def test_native_svg_helper_embeds_assets_and_maps_local_navigation(self):
        (self.root / "pixel.png").write_bytes(png_bytes())
        self.deck["slides"][0]["elements"].append({"id": "image", "type": "image", "x": 1, "y": 1, "width": 40, "height": 40, "path": "pixel.png", "alt": "test", "href": "#two"})
        svg = ET.fromstring(svg_markup(self.deck, 0, self.root, {"two": "#chapter-two"}))
        self.assertEqual(svg.find(".//" + S + "a").attrib["href"], "#chapter-two")
        self.assertTrue(svg.find(".//" + S + "image").attrib["href"].startswith("data:image/png;base64,"))
        for mapping in ({}, {"two": "javascript:alert(1)"}, {"two": "#bad space"}):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                svg_markup(self.deck, 0, self.root, mapping)
        with self.assertRaises(ValueError):
            svg_markup(self.deck, True, self.root)

    def test_type_errors_and_unsafe_urls_leave_output_intact(self):
        output = self.root / "untouched.html"
        output.write_text("original")
        with self.assertRaises(ValueError):
            export_html(self.deck, output, interactive="yes")
        self.deck["slides"][0]["elements"][0]["href"] = "javascript:alert(1)"
        with self.assertRaises(ValueError):
            export_html(self.deck, output, interactive=True)
        self.assertEqual(output.read_text(), "original")

    def test_cli_requires_html_and_keeps_default_script_free(self):
        source = self.root / "deck.json"
        source.write_text(json.dumps(self.deck))
        for suffix in ("pptx", "svg", "pdf"):
            output = self.root / ("bad." + suffix)
            command = [sys.executable, "-m", "openslide_tk", "export", str(source), str(output), "--interactive"]
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("--interactive requires an .html output", result.stderr)
            self.assertFalse(output.exists())
        for interactive in (False, True):
            output = self.root / (str(interactive) + ".html")
            command = [sys.executable, "-m", "openslide_tk", "export", str(source), str(output)]
            if interactive:
                command.append("--interactive")
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual("<script>" in output.read_text(), interactive)

    def test_pptx_east_asian_face_and_svg_fallback_are_distinct(self):
        element = self.deck["slides"][0]["elements"][0]
        for face in (None, "Noto Sans CJK TC"):
            if face:
                element["east_asian_font"] = face
            path = export_pptx(self.deck, self.root / "font.pptx")
            with zipfile.ZipFile(path) as archive:
                slide = ET.fromstring(archive.read("ppt/slides/slide1.xml"))
                for run in list(slide.iter(A + "rPr")) + list(slide.iter(A + "endParaRPr")):
                    self.assertEqual(run.find(A + "latin").attrib["typeface"], "Arial")
                    self.assertEqual(run.find(A + "ea").attrib["typeface"], face or "Microsoft JhengHei")
                for filename in ("ppt/theme/theme1.xml", "ppt/theme/theme2.xml", "ppt/notesSlides/notesSlide1.xml"):
                    theme = ET.fromstring(archive.read(filename))
                    self.assertTrue(list(theme.iter(A + "ea")))
                    self.assertTrue(all(n.attrib["typeface"] == (face or "Microsoft JhengHei") for n in theme.iter(A + "ea")))
            svg = ET.fromstring(svg_markup(self.deck, 0))
            stack = svg.find(".//" + S + "text").attrib["font-family"]
            self.assertTrue(all(name in stack for name in ("Arial", "PingFang TC", "Microsoft JhengHei", "Noto Sans CJK TC", "sans-serif")))
            if face:
                self.assertLess(stack.index(face), stack.index("PingFang TC"))

    def test_font_names_are_individual_faces_not_css_lists(self):
        for key in ("font_family", "east_asian_font"):
            for value in ("", "Arial, sans-serif", "Font\nSecond", "x" * 129, 42):
                deck = copy.deepcopy(self.deck)
                deck["slides"][0]["elements"][0][key] = value
                errors = [d for d in validate_deck(deck) if d["severity"] == "error"]
                self.assertTrue(errors, (key, value))
                self.assertTrue(any(d["path"].endswith("." + key) for d in errors))

    @unittest.skipUnless(shutil.which("node"), "Optional state-machine QA needs a JavaScript interpreter; exports do not")
    def test_presenter_keys_share_reveal_state_and_preserve_control_focus(self):
        assertions = r'''
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);
vm.runInContext(`globalThis.state = new OpenSlidePlayback([[4,2],[],[1]]);`, context);
const s = context.state;
const key = (key, extra={}) => ({key, target:{closest:()=>null}, ...extra});
assert.equal(s.handleKey(key("PageDown")), true); assert.equal(s.revealed,1); assert.equal(s.index,0);
assert.equal(s.handleKey(key(" ")), true); assert.equal(s.revealed,2); assert.equal(s.index,0);
assert.equal(s.handleKey(key("PageDown")), true); assert.equal(s.index,1);
assert.equal(s.handleKey(key(" ",{shiftKey:true})), true); assert.equal(s.index,0); assert.equal(s.revealed,2);
assert.equal(s.handleKey(key("PageUp")), true); assert.equal(s.revealed,1);
assert.equal(s.handleKey(key(" ",{shiftKey:true})), true); assert.equal(s.revealed,0);
assert.equal(s.handleKey(key("PageUp")), true); assert.equal(s.index,0); assert.equal(s.revealed,0);
assert.equal(s.handleKey(key("End")), true); assert.equal(s.index,2); assert.equal(s.revealed,1);
assert.equal(s.handleKey(key(" ")), true); assert.equal(s.index,2); assert.equal(s.revealed,1);
assert.equal(s.handleKey(key("Home")), true); assert.equal(s.index,0); assert.equal(s.revealed,0);
assert.equal(s.handleKey(key("Spacebar")), true); assert.equal(s.revealed,1);
s.setFull(true); s.handleKey(key("PageDown")); assert.equal(s.index,1);
s.handleKey(key(" ",{shiftKey:true})); assert.equal(s.index,0);
s.setFull(false); s.go(0);
// Simulate closest() matching a focused control or an ancestor of its child.
for (const selector of ["input","textarea","select","[contenteditable]","[role='textbox']",".os-notes"]) {
 const target={closest:query=>query.split(", ").includes(selector)?{}:null};
 for (const name of [" ","PageDown","PageUp","ArrowRight","Home","End"]) {
  assert.equal(s.handleKey(key(name,{target})),false,selector+" "+name);
  assert.equal(s.index,0); assert.equal(s.revealed,0);
 }
 assert.equal(s.handleKey(key(" ",{target,shiftKey:true})),false);
}
// Clicking Next leaves the button focused; a presentation remote must still
// reveal the next group and advance. Space/Enter must not cause a second action.
for (const selector of ["button","a","summary","[role='button']","[role='link']"]) {
 const target={closest:query=>query.split(", ").includes(selector)?{}:null};
 s.go(0); s.next(); // Native click already revealed the first group.
 assert.equal(s.handleKey(key("PageDown",{target})),true,selector);
 assert.equal(s.index,0); assert.equal(s.revealed,2);
 for (const name of [" ","Spacebar","Enter"]) {
  assert.equal(s.handleKey(key(name,{target})),false,selector+" "+name);
  assert.equal(s.index,0); assert.equal(s.revealed,2);
 }
 assert.equal(s.handleKey(key(" ",{target,shiftKey:true})),false);
 s.handleKey(key("ArrowRight",{target})); assert.equal(s.index,1);
 s.handleKey(key("PageUp",{target})); assert.equal(s.index,0); assert.equal(s.revealed,2);
 s.handleKey(key("ArrowLeft",{target})); assert.equal(s.revealed,1);
 s.handleKey(key("End",{target})); assert.equal(s.index,2); assert.equal(s.revealed,1);
 s.handleKey(key("Home",{target})); assert.equal(s.index,0); assert.equal(s.revealed,0);
}
for (const flag of ["defaultPrevented","isComposing","altKey","ctrlKey","metaKey"]) {
 assert.equal(s.handleKey(key(" ",{[flag]:true})),false,flag);
}
assert.equal(s.handleKey(key("PageDown",{shiftKey:true})),false);
assert.equal(s.handleKey(key("PageDown"),true),false);
assert.equal(s.handleKey(key("Enter")),false);
assert.equal(s.index,0); assert.equal(s.revealed,0);
console.log("presenter keys and focus boundaries passed");
'''
        result = subprocess.run([shutil.which("node"), "-e", assertions, str(PLAYER)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("presenter keys and focus boundaries passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Optional state-machine QA needs a JavaScript interpreter; exports do not")
    def test_javascript_state_machine_reveals_before_advancing_and_reverses(self):
        # Run the actual shipped state class with no browser globals. This uses
        # Node only as an available test interpreter, never during export/playback.
        assertions = r'''
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);
vm.runInContext(`globalThis.state = new OpenSlidePlayback([[9, 2, 2], [], [3]]);`, context);
const s = context.state;
assert.equal(s.canPrevious, false);
assert.equal(s.visible(2), false);
s.next(); assert.equal(s.index, 0); assert.equal(s.visible(2), true); assert.equal(s.visible(9), false);
s.next(); assert.equal(s.visible(9), true); assert.equal(s.index, 0);
s.next(); assert.equal(s.index, 1); assert.equal(s.revealed, 0);
s.previous(); assert.equal(s.index, 0); assert.equal(s.revealed, 2);
s.previous(); assert.equal(s.revealed, 1);
s.setFull(true); assert.equal(s.visible(9), true);
s.next(); assert.equal(s.index, 1);
s.next(); assert.equal(s.index, 2); assert.equal(s.canNext, false);
s.next(); assert.equal(s.index, 2);
s.setFull(false); assert.equal(s.canNext, true);
s.next(); assert.equal(s.visible(3), true); assert.equal(s.canNext, false);
s.go(0); assert.equal(s.revealed, 0);
s.go(999, true); assert.equal(s.index, 2); assert.equal(s.revealed, 1);
s.go(-3); assert.equal(s.index, 0); assert.equal(s.revealed, 0);
console.log("playback state passed");
'''
        result = subprocess.run([shutil.which("node"), "-e", assertions, str(PLAYER)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("playback state passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
