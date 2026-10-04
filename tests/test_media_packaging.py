"""Native media keeps source bytes without a dependency on a case's artwork."""
from pathlib import Path
import tempfile
import unittest
import zipfile

from openslide_tk.pptx import export_pptx
try:
    from .test_model import png_bytes, sample_deck
except ImportError:
    from test_model import png_bytes, sample_deck


class MediaPackagingTests(unittest.TestCase):
    def test_png_media_is_preserved_without_loss_or_recompression(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = png_bytes()
            (root / "pixel.png").write_bytes(source)
            deck = sample_deck()
            for index in range(2):
                deck["slides"][0]["elements"].append({
                    "id": f"image-{index}", "type": "image", "x": 100 + index * 150,
                    "y": 650, "width": 100, "height": 100, "path": "pixel.png", "alt": "Test pixel",
                })
            output = export_pptx(deck, root / "deck.pptx", root)
            with zipfile.ZipFile(output) as archive:
                media = [item for item in archive.infolist() if item.filename.startswith("ppt/media/")]
                self.assertEqual(len(media), 1, "Repeated assets are deduplicated")
                self.assertEqual(archive.read(media[0]), source)
                self.assertEqual(media[0].compress_type, zipfile.ZIP_STORED)
                self.assertEqual(archive.getinfo("ppt/slides/slide1.xml").compress_type, zipfile.ZIP_DEFLATED)


if __name__ == "__main__":
    unittest.main()
