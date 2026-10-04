"""A deck's lang reaches PPTX proofing marks and the HTML wrapper; decks without lang keep the original zh output."""
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

from openslide_tk.export import export_html
from openslide_tk.model import validate_deck
from openslide_tk.pptx import export_pptx
try:
    from .test_model import sample_deck
except ImportError:
    from test_model import sample_deck

CJK = re.compile(r"[㐀-鿿]")


def english_deck(lang="en-US"):
    deck = sample_deck()
    deck["title"] = "English & Export"
    deck["slides"][0]["notes"] = "Speaker notes\nSecond line"
    deck["slides"][0]["elements"][0]["text"] = "Editable text & < >"
    deck["slides"].append({"id": "s2", "title": "Second", "notes": "More notes", "elements": [
        {"id": "t2", "type": "text", "x": 100, "y": 100, "width": 900, "height": 200, "text": "Two", "font_size": 48}]})
    if lang is not None:
        deck["lang"] = lang
    return deck


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def pptx_langs(self, deck):
        path = export_pptx(deck, self.root / "deck.pptx", self.root)
        with zipfile.ZipFile(path) as z:
            parts = [n for n in z.namelist() if re.fullmatch(r"ppt/(slides/slide|notesSlides/notesSlide)\d+\.xml", n)]
            self.assertEqual(sum("notesSlide" in n for n in parts), 2)
            return {n: set(re.findall(r' lang="([^"]+)"', z.read(n).decode("utf-8"))) for n in parts}

    def test_lang_marks_every_slide_and_notes_run_in_pptx(self):
        self.assertEqual(validate_deck(english_deck()), [])
        langs = self.pptx_langs(english_deck())
        self.assertEqual(len(langs), 4)
        for part, found in langs.items():
            self.assertEqual(found, {"en-US"}, part)

    def test_english_static_html_has_no_chinese_wrapper(self):
        text = export_html(english_deck(), self.root / "deck.html", self.root).read_text(encoding="utf-8")
        self.assertIn('<html lang="en-US">', text)
        self.assertIn(">Skip to slides<", text)
        self.assertIn("<summary>Speaker notes</summary>", text)
        self.assertEqual(CJK.findall(text), [])

    def test_unset_or_chinese_lang_keeps_the_bilingual_wrapper(self):
        for lang, html_lang in ((None, "zh-Hant"), ("zh-TW", "zh-TW"), ("ZH-Hant", "ZH-Hant")):
            with self.subTest(lang=lang):
                deck = english_deck(lang)
                text = export_html(deck, self.root / "deck.html", self.root).read_text(encoding="utf-8")
                self.assertIn(f'<html lang="{html_lang}">', text)
                self.assertIn("Skip to slides / 跳至投影片", text)
                self.assertIn("Speaker notes / 講者備註", text)
                expected = {"zh-TW"} if lang is None else {lang}
                self.assertTrue(all(found == expected for found in self.pptx_langs(deck).values()))

    def test_player_declares_the_deck_language(self):
        for lang, html_lang in (("en-GB", "en-GB"), (None, "zh-Hant")):
            with self.subTest(lang=lang):
                text = export_html(english_deck(lang), self.root / "player.html", self.root, interactive=True).read_text(encoding="utf-8")
                self.assertIn(f'<html lang="{html_lang}">', text)

    def test_only_language_tags_are_accepted(self):
        longest = "en" + "-abcdefgh" * 3 + "-abcde"  # 35 characters: the longest tag accepted
        self.assertEqual(len(longest), 35)
        for good in ("en", "en-US", "zh-Hant-TW", "sr-Latn", "es-419", longest):
            with self.subTest(good=good):
                self.assertEqual(validate_deck(english_deck(good)), [])
        for bad in ("english", "", " en", "en_US", "e", "en-", "en--US", "en-US-" + "x" * 30, "x" * 36, longest + "f", 5, None, ["en"]):
            with self.subTest(bad=bad):
                deck = english_deck()
                deck["lang"] = bad
                codes = [d["code"] for d in validate_deck(deck)]
                self.assertEqual(codes, ["invalid_lang"])
                with self.assertRaises(ValueError):
                    export_pptx(deck, self.root / "bad.pptx", self.root)


if __name__ == "__main__":
    unittest.main()
