"""Self-contained SVG, static HTML and native JavaScript player exports."""
from __future__ import annotations

import base64
import hashlib
from html import escape
from pathlib import Path
import xml.etree.ElementTree as ET

from .model import assert_valid, bilingual_labels, html_language, resolve_image, wrap_text
from .storage import atomic_write
from .fonts import document_fonts

SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG)


def write_atomic(path, data):
    """Keep the exporter interface while sharing storage's permission policy."""
    return atomic_write(path, data)


def _n(value):
    return f"{value:.6f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)


def _font_stack(element):
    # OOXML uses individual faces; the browser can use an ordered fallback list.
    names = [element.get("font_family", "Arial")]
    if element.get("east_asian_font"):
        names.append(element["east_asian_font"])
    names.extend(("PingFang TC", "Microsoft JhengHei", "Noto Sans CJK TC"))
    quoted = ['"' + name.replace("\\", "\\\\").replace('"', '\\"').replace("<", "\\3c ").replace(">", "\\3e ").replace("&", "\\26 ") + '"'
              for name in dict.fromkeys(names)]
    return ", ".join(quoted + ["sans-serif"])


def _document_font_stack(deck):
    latin, east_asian = document_fonts(deck)
    return _font_stack({"font_family": latin, "east_asian_font": east_asian})


def _svg(deck, slide_index, base_dir, anchor_map=None):
    slide = deck["slides"][slide_index]
    width, height = deck["width"], deck["height"]
    svg = ET.Element(f"{{{SVG}}}svg", {
        "viewBox": f"0 0 {_n(width)} {_n(height)}", "width": _n(width), "height": _n(height),
        "role": "img", "aria-labelledby": f"title-{slide_index}",
    })
    ET.SubElement(svg, "title", {"id": f"title-{slide_index}"}).text = slide.get("title", deck["title"])
    ET.SubElement(svg, "desc").text = slide.get("notes", "")
    ET.SubElement(svg, "rect", {"width": _n(width), "height": _n(height), "fill": slide.get("background", "#FFFFFF")})
    definitions = ET.SubElement(svg, "defs")
    for index, element in enumerate(slide["elements"]):
        kind = element["type"]
        x, y, w, h = (element[k] for k in ("x", "y", "width", "height"))
        container = svg
        if "step" in element:
            container = ET.SubElement(container, "g", {"data-os-step": str(element["step"])})
        href = element.get("href")
        if href:
            if anchor_map and href.startswith("#"):
                href = anchor_map[href[1:]]
            container = ET.SubElement(container, "a", {"href": href})
        group = ET.SubElement(container, "g", {"opacity": _n(element.get("opacity", 1)), "data-element-id": element["id"]})
        if element.get("alt"):
            ET.SubElement(group, "title").text = element["alt"]
        attrs = {"fill": element.get("fill") or "none", "stroke": element.get("stroke") or "none",
                 "stroke-width": _n(element.get("stroke_width", 1))}
        if kind == "line":
            attrs.update(x1=_n(x), y1=_n(y), x2=_n(x + w), y2=_n(y + h))
            ET.SubElement(group, "line", attrs)
        elif kind == "ellipse":
            attrs.update(cx=_n(x + w / 2), cy=_n(y + h / 2), rx=_n(w / 2), ry=_n(h / 2))
            ET.SubElement(group, "ellipse", attrs)
        elif kind in ("rect", "text"):
            attrs.update(x=_n(x), y=_n(y), width=_n(w), height=_n(h))
            ET.SubElement(group, "rect", attrs)
            if kind == "text":
                clip_id = f"clip-{slide_index}-{index}"
                clip = ET.SubElement(definitions, "clipPath", {"id": clip_id})
                ET.SubElement(clip, "rect", {"x": _n(x), "y": _n(y), "width": _n(w), "height": _n(h)})
                font_size = element.get("font_size", 48)
                align = element.get("align", "left")
                anchor_x = x + {"left": 0, "center": w / 2, "right": w}[align]
                text = ET.SubElement(group, "text", {
                    "fill": element.get("color", "#172F39"), "font-family": _font_stack(element),
                    "font-size": _n(font_size), "font-weight": "700" if element.get("bold", False) else "400",
                    "text-anchor": {"left": "start", "center": "middle", "right": "end"}[align],
                    "clip-path": f"url(#{clip_id})", "{http://www.w3.org/XML/1998/namespace}space": "preserve",
                })
                for li, line in enumerate(wrap_text(element["text"], w, font_size)):
                    ET.SubElement(text, "tspan", {"x": _n(anchor_x), "y": _n(y + font_size * (0.85 + li * 1.2))}).text = line
        elif kind == "image":
            _, mime, data = resolve_image(element["path"], base_dir)
            ET.SubElement(group, "image", {
                "x": _n(x), "y": _n(y), "width": _n(w), "height": _n(h), "preserveAspectRatio": "none",
                "href": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}",
            })
            if element.get("stroke"):
                attrs.update(x=_n(x), y=_n(y), width=_n(w), height=_n(h), fill="none")
                ET.SubElement(group, "rect", attrs)
    return ET.tostring(svg, encoding="unicode", short_empty_elements=True)


def svg_markup(deck, slide_index, base_dir=None, anchor_map=None) -> str:
    """Return an inline SVG for a zero-based slide, with embedded local images.

    SVG IDs include the slide index, so one deck can be embedded in a document.
    Map scene slide IDs to local anchors with ``anchor_map`` when embedding.
    """
    assert_valid(deck, base_dir)
    if type(slide_index) is not int or not 0 <= slide_index < len(deck["slides"]):
        raise ValueError("Slide index is outside the deck")
    if anchor_map is not None:
        if not isinstance(anchor_map, dict) or any(
                not isinstance(key, str) or not isinstance(value, str) or not value.startswith("#")
                or len(value) < 2 or any(c.isspace() or ord(c) < 32 for c in value)
                for key, value in anchor_map.items()):
            raise ValueError("anchor_map must map slide IDs to local #anchors")
        required = {e["href"][1:] for s in deck["slides"] for e in s["elements"]
                    if e.get("href", "").startswith("#")}
        if not required <= anchor_map.keys():
            raise ValueError("anchor_map must include all referenced slide IDs")
    return _svg(deck, slide_index, base_dir, anchor_map)


def export_svg(deck, slide_index, output_path, base_dir=None) -> Path:
    """Export one zero-based slide with embedded raster assets and editable text."""
    return write_atomic(output_path, '<?xml version="1.0" encoding="UTF-8"?>\n' + svg_markup(deck, slide_index, base_dir))


def _player_html(deck, base_dir):
    assets = Path(__file__).with_name("web")
    css = (assets / "player.css").read_text(encoding="utf-8")
    javascript = (assets / "player.js").read_text(encoding="utf-8")
    title = escape(deck["title"])
    anchors = {slide["id"]: f"#slide-{i + 1}" for i, slide in enumerate(deck["slides"])}
    sections, cards = [], []
    for i, slide in enumerate(deck["slides"]):
        name = escape(slide.get("title") or f"投影片 {i + 1}")
        sections.append(
            f'<section class="os-slide" id="slide-{i + 1}" data-os-slide="{i + 1}" '
            f'data-os-transition="{slide.get("transition", "none")}" aria-label="{name}">'
            + _svg(deck, i, base_dir, anchors)
            + '<details class="os-notes" data-os-notes><summary>講者備註</summary>'
            + f'<p>{escape(slide.get("notes") or "本頁沒有講者備註。")}</p></details></section>')
        cards.append(f'<a class="os-card" href="#slide-{i + 1}" data-os-go="{i + 1}">'
                     f'<span class="os-preview" aria-hidden="true"></span>'
                     f'<span class="os-card-title"><b>{i + 1:02d}</b> {name}</span></a>')
    print_css = f'@page {{ size: {_n(deck["width"] / 144)}in {_n(deck["height"] / 144)}in; margin: 0; }}\n'
    print_css += f'@media print {{ .os-slide {{ height: {_n(deck["height"] / 144)}in !important; }} }}'
    stylesheet = css + "\nbody.os-player { font-family: " + _document_font_stack(deck) + "; }\n" + print_css
    script_hash = base64.b64encode(hashlib.sha256(javascript.encode("utf-8")).digest()).decode("ascii")
    style_hash = base64.b64encode(hashlib.sha256(stylesheet.encode("utf-8")).digest()).decode("ascii")
    policy = ("default-src 'none'; img-src data:; "
              f"script-src 'sha256-{script_hash}'; style-src 'sha256-{style_hash}'; "
              "base-uri 'none'; form-action 'none'; object-src 'none'")
    # CSS font declarations are quoted and raw-text delimiters escaped. Script
    # is the trusted package asset; no scene JSON is interpolated into JavaScript.
    return f'''<!doctype html>
<html lang="{escape(html_language(deck), quote=True)}"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{escape(policy, quote=True)}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="open-slide-py offline player">
<title>{title}</title><style>{stylesheet}</style></head>
<body class="os-player">
<a class="os-skip" href="#os-stage">跳至投影片</a>
<header class="os-top"><div class="os-heading"><span class="os-brand">open-slide-py</span><h1>{title}</h1></div>
<div class="os-top-actions" data-os-controls hidden><button type="button" id="os-catalog" aria-haspopup="dialog">目錄</button><button type="button" id="os-tools" aria-haspopup="dialog">工具</button></div></header>
<main id="os-stage" tabindex="-1">{''.join(sections)}</main>
<footer class="os-controls" data-os-controls hidden>
<div class="os-navigation"><button type="button" id="os-prev" aria-label="上一個步驟或上一頁" title="← 上一步">←</button>
<div class="os-position"><span id="os-page" aria-live="polite" aria-atomic="true">1 / {len(sections)}</span><progress id="os-progress" max="{len(sections)}" value="1" aria-label="投影片進度"></progress></div>
<button type="button" id="os-next" aria-label="下一個步驟或下一頁" title="→ 下一步">→</button></div>
<div class="os-status"><span id="os-step-status" aria-live="polite" aria-atomic="true"></span><span class="os-timer-label">播放計時 <output id="os-timer" aria-label="播放計時">00:00</output></span></div>
</footer>
<dialog id="os-directory" aria-labelledby="os-directory-title"><div class="os-dialog-heading"><h2 id="os-directory-title">投影片目錄</h2><button type="button" data-os-close aria-label="關閉目錄">關閉</button></div><div class="os-cards">{''.join(cards)}</div></dialog>
<dialog id="os-toolbox" aria-labelledby="os-toolbox-title"><div class="os-dialog-heading"><h2 id="os-toolbox-title">播放工具</h2><button type="button" data-os-close aria-label="關閉工具">關閉</button></div>
<div class="os-tool-grid"><button type="button" id="os-notes-toggle" aria-pressed="false">講者備註</button><button type="button" id="os-full-toggle" aria-pressed="false">顯示完整頁</button><button type="button" id="os-fullscreen" aria-pressed="false">全螢幕</button><button type="button" id="os-timer-toggle" aria-pressed="false">開始計時</button><button type="button" id="os-timer-reset">計時歸零</button></div>
<p class="os-help">→ / PageDown / 空白鍵前進；← / PageUp / Shift＋空白鍵後退。Home 回首頁，End 到末頁。觸控左右滑動也能換步驟。目錄可直接跳頁，Esc 關閉面板。</p><p class="os-help">逐步模式會依作者設定顯示內容。「顯示完整頁」可一次展開；列印永遠包含全部內容。輸入框、按鈕與面板內保留原本的鍵盤操作。</p><p id="os-message" role="status"></p></dialog>
<script>{javascript}</script></body></html>'''


def export_html(deck, output_path, base_dir=None, *, interactive=False) -> Path:
    """Export offline HTML; opt into the native player with ``interactive=True``.

    The default remains script-free. Both modes embed local image assets and
    print complete slides; interactive mode also works as a full document when
    scripting is disabled. No network or JavaScript build runtime is needed.
    """
    assert_valid(deck, base_dir)
    if type(interactive) is not bool:
        raise ValueError("interactive must be true or false")
    if interactive:
        return write_atomic(output_path, _player_html(deck, base_dir))
    title = escape(deck["title"])
    anchor_map = {slide["id"]: f"#slide-{i + 1}" for i, slide in enumerate(deck["slides"])}
    links = "".join(f'<a href="#slide-{i + 1}" title="{escape(slide.get("title", ""), quote=True)}">{i + 1}</a>'
                    for i, slide in enumerate(deck["slides"]))
    both = bilingual_labels(deck)
    notes_label = "Speaker notes / 講者備註" if both else "Speaker notes"
    skip_label = "Skip to slides / 跳至投影片" if both else "Skip to slides"
    sections = []
    for i, slide in enumerate(deck["slides"]):
        svg = _svg(deck, i, base_dir, anchor_map)
        notes = escape(slide.get("notes", ""))
        note_markup = f'<details class="notes"><summary>{notes_label}</summary><p>{notes}</p></details>' if notes else ""
        sections.append(f'<section id="slide-{i + 1}" aria-label="{escape(slide.get("title", "Slide " + str(i + 1)), quote=True)}">{svg}{note_markup}</section>')
    html = f'''<!doctype html>
<html lang="{escape(html_language(deck), quote=True)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="open-slide-py (Python standard library)">
<title>{title}</title><style>
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; scroll-snap-type: y proximity; }}
body {{ margin: 0; background: #161412; color: #F5F1E8; font-family: {_document_font_stack(deck)}; }}
a {{ color: inherit; }}
.skip {{ position: absolute; left: -10000px; }} .skip:focus {{ left: 1rem; top: 1rem; z-index: 5; }}
nav {{ position: fixed; top: 0; left: 0; right: 0; z-index: 3; display: flex; gap: .55rem; align-items: center; padding: .7rem 1rem; background: #161412ed; overflow-x: auto; }}
nav strong {{ margin-right: 1rem; white-space: nowrap; }}
nav a {{ padding: .4rem .6rem; border: 1px solid #56657a; border-radius: .25rem; text-decoration: none; }}
a:focus-visible, summary:focus-visible {{ outline: 3px solid #73c9ff; outline-offset: 3px; }}
main {{ padding-top: 4rem; }}
section {{ min-height: calc(100vh - 4rem); max-width: 100%; scroll-margin-top: 4rem; scroll-snap-align: start; padding: .5rem 2vw 1.5rem; display: flex; flex-direction: column; justify-content: center; align-items: center; }}
section > svg {{ display: block; max-width: 100%; width: min(96vw, calc((100vh - 7rem) * {_n(deck['width'] / deck['height'])})); height: auto; background: white; }}
.notes {{ max-width: 72rem; width: 100%; padding: 1rem; }} .notes p {{ white-space: pre-wrap; line-height: 1.5; }}
@media (prefers-reduced-motion: reduce) {{ html {{ scroll-behavior: auto; }} }}
@page {{ size: {_n(deck['width'] / 144)}in {_n(deck['height'] / 144)}in; margin: 0; }}
@media print {{
html, body {{ background: white; scroll-snap-type: none; }} nav, .skip, .notes {{ display: none; }}
main {{ padding: 0; }} section {{ padding: 0; margin: 0; min-height: 0; height: {_n(deck['height'] / 144)}in; break-after: page; }}
section:last-child {{ break-after: auto; }} section > svg {{ width: 100%; height: 100%; max-width: none; }}
}}
</style></head><body>
<a class="skip" href="#slides">{skip_label}</a>
<nav aria-label="Slides"><strong>{title}</strong>{links}</nav>
<main id="slides">{''.join(sections)}</main>
</body></html>'''
    return write_atomic(output_path, html)
