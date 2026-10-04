"""Validated, portable slide data and safe local raster assets (stdlib only)."""
from __future__ import annotations

import json
import math
from pathlib import Path, PurePosixPath
import re
import struct
import unicodedata
from urllib.parse import urlsplit
import zlib

SCHEMA_VERSION = 1
MAX_DOCUMENT_BYTES = 32 * 1024 * 1024
MAX_IMAGE_BYTES = 25 * 1024 * 1024
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
LANG_RE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*")
DECK_FIELDS = {"schema_version", "id", "title", "width", "height", "slides", "metadata", "lang"}
SLIDE_FIELDS = {"id", "title", "background", "notes", "elements", "transition"}
ELEMENT_FIELDS = {
    "id", "type", "x", "y", "width", "height", "fill", "stroke", "stroke_width",
    "opacity", "text", "font_family", "east_asian_font", "font_size", "bold", "align", "color", "path", "alt", "href", "step",
}
ELEMENT_TYPES = {"text", "rect", "ellipse", "line", "image"}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and -1e100 < value < 1e100 and math.isfinite(value)


def _xml_text(value):
    return all(c in "\t\n\r" or 0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD
               or 0x10000 <= ord(c) <= 0x10FFFF for c in value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON property: {key}")
        result[key] = value
    return result


def load_deck(path) -> dict:
    """Read UTF-8 JSON, reject ambiguous JSON and validate assets beside the file."""
    source = Path(path)
    if source.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError("Deck exceeds the 32 MiB document limit")
    try:
        deck = json.loads(source.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object,
                          parse_constant=lambda s: (_ for _ in ()).throw(ValueError(f"Invalid JSON number: {s}")))
    except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
        raise ValueError(f"Invalid deck JSON: {exc}") from exc
    assert_valid(deck, source.parent)
    return deck


def assert_valid(deck, base_dir=None):
    diagnostics = validate_deck(deck, base_dir)
    errors = [d for d in diagnostics if d["severity"] == "error"]
    if errors:
        raise ValueError("Invalid deck:\n" + "\n".join(f"{d['path']}: {d['message']}" for d in errors[:30]))
    return diagnostics


def resolve_image(path, base_dir=None):
    """Resolve only regular raster files contained in the deck's asset directory."""
    if not isinstance(path, str) or not path or "\\" in path or "\x00" in path:
        raise ValueError("Image path must be a nonempty relative POSIX path")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or re.match(r"^[A-Za-z]:", path):
        raise ValueError("Image path must stay within the deck directory")
    root = Path(base_dir if base_dir is not None else ".").resolve()
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("Image symlink escapes the deck directory")
    if not candidate.is_file():
        raise ValueError(f"Image file does not exist: {path}")
    if candidate.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds the 25 MiB asset limit")
    data = candidate.read_bytes()
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds the 25 MiB asset limit")
    mime, width, height = image_info(data)
    valid_suffixes = {"image/png": {".png"}, "image/jpeg": {".jpg", ".jpeg"}, "image/gif": {".gif"}}
    if candidate.suffix.lower() not in valid_suffixes[mime]:
        raise ValueError("Image extension does not match its PNG, JPEG or GIF contents")
    if width <= 0 or height <= 0 or width * height > 40_000_000:
        raise ValueError("Image dimensions must be positive and at most 40 megapixels")
    return candidate, mime, data


def image_info(data):
    """Identify supported raster formats without importing an imaging library."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        pos, dimensions, saw_data, saw_end = 8, None, False, False
        while pos + 12 <= len(data):
            length = int.from_bytes(data[pos:pos + 4], "big")
            kind = data[pos + 4:pos + 8]
            end = pos + 12 + length
            if end > len(data):
                raise ValueError("Truncated PNG chunk")
            payload = data[pos + 8:pos + 8 + length]
            crc = int.from_bytes(data[pos + 8 + length:end], "big")
            if zlib.crc32(kind + payload) & 0xFFFFFFFF != crc:
                raise ValueError("Invalid PNG checksum")
            if kind == b"IHDR":
                if dimensions is not None or pos != 8 or length != 13:
                    raise ValueError("Invalid PNG header")
                dimensions = struct.unpack(">II", payload[:8])
            elif kind == b"IDAT":
                saw_data = True
            elif kind == b"IEND":
                saw_end = length == 0 and end == len(data)
                break
            pos = end
        if not dimensions or not saw_data or not saw_end:
            raise ValueError("Incomplete PNG image")
        return "image/png", *dimensions
    if data.startswith((b"GIF87a", b"GIF89a")):
        if len(data) < 14 or data[-1:] != b";":
            raise ValueError("Incomplete GIF image")
        return "image/gif", *struct.unpack("<HH", data[6:10])
    if data.startswith(b"\xff\xd8"):
        if not data.endswith(b"\xff\xd9"):
            raise ValueError("Incomplete JPEG image")
        pos = 2
        while pos + 4 <= len(data):
            if data[pos] != 0xFF:
                break
            while pos < len(data) and data[pos] == 0xFF:
                pos += 1
            if pos >= len(data):
                break
            marker = data[pos]
            pos += 1
            if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
                continue
            if pos + 2 > len(data):
                break
            length = int.from_bytes(data[pos:pos + 2], "big")
            if length < 2 or pos + length > len(data):
                break
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                if length < 8:
                    break
                height, width = struct.unpack(">HH", data[pos + 3:pos + 7])
                return "image/jpeg", width, height
            if marker == 0xDA:
                break
            pos += length
        raise ValueError("JPEG has no valid size header")
    raise ValueError("Only PNG, JPEG and GIF raster images are supported")


def text_width(text, font_size):
    """Conservative font-independent width estimate, including CJK characters."""
    units = 0.0
    for char in text:
        if unicodedata.combining(char):
            continue
        if char == "\t":
            units += 2.4
        elif unicodedata.east_asian_width(char) in "WF":
            units += 1.0
        elif char in "MW@%&":
            units += 0.9
        elif char in "il.,:;!'| ":
            units += 0.3
        else:
            units += 0.57
    return units * font_size


def wrap_text(text, width, font_size):
    """Stable linear-time wrapping; explicit line breaks are preserved."""
    lines = []
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = []
        current_width = 0.0
        for token in re.findall(r"[^\S\n]+|[^\W\s]+|[^\w\s]", paragraph, re.UNICODE):
            token_width = text_width(token, font_size)
            if current and current_width + token_width > width:
                lines.append("".join(current).rstrip())
                current = []
                current_width = 0.0
                if token.isspace():
                    continue
            for char in token:
                char_width = text_width(char, font_size)
                if current and current_width + char_width > width:
                    lines.append("".join(current).rstrip())
                    current = []
                    current_width = 0.0
                current.append(char)
                current_width += char_width
        lines.append("".join(current).rstrip())
    return lines


def pptx_language(deck) -> str:
    """Proofing language of PPTX text runs; decks without lang keep the original zh-TW."""
    return deck.get("lang") or "zh-TW"


def html_language(deck) -> str:
    """The html lang attribute; decks without lang keep the original zh-Hant."""
    return deck.get("lang") or "zh-Hant"


def bilingual_labels(deck) -> bool:
    """HTML wrapper labels stay bilingual for Chinese or unset decks; other languages get English only."""
    lang = deck.get("lang")
    return not lang or lang.lower().startswith("zh")


def validate_deck(deck, base_dir=None) -> list[dict]:
    """Return errors and advisory layout warnings without modifying the input."""
    out = []

    def add(code, path, message, severity="error"):
        out.append({"severity": severity, "code": code, "path": path, "message": message})

    def fields(value, allowed, path):
        for key in value:
            if key not in allowed:
                add("unknown_field", f"{path}.{key}", f"Unsupported property: {key}")

    def string(value, path, nonempty=False):
        if not isinstance(value, str) or (nonempty and not value.strip()):
            add("invalid_string", path, "Expected a nonempty string" if nonempty else "Expected a string")
            return False
        if not _xml_text(value):
            add("invalid_character", path, "Contains characters forbidden in XML 1.0")
            return False
        if len(value) > 200000:
            add("text_limit", path, "Text exceeds the 200,000 character limit")
            return False
        return True

    def color(value, path, nullable=False):
        if nullable and value is None:
            return
        if not isinstance(value, str) or not COLOR_RE.fullmatch(value):
            add("invalid_color", path, "Expected a six-digit color such as #123ABC" + (" or null" if nullable else ""))

    if not isinstance(deck, dict):
        add("invalid_deck", "$", "Deck must be a JSON object")
        return out
    fields(deck, DECK_FIELDS, "$")
    if type(deck.get("schema_version")) is not int or deck.get("schema_version") != SCHEMA_VERSION:
        add("schema_version", "$.schema_version", "Only schema_version 1 is supported")
    string(deck.get("id"), "$.id", True)
    string(deck.get("title"), "$.title", True)
    for key in ("width", "height"):
        value = deck.get(key)
        if not _number(value) or not 1 <= value <= 20000:
            add("canvas_size", f"$.{key}", "Canvas size must be a finite number from 1 to 20,000")
    metadata = deck.get("metadata", {})
    if not isinstance(metadata, dict):
        add("invalid_metadata", "$.metadata", "Metadata must map string keys to string values")
    else:
        for key, value in metadata.items():
            string(key, "$.metadata key", True)
            string(value, f"$.metadata.{key}")
    if "lang" in deck:
        lang = deck["lang"]
        if not isinstance(lang, str) or len(lang) > 35 or not LANG_RE.fullmatch(lang):
            add("invalid_lang", "$.lang", "Expected a language tag such as en-US or zh-TW")
    slides = deck.get("slides")
    if not isinstance(slides, list) or not 1 <= len(slides) <= 1000:
        add("slide_count", "$.slides", "Deck needs 1 to 1,000 slides")
        return out
    slide_ids = set()
    all_slide_ids = {s.get("id") for s in slides if isinstance(s, dict) and isinstance(s.get("id"), str)}
    checked_images = {}
    for si, slide in enumerate(slides):
        sp = f"$.slides[{si}]"
        if not isinstance(slide, dict):
            add("invalid_slide", sp, "Slide must be an object")
            continue
        fields(slide, SLIDE_FIELDS, sp)
        sid = slide.get("id")
        if string(sid, sp + ".id", True):
            if sid in slide_ids:
                add("duplicate_id", sp + ".id", "Slide IDs must be unique")
            slide_ids.add(sid)
        for key in ("title", "notes"):
            if key in slide:
                string(slide[key], sp + "." + key)
        color(slide.get("background", "#FFFFFF"), sp + ".background")
        if slide.get("transition", "none") not in ("none", "fade"):
            add("slide_transition", sp + ".transition", "Transition must be none or fade")
        elements = slide.get("elements")
        if not isinstance(elements, list) or len(elements) > 2000:
            add("element_count", sp + ".elements", "Elements must be an array of at most 2,000 objects")
            continue
        ids = set()
        for ei, element in enumerate(elements):
            ep = f"{sp}.elements[{ei}]"
            if not isinstance(element, dict):
                add("invalid_element", ep, "Element must be an object")
                continue
            fields(element, ELEMENT_FIELDS, ep)
            eid = element.get("id")
            if string(eid, ep + ".id", True):
                if eid in ids:
                    add("duplicate_id", ep + ".id", "Element IDs must be unique within their slide")
                ids.add(eid)
            if "step" in element and (type(element["step"]) is not int or not 1 <= element["step"] <= 10000):
                add("element_step", ep + ".step", "Step must be an integer from 1 to 10,000")
            kind = element.get("type")
            if not isinstance(kind, str) or kind not in ELEMENT_TYPES:
                add("element_type", ep + ".type", "Supported types: text, rect, ellipse, line, image")
            geometry_ok = True
            for key in ("x", "y", "width", "height"):
                value = element.get(key)
                minimum = 0 if kind == "line" else 0.01
                if not _number(value) or abs(value) > 100000 or (key in ("width", "height") and value < minimum):
                    add("geometry", ep + "." + key, "Expected finite coordinates and positive dimensions (lines may have zero extent)")
                    geometry_ok = False
            if geometry_ok and all(_number(deck.get(k)) for k in ("width", "height")):
                if element["x"] < 0 or element["y"] < 0 or element["x"] + element["width"] > deck["width"] or element["y"] + element["height"] > deck["height"]:
                    add("out_of_bounds", ep, "Element extends outside the slide canvas", "warning")
            for key in ("fill", "stroke"):
                if key in element:
                    color(element[key], ep + "." + key, True)
            if "color" in element:
                color(element["color"], ep + ".color")
            for key, low, high, default in (("stroke_width", 0, 1000, 1), ("opacity", 0, 1, 1), ("font_size", 1, 4000, 48)):
                val = element.get(key, default)
                if not _number(val) or not low <= val <= high:
                    add("numeric_range", ep + "." + key, f"Expected a finite number from {low} to {high}")
            for key in ("text", "font_family", "east_asian_font", "alt", "path", "href"):
                if key in element:
                    valid_string = string(element[key], ep + "." + key, key in ("font_family", "east_asian_font"))
                    if valid_string and key in ("font_family", "east_asian_font"):
                        if len(element[key]) > 128 or any(c in element[key] for c in ",\r\n\t"):
                            add("font_name", ep + "." + key, "Expected one font family name, at most 128 characters; CSS fallback lists are not supported")
            if "bold" in element and not isinstance(element["bold"], bool):
                add("invalid_boolean", ep + ".bold", "Expected true or false")
            if element.get("align", "left") not in ("left", "center", "right"):
                add("text_align", ep + ".align", "Alignment must be left, center or right")
            href = element.get("href")
            if isinstance(href, str) and href:
                try:
                    uri = urlsplit(href)
                    valid_href = uri.scheme in ("http", "https") and bool(uri.hostname) or uri.scheme == "mailto" and bool(uri.path)
                    if href.startswith("#"):
                        valid_href = href[1:] in all_slide_ids
                    if not valid_href or any(c.isspace() or ord(c) < 32 for c in href):
                        add("unsafe_link", ep + ".href", "Link must be http(s), mailto, or # followed by an existing slide ID")
                except ValueError:
                    add("unsafe_link", ep + ".href", "Malformed hyperlink")
            if kind == "text":
                if "text" not in element:
                    add("missing_text", ep + ".text", "Text element requires text")
                size = element.get("font_size", 48)
                if geometry_ok and isinstance(element.get("text"), str) and _number(size) and size > 0:
                    lines = wrap_text(element["text"], element["width"], size)
                    if len(lines) * size * 1.2 > element["height"] + 0.1:
                        add("text_overflow", ep, "Estimated text height exceeds its box; enlarge the box or shorten the text", "warning")
            if kind == "image":
                asset = element.get("path")
                try:
                    if not isinstance(asset, str):
                        raise ValueError("Image element requires a relative path")
                    if asset not in checked_images:
                        try:
                            resolve_image(asset, base_dir)
                            checked_images[asset] = None
                        except (OSError, ValueError) as exc:
                            checked_images[asset] = str(exc)
                    if checked_images[asset]:
                        raise ValueError(checked_images[asset])
                except (OSError, ValueError) as exc:
                    add("invalid_image", ep + ".path", str(exc))
                if not element.get("alt"):
                    add("missing_alt", ep + ".alt", "Add alternative text for this image", "warning")
    return out
