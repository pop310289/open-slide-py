import copy
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
import posixpath
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from openslide_tk.export import export_html, export_svg
from openslide_tk.pptx import export_pptx
try:
    from .test_model import png_bytes, sample_deck
except ImportError:
    from test_model import png_bytes, sample_deck

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
S = "{http://www.w3.org/2000/svg}"


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.ids = []
        self.links = []

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        self.tags.append(tag)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a":
            self.links.append(attrs.get("href"))


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.deck = sample_deck()
        (self.root / "pixel.png").write_bytes(png_bytes())
        elements = self.deck["slides"][0]["elements"]
        for index, kind in enumerate(("rect", "ellipse", "line", "image", "image")):
            element = {"id": kind + str(index), "type": kind, "x": 100 + 240 * index, "y": 500, "width": 200,
                       "height": 100, "fill": "#778899", "stroke": "#CCDDEE", "stroke_width": 4, "opacity": 0.65}
            if kind == "line":
                element["height"] = 0
            if kind == "image":
                element.update(path="pixel.png", alt="A tiny red pixel")
            elements.append(element)
        self.deck["slides"].append({"id": "s2", "title": "Second", "background": "#FFFFFF", "elements": []})
        elements[0]["href"] = "https://example.org/?a=1&b=2"
        elements[1]["href"] = "#s2"

    def tearDown(self):
        self.temporary.cleanup()

    def test_pptx_is_valid_opc_with_native_content_and_notes(self):
        path = export_pptx(self.deck, self.root / "deck.pptx", self.root)
        with zipfile.ZipFile(path) as archive:
            self.assertIsNone(archive.testzip())
            names = set(archive.namelist())
            parsed = {name: ET.fromstring(archive.read(name)) for name in names if name.endswith((".xml", ".rels"))}
            for name, document in parsed.items():
                if not name.endswith(".rels"):
                    continue
                if name == "_rels/.rels":
                    parent = ""
                    source_name = None
                else:
                    relpath = PurePosixPath(name)
                    parent = str(relpath.parent.parent)
                    source_name = parent + "/" + relpath.name[:-5]
                rel_ids = set()
                for relation in document:
                    self.assertNotIn(relation.attrib["Id"], rel_ids)
                    rel_ids.add(relation.attrib["Id"])
                    if relation.attrib.get("TargetMode") == "External":
                        continue
                    target = posixpath.normpath(posixpath.join(parent, relation.attrib["Target"]))
                    self.assertIn(target, names, f"Broken relationship from {name}: {target}")
                if source_name:
                    for node in parsed[source_name].iter():
                        for key, value in node.attrib.items():
                            if key in (R + "id", R + "embed", R + "link"):
                                self.assertIn(value, rel_ids)
            master_themes = []
            for master in ("ppt/slideMasters/_rels/slideMaster1.xml.rels", "ppt/notesMasters/_rels/notesMaster1.xml.rels"):
                master_themes.extend(relation.attrib["Target"] for relation in parsed[master]
                                     if relation.attrib["Type"].endswith("/theme"))
            self.assertEqual(len(set(master_themes)), 2, "PowerPoint notes and slide masters need separate theme parts")
            slide = parsed["ppt/slides/slide1.xml"]
            native_text = [node.text for node in slide.iter(A + "t")]
            self.assertEqual(native_text, ["Editable text 中文 & < >"])
            self.assertEqual(len(list(slide.iter(P + "pic"))), 2)
            self.assertEqual(len(list(slide.iter(P + "sp"))), 4)
            self.assertEqual(len([name for name in names if name.startswith("ppt/media/")]), 1)
            self.assertEqual([n.text or "" for n in parsed["ppt/notesSlides/notesSlide1.xml"].iter(A + "t")], ["Speaker notes", "第二行"])
            size = parsed["ppt/presentation.xml"].find(P + "sldSz")
            self.assertEqual(size.attrib, {"cx": "12192000", "cy": "6858000"})
            self.assertEqual(slide.find(".//" + A + "rPr").attrib["sz"], "3200")
            self.assertTrue(all(info.date_time == (2000, 1, 1, 0, 0, 0) for info in archive.infolist()))
            ct = parsed["[Content_Types].xml"]
            overrides = {node.attrib["PartName"].lstrip("/") for node in ct if "PartName" in node.attrib}
            self.assertTrue({name for name in names if name.endswith(".xml") and name != "[Content_Types].xml"} <= overrides)

    def test_omitted_text_defaults_match_tcl_viewer(self):
        text_element = self.deck["slides"][0]["elements"][0]
        for key in ("font_size", "font_family", "color"):
            text_element.pop(key, None)
        pptx = export_pptx(self.deck, self.root / "default.pptx", self.root)
        with zipfile.ZipFile(pptx) as archive:
            root = ET.fromstring(archive.read("ppt/slides/slide1.xml"))
            run = root.find(".//" + A + "rPr")
            self.assertEqual(run.attrib["sz"], "2400")
            self.assertEqual(run.find(A + "solidFill/" + A + "srgbClr").attrib["val"], "172F39")
            self.assertEqual(run.find(A + "latin").attrib["typeface"], "Arial")
        svg = ET.fromstring(export_svg(self.deck, 0, self.root / "default.svg", self.root).read_bytes())
        text = svg.find(".//" + S + "text")
        self.assertEqual(text.attrib["font-size"], "48")
        self.assertEqual(text.attrib["fill"], "#172F39")

    def test_exports_are_reproducible_and_do_not_mutate_deck(self):
        before = copy.deepcopy(self.deck)
        for exporter, suffix in ((export_pptx, ".pptx"), (export_html, ".html")):
            first = exporter(self.deck, self.root / ("one" + suffix), self.root).read_bytes()
            second = exporter(self.deck, self.root / ("two" + suffix), self.root).read_bytes()
            self.assertEqual(first, second)
        self.assertEqual(self.deck, before)

    def test_svg_has_embedded_assets_native_text_alpha_and_escape(self):
        path = export_svg(self.deck, 0, self.root / "page.svg", self.root)
        root = ET.fromstring(path.read_bytes())
        self.assertEqual(root.tag, S + "svg")
        self.assertEqual(root.attrib["viewBox"], "0 0 1920 1080")
        text = root.find(".//" + S + "tspan")
        self.assertEqual(text.text, "Editable text 中文 & < >")
        self.assertTrue(all(node.attrib["href"].startswith("data:image/png;base64,") for node in root.iter(S + "image")))
        self.assertEqual(len(list(root.iter(S + "image"))), 2)
        self.assertTrue(any(node.attrib.get("opacity") == "0.65" for node in root.iter(S + "g")))
        self.assertNotIn("<script", path.read_text())

    def test_html_is_script_free_self_contained_accessible_and_printable(self):
        self.deck["title"] = '<script>alert("unsafe")</script>'
        text = export_html(self.deck, self.root / "deck.html", self.root).read_text()
        parser = Tags()
        parser.feed(text)
        self.assertNotIn("script", parser.tags)
        self.assertEqual(parser.tags.count("svg"), 2)
        self.assertEqual(parser.tags.count("section"), 2)
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        self.assertIn("#slide-2", parser.links)
        self.assertIn("@media print", text)
        self.assertIn("prefers-reduced-motion", text)
        self.assertIn("data:image/png;base64,", text)
        self.assertIn("Speaker notes", text)
        self.assertIn("&lt;script&gt;", text)

    def test_invalid_export_leaves_existing_output_unchanged(self):
        path = self.root / "existing.pptx"
        path.write_bytes(b"original")
        self.deck["slides"][0]["elements"][0]["font_size"] = float("nan")
        with self.assertRaises(ValueError):
            export_pptx(self.deck, path, self.root)
        self.assertEqual(path.read_bytes(), b"original")
        with self.assertRaises(ValueError):
            export_html(self.deck, path, self.root)
        self.assertEqual(path.read_bytes(), b"original")

    def test_pptx_specific_size_limits_fail_before_writing(self):
        output = self.root / "unsupported.pptx"
        for dimension in (143, 8065):
            deck = copy.deepcopy(self.deck)
            deck["width"] = dimension
            with self.subTest(dimension=dimension), self.assertRaisesRegex(ValueError, "PPTX canvas"):
                export_pptx(deck, output, self.root)
            self.assertFalse(output.exists())
        for font_size in (1, 2641):
            deck = copy.deepcopy(self.deck)
            deck["slides"][0]["elements"][0]["font_size"] = font_size
            with self.subTest(font_size=font_size), self.assertRaisesRegex(ValueError, "PPTX text"):
                export_pptx(deck, output, self.root)
            self.assertFalse(output.exists())

    def test_bad_svg_slide_indices_rejected(self):
        for index in (-1, 2, True, 0.0):
            with self.subTest(index=index), self.assertRaises(ValueError):
                export_svg(self.deck, index, self.root / "bad.svg", self.root)

    def test_images_load_relative_to_deck_directory(self):
        with self.assertRaises(ValueError):
            export_pptx(self.deck, self.root / "no-base.pptx", self.root / "missing")


if __name__ == "__main__":
    unittest.main()
