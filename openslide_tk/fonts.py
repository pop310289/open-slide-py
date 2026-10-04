"""Font declarations and deterministic document defaults, without font loading.

Inputs are validated scene dictionaries. Font availability and glyph substitution
belong to the displaying application; this module does not embed system fonts.
"""

DEFAULT_LATIN = "Arial"
DEFAULT_EAST_ASIAN = "Microsoft JhengHei"


def element_fonts(element):
    return (element.get("font_family", DEFAULT_LATIN),
            element.get("east_asian_font", DEFAULT_EAST_ASIAN))


def document_fonts(deck):
    """Infer each script's common face; mixed/empty scripts use legacy defaults.

The rule is order-independent, includes omitted fields via their defaults, and
never changes the font explicitly declared on a text element.
"""
    pairs = [element_fonts(e) for s in deck["slides"] for e in s["elements"] if e["type"] == "text"]
    defaults = (DEFAULT_LATIN, DEFAULT_EAST_ASIAN)
    result = []
    for index, default in enumerate(defaults):
        faces = {pair[index] for pair in pairs}
        result.append(next(iter(faces)) if len(faces) == 1 else default)
    return tuple(result)


def contains_east_asian(text):
    # CJK radicals/punctuation/kana/bopomofo/ideographs, Hangul, compatibility
    # forms, fullwidth forms, and supplementary Han extensions. Emoji alone do
    # not choose a CJK font. Explicit code points avoid Tcl8/9 surrogate variance.
    ranges = ((0x2E80, 0xA4CF), (0xAC00, 0xD7AF), (0xF900, 0xFAFF),
              (0xFE30, 0xFE4F), (0xFF00, 0xFFEF), (0x20000, 0x323AF))
    return any(any(low <= ord(char) <= high for low, high in ranges) for char in text)


def canvas_font(element):
    """Tk has one family per text item, so a mixed item uses its explicit EA face.

Omitted EA fields preserve the previous Tk family selection. ASCII-only text
keeps the Latin family even when an EA face is declared.
"""
    if element.get("east_asian_font") and contains_east_asian(element.get("text", "")):
        return element["east_asian_font"]
    return element.get("font_family", DEFAULT_LATIN)
