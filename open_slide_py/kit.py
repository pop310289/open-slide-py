"""Building blocks for decks written in Python: themed text, cards, badges, headers and bar charts.

Text boxes are sized from the font's advance widths (model.wrap_text), every colour comes from one theme, and the
result is plain scene JSON that validate_deck checks and every exporter accepts.

    from open_slide_py.kit import Kit
    kit = Kit("light-red")
    head, top = kit.header(2, "HABIT 1 OF 4", "One slide, one message", "Write the title as the point.")
    body = [kit.card("c", kit.left, top, 800, 300, focal=True), kit.text("t", kit.left + 48, top + 44, 704, "...")]
    deck = kit.deck("my-deck", "My deck", [kit.slide(2, "One slide, one message", head + body, notes="...")])
"""
from __future__ import annotations

import math

from .model import text_width, wrap_text

# A theme is the whole colour design; both below keep text at 4.5:1 or more (the palette table in references/authoring.md).
#   bg, ink, muted, accent    slide background, main text, secondary text, emphasis
#   neutral                   base of translucent lines, bars and card borders
#   card_stops                card gradient at 135 degrees, from the top-right corner to the bottom-left, (colour, opacity) pairs
#   card_stroke, card_shadow  border opacity and drop shadow of ordinary cards
#   focal_stroke, focal_glow  border and glow opacity of the one card that matters most on a slide
#   weak                      fill and text of a deliberately weak-contrast example
THEMES = {
    "dark-orange": {"bg": "#0E0F12", "ink": "#EDE7DF", "muted": "#A9A39B", "accent": "#FF7A3D", "neutral": "#FFFFFF",
                    "card_stops": (("#FFFFFF", 0.10), ("#FFFFFF", 0.03)), "card_stroke": 0.18, "card_shadow": None,
                    "focal_stroke": 0.55, "focal_glow": 0.28, "weak": ("#45484D", "#5C6066")},
    # On white, translucent white cards disappear: white-to-grey cards with a thin dark border and a soft shadow instead.
    "light-red": {"bg": "#FFFFFF", "ink": "#1B1B1F", "muted": "#5F6368", "accent": "#D0202E", "neutral": "#1B1B1F",
                  "card_stops": (("#FFFFFF", 1.0), ("#F3F3F5", 1.0)), "card_stroke": 0.12,
                  "card_shadow": {"color": "#000000", "opacity": 0.10, "blur": 30, "distance": 8},
                  "focal_stroke": 0.7, "focal_glow": 0.16, "weak": ("#E4E4E7", "#CACACF")},
}
ROLES = ("bg", "ink", "muted", "accent", "neutral")
LINE_HEIGHT = 1.2


def bottom(element):
    return element["y"] + element["height"]


class Kit:
    """Element factories bound to one theme and canvas."""

    def __init__(self, theme="dark-orange", width=1920, height=1080, margin=120, body=40, label=30, serif="Georgia", sans="Arial"):
        if isinstance(theme, str):
            if theme not in THEMES:
                raise ValueError(f"Unknown theme {theme!r}; use one of {', '.join(THEMES)} or pass a theme dictionary")
            theme = THEMES[theme]
        missing = [key for key in THEMES["dark-orange"] if key not in theme]
        if missing:
            raise ValueError("Theme is missing: " + ", ".join(missing))
        self.theme = dict(theme)
        self.width, self.height, self.left, self.right = width, height, margin, width - margin
        self.content_width = width - 2 * margin
        self.body, self.label, self.serif, self.sans = body, label, serif, sans

    def colour(self, value):
        """A theme role (bg, ink, muted, accent, neutral) or a #RRGGBB colour."""
        return self.theme[value] if value in ROLES else value

    def text(self, id, x, y, w, body, size=None, font=None, color="ink", bold=False, align="left", accent=(), strong=(), pad=0.15, **extra):
        """A text box exactly as tall as its wrapped lines; accent and strong list phrases to colour or embolden."""
        size, font = size or self.body, font or self.sans
        lines = len(wrap_text(body, w, size, font, bold))
        element = {"id": id, "type": "text", "x": x, "y": y, "width": w, "height": round(lines * size * LINE_HEIGHT + size * pad),
                   "text": body, "font_size": size, "font_family": font, "color": self.colour(color)}
        if bold:
            element["bold"] = True
        if align != "left":
            element["align"] = align
        highlights = [{"text": phrase, "color": self.theme["accent"]} for phrase in accent] + [{"text": phrase, "bold": True} for phrase in strong]
        if highlights:
            element["highlights"] = highlights
        element.update(extra)
        return element

    def card(self, id, x, y, w, h, focal=False, radius=32):
        """A rounded card in the theme's style; the focal one gets the accent border and glow."""
        stops = [{"color": c, "opacity": o, "at": at} if o < 1 else {"color": c, "at": at} for (c, o), at in zip(self.theme["card_stops"], (0, 1))]
        element = {"id": id, "type": "rect", "x": x, "y": y, "width": w, "height": h, "radius": radius, "gradient": {"angle": 135, "stops": stops},
                   "stroke": self.theme["accent"] if focal else self.theme["neutral"],
                   "stroke_opacity": self.theme["focal_stroke"] if focal else self.theme["card_stroke"], "stroke_width": 2}
        if self.theme["card_shadow"]:
            element["shadow"] = dict(self.theme["card_shadow"])
        if focal:
            element["glow"] = {"color": self.theme["accent"], "opacity": self.theme["focal_glow"], "radius": 22}
        return element

    def rule(self, id, x, y, w=96, color="accent", opacity=1.0, width=3):
        element = {"id": id, "type": "line", "x": x, "y": y, "width": w, "height": 0, "stroke": self.colour(color), "stroke_width": width}
        if opacity < 1:
            element["stroke_opacity"] = opacity
        return element

    def badge(self, id, x, y, label, w=84, h=56):
        """An outlined number badge such as 01; returns its box and its text."""
        return [{"id": id + "-box", "type": "rect", "x": x, "y": y, "width": w, "height": h, "radius": 14,
                 "stroke": self.theme["accent"], "stroke_opacity": 0.8, "stroke_width": 2},
                self.text(id, x, y + 8, w, label, self.label, color="accent", bold=True, align="center")]

    def pill(self, id, x, y, w, h=14, opacity=0.16):
        """A rounded neutral bar, for placeholder lines and mock-ups."""
        return {"id": id, "type": "rect", "x": x, "y": y, "width": w, "height": h, "radius": h // 2,
                "fill": self.theme["neutral"], "fill_opacity": opacity}

    def header(self, no, label, title, subtitle=None, accent=(), title_size=72):
        """Kicker, accent rule, one-line serif title and an optional muted subtitle; returns (elements, first free y)."""
        elements = [self.text(f"label{no}", self.left, 84, 1100, label, self.label, color="accent", bold=True),
                    self.rule(f"rule{no}", self.left, 136, 420, opacity=0.6, width=2),
                    self.text(f"title{no}", self.left, 164, self.content_width, title, title_size, font=self.serif, accent=accent)]
        if subtitle:
            elements.append(self.text(f"subtitle{no}", self.left, bottom(elements[-1]) + 12, self.content_width, subtitle, color="muted"))
        return elements, bottom(elements[-1]) + 44

    def bar_chart(self, id, x, y, w, items, unit="", max_value=None, focus=0, size=None, bar_height=56, gap=40, value_format="{:g}"):
        """Horizontal bars from one zero line, each labelled, with its value at the bar end; returns (elements, bottom y).

        items are (label, value) pairs with non-negative values; bar lengths are proportional to the values from zero,
        so the chart never exaggerates a difference. focus is the index of the bar in the accent colour (None for none).
        """
        if not items:
            raise ValueError("bar_chart needs at least one (label, value) item")
        values = [value for _, value in items]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values):
            raise ValueError("bar_chart values must be finite, non-negative numbers")
        top = max(values) if max_value is None else max_value
        if top <= 0 or top < max(values):
            raise ValueError("max_value must be positive and at least the largest value")
        size = size or self.body
        label_w = math.ceil(max(text_width(label, size, self.sans) for label, _ in items)) + 24
        shown = [value_format.format(v) + unit for v in values]
        value_w = math.ceil(max(text_width(s, size, self.sans, True) for s in shown)) + 16
        zero, length = x + label_w, w - label_w - value_w
        if length <= 0:
            raise ValueError("bar_chart is too narrow for its labels and values")
        row = bar_height + gap
        height = len(items) * row - gap
        offset = round((bar_height - size * LINE_HEIGHT) / 2)
        elements = [{"id": f"{id}-axis", "type": "line", "x": zero, "y": y - 12, "width": 0, "height": height + 24,
                     "stroke": self.theme["neutral"], "stroke_opacity": 0.35, "stroke_width": 2}]
        for i, ((label, value), text) in enumerate(zip(items, shown)):
            top_y, bar_len = y + i * row, round(value / top * length)
            elements.append(self.text(f"{id}-label{i + 1}", x, top_y + offset, label_w - 24, label, size))
            if bar_len > 0:
                bar = {"id": f"{id}-bar{i + 1}", "type": "rect", "x": zero, "y": top_y, "width": bar_len, "height": bar_height,
                       "radius": min(10, bar_height // 4), "fill": self.theme["accent"] if i == focus else self.theme["neutral"]}
                if i != focus:
                    bar["fill_opacity"] = 0.35
                elements.append(bar)
            elements.append(self.text(f"{id}-value{i + 1}", zero + bar_len + 16, top_y + offset, value_w - 16, text, size, bold=True))
        return elements, y + height

    def slide(self, no, title, elements, notes=""):
        return {"id": f"s{no}", "title": title, "background": self.theme["bg"], "elements": elements, "notes": notes}

    def deck(self, id, title, slides, lang="en-US"):
        return {"schema_version": 1, "id": id, "title": title, "width": self.width, "height": self.height, "lang": lang, "slides": slides}

    def check(self, slide, inset=20, margin_y=60):
        """Layout problems validate_deck cannot know about: text leaving the card it starts in, and elements outside the margins."""
        problems = []
        cards = [e for e in slide["elements"] if e["type"] == "rect" and e.get("radius", 0) >= 24]
        for t in (e for e in slide["elements"] if e["type"] == "text"):
            for c in cards:
                if c["x"] <= t["x"] < c["x"] + c["width"] and c["y"] <= t["y"] < c["y"] + c["height"]:
                    if bottom(t) > bottom(c) - inset or t["x"] + t["width"] > c["x"] + c["width"] - inset:
                        problems.append(f'{slide["id"]}: {t["id"]} leaves {c["id"]}')
        for e in slide["elements"]:
            if e["x"] < self.left or e["x"] + e["width"] > self.right or e["y"] < margin_y or e["y"] + e["height"] > self.height - margin_y:
                problems.append(f'{slide["id"]}: {e["id"]} crosses the margin')
        return problems
