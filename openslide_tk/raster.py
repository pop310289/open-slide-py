"""Bounded PNG decoding and smooth resizing using the Python standard library.

Supports noninterlaced 8-bit PNG samples. Interpolation uses premultiplied alpha
in the encoded color space; it does not perform ICC or gamma conversion.
"""

from collections import OrderedDict
import hashlib
import math
import struct
import threading
import zlib


SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_ENCODED_BYTES = 32 * 1024 * 1024
MAX_INPUT_PIXELS = 16_000_000
MAX_OUTPUT_PIXELS = 4_000_000
MAX_DIMENSION = 8192
MAX_CHUNKS = 4096
MAX_DECODED_CACHE_BYTES = 32 * 1024 * 1024
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
_decoded_cache = OrderedDict()
_cache_bytes = 0
_cache_lock = threading.Lock()


class PNGError(ValueError):
    """Malformed PNG data or an exceeded resource limit."""


class UnsupportedPNG(PNGError):
    """A recognized PNG variant requiring the viewer's fallback decoder."""


def _dimensions(width, height, limit):
    if type(width) is not int or type(height) is not int:
        raise PNGError("PNG dimensions must be integers")
    if not 1 <= width <= MAX_DIMENSION or not 1 <= height <= MAX_DIMENSION:
        raise PNGError(f"PNG dimensions must be between 1 and {MAX_DIMENSION}")
    if width * height > limit:
        raise PNGError(f"PNG exceeds the {limit:,} pixel limit")


def _paeth(left, above, upper_left):
    prediction = left + above - upper_left
    a, b, c = abs(prediction - left), abs(prediction - above), abs(prediction - upper_left)
    return left if a <= b and a <= c else above if b <= c else upper_left


def _decode_png(data):
    if not isinstance(data, (bytes, bytearray)) or not data.startswith(SIGNATURE):
        raise PNGError("Expected PNG bytes")
    if len(data) > MAX_ENCODED_BYTES:
        raise PNGError("PNG exceeds the 32 MiB encoded-data limit")
    offset, count = 8, 0
    header = palette = transparency = None
    compressed = bytearray()
    saw_idat = after_idat = saw_end = False
    while offset < len(data):
        count += 1
        if count > MAX_CHUNKS:
            raise PNGError("PNG contains too many chunks")
        if offset + 12 > len(data):
            raise PNGError("Truncated PNG chunk")
        length = struct.unpack_from(">I", data, offset)[0]
        end = offset + length + 12
        if end > len(data):
            raise PNGError("Truncated PNG chunk payload")
        kind = bytes(data[offset + 4:offset + 8])
        payload = data[offset + 8:offset + 8 + length]
        crc = struct.unpack_from(">I", data, offset + 8 + length)[0]
        if zlib.crc32(payload, zlib.crc32(kind)) & 0xFFFFFFFF != crc:
            raise PNGError("Invalid PNG checksum")
        if not all(65 <= char <= 90 or 97 <= char <= 122 for char in kind) or kind[2] & 32:
            raise PNGError("Invalid PNG chunk name")
        if header is None and kind != b"IHDR":
            raise PNGError("PNG must begin with IHDR")
        if saw_idat and kind != b"IDAT":
            after_idat = True
        if kind == b"IHDR":
            if header is not None or length != 13:
                raise PNGError("Invalid or duplicate PNG header")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            _dimensions(width, height, MAX_INPUT_PIXELS)
            if color not in CHANNELS or depth != 8 or interlace != 0:
                raise UnsupportedPNG("Smooth resizing supports only noninterlaced 8-bit PNG images")
            if compression != 0 or filtering != 0:
                raise UnsupportedPNG("Unsupported PNG compression or filtering method")
            header = (width, height, color)
        elif kind == b"PLTE":
            if palette is not None or saw_idat or transparency is not None or not length or length % 3 or length > 768 or header[2] in (0, 4):
                raise PNGError("Invalid PNG palette")
            palette = bytes(payload)
        elif kind == b"tRNS":
            color = header[2]
            if transparency is not None or saw_idat:
                raise PNGError("Invalid PNG transparency ordering")
            valid = (color == 0 and length == 2) or (color == 2 and length == 6) or (color == 3 and palette is not None and 0 < length <= len(palette) // 3)
            if not valid:
                raise PNGError("Invalid PNG transparency")
            transparency = bytes(payload)
        elif kind == b"IDAT":
            if after_idat or (header[2] == 3 and palette is None):
                raise PNGError("Invalid PNG image-data ordering")
            compressed.extend(payload)
            saw_idat = True
        elif kind == b"IEND":
            if length or not saw_idat or end != len(data):
                raise PNGError("Invalid PNG ending")
            saw_end = True
            break
        elif kind in (b"acTL", b"fcTL", b"fdAT"):
            raise UnsupportedPNG("Animated PNG requires the viewer's fallback decoder")
        elif not kind[0] & 32:
            raise UnsupportedPNG("Unknown critical PNG chunk: " + kind.decode("ascii"))
        offset = end
    if header is None or not saw_end:
        raise PNGError("Incomplete PNG image")
    width, height, color = header
    channels = CHANNELS[color]
    stride = width * channels
    expected = (stride + 1) * height
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(compressed, expected + 1)
    except zlib.error as exc:
        raise PNGError("Invalid PNG compressed data") from exc
    if len(raw) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise PNGError("PNG decompressed data does not match its dimensions")

    samples = bytearray(stride * height)
    for row_number in range(height):
        start = row_number * (stride + 1)
        filter_type = raw[start]
        if filter_type > 4:
            raise PNGError("Unknown PNG row filter")
        row = bytearray(raw[start + 1:start + stride + 1])
        previous = samples[(row_number - 1) * stride:row_number * stride] if row_number else bytes(stride)
        if filter_type == 1:
            for index in range(channels, stride):
                row[index] = (row[index] + row[index - channels]) & 255
        elif filter_type == 2:
            for index in range(stride):
                row[index] = (row[index] + previous[index]) & 255
        elif filter_type == 3:
            for index in range(stride):
                left = row[index - channels] if index >= channels else 0
                row[index] = (row[index] + (left + previous[index]) // 2) & 255
        elif filter_type == 4:
            for index in range(stride):
                left = row[index - channels] if index >= channels else 0
                upper_left = previous[index - channels] if index >= channels else 0
                row[index] = (row[index] + _paeth(left, previous[index], upper_left)) & 255
        samples[row_number * stride:(row_number + 1) * stride] = row

    if color == 6:
        return width, height, samples
    rgba = bytearray(width * height * 4)
    if color in (0, 2, 4):
        if color == 2:
            rgba[0::4], rgba[1::4], rgba[2::4] = samples[0::3], samples[1::3], samples[2::3]
        else:
            gray = samples[0::channels]
            rgba[0::4], rgba[1::4], rgba[2::4] = gray, gray, gray
        rgba[3::4] = samples[1::2] if color == 4 else b"\xff" * (width * height)
        if transparency is None:
            return width, height, rgba
    transparent_gray = struct.unpack(">H", transparency)[0] if transparency and color == 0 else None
    transparent_rgb = struct.unpack(">HHH", transparency) if transparency and color == 2 else None
    for number in range(width * height):
        source, target = number * channels, number * 4
        if color == 0:
            if samples[source] == transparent_gray:
                rgba[target + 3] = 0
        elif color == 2:
            rgb = tuple(samples[source:source + 3])
            if rgb == transparent_rgb:
                rgba[target + 3] = 0
        elif color == 3:
            entry = samples[source]
            if entry * 3 + 3 > len(palette):
                raise PNGError("PNG palette index is out of range")
            rgba[target:target + 3] = palette[entry * 3:entry * 3 + 3]
            rgba[target + 3] = transparency[entry] if transparency and entry < len(transparency) else 255
    return width, height, rgba


def _chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(payload, zlib.crc32(kind)) & 0xFFFFFFFF)


def _decoded_source(data):
    global _cache_bytes
    if not isinstance(data, (bytes, bytearray)):
        raise PNGError("Expected PNG bytes")
    if len(data) > MAX_ENCODED_BYTES:
        raise PNGError("PNG exceeds the 32 MiB encoded-data limit")
    data = bytes(data)
    digest = hashlib.sha256(data).digest()
    with _cache_lock:
        if digest in _decoded_cache:
            _decoded_cache.move_to_end(digest)
            return _decoded_cache[digest]
    width, height, rgba = _decode_png(data)
    if len(rgba) <= MAX_DECODED_CACHE_BYTES:
        record = (width, height, bytes(rgba))
        with _cache_lock:
            previous = _decoded_cache.pop(digest, None)
            if previous is not None:
                _cache_bytes -= len(previous[2])
            while _decoded_cache and (_cache_bytes + len(rgba) > MAX_DECODED_CACHE_BYTES or len(_decoded_cache) >= 8):
                _, removed = _decoded_cache.popitem(last=False)
                _cache_bytes -= len(removed[2])
            _decoded_cache[digest] = record
            _cache_bytes += len(rgba)
        return record
    return width, height, rgba


def _encode_png(width, height, rgba):
    stride = width * 4
    rows = b"".join(b"\0" + rgba[start:start + stride] for start in range(0, len(rgba), stride))
    return SIGNATURE + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) + _chunk(b"IDAT", zlib.compress(rows, 6)) + _chunk(b"IEND", b"")


def _coordinates(source, target):
    output = []
    for index in range(target):
        position = max(0.0, min(source - 1.0, (index + 0.5) * source / target - 0.5))
        before = math.floor(position)
        output.append((before, min(before + 1, source - 1), position - before))
    return output


def resize_png(data, width, height):
    """Return a deterministic RGBA PNG resized with bilinear alpha-safe sampling.

    Raises PNGError for malformed data/resource limits and UnsupportedPNG for
    unsupported variants. Both inherit ValueError so callers can fall back.
    Source is limited to 16M pixels/32 MiB; target to 4M pixels and 8192 per axis.
    A thread-safe content-addressed cache retains at most 8 decoded sources and
    32 MiB of immutable pixel buffers across main/presenter window sizes.
    """
    _dimensions(width, height, MAX_OUTPUT_PIXELS)
    source_width, source_height, source = _decoded_source(data)
    if (width, height) == (source_width, source_height):
        return _encode_png(width, height, source)
    xs, ys = _coordinates(source_width, width), _coordinates(source_height, height)
    output = bytearray(width * height * 4)
    opaque = source[3::4].count(255) == source_width * source_height
    target = 0
    for y0, y1, fy in ys:
        row0, row1 = y0 * source_width * 4, y1 * source_width * 4
        for x0, x1, fx in xs:
            p0, p1, p2, p3 = row0 + x0 * 4, row0 + x1 * 4, row1 + x0 * 4, row1 + x1 * 4
            a0, a1, a2, a3 = (1 - fx) * (1 - fy), fx * (1 - fy), (1 - fx) * fy, fx * fy
            if opaque:
                for channel in range(3):
                    output[target + channel] = min(255, int(source[p0 + channel] * a0 + source[p1 + channel] * a1 + source[p2 + channel] * a2 + source[p3 + channel] * a3 + .5))
                output[target + 3] = 255
                target += 4
                continue
            a0, a1, a2, a3 = a0 * source[p0 + 3], a1 * source[p1 + 3], a2 * source[p2 + 3], a3 * source[p3 + 3]
            alpha = a0 + a1 + a2 + a3
            if alpha > 0:
                for channel in range(3):
                    output[target + channel] = min(255, int((source[p0 + channel] * a0 + source[p1 + channel] * a1 + source[p2 + channel] * a2 + source[p3 + channel] * a3) / alpha + .5))
                output[target + 3] = min(255, int(alpha + .5))
            target += 4
    return _encode_png(width, height, output)
