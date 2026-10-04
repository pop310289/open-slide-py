"""JPEG and GIF headers are read without an imaging library; incomplete or unsized files are rejected."""
import struct
import unittest

from openslide_tk.model import image_info


def segment(marker, payload):
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def sof(marker=0xC0, width=3, height=2):
    return segment(marker, bytes([8]) + struct.pack(">HH", height, width) + bytes([3]) + bytes(9))


APP0 = segment(0xE0, b"JFIF\x00" + bytes(9))
DHT = segment(0xC4, bytes(20))  # 0xC4 is a Huffman table, not a frame header
SOS = segment(0xDA, bytes(10))
SOI, EOI = b"\xff\xd8", b"\xff\xd9"


class JpegTests(unittest.TestCase):
    def test_baseline_and_progressive_frames_give_width_and_height(self):
        self.assertEqual(image_info(SOI + APP0 + sof(0xC0, 640, 480) + SOS + b"\x00\x01" + EOI), ("image/jpeg", 640, 480))
        self.assertEqual(image_info(SOI + APP0 + sof(0xC2, 7, 9) + SOS + EOI), ("image/jpeg", 7, 9))

    def test_tables_fill_bytes_and_standalone_markers_are_skipped(self):
        data = SOI + DHT + b"\xff\xff" + b"\xff\xd0" + APP0 + sof(0xC1, 12, 34) + EOI
        self.assertEqual(image_info(data), ("image/jpeg", 12, 34))

    def test_unsized_or_incomplete_jpegs_are_rejected(self):
        cases = {
            "no end marker": (SOI + APP0 + sof() + SOS, "Incomplete JPEG image"),
            "scan before any frame header": (SOI + APP0 + SOS + EOI, "no valid size header"),
            "frame header after the scan starts": (SOI + SOS + sof(0xC0, 5, 5) + EOI, "no valid size header"),
            "segment longer than the file": (SOI + b"\xff\xe0\x7f\xff" + EOI, "no valid size header"),
            "frame header too short": (SOI + segment(0xC0, bytes(4)) + EOI, "no valid size header"),
            "garbage after SOI": (SOI + b"\x00\x00\x00\x00" + EOI, "no valid size header"),
        }
        for name, (data, message) in cases.items():
            with self.subTest(name):
                with self.assertRaisesRegex(ValueError, message):
                    image_info(data)


class GifTests(unittest.TestCase):
    def test_logical_screen_size_is_read(self):
        for signature in (b"GIF87a", b"GIF89a"):
            with self.subTest(signature=signature):
                data = signature + struct.pack("<HH", 300, 200) + bytes(3) + b"\x2c" + bytes(9) + b";"
                self.assertEqual(image_info(data), ("image/gif", 300, 200))

    def test_truncated_gif_is_rejected(self):
        for data in (b"GIF89a" + struct.pack("<HH", 1, 1), b"GIF89a" + struct.pack("<HH", 1, 1) + bytes(10),
                     b"GIF89a" + struct.pack("<HH", 1, 1) + bytes(2) + b";"):  # 13 bytes: one short of a header
            with self.subTest(length=len(data)):
                with self.assertRaisesRegex(ValueError, "Incomplete GIF image"):
                    image_info(data)


class UnknownFormatTests(unittest.TestCase):
    def test_other_bytes_are_rejected(self):
        for data in (b"", b"BM" + bytes(40), b"<svg/>"):
            with self.subTest(data=data[:4]):
                with self.assertRaisesRegex(ValueError, "Only PNG, JPEG and GIF"):
                    image_info(data)


if __name__ == "__main__":
    unittest.main()
