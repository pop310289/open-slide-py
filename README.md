# open-slide-py

A Python standard-library and Tcl/Tk port of [open-slide](https://github.com/open-slide/open-slide). Write a slide deck as a JSON scene, then export it as an editable PowerPoint file (PPTX), SVG, a static HTML reading version or an offline interactive player. The repository is also an agent skill (`SKILL.md`) for Claude Code, Codex and OpenCode.

> **Status: preview (0.1.0).** This is an unofficial port. It is not affiliated with the open-slide project, and it is unrelated to the OpenSlide whole-slide imaging library.

## Features

- **No dependencies.** Validation and export use only the Python 3.10+ standard library. The desktop editor additionally needs Tcl/Tk 8.6+ (`wish`). macOS ships Tcl/Tk 8.5 in `/usr/bin`, which is too old and is skipped automatically; install a newer one (for example `brew install tcl-tk`) or point `OPENSLIDE_WISH` at a `wish` 8.6+.
- **Editable PPTX.** Text, rectangles, ellipses, lines and images become native PowerPoint objects, and speaker notes are kept.
- **Two HTML outputs.** The default HTML is static and contains no JavaScript. `--interactive` adds an offline player with keyboard and touch navigation, step-by-step reveal, a slide index, speaker notes and a timer; its inline CSS and JavaScript are pinned by a Content-Security-Policy hash.
- **Validation before export.** Schema, geometry, image assets and an estimate of text overflow are checked. An invalid deck never overwrites an existing output file.
- **Reproducible output.** Exporting the same scene twice gives byte-identical PPTX files.

## Quick start

Run the commands from the repository root; the package does not need to be installed. `validate` prints every error and warning as JSON and exits with status 1 when there are errors. `init` writes a small Traditional Chinese sample deck; for an English start, copy the example under *Scene format*.

```sh
git clone https://github.com/pop310289/open-slide-py
cd open-slide-py
python3 -m openslide_tk init /path/to/deck.json
python3 -m openslide_tk validate /path/to/deck.json
python3 -S -m openslide_tk export /path/to/deck.json /path/to/deck.pptx
python3 -S -m openslide_tk export /path/to/deck.json /path/to/deck.html
python3 -S -m openslide_tk export /path/to/deck.json /path/to/player.html --interactive
python3 -S -m openslide_tk export /path/to/deck.json /path/to/slide-1.svg --slide 1
python3 -m openslide_tk view /path/to/deck.json   # Tk desktop editor
```

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
- Set a top-level `lang` (for example `en-US`) for decks that are not in Chinese. It sets the PowerPoint proofing language and the HTML `lang`, and switches the static HTML labels to English. Decks without `lang` keep the original Traditional Chinese defaults (`zh-TW` in PPTX, `zh-Hant` in HTML).

The full reference is [references/scene.md](references/scene.md). The detailed documentation (`SKILL.md` and `references/`) is written in Traditional Chinese.

## Use as an agent skill

Clone or link the repository into a folder named `open-slide-py`, so that the folder matches the skill name:

| Agent | User-level location |
| --- | --- |
| Claude Code | `~/.claude/skills/open-slide-py/` |
| Codex | `~/.agents/skills/open-slide-py/` |
| OpenCode | `~/.config/opencode/skills/open-slide-py/` |

In a comparison on a five-slide English deck (one run each, October 2026), Claude Code and Codex both produced complete decks with this skill. A small local model (Qwen3 8B in OpenCode) did not.

## Tests

```sh
python3 -S -m unittest discover -s tests
python3 scripts/verify_skill.py --output /tmp/open-slide-py-verification.json
```

Some tests are skipped when their tools are missing: four open real Tk windows and run only with `OPENSLIDE_GUI_TEST=1` (`verify_skill.py --gui` sets it), the Tcl bridge tests need Tcl 8.6+, and two optional tests check the player's JavaScript with Node.js. `verify_skill.py` runs the tests, exports all four formats with `python3 -S` and checks the slide text, the notes and repeated exports.

## Known limitations

- Opening, editing and re-saving the PPTX in PowerPoint or Keynote has not been verified, and neither has Windows font substitution.
- Fonts are declared, not embedded, so the device that opens the file decides the actual glyphs.
- The interactive player's controls, the desktop editor and the `init` sample deck are in Traditional Chinese.
- PPTX text is broken into lines in advance (one paragraph per line, no automatic wrapping), so every renderer breaks lines in the same place, but PowerPoint does not reflow the text when you edit it.
- A `line` runs from the top-left to the bottom-right corner of its box; the other diagonal cannot be drawn.
- `validate` estimates text overflow but does not detect overlapping text boxes.
- There is no PPTX import, video, Morph transition or native PDF writer. To get a PDF, print the HTML.

## Origin and license

open-slide-py ports the behavior and design concepts of [open-slide](https://github.com/open-slide/open-slide), Copyright (c) 2026 Yiwei Ho, released under the MIT License (see [LICENSE-UPSTREAM](LICENSE-UPSTREAM)). open-slide-py itself is released under the MIT License (see [LICENSE](LICENSE)).
