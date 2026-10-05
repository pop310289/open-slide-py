# open-slide-py

A Python standard-library port of [open-slide](https://github.com/open-slide/open-slide). Write a slide deck as a JSON scene, then export it as an editable PowerPoint file (PPTX), SVG, a static HTML reading version or an offline interactive player. The repository is also an agent skill (`SKILL.md`) for Claude Code, Codex and OpenCode.

> **Status: preview (0.2.0).** This is an unofficial port. It is not affiliated with the open-slide project, and it is unrelated to the OpenSlide whole-slide imaging library; for that, see [openslide-python](https://github.com/openslide/openslide-python).

## Features

- **No dependencies.** Everything uses only the Python 3.10+ standard library. There is no visual editor: you edit the JSON scene, write it with a short Python script, or let an agent do either.
- **Editable PPTX.** Text, rectangles, ellipses, lines and images become native PowerPoint objects, speaker notes are kept, and PowerPoint re-wraps text you edit (`--fixed-lines` keeps the exact line breaks of the web exports instead).
- **Cards, emphasis and palettes.** Rounded corners, separate fill and stroke opacity, gradients, glow, shadow and highlighted words are native PowerPoint styles. The kit (`open_slide_py/kit.py`) builds themed cards, number badges, headers and bar charts that start at zero, with two palettes whose text keeps at least 4.5:1 contrast.
- **Text that fits.** Lines wrap by the real advance widths of common fonts (Arial, Georgia, Times New Roman, Verdana, Courier New, Trebuchet MS, Tahoma and their metric-compatible open fonts), within 0.1% of Chrome's measurements on average, and a paragraph's last line never holds a lone word when the word before can join it.
- **Layout warnings.** Besides the schema, geometry, image assets and text overflow, `validate` warns about overlapping text, low contrast against what lies behind the text, sentences smaller than 18 pt and sentences repeated across slides. Deliberate exceptions are marked with `ignore_warnings`. An invalid deck never overwrites an existing output file.
- **Two HTML outputs.** The default HTML is static and contains no JavaScript. `--interactive` adds an offline player with keyboard and touch navigation, step-by-step reveal, a slide index, speaker notes and a timer, with English controls for decks that are not in Chinese; its inline CSS and JavaScript are pinned by a Content-Security-Policy hash.
- **Reproducible output.** Exporting the same scene twice gives byte-identical PPTX files.

## Quick start

Run the commands from the repository root; the package does not need to be installed. `validate` prints every error and warning as JSON and exits with status 1 when there are errors. `init --lang en-US` writes a small English starter deck (without `--lang`, the starter is in Traditional Chinese).

```sh
git clone https://github.com/pop310289/open-slide-py
cd open-slide-py
python3 -m open_slide_py init /path/to/deck.json --lang en-US
python3 -m open_slide_py validate /path/to/deck.json
python3 -S -m open_slide_py export /path/to/deck.json /path/to/deck.pptx
python3 -S -m open_slide_py export /path/to/deck.json /path/to/deck.html
python3 -S -m open_slide_py export /path/to/deck.json /path/to/player.html --interactive
python3 -S -m open_slide_py export /path/to/deck.json /path/to/slide-1.svg --slide 1
python3 examples/build_good_slides.py --theme light-red /path/to/good-slides.json
```

The last line builds the six-slide English example "How to make good slides" with the kit; `examples/good-slides.json` is the same deck in the dark palette.

## Scene format

```json
{
  "schema_version": 1, "id": "hello", "title": "Hello", "width": 1920, "height": 1080, "lang": "en-US",
  "slides": [
    {"id": "s1", "title": "Cover", "background": "#142F37", "notes": "Say hello.",
     "elements": [
       {"id": "t1", "type": "text", "x": 120, "y": 420, "width": 1680, "height": 160,
        "text": "Hello, open-slide-py", "font_size": 96, "bold": true, "color": "#FFFFFF"}
     ]}
  ]
}
```

- Element types: `text`, `rect`, `ellipse`, `line` and `image` (PNG, JPEG or GIF, referenced by a relative path inside the JSON file's folder).
- Coordinates and font sizes are in canvas pixels. In PPTX one pixel is 0.5 pt, so a 1920×1080 canvas becomes a 13.33×7.5 in slide.
- Set a top-level `lang` (for example `en-US`) for decks that are not in Chinese. It sets the PowerPoint proofing language and the HTML `lang`, and switches the static HTML labels and the player controls to English. Decks without `lang` keep the original Traditional Chinese defaults (`zh-TW` in PPTX, `zh-Hant` in HTML).

The full reference, including the style fields, the warnings and the Python API, is [references/scene.md](references/scene.md); how to write a deck that reads well is in [references/authoring.md](references/authoring.md).

## Writing a deck in Python

```python
from open_slide_py.kit import Kit
kit = Kit("light-red")  # or "dark-orange", or your own palette dict
head, top = kit.header(1, "WHY IT MATTERS", "Meetings cost the team 8 hours a week", "Example numbers.")
chart, end = kit.bar_chart("hours", kit.left, top, 1200, [("Status meeting", 8), ("Written update", 1.3)], unit=" h")
slide = kit.slide(1, "Cost", head + chart, notes="Eight people, one hour each.")
deck = kit.deck("my-deck", "My deck", [slide])
```

Text boxes come out exactly as tall as their wrapped lines, colours come from the palette, and `kit.check(slide)` reports text that leaves its card or crosses the margins.

## Use as an agent skill

Clone or link the repository into a folder named `open-slide-py`, so that the folder matches the skill name:

| Agent | User-level location |
| --- | --- |
| Claude Code | `~/.claude/skills/open-slide-py/` |
| Codex | `~/.agents/skills/open-slide-py/` |
| OpenCode | `~/.config/opencode/skills/open-slide-py/` |

In a comparison on a five-slide English deck (one run each, October 2026), Claude Code and Codex both produced complete decks with this skill. A small local model (Qwen3 8B in OpenCode) did not.

## Quality

The maintainers run 127 tests (macOS, Python 3.14 and 3.9) before each update, plus an export check that runs exactly the files in this repository and a check that keeps this English documentation in step with the original Chinese documents. The tests are not included here; this repository contains only what you need to make slides.

## Known limitations

- Opening, editing and re-saving the PPTX in PowerPoint or Keynote has not been verified, and neither has Windows font substitution. The PPTX files were checked with GenOffice, which is not PowerPoint.
- Fonts are declared, not embedded, so the device that opens the file decides the actual glyphs.
- PowerPoint wraps PPTX text itself, so its line breaks may differ slightly from the SVG and HTML exports; `--fixed-lines` keeps them identical, but then edited text does not re-wrap.
- Warnings are estimates; look at the real rendering before you call a deck done.
- A `line` runs from the top-left to the bottom-right corner of its box; the other diagonal cannot be drawn.
- PowerPoint has no background blur, so frosted glass is approximated with translucent fills, thin borders and glow.
- There is no PPTX import, video, Morph transition or native PDF writer. To get a PDF, print the HTML.

## Origin and license

open-slide-py ports the behavior and design concepts of [open-slide](https://github.com/open-slide/open-slide), Copyright (c) 2026 Yiwei Ho, released under the MIT License (see [LICENSE-UPSTREAM](LICENSE-UPSTREAM)). open-slide-py itself is released under the MIT License (see [LICENSE](LICENSE)).
