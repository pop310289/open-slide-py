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
