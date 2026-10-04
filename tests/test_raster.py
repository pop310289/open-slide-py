from concurrent.futures import ThreadPoolExecutor
import struct
import unittest
import zlib

from openslide_tk.model import image_info
from openslide_tk.raster import PNGError, UnsupportedPNG, resize_png


SIGNATURE = b"\x89PNG\r\n\x1a\n"


def chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def make_png(width, height, raw, color=6, depth=8, interlace=0, palette=None, transparency=None):
    parts = [SIGNATURE, chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, interlace))]
    if palette is not None:
        parts.append(chunk(b"PLTE", bytes(palette)))
    if transparency is not None:
        parts.append(chunk(b"tRNS", bytes(transparency)))
    return b"".join(parts) + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b"")


def pixels(png):
    offset, compressed = 8, bytearray()
    while offset < len(png):
        length = struct.unpack_from(">I", png, offset)[0]
        kind, content = png[offset + 4:offset + 8], png[offset + 8:offset + 8 + length]
        if kind == b"IHDR":
            width, height, depth, color, _, _, _ = struct.unpack(">IIBBBBB", content)
            assert (depth, color) == (8, 6)
        elif kind == b"IDAT":
            compressed.extend(content)
        offset += length + 12
    raw = zlib.decompress(compressed)
    result = []
    for row in range(height):
        start = row * (width * 4 + 1)
        assert raw[start] == 0
        result.extend(tuple(raw[start + 1 + x * 4:start + 5 + x * 4]) for x in range(width))
    return width, height, result


class RasterTests(unittest.TestCase):
    def test_rgb_and_rgba_preserve_colors_and_alpha(self):
        samples = [
            (make_png(2, 1, [0, 255, 0, 12, 0, 80, 255], color=2), [(255, 0, 12, 255), (0, 80, 255, 255)]),
            (make_png(2, 1, [0, 255, 0, 12, 37, 0, 80, 255, 128]), [(255, 0, 12, 37), (0, 80, 255, 128)]),
        ]
        for source, expected in samples:
            with self.subTest(expected=expected):
                result = resize_png(source, 2, 1)
                self.assertEqual(pixels(result), (2, 1, expected))
                self.assertEqual(image_info(result), ("image/png", 2, 1))

    def test_grayscale_gray_alpha_and_transparency(self):
        gray = make_png(2, 1, [0, 80, 160], color=0, transparency=[0, 80])
        self.assertEqual(pixels(resize_png(gray, 2, 1))[2], [(80, 80, 80, 0), (160, 160, 160, 255)])
        gray_alpha = make_png(1, 1, [0, 42, 123], color=4)
        self.assertEqual(pixels(resize_png(gray_alpha, 1, 1))[2], [(42, 42, 42, 123)])
        rgb = make_png(2, 1, [0, 1, 2, 3, 4, 5, 6], color=2, transparency=[0, 1, 0, 2, 0, 3])
        self.assertEqual(pixels(resize_png(rgb, 2, 1))[2], [(1, 2, 3, 0), (4, 5, 6, 255)])

    def test_palette_partial_transparency_and_default_opaque_entries(self):
        source = make_png(3, 1, [0, 0, 1, 2], color=3, palette=[255, 0, 0, 0, 255, 0, 0, 0, 255], transparency=[0, 128])
        self.assertEqual(pixels(resize_png(source, 3, 1))[2], [(255, 0, 0, 0), (0, 255, 0, 128), (0, 0, 255, 255)])

    def test_all_five_filters_reconstruct_previous_and_neighbor_samples(self):
        first = [10, 20, 30, 40, 50, 60]
        second = [15, 35, 55, 75, 95, 115]
        encoded_rows = {
            0: second,
            1: [15, 35, 55, 60, 60, 60],
            2: [5, 15, 25, 35, 45, 55],
            3: [10, 25, 40, 48, 53, 58],
            4: [5, 15, 25, 35, 45, 55],
        }
        expected = [(10, 20, 30, 255), (40, 50, 60, 255), (15, 35, 55, 255), (75, 95, 115, 255)]
        for filter_type, encoded in encoded_rows.items():
            with self.subTest(filter=filter_type):
                source = make_png(2, 2, [0, *first, filter_type, *encoded], color=2)
                self.assertEqual(pixels(resize_png(source, 2, 2))[2], expected)

    def test_bilinear_midpoint_and_clamped_edges(self):
        source = make_png(2, 1, [0, 0, 0, 0, 255, 255, 255, 255, 255])
        self.assertEqual(pixels(resize_png(source, 3, 1))[2], [(0, 0, 0, 255), (128, 128, 128, 255), (255, 255, 255, 255)])
        self.assertEqual(pixels(resize_png(source, 1, 1))[2], [(128, 128, 128, 255)])

    def test_filter_boundaries_and_paeth_upper_left_predictor(self):
        for filter_type, encoded in {0: [10, 20], 1: [10, 10], 2: [10, 20], 3: [10, 15], 4: [10, 10]}.items():
            with self.subTest(filter=filter_type):
                source = make_png(2, 1, [filter_type, *encoded], color=0)
                self.assertEqual(pixels(resize_png(source, 2, 1))[2], [(10, 10, 10, 255), (20, 20, 20, 255)])
        source = make_png(2, 2, [4, 130, 20, 4, 226, 206], color=0)
        expected = [(value, value, value, 255) for value in [130, 150, 100, 80]]
        self.assertEqual(pixels(resize_png(source, 2, 2))[2], expected)

    def test_alpha_interpolation_does_not_bleed_invisible_color(self):
        source = make_png(2, 1, [0, 255, 0, 0, 255, 0, 0, 255, 0])
        self.assertEqual(pixels(resize_png(source, 1, 1))[2], [(255, 0, 0, 128)])
        transparent = make_png(1, 1, [0, 10, 20, 30, 0])
        self.assertEqual(pixels(resize_png(transparent, 3, 2))[2], [(0, 0, 0, 0)] * 6)

    def test_single_pixel_expands_in_both_dimensions_and_is_reproducible(self):
        source = make_png(1, 1, [0, 10, 20, 30, 255])
        result = resize_png(source, 5, 4)
        self.assertEqual(pixels(result), (5, 4, [(10, 20, 30, 255)] * 20))
        self.assertEqual(result, resize_png(source, 5, 4))

    def test_cached_sources_are_keyed_by_content_not_dimensions_or_identity(self):
        first = make_png(1, 1, [0, 200, 10, 20, 255])
        second = make_png(1, 1, [0, 20, 10, 200, 255])
        self.assertEqual(pixels(resize_png(first, 2, 1))[2], [(200, 10, 20, 255)] * 2)
        self.assertEqual(pixels(resize_png(second, 2, 1))[2], [(20, 10, 200, 255)] * 2)
        mutable = bytearray(first)
        resize_png(mutable, 3, 1)
        mutable[40] ^= 1
        with self.assertRaises(PNGError):
            resize_png(mutable, 3, 1)

    def test_concurrent_presenter_sizes_do_not_mix_image_buffers(self):
        cases = [(number, make_png(1, 1, [0, number * 13, number * 7, 255 - number, 255])) for number in range(1, 13)]

        def resize(case):
            number, source = case
            return number, pixels(resize_png(source, number + 1, 2))

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(resize, cases))
        for number, (width, height, actual) in results:
            self.assertEqual((width, height), (number + 1, 2))
            self.assertEqual(actual, [(number * 13, number * 7, 255 - number, 255)] * ((number + 1) * 2))

    def test_invalid_dimensions_and_resource_limits_rejected(self):
        source = make_png(1, 1, [0, 0, 0, 0, 255])
        for dimensions in [(0, 1), (-1, 1), (1.5, 1), (True, 1), (8193, 1), (3000, 3000)]:
            with self.subTest(dimensions=dimensions), self.assertRaises(PNGError):
                resize_png(source, *dimensions)
        oversized = make_png(5000, 5000, [])
        with self.assertRaises(PNGError):
            resize_png(oversized, 1, 1)

    def test_corrupt_truncated_overexpanded_and_unknown_filter_rejected(self):
        good = make_png(1, 1, [0, 10, 20, 30, 255])
        invalid = [b"not png", good[:-1], good + b"trailing", good[:40] + bytes([good[40] ^ 1]) + good[41:], make_png(1, 1, [0, 1]), make_png(1, 1, [0] * 1000), make_png(1, 1, [5, 1, 2, 3, 4])]
        for index, source in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(PNGError):
                resize_png(source, 1, 1)

    def test_palette_errors_and_unsupported_variants_are_explicit(self):
        invalid = [make_png(1, 1, [0, 1], color=3, palette=[1, 2, 3]), make_png(1, 1, [0, 0], color=3), make_png(1, 1, [0, 0, 0, 0, 0], transparency=[1])]
        for source in invalid:
            with self.assertRaises(PNGError):
                resize_png(source, 1, 1)
        for source in [make_png(1, 1, [], depth=16), make_png(1, 1, [], interlace=1)]:
            with self.assertRaises(UnsupportedPNG):
                resize_png(source, 1, 1)


if __name__ == "__main__":
    unittest.main()
