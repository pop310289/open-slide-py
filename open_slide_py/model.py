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

from .fonts import DEFAULT_LATIN
from .metrics import advance_widths

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
    "radius", "fill_opacity", "stroke_opacity", "gradient", "shadow", "glow", "highlights", "ignore_warnings",
}
# Advisory layout warnings; an element can list the ones it shows on purpose in ignore_warnings.
WARNING_CODES = ("text_overflow", "text_overlap", "low_contrast", "small_text", "repeated_text")
MIN_CONTRAST, MIN_CONTRAST_LARGE = 4.5, 3.0  # WCAG AA; large text is 18 pt, or 14 pt bold
SMALL_TEXT_AT_1920 = 36  # 18 pt on the default 1920 px (13.33 in) canvas, a common floor for sentences on a projected slide
SENTENCE_WORDS = 5  # shorter text, and text in capitals, counts as a label
WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)?")
CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\uf900-\ufaff]")
DEFAULT_TEXT_COLOR = "#172F39"
# Optional styles: which element types accept them, and the fields allowed inside the style objects.
STYLE_TYPES = {"radius": {"rect", "text"}, "gradient": {"rect", "ellipse", "text"}, "shadow": {"rect", "ellipse", "image"},
               "glow": {"rect", "ellipse", "image"}, "highlights": {"text"}}
SHADOW_FIELDS = {"color": "#000000", "opacity": 0.35, "blur": 24, "distance": 8, "angle": 90}
GLOW_FIELDS = {"color": None, "opacity": 0.4, "radius": 16}
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


def _reject_constant(name):
    raise ValueError(f"Invalid JSON number: {name}")


def read_deck(path):
    """Read UTF-8 JSON and reject ambiguous JSON (duplicate keys, NaN, Infinity) without validating the scene."""
    source = Path(path)
    if source.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError("Deck exceeds the 32 MiB document limit")
    try:
        return json.loads(source.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError(f"Invalid deck JSON: {exc}") from exc


def load_deck(path) -> dict:
    """Read a deck and validate it, including the assets beside the file."""
    deck = read_deck(path)
    assert_valid(deck, Path(path).parent)
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


# Tabled advance widths are exact for the font file; 2% covers rounding and substitute fonts with nearly equal widths.
TABLE_MARGIN = 1.02


def text_width(text, font_size, font_family=None, bold=False):
    """Width in pixels: the font's advance widths when it is tabled, else a conservative font-independent estimate."""
    table = advance_widths(font_family, bold)
    units = 0.0
    for char in text:
        if unicodedata.combining(char):
            continue
        if table is not None and char in table:
            units += table[char] / 1000 * TABLE_MARGIN
        elif char == "\t":
            units += 2.4
        elif unicodedata.east_asian_width(char) in "WF":
            units += 1.0
        elif char in "MW@%&":
            units += 0.9
        elif char in "il.,:;!'| \u00a0\u202f":
            units += 0.3
        else:
            units += 0.57
    return units * font_size


# Closing punctuation must not begin a line; the word (or CJK character) before it moves down with it.
NO_LINE_START = frozenset(".,;:!?%)]}»…’”、。，．；：！？％）］｝」』〕〉》】〗〙〛")
# No-break, figure and narrow no-break spaces are never a line break: "24 pt" or "Fig. 3" stays on one line.
NO_BREAK_SPACES = "\u00a0\u2007\u202f"
TOKEN_RE = re.compile(rf"[^\S\n{NO_BREAK_SPACES}]+|[{NO_BREAK_SPACES}]+|[^\W\s]+|[^\w\s]")


def breaks(char):
    return char.isspace() and char not in NO_BREAK_SPACES


def wrap_tokens(paragraph):
    """Whitespace runs, word runs and single symbols; a no-break space glues the tokens on both sides into one."""
    tokens = []
    for token in TOKEN_RE.findall(paragraph):
        if tokens and (token[0] in NO_BREAK_SPACES or tokens[-1][-1] in NO_BREAK_SPACES) \
                and not breaks(token[0]) and not breaks(tokens[-1][-1]):
            tokens[-1] += token
        else:
            tokens.append(token)
    return tokens


def wrap_text(text, width, font_size, font_family=None, bold=False):
    """Stable linear-time wrapping; explicit line breaks are preserved and closing punctuation never starts a line."""
    lines = []
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        first_line = len(lines)
        if not paragraph:
            lines.append("")
            continue
        current = []
        current_width = 0.0
        for token in wrap_tokens(paragraph):
            token_width = text_width(token, font_size, font_family, bold)
            if current and current_width + token_width > width:
                carry = []
                if token[0] in NO_LINE_START and not breaks(current[-1]):
                    start = len(current)
                    while start > 0 and not breaks(current[start - 1]):
                        start -= 1
                    if start == 0:  # one word or CJK run: move its last character, with any closing punctuation after it
                        start = len(current) - 1
                        while start > 0 and current[start] in NO_LINE_START:
                            start -= 1
                    carry = current[start:]
                    if not "".join(current[:start]).strip():
                        carry = []  # nothing would be left on this line: keep the old break
                    current = current[:len(current) - len(carry)]
                lines.append("".join(current).rstrip())
                current = carry
                current_width = text_width("".join(carry), font_size, font_family, bold)
                if breaks(token[0]):
                    continue
            for char in token:
                char_width = text_width(char, font_size, font_family, bold)
                if current and current_width + char_width > width:
                    lines.append("".join(current).rstrip())
                    current = []
                    current_width = 0.0
                current.append(char)
                current_width += char_width
        lines.append("".join(current).rstrip())
        _rebalance_last_line(lines, paragraph, first_line, width, font_size, font_family, bold)
    return lines


def _rebalance_last_line(lines, paragraph, first_line, width, font_size, font_family, bold):
    """A lone word on a paragraph's last line takes the last word of the line above, if it fits and two words stay above."""
    if len(lines) - first_line < 2 or any(breaks(c) for c in lines[-1]):
        return
    above = lines[-2]
    cut = max((i for i, c in enumerate(above) if breaks(c)), default=-1)
    if cut <= 0 or not any(breaks(c) for c in above[:cut].rstrip()):
        return
    source = paragraph.rstrip()
    # Lines are slices of the paragraph with only break whitespace dropped, so the moved word and the lone word, with
    # the original whitespace between them, are the end of the paragraph.
    moved = source[len(source) - len(lines[-1]) - (len(above) - cut - 1) - _gap(source, len(source) - len(lines[-1])):]
    if not moved.startswith(above[cut + 1:]) or text_width(moved, font_size, font_family, bold) > width:
        return
    lines[-2:] = [above[:cut].rstrip(), moved]


def _gap(text, end):
    """Length of the break whitespace that ends just before index end."""
    i = end
    while i > 0 and breaks(text[i - 1]):
        i -= 1
    return end - i


def _text_styles(element):
    """The element's normalised text, its base (colour, bold) and one style per character with highlights applied.

    Every highlight marks all occurrences of its text; a later highlight wins where two overlap.
    """
    text = element["text"].replace("\r\n", "\n").replace("\r", "\n")
    base = (element.get("color", DEFAULT_TEXT_COLOR), element.get("bold", False))
    styles = [base] * len(text)
    for mark in element.get("highlights", []):
        style = (mark.get("color", base[0]), mark.get("bold", base[1]))
        start = text.find(mark["text"])
        while start != -1:
            styles[start:start + len(mark["text"])] = [style] * len(mark["text"])
            start = text.find(mark["text"], start + len(mark["text"]))
    return text, base, styles


def _runs(part, styles, start, base):
    runs = []
    for offset, char in enumerate(part):
        style = styles[start + offset]
        if runs and runs[-1][1:] == style:
            runs[-1] = (runs[-1][0] + char, *style)
        else:
            runs.append((char, *style))
    return runs or [("", *base)]


def styled_lines(element):
    """wrap_text lines of a text element, each as [(text, color, bold)] runs with its highlights applied."""
    text, base, styles = _text_styles(element)
    out, pos = [], 0
    for line in wrap_text(text, element["width"], element.get("font_size", 48), element.get("font_family", DEFAULT_LATIN), element.get("bold", False)):
        if not line:
            out.append([("", *base)])
            continue
        # wrap_text only drops whitespace between lines, so each line is the next slice after skipping it.
        while pos < len(text) and not text.startswith(line, pos) and text[pos].isspace():
            pos += 1
        if not text.startswith(line, pos):
            raise ValueError("Internal error: wrapped line does not match the source text")
        out.append(_runs(line, styles, pos, base))
        pos += len(line)
    return out


def styled_paragraphs(element):
    """The text's own paragraphs (split at explicit line breaks, not wrapped) as runs, for renderers that wrap text themselves.

    When a paragraph wraps and its last wrapped line holds two words or more, those last two words are joined by a
    no-break space, so a renderer that wraps greedily (PowerPoint) cannot leave the last word alone on a line either.
    """
    text, base, styles = _text_styles(element)
    size, font, bold = element.get("font_size", 48), element.get("font_family", DEFAULT_LATIN), element.get("bold", False)
    out, pos = [], 0
    for paragraph in text.split("\n"):
        lines = wrap_text(paragraph, element["width"], size, font, bold)
        cut = paragraph.rstrip(" ").rfind(" ")
        if len(lines) > 1 and len(lines[-1].strip(" ").split(" ")) > 1 and cut > 0:
            paragraph = paragraph[:cut] + "\u00a0" + paragraph[cut + 1:]
        out.append(_runs(paragraph, styles, pos, base))
        pos += len(paragraph) + 1
    return out


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

    def number(value, path, low, high):
        if not _number(value) or not low <= value <= high:
            add("numeric_range", path, f"Expected a finite number from {low} to {high}")

    def gradient(value, path):
        if not isinstance(value, dict) or set(value) - {"angle", "stops"}:
            add("invalid_gradient", path, "Gradient must be an object with angle and stops")
            return
        number(value.get("angle", 90), path + ".angle", 0, 360)
        stops = value.get("stops")
        if not isinstance(stops, list) or not 2 <= len(stops) <= 8:
            add("invalid_gradient", path + ".stops", "Gradient needs 2 to 8 stops")
            return
        previous = 0
        for i, stop in enumerate(stops):
            sp = f"{path}.stops[{i}]"
            if not isinstance(stop, dict) or set(stop) - {"color", "opacity", "at"} or "color" not in stop or "at" not in stop:
                add("invalid_gradient", sp, "Each stop needs color and at, and may have opacity")
                continue
            color(stop["color"], sp + ".color")
            number(stop.get("opacity", 1), sp + ".opacity", 0, 1)
            number(stop["at"], sp + ".at", 0, 1)
            if _number(stop["at"]):
                if stop["at"] < previous:
                    add("invalid_gradient", sp + ".at", "Stop positions must not decrease")
                previous = stop["at"]

    def effect(value, path, allowed):
        if not isinstance(value, dict) or set(value) - set(allowed):
            add("invalid_effect", path, "Allowed fields: " + ", ".join(allowed))
            return
        if allowed["color"] is None and "color" not in value:
            add("invalid_effect", path + ".color", "This effect needs a color")
        if "color" in value:
            color(value["color"], path + ".color")
        number(value.get("opacity", 0), path + ".opacity", 0, 1)
        for key in ("blur", "distance", "radius"):
            if key in allowed:
                number(value.get(key, 0), f"{path}.{key}", 0, 500)
        if "angle" in allowed:
            number(value.get("angle", 0), path + ".angle", 0, 360)

    def highlights(value, text, path):
        if not isinstance(value, list) or len(value) > 50:
            add("invalid_highlight", path, "Highlights must be a list of at most 50 objects")
            return
        for i, mark in enumerate(value):
            hp = f"{path}[{i}]"
            if not isinstance(mark, dict) or set(mark) - {"text", "color", "bold"} or not ({"color", "bold"} & set(mark)):
                add("invalid_highlight", hp, "Each highlight needs text and a color or bold")
                continue
            if string(mark.get("text"), hp + ".text", True) and isinstance(text, str) and mark["text"] not in text.replace("\r\n", "\n").replace("\r", "\n"):
                add("invalid_highlight", hp + ".text", "Highlighted text must appear in the element text")
            if "color" in mark:
                color(mark["color"], hp + ".color")
            if "bold" in mark and not isinstance(mark["bold"], bool):
                add("invalid_boolean", hp + ".bold", "Expected true or false")

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
            if "ignore_warnings" in element:
                ignore = element["ignore_warnings"]
                if not isinstance(ignore, list) or any(not isinstance(code, str) or code not in WARNING_CODES for code in ignore):
                    add("invalid_ignore", ep + ".ignore_warnings", "ignore_warnings lists warning codes: " + ", ".join(WARNING_CODES))
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
            for key, low, high, default in (("stroke_width", 0, 1000, 1), ("opacity", 0, 1, 1), ("font_size", 1, 4000, 48),
                                            ("fill_opacity", 0, 1, 1), ("stroke_opacity", 0, 1, 1), ("radius", 0, 100000, 0)):
                val = element.get(key, default)
                if not _number(val) or not low <= val <= high:
                    add("numeric_range", ep + "." + key, f"Expected a finite number from {low} to {high}")
            for key in ("text", "font_family", "east_asian_font", "alt", "path", "href"):
                if key in element:
                    valid_string = string(element[key], ep + "." + key, key in ("font_family", "east_asian_font"))
                    if valid_string and key in ("font_family", "east_asian_font"):
                        if len(element[key]) > 128 or any(c in element[key] for c in ",\r\n\t"):
                            add("font_name", ep + "." + key, "Expected one font family name, at most 128 characters; CSS fallback lists are not supported")
            for key, kinds in STYLE_TYPES.items():
                if key in element and kind not in kinds:
                    add("unsupported_style", ep + "." + key, f"{key} applies only to {', '.join(sorted(kinds))} elements")
            if "gradient" in element:
                gradient(element["gradient"], ep + ".gradient")
            if "shadow" in element:
                effect(element["shadow"], ep + ".shadow", SHADOW_FIELDS)
            if "glow" in element:
                effect(element["glow"], ep + ".glow", GLOW_FIELDS)
            if "highlights" in element and kind == "text":
                highlights(element["highlights"], element.get("text"), ep + ".highlights")
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
                    lines = wrap_text(element["text"], element["width"], size, element.get("font_family", DEFAULT_LATIN), element.get("bold", False) is True)
                    if len(lines) * size * 1.2 > element["height"] + 0.1 and not _ignored(element, "text_overflow"):
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
    if not any(d["severity"] == "error" for d in out):
        out.extend(layout_warnings(deck))
    return out


def _ignored(element, code):
    ignore = element.get("ignore_warnings")
    return isinstance(ignore, list) and code in ignore


def _words(text):
    """Latin words, plus CJK characters counted two to a word."""
    return len(WORD_RE.findall(CJK_RE.sub(" ", text))) + len(CJK_RE.findall(text)) / 2


def _sentence(text):
    """At least five words and not set in capitals (capitals mark a label or kicker, which may be small and recur)."""
    capitals = any(c.isupper() for c in text) and not any(c.islower() for c in text)  # scripts without case never count as capitals
    return _words(text) >= SENTENCE_WORDS and not capitals


def _luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b):
    """WCAG contrast ratio of two #RRGGBB colours."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _blend(base, top, opacity):
    return "#" + "".join(f"{round(int(base[i:i + 2], 16) * (1 - opacity) + int(top[i:i + 2], 16) * opacity):02X}" for i in (1, 3, 5))


def text_extent(element):
    """(x0, y0, x1, y1) that the wrapped text of a text element covers, by its alignment."""
    size = element.get("font_size", 48)
    font, bold = element.get("font_family", DEFAULT_LATIN), element.get("bold", False) is True
    lines = wrap_text(element["text"], element["width"], size, font, bold)
    used = max((text_width(line, size, font, bold) for line in lines), default=0.0)
    slack = max(element["width"] - used, 0.0)
    x0 = element["x"] + {"center": slack / 2, "right": slack}.get(element.get("align", "left"), 0.0)
    return x0, element["y"], x0 + used, element["y"] + len(lines) * size * 1.2


def _backdrops(slide, index, x, y):
    """Colours that can lie behind point (x, y), from the background up; None when an image is under it."""
    colours = [slide.get("background", "#FFFFFF")]
    for element in slide["elements"][:index]:
        kind = element.get("type")
        ex, ey, ew, eh = element.get("x", 0), element.get("y", 0), element.get("width", 0), element.get("height", 0)
        if kind == "ellipse":
            if ew <= 0 or eh <= 0 or ((x - ex - ew / 2) / (ew / 2)) ** 2 + ((y - ey - eh / 2) / (eh / 2)) ** 2 > 1:
                continue
        elif kind in ("rect", "image"):
            if not (ex <= x <= ex + ew and ey <= y <= ey + eh):
                continue
        else:
            continue
        if kind == "image":
            return None
        alpha = element.get("opacity", 1)
        if element.get("gradient"):
            layers = [(stop["color"], stop.get("opacity", 1) * alpha) for stop in element["gradient"]["stops"]]
        elif element.get("fill"):
            layers = [(element["fill"], element.get("fill_opacity", 1) * alpha)]
        else:
            continue
        colours = list(dict.fromkeys(_blend(c, top, a) for c in colours for top, a in layers))[:32]
    return colours


def layout_warnings(deck):
    """Overlapping text, low contrast, small sentences and sentences repeated across slides (well-formed decks only)."""
    out, seen = [], {}
    scale = deck["width"] / 1920
    small = SMALL_TEXT_AT_1920 * scale

    def add(code, path, message):
        out.append({"severity": "warning", "code": code, "path": path, "message": message})

    for si, slide in enumerate(deck["slides"]):
        placed = []
        for ei, element in enumerate(slide["elements"]):
            if element.get("type") != "text" or not element.get("text", "").strip():
                continue
            ep = f"$.slides[{si}].elements[{ei}]"
            extent = text_extent(element)
            if not _ignored(element, "text_overlap"):
                for other, (ox0, oy0, ox1, oy1) in placed:
                    if min(extent[2], ox1) - max(extent[0], ox0) > 2 and min(extent[3], oy1) - max(extent[1], oy0) > 2:
                        add("text_overlap", ep, f"Text overlaps text element '{other}'; move or shorten one of them")
                        break
            placed.append((element.get("id"), extent))
            size = element.get("font_size", 48)
            if not _ignored(element, "low_contrast"):
                backs = _backdrops(slide, ei, (extent[0] + extent[2]) / 2, extent[1] + min(extent[3] - extent[1], size * 1.2) / 2)
                if backs is not None:
                    colours = {element.get("color", DEFAULT_TEXT_COLOR)} | {h["color"] for h in element.get("highlights", []) if "color" in h}
                    alpha = element.get("opacity", 1)
                    worst = min(contrast_ratio(_blend(back, colour, alpha), back) for back in backs for colour in colours)
                    large = size >= 36 * scale or element.get("bold") is True and size >= 28 * scale
                    floor = MIN_CONTRAST_LARGE if large else MIN_CONTRAST
                    if worst < floor:
                        add("low_contrast", ep, f"Text contrast is {worst:.1f}:1, below {floor:g}:1 against what lies behind it")
            sentence = _sentence(element["text"])
            if sentence and size < small and not _ignored(element, "small_text"):
                add("small_text", ep, f"A sentence at {size:g} px is below {small:g} px (18 pt on a 1920 px canvas); enlarge it or cut words")
            if sentence:
                seen.setdefault(" ".join(element["text"].lower().split()), []).append((si, ep, element))
    for places in seen.values():
        first = places[0][0]
        for si, ep, element in places:
            if si != first and not _ignored(element, "repeated_text"):
                add("repeated_text", ep, f"The same sentence is on slide {first + 1}; say it once or make it a deliberate callback")
    return out
