# Scene and API

## Format

Root object: `schema_version: 1`, `id`, `title`, `width`, `height`, `slides`, and optionally `metadata` (string keys and string values only; turn structured data into one piece of text first) and `lang`. Each slide has a unique `id`, a `title` and `elements`, and optionally `background`, `notes` and `transition`. Each element has an `id` unique within its slide, plus `type`, `x`, `y`, `width` and `height`.

```json
{"schema_version":1,"id":"demo","title":"My deck","width":1920,"height":1080,"lang":"en-US","slides":[{"id":"s1","title":"Cover","background":"#142F37","notes":"Speaker notes","elements":[{"id":"title","type":"text","x":120,"y":250,"width":1680,"height":180,"text":"From design to delivery","font_size":100,"font_family":"Arial","east_asian_font":"PingFang TC","color":"#FFFFFF"}]}]}
```

| type | Main fields |
|---|---|
| `text` | `text`, `font_size`, `font_family`, `east_asian_font`, `color`, `bold`, `align`, `ignore_warnings` |
| `rect` / `ellipse` | `fill`, `stroke`, `stroke_width`, `opacity` |
| `line` | `stroke`, `stroke_width`; the width or height may be 0 |
| `image` | `path`, `alt`; the path is relative and inside the JSON's folder |

`validate_deck` in `open_slide_py/model.py` is the authority on every field and limit. Colours are six-digit `#RRGGBB`; font sizes and coordinates are canvas pixels. In PPTX one pixel is 6350 EMU and text uses 0.5 pt per pixel. PPTX canvas sides are 144..8064 px and font sizes 2..2640 px. Images may not exceed 25 MiB or 40 megapixels.

`href` may be HTTP(S), mailto or `#slide-id`. `step` is a positive integer; elements with the same value appear together; `transition` is `none` or `fade`. The interactive web version orders the steps that exist, starts each new slide at zero and shows a slide complete when you go back to it. "Show full slide" pauses step mode. PPTX, SVG, static HTML, printing and pages with JavaScript disabled always show every element.

## Styles (cards and emphasis)

| Field | Applies to | Meaning |
|---|---|---|
| `radius` | rect, text | Corner radius in pixels, at most half the short side |
| `fill_opacity`, `stroke_opacity` | elements with a fill or border | Separate opacity (0–1) of the fill and of the border, multiplied by `opacity` |
| `gradient` | rect, ellipse, text | Linear gradient that replaces `fill`: `{"angle": 135, "stops": [{"color": "#FFFFFF", "opacity": 0.12, "at": 0}, {"color": "#FFFFFF", "opacity": 0.02, "at": 1}]}`. `angle` 0 runs left to right and 90 top to bottom; 2–8 stops, `at` from 0 to 1 and never decreasing, `opacity` defaults to 1 |
| `shadow` | rect, ellipse, image | Drop shadow: `color` (default `#000000`), `opacity` (0.35), `blur` (24), `distance` (8), `angle` (90, downwards) |
| `glow` | rect, ellipse, image | Glow: `color` (required), `opacity` (0.4), `radius` (16) |
| `highlights` | text | Colour or embolden phrases inside the text: `[{"text": "admit uncertainty", "color": "#FF7A3D"}, {"text": "4 times", "bold": true}]`. A phrase must occur in `text`; every occurrence is styled, and a later highlight wins where two overlap |

PPTX uses native formats throughout (rounded rectangles, gradient fills, glow and outer shadow, several text runs in one paragraph), so everything stays editable. By default PPTX text has one `a:p` per paragraph and PowerPoint wraps it itself (`wrap="square"`), re-wrapping edited text; line breaks may differ slightly from SVG and HTML. When a paragraph wraps and its last line holds two words or more, those last two words are joined by a no-break space, so PowerPoint does not leave the last word alone on a line. For exactly the same breaks use `export --fixed-lines` (Python: `export_pptx(..., reflow=False)`); PowerPoint then keeps the lines as they are. HTML and SVG use `rx`, `linearGradient`, SVG filters and nested `tspan`. PowerPoint has no background blur, so frosted glass cannot be blurred; on a dark background, a translucent fill, a thin border and a glow are enough for a glass card. Glow and shadow cannot be used on text elements; to lift a block of text, put a rect under it.

## Language

`lang` is an optional language tag such as `en-US` or `zh-TW` (letters and hyphens, at most 35 characters). It sets the proofing language of PPTX text and speaker notes and the HTML `lang` attribute; for a language that is not Chinese (not starting with `zh`) the static HTML frame text is English only. Without it, decks keep `zh-TW` (PPTX), `zh-Hant` (HTML) and bilingual frame text. The interactive player's buttons and help switch too: Chinese for Chinese or untagged decks, English for every other language. `init --lang en-US` creates an English starter deck. Language fields inside `metadata` are not read.

## Warnings

`validate` checks the layout only when there are no errors, and reports `severity: "warning"`:

| Code | When |
|---|---|
| `text_overflow` | After wrapping by font width, the text is taller than its box |
| `text_overlap` | The areas two texts actually cover overlap (text width by alignment, not the boxes) |
| `low_contrast` | Text or a highlighted phrase has less than 4.5:1 contrast with what lies behind it; 3:1 from 18 pt, or 14 pt bold, after scaling. The backdrop is the background plus the shapes under the text (translucent fills are blended, gradients count their worst end); text over an image is not judged |
| `small_text` | A sentence of five or more words (two Chinese characters count as one word), not a label in capitals, is smaller than 36 px (18 pt) on a 1920 px canvas, scaled for other canvas widths |
| `repeated_text` | The same sentence (five or more words, ignoring case and spacing, labels in capitals excepted) is on two or more slides; reported from the second occurrence |
| `missing_alt` | An image has no alternative text |

For a deliberate exception (a "too small" or "grey on grey" example, a sentence that calls back to the opening), add a list such as `"ignore_warnings": ["small_text"]` to the element; it accepts only `text_overflow`, `text_overlap`, `low_contrast`, `small_text` and `repeated_text`.

## Fonts and differences between outputs

The default Latin font is Arial and the default East Asian font Microsoft JhengHei. Lines wrap by the font's real widths: Arial, Georgia, Times New Roman, Verdana, Courier New, Trebuchet MS and Tahoma (regular and bold) use their advance widths plus a 2% margin; Helvetica, Liberation Sans and Arimo count as Arial, Gelasio as Georgia, Times, Liberation Serif and Tinos as Times New Roman, and Courier, Liberation Mono and Cousine as Courier New. Other fonts use a conservative font-independent estimate, which can be too narrow for capitals and arrows; use a listed font when line breaks must be exact. `font_family` and `east_asian_font` each take one font name, not a comma-separated list. When the whole deck uses one face per script, the document theme, notes and HTML frame use it; with mixed faces or no text, that script falls back to the default, and individual elements keep their own fonts.

PPTX writes `a:latin` and `a:ea` separately; when the document's East Asian face is PingFang TC, both themes set Microsoft JhengHei as the Hant supplemental font and keep other explicit faces. This is only a theme hint: it does not guarantee that text set in PingFang will use it on a Windows machine without that font, and Windows itself is still untested. HTML and SVG get their own CSS fallback stack. Fonts are not embedded; the actual glyphs come from the viewing device.

## Python API

Run from this skill's root folder, or put it on `PYTHONPATH`:

```python
from pathlib import Path
from open_slide_py.model import load_deck, validate_deck
from open_slide_py.storage import save_deck
from open_slide_py.export import export_html, export_svg, svg_markup
from open_slide_py.pptx import export_pptx

source = Path('/path/to/my-deck.json')
deck = load_deck(source)
diagnostics = validate_deck(deck, source.parent)
export_pptx(deck, '/path/to/deck.pptx', source.parent)
export_html(deck, '/path/to/static.html', source.parent)
export_html(deck, '/path/to/player.html', source.parent, interactive=True)
export_svg(deck, 0, '/path/to/first.svg', source.parent)
```

With the kit, elements follow the palette and text boxes are sized by font width:

```python
from open_slide_py.kit import Kit
kit = Kit("light-red")  # or "dark-orange", or your own palette dict (same keys as kit.THEMES)
head, top = kit.header(1, "LABEL", "One-line conclusion", "A short subtitle.")
chart, end = kit.bar_chart("hours", kit.left, top, 1200, [("Meeting", 8), ("Written update", 1.3)], unit=" h")
slide = kit.slide(1, "Title", head + chart, notes="...")
problems = kit.check(slide)  # text leaving its card, elements past the margins
deck = kit.deck("my-deck", "My deck", [slide])
```

`read_deck` only parses JSON (rejecting duplicate keys, NaN and Infinity) without validating the scene; `load_deck` parses and validates. `svg_markup(deck, slide_index, base_dir=None, anchor_map=None)` returns an escaped SVG string with images embedded. Indexes start at 0; `anchor_map` accepts only local `#anchor` targets and must cover every referenced slide id. When the same slide's SVG is embedded twice, rewrite its IDs and clip-path references.

Saving and exporting replace files atomically. New files follow the umask and overwrites keep the target's POSIX mode; copying ACLs or ownership is not claimed. Invalid input and failed output never damage an existing file.
