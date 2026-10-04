"""Deterministic editable PresentationML export, implemented with Python stdlib.

Canvas units match open-slide's documented PPTX units: 6,350 EMU per pixel,
and 50 hundredths of a point per font pixel. No JavaScript renderer is needed.
"""
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
import zipfile

from .export import write_atomic
from .model import DEFAULT_TEXT_COLOR, GLOW_FIELDS, SHADOW_FIELDS, assert_valid, pptx_language, resolve_image, styled_lines
from .fonts import document_fonts, element_fonts

NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_P = "application/vnd.openxmlformats-officedocument.presentationml"
DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
NAMESPACES = f'xmlns:a="{NS_A}" xmlns:p="{NS_P}" xmlns:r="{NS_R}"'
EMU_PER_PX = 6350
CLRMAPPING = 'bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"'
GROUP = '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'


def _e(value):
    return escape(str(value), {'"': '&quot;', "'": '&apos;'})


def _emu(value):
    return int(value * EMU_PER_PX + 0.5) if value >= 0 else -int(-value * EMU_PER_PX + 0.5)


def _fill(color, opacity=1):
    if not color:
        return "<a:noFill/>"
    alpha = f'<a:alpha val="{round(opacity * 100000)}"/>' if opacity < 1 else ""
    return f'<a:solidFill><a:srgbClr val="{color[1:].upper()}">{alpha}</a:srgbClr></a:solidFill>'


def _alpha(value):
    return f'<a:alpha val="{round(value * 100000)}"/>' if value < 1 else ""


def _degrees(value):
    return round(value * 60000) % 21600000


def _shape_fill(element):
    opacity = element.get("opacity", 1)
    gradient = element.get("gradient")
    if not gradient:
        return _fill(element.get("fill"), opacity * element.get("fill_opacity", 1))
    stops = "".join(f'<a:gs pos="{round(stop["at"] * 100000)}"><a:srgbClr val="{stop["color"][1:].upper()}">'
                    f'{_alpha(stop.get("opacity", 1) * opacity)}</a:srgbClr></a:gs>' for stop in gradient["stops"])
    return f'<a:gradFill rotWithShape="1"><a:gsLst>{stops}</a:gsLst><a:lin ang="{_degrees(gradient.get("angle", 90))}" scaled="0"/></a:gradFill>'


def _effects(element):
    parts = []
    if element.get("glow"):
        glow = {**GLOW_FIELDS, **element["glow"]}
        parts.append(f'<a:glow rad="{_emu(glow["radius"])}"><a:srgbClr val="{glow["color"][1:].upper()}">{_alpha(glow["opacity"])}</a:srgbClr></a:glow>')
    if element.get("shadow"):
        shadow = {**SHADOW_FIELDS, **element["shadow"]}
        parts.append(f'<a:outerShdw blurRad="{_emu(shadow["blur"])}" dist="{_emu(shadow["distance"])}" dir="{_degrees(shadow["angle"])}" algn="ctr" '
                     f'rotWithShape="0"><a:srgbClr val="{shadow["color"][1:].upper()}">{_alpha(shadow["opacity"])}</a:srgbClr></a:outerShdw>')
    return f'<a:effectLst>{"".join(parts)}</a:effectLst>' if parts else ""


def _outline(element):
    opacity = element.get("opacity", 1) * element.get("stroke_opacity", 1)
    return f'<a:ln w="{_emu(element.get("stroke_width", 1))}">{_fill(element.get("stroke"), opacity)}<a:prstDash val="solid"/></a:ln>'


def _transform(element):
    return f'<a:xfrm><a:off x="{_emu(element["x"])}" y="{_emu(element["y"])}"/><a:ext cx="{_emu(element["width"])}" cy="{_emu(element["height"])}"/></a:xfrm>'


def _rels(entries):
    items = []
    for rid, kind, target, external in entries:
        mode = ' TargetMode="External"' if external else ""
        items.append(f'<Relationship Id="{_e(rid)}" Type="{_e(kind if "://" in kind else NS_R + "/" + kind)}" Target="{_e(target)}"{mode}/>')
    return DECL + f'<Relationships xmlns="{NS_REL}">{"".join(items)}</Relationships>'


def _text_body(element, lang):
    size = element.get("font_size", 48)
    font, east_asian_font = map(_e, element_fonts(element))
    font_xml = f'<a:latin typeface="{font}"/><a:ea typeface="{east_asian_font}"/><a:cs typeface="{font}"/>'
    opacity = element.get("opacity", 1)

    def attrs(bold):
        flag = ' b="1"' if bold else ' b="0"'
        return f'lang="{_e(lang)}" sz="{round(size * 50)}"{flag} dirty="0"'

    def style(color):
        return _fill(color, opacity) + font_xml

    base_color, base_bold = element.get("color", DEFAULT_TEXT_COLOR), element.get("bold", False)
    paragraphs = []
    for runs in styled_lines(element):
        alignment = {"left": "l", "center": "ctr", "right": "r"}[element.get("align", "left")]
        properties = f'<a:pPr algn="{alignment}" marL="0" marR="0" indent="0"><a:lnSpc><a:spcPts val="{round(size * 60)}"/></a:lnSpc><a:spcBef><a:spcPts val="0"/></a:spcBef><a:spcAft><a:spcPts val="0"/></a:spcAft><a:buNone/></a:pPr>'
        text_runs = "".join(f'<a:r><a:rPr {attrs(bold)}>{style(color)}</a:rPr><a:t xml:space="preserve">{_e(part)}</a:t></a:r>'
                            for part, color, bold in runs)
        paragraphs.append(f'<a:p>{properties}{text_runs}<a:endParaRPr {attrs(base_bold)}>{style(base_color)}</a:endParaRPr></a:p>')
    return '<p:txBody><a:bodyPr wrap="none" lIns="0" tIns="0" rIns="0" bIns="0" anchor="t"><a:noAutofit/></a:bodyPr><a:lstStyle/>' + ''.join(paragraphs) + '</p:txBody>'


def _shape(element, shape_id, hyperlink="", image_rid=None, lang="zh-TW"):
    kind = element["type"]
    properties = f'<p:cNvPr id="{shape_id}" name="{_e(element["id"])}" descr="{_e(element.get("alt", ""))}">{hyperlink}</p:cNvPr>'
    geometry = {"text": "rect", "rect": "rect", "ellipse": "ellipse", "line": "line", "image": "rect"}[kind]
    radius = element.get("radius", 0) if kind in ("rect", "text") else 0
    if radius:
        adjust = min(50000, round(radius / max(min(element["width"], element["height"]), 1e-9) * 100000))
        geometric = _transform(element) + f'<a:prstGeom prst="roundRect"><a:avLst><a:gd name="adj" fmla="val {adjust}"/></a:avLst></a:prstGeom>'
    else:
        geometric = _transform(element) + f'<a:prstGeom prst="{geometry}"><a:avLst/></a:prstGeom>'
    if kind == "image":
        opacity = element.get("opacity", 1)
        alpha = f'<a:alphaModFix amt="{round(opacity * 100000)}"/>' if opacity < 1 else ""
        return f'<p:pic><p:nvPicPr>{properties}<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="{image_rid}">{alpha}</a:blip><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr>{geometric}{_outline(element)}{_effects(element)}</p:spPr></p:pic>'
    txbox = ' txBox="1"' if kind == "text" else ""
    body = _text_body(element, lang) if kind == "text" else ""
    return f'<p:sp><p:nvSpPr>{properties}<p:cNvSpPr{txbox}/><p:nvPr/></p:nvSpPr><p:spPr>{geometric}{_shape_fill(element)}{_outline(element)}{_effects(element)}</p:spPr>{body}</p:sp>'


def _theme(font_pair):
    latin, east_asian = map(_e, font_pair)
    # A supplemental Hant theme face for Office on Windows. Explicit a:ea runs
    # retain the author's face; this hint is not an embedded font or a guarantee
    # that a renderer substitutes a missing explicit face through the theme.
    hant = "Microsoft JhengHei" if font_pair[1] == "PingFang TC" else east_asian
    colors = {"dk1": "111827", "lt1": "FFFFFF", "dk2": "26334B", "lt2": "F1F5F9", "accent1": "147D92", "accent2": "BD5443", "accent3": "6A54A3", "accent4": "739649", "accent5": "DA9930", "accent6": "5875AC", "hlink": "0563C1", "folHlink": "954F72"}
    clr = ''.join(f'<a:{name}><a:srgbClr val="{value}"/></a:{name}>' for name, value in colors.items())
    fonts = ''.join(f'<a:{name}><a:latin typeface="{latin}"/><a:ea typeface="{east_asian}"/><a:cs typeface="{latin}"/><a:font script="Hant" typeface="{hant}"/></a:{name}>' for name in ("majorFont", "minorFont"))
    fill = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    lines = ''.join(f'<a:ln w="{width}" cap="flat" cmpd="sng" algn="ctr">{fill}<a:prstDash val="solid"/><a:miter lim="800000"/></a:ln>' for width in (6350, 12700, 19050))
    return DECL + f'<a:theme xmlns:a="{NS_A}" name="open-slide-py"><a:themeElements><a:clrScheme name="open-slide-py">{clr}</a:clrScheme><a:fontScheme name="{latin}">{fonts}</a:fontScheme><a:fmtScheme name="open-slide-py"><a:fillStyleLst>{fill * 3}</a:fillStyleLst><a:lnStyleLst>{lines}</a:lnStyleLst><a:effectStyleLst>{"<a:effectStyle><a:effectLst/></a:effectStyle>" * 3}</a:effectStyleLst><a:bgFillStyleLst>{fill * 3}</a:bgFillStyleLst></a:fmtScheme></a:themeElements><a:objectDefaults/><a:extraClrSchemeLst/></a:theme>'


def _notes_master():
    body = '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Notes"/><p:cNvSpPr/><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr><a:xfrm><a:off x="685800" y="4114800"/><a:ext cx="5486400" cy="4114800"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>'
    return DECL + f'<p:notesMaster {NAMESPACES}><p:cSld><p:spTree>{GROUP}{body}</p:spTree></p:cSld><p:clrMap {CLRMAPPING}/><p:notesStyle><a:lvl1pPr><a:defRPr sz="1200"/></a:lvl1pPr></p:notesStyle></p:notesMaster>'


def _notes(text, font_pair, lang):
    latin, east_asian = map(_e, font_pair)
    paragraphs = ''.join(f'<a:p><a:r><a:rPr lang="{_e(lang)}" sz="1200"><a:latin typeface="{latin}"/><a:ea typeface="{east_asian}"/></a:rPr><a:t xml:space="preserve">{_e(line)}</a:t></a:r></a:p>' for line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'))
    body = f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="Notes"/><p:cNvSpPr/><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>{paragraphs}</p:txBody></p:sp>'
    return DECL + f'<p:notes {NAMESPACES}><p:cSld><p:spTree>{GROUP}{body}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>'


def build_pptx_parts(deck, base_dir=None):
    """Return every OPC part; useful for inspection and independent testing."""
    assert_valid(deck, base_dir)
    if any(not 144 <= deck[axis] <= 8064 for axis in ("width", "height")):
        raise ValueError("PPTX canvas dimensions must each be 144 to 8,064 pixels (1 to 56 inches)")
    for slide in deck["slides"]:
        for element in slide["elements"]:
            if element["type"] == "text" and not 2 <= element.get("font_size", 48) <= 2640:
                raise ValueError("PPTX text font_size must be 2 to 2,640 pixels to preserve exact line spacing")
    parts = {}
    slides = deck["slides"]
    font_pair = document_fonts(deck)
    lang = pptx_language(deck)
    has_notes = any(slide.get("notes") for slide in slides)
    content_overrides = []

    def add(name, data, content_type=None):
        parts[name] = data.encode("utf-8") if isinstance(data, str) else data
        if content_type:
            content_overrides.append(("/" + name, content_type))

    root_rels = [("rId1", "officeDocument", "ppt/presentation.xml", False),
                 ("rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml", False),
                 ("rId3", "extended-properties", "docProps/app.xml", False)]
    add("_rels/.rels", _rels(root_rels))
    creator = deck.get("metadata", {}).get("author", "open-slide-py")
    description = deck.get("metadata", {}).get("description", "")
    core = f'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>{_e(deck["title"])}</dc:title><dc:creator>{_e(creator)}</dc:creator><dc:description>{_e(description)}</dc:description><cp:lastModifiedBy>open-slide-py</cp:lastModifiedBy><cp:revision>1</cp:revision><dcterms:created xsi:type="dcterms:W3CDTF">2000-01-01T00:00:00Z</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">2000-01-01T00:00:00Z</dcterms:modified></cp:coreProperties>'
    add("docProps/core.xml", DECL + core, "application/vnd.openxmlformats-package.core-properties+xml")
    app = f'<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>open-slide-py</Application><PresentationFormat>Custom</PresentationFormat><Slides>{len(slides)}</Slides><Notes>{sum(bool(s.get("notes")) for s in slides)}</Notes><HiddenSlides>0</HiddenSlides><AppVersion>1.0</AppVersion></Properties>'
    add("docProps/app.xml", DECL + app, "application/vnd.openxmlformats-officedocument.extended-properties+xml")
    pres_rels = [("rId1", "slideMaster", "slideMasters/slideMaster1.xml", False)]
    slide_ids = ''.join(f'<p:sldId id="{256 + i}" r:id="rId{i + 2}"/>' for i in range(len(slides)))
    pres_rels.extend((f"rId{i + 2}", "slide", f"slides/slide{i + 1}.xml", False) for i in range(len(slides)))
    notes_master_ref = ""
    if has_notes:
        nrid = f"rId{len(slides) + 2}"
        pres_rels.append((nrid, "notesMaster", "notesMasters/notesMaster1.xml", False))
        notes_master_ref = f'<p:notesMasterIdLst><p:notesMasterId r:id="{nrid}"/></p:notesMasterIdLst>'
        add("ppt/notesMasters/notesMaster1.xml", _notes_master(), f"{CT_P}.notesMaster+xml")
        add("ppt/notesMasters/_rels/notesMaster1.xml.rels", _rels([("rId1", "theme", "../theme/theme2.xml", False)]))
        add("ppt/theme/theme2.xml", _theme(font_pair), "application/vnd.openxmlformats-officedocument.theme+xml")
    presentation = f'<p:presentation {NAMESPACES}><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>{notes_master_ref}<p:sldIdLst>{slide_ids}</p:sldIdLst><p:sldSz cx="{_emu(deck["width"])}" cy="{_emu(deck["height"])}"/><p:notesSz cx="6858000" cy="9144000"/><p:defaultTextStyle/></p:presentation>'
    add("ppt/presentation.xml", DECL + presentation, f"{CT_P}.presentation.main+xml")
    add("ppt/_rels/presentation.xml.rels", _rels(pres_rels))
    master = f'<p:sldMaster {NAMESPACES}><p:cSld><p:spTree>{GROUP}</p:spTree></p:cSld><p:clrMap {CLRMAPPING}/><p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst><p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>'
    add("ppt/slideMasters/slideMaster1.xml", DECL + master, f"{CT_P}.slideMaster+xml")
    add("ppt/slideMasters/_rels/slideMaster1.xml.rels", _rels([("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml", False), ("rId2", "theme", "../theme/theme1.xml", False)]))
    layout = f'<p:sldLayout {NAMESPACES} type="blank" preserve="1"><p:cSld name="Blank"><p:spTree>{GROUP}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>'
    add("ppt/slideLayouts/slideLayout1.xml", DECL + layout, f"{CT_P}.slideLayout+xml")
    add("ppt/slideLayouts/_rels/slideLayout1.xml.rels", _rels([("rId1", "slideMaster", "../slideMasters/slideMaster1.xml", False)]))
    add("ppt/theme/theme1.xml", _theme(font_pair), "application/vnd.openxmlformats-officedocument.theme+xml")
    image_names = {}
    image_extensions = set()
    slide_targets = {slide["id"]: i + 1 for i, slide in enumerate(slides)}
    for index, slide in enumerate(slides, 1):
        relationships = [("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml", False)]
        relation_lookup = {}

        def relationship(kind, target, external=False):
            key = (kind, target, external)
            if key not in relation_lookup:
                relation_lookup[key] = f"rId{len(relationships) + 1}"
                relationships.append((relation_lookup[key], kind, target, external))
            return relation_lookup[key]

        shapes = []
        for element_index, element in enumerate(slide["elements"], 2):
            hyperlink = ""
            if element.get("href"):
                href = element["href"]
                if href.startswith("#"):
                    rid = relationship("slide", f"slide{slide_targets[href[1:]]}.xml")
                    hyperlink = f'<a:hlinkClick r:id="{rid}" action="ppaction://hlinksldjump"/>'
                else:
                    rid = relationship("hyperlink", href, True)
                    hyperlink = f'<a:hlinkClick r:id="{rid}"/>'
            image_rid = None
            if element["type"] == "image":
                _, mime, payload = resolve_image(element["path"], base_dir)
                extension = {"image/png": "png", "image/jpeg": "jpeg", "image/gif": "gif"}[mime]
                digest = hashlib.sha256(payload).hexdigest()
                if digest not in image_names:
                    name = f"image-{digest}.{extension}"
                    image_names[digest] = name
                    image_extensions.add((extension, mime))
                    add("ppt/media/" + name, payload)
                image_rid = relationship("image", "../media/" + image_names[digest])
            shapes.append(_shape(element, element_index, hyperlink, image_rid, lang))
        background = _fill(slide.get("background", "#FFFFFF"))
        slide_xml = f'<p:sld {NAMESPACES}><p:cSld name="{_e(slide.get("title", ""))}"><p:bg><p:bgPr>{background}<a:effectLst/></p:bgPr></p:bg><p:spTree>{GROUP}{"".join(shapes)}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'
        add(f"ppt/slides/slide{index}.xml", DECL + slide_xml, f"{CT_P}.slide+xml")
        if slide.get("notes"):
            relationship("notesSlide", f"../notesSlides/notesSlide{index}.xml")
            add(f"ppt/notesSlides/notesSlide{index}.xml", _notes(slide["notes"], font_pair, lang), f"{CT_P}.notesSlide+xml")
            add(f"ppt/notesSlides/_rels/notesSlide{index}.xml.rels", _rels([("rId1", "notesMaster", "../notesMasters/notesMaster1.xml", False), ("rId2", "slide", f"../slides/slide{index}.xml", False)]))
        add(f"ppt/slides/_rels/slide{index}.xml.rels", _rels(relationships))
    defaults = '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
    defaults += ''.join(f'<Default Extension="{ext}" ContentType="{mime}"/>' for ext, mime in sorted(image_extensions))
    overrides = ''.join(f'<Override PartName="{name}" ContentType="{content_type}"/>' for name, content_type in sorted(content_overrides))
    add("[Content_Types].xml", DECL + f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">{defaults}{overrides}</Types>')
    return parts


def export_pptx(deck, output_path, base_dir=None) -> Path:
    """Write an editable, reproducible PPTX with shapes, text, images and notes."""
    parts = build_pptx_parts(deck, base_dir)
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(parts.items()):
            entry = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_STORED if name.startswith("ppt/media/") else zipfile.ZIP_DEFLATED
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data, compress_type=entry.compress_type, compresslevel=9)
    return write_atomic(output_path, output.getvalue())
