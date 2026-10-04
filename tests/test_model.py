import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from openslide_tk.model import image_info, load_deck, resolve_image, validate_deck, wrap_text


def sample_deck():
    return {
        "schema_version": 1, "id": "test", "title": "中文 & Export", "width": 1920, "height": 1080,
        "slides": [{"id": "s1", "title": "Slide <one>", "background": "#112233", "notes": "Speaker notes\n第二行",
                    "elements": [{"id": "title", "type": "text", "x": 100, "y": 100, "width": 1700, "height": 200,
                                  "text": "Editable text 中文 & < >", "font_size": 64, "font_family": "Arial", "color": "#FFFFFF"}]}],
    }


def png_bytes():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\0\xff\0\0")) + chunk(b"IEND", b"")


class ModelTests(unittest.TestCase):
    def test_valid_model_is_not_modified(self):
        deck = sample_deck()
        before = copy.deepcopy(deck)
        self.assertEqual(validate_deck(deck), [])
        self.assertEqual(deck, before)

    def test_finite_geometry_and_exact_types(self):
        values = [float("nan"), float("inf"), -float("inf"), True, "100", None, 10 ** 1000]
        for value in values:
            with self.subTest(value=type(value).__name__):
                deck = sample_deck()
                deck["slides"][0]["elements"][0]["x"] = value
                self.assertIn("geometry", [d["code"] for d in validate_deck(deck)])
        deck = sample_deck()
        deck["schema_version"] = True
        self.assertIn("schema_version", [d["code"] for d in validate_deck(deck)])

    def test_errors_cover_unsupported_fields_colors_ids_and_xml(self):
        deck = sample_deck()
        deck["remote_code"] = "never run"
        element = deck["slides"][0]["elements"][0]
        element["color"] = "red"
        element["text"] = "NUL\x00surrogate\ud800"
        deck["slides"][0]["elements"].append(copy.deepcopy(element))
        deck["slides"].append(copy.deepcopy(deck["slides"][0]))
        codes = {d["code"] for d in validate_deck(deck)}
        self.assertTrue({"unknown_field", "invalid_color", "duplicate_id", "invalid_character"} <= codes)

    def test_layout_issues_are_advisory(self):
        deck = sample_deck()
        element = deck["slides"][0]["elements"][0]
        element.update(x=1900, height=20)
        diagnostics = validate_deck(deck)
        self.assertEqual({d["code"] for d in diagnostics}, {"out_of_bounds", "text_overflow"})
        self.assertTrue(all(d["severity"] == "warning" for d in diagnostics))

    def test_json_duplicate_nan_and_invalid_utf8_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deck.json"
            for invalid in (b'{"id":"a","id":"b"}', b'{"x": NaN}', b'\xff', b'{"x": [}'):
                path.write_bytes(invalid)
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    load_deck(path)
            path.write_text(json.dumps(sample_deck()), encoding="utf-8-sig")
            self.assertEqual(load_deck(path), sample_deck())

    def test_asset_containment_checksum_and_header(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            (root / "pixel.png").write_bytes(png_bytes())
            path, mime, data = resolve_image("pixel.png", root)
            self.assertEqual((mime, image_info(data)[1:]), ("image/png", (1, 1)))
            self.assertEqual(path, (root / "pixel.png").resolve())
            for forbidden in ("../pixel.png", str(root / "pixel.png"), "C:\\image.png", "https://example.com/a.png", "missing.png"):
                with self.subTest(path=forbidden), self.assertRaises(ValueError):
                    resolve_image(forbidden, root)
            other = Path(outside) / "out.png"
            other.write_bytes(png_bytes())
            (root / "escape.png").symlink_to(other)
            with self.assertRaisesRegex(ValueError, "symlink"):
                resolve_image("escape.png", root)
            (root / "fake.png").write_text('<svg><script>alert(1)</script></svg>')
            with self.assertRaises(ValueError):
                resolve_image("fake.png", root)
            damaged = bytearray(png_bytes())
            damaged[40] ^= 1
            with self.assertRaises(ValueError):
                image_info(bytes(damaged))
            for i in (0, 8, 20, 40, len(data) - 1):
                with self.subTest(truncated=i), self.assertRaises(ValueError):
                    image_info(data[:i])

    def test_links_and_step_metadata(self):
        deck = sample_deck()
        element = deck["slides"][0]["elements"][0]
        deck["metadata"] = {"author": "Tester", "source": "Local"}
        deck["slides"][0]["transition"] = "fade"
        element["step"] = 1
        for href in ("https://example.org/a?b=1&c=2", "mailto:a@example.org", "#s1"):
            element["href"] = href
            self.assertEqual(validate_deck(deck), [])
        for href in ("javascript:alert(1)", "data:text/html,hi", "file:///etc/passwd", "#missing", "http://", "https://a.org/a b"):
            element["href"] = href
            self.assertIn("unsafe_link", [d["code"] for d in validate_deck(deck)])
        element.pop("href")
        for step in (0, -1, True, 1.2):
            element["step"] = step
            self.assertIn("element_step", [d["code"] for d in validate_deck(deck)])

    def test_arbitrary_json_shapes_return_diagnostics(self):
        for value in (None, [], "a", 3, {}, {"slides": [None]}):
            with self.subTest(value=value):
                self.assertTrue(validate_deck(value))
        for value in ([], {}, None, True):
            deck = sample_deck()
            deck["slides"][0]["elements"][0]["type"] = value
            self.assertTrue(validate_deck(deck))

    def test_wrapping_handles_cjk_newlines_and_long_words(self):
        self.assertEqual(wrap_text("你好世界", 80, 40), ["你好", "世界"])
        self.assertEqual(wrap_text("first\n\nlast", 1000, 40), ["first", "", "last"])
        self.assertGreater(len(wrap_text("abcdefghijklmnopqrstuvwxyz", 80, 40)), 3)
        self.assertEqual(wrap_text("e\u0301", 40, 40), ["e\u0301"])


if __name__ == "__main__":
    unittest.main()
