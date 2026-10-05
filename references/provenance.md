# Provenance and scope

open-slide-py reimplements the behaviour and design concepts of open-slide (by Yiwei Ho, MIT licence, see `LICENSE-UPSTREAM`) with the Python standard library. It is not an official version of open-slide, and it is unrelated to the OpenSlide whole-slide imaging library (`openslide-python`). This project is released under the MIT licence (see `LICENSE`).

## What is included

- `open_slide_py/`: the scene model and validation, layout warnings, the PPTX, SVG, static HTML and interactive player exports, the player's CSS and JS, the font width tables (`metrics.py`) and the kit (`kit.py`).
- `examples/demo.json`: a three-slide demo in Traditional Chinese. `examples/build_good_slides.py` and `examples/good-slides.json`: a six-slide English example written with the kit (`--theme` picks either palette).
- The width tables are advance widths per 1000 em read from the macOS font files: numbers only, no glyph outlines. The metric-compatible open fonts (Liberation, Arimo, Tinos, Cousine, Gelasio) have the same widths.
- Not included: the upstream React/Node version's adapters, case outputs, deployment scripts and comparison tools. There is no visual editor; edit the JSON directly.
- The maintainers keep the tests and check scripts separately and run them before each update; they are not published here.

## Verified and not verified

- Verified (macOS, Python 3.14 and 3.9): 127 tests; all four formats export under `python3 -S`; exporting the same scene twice gives byte-identical PPTX files; PPTX keeps every slide's text and speaker notes; the static HTML contains no JavaScript.
- Widths: against 580 English lines measured by Chrome with the real fonts, the tables have a mean error of 0.1% and underestimate by at most 0.045%; the earlier font-independent estimate had a mean error of 10.0% and underestimated every line in capitals.
- A second PPTX renderer: GenOffice 0.11.0 `slides audit` and `slides render` found no layout issues in the six-slide example in both palettes, with PowerPoint wrapping and with `--fixed-lines`, and drew the glow, shadows and gradients; with PowerPoint wrapping, no wrapped paragraph ends with a lone word (10 wrapped paragraphs in the two examples; 4 did before this was fixed). It is not PowerPoint.
- Not verified: opening, editing, saving and reopening in PowerPoint or Keynote; Windows font substitution and layout; touch on a physical phone. Fonts are declared, not embedded, so the device that opens the file decides the actual glyphs.
- Known limitations: a `line` runs only from the top-left to the bottom-right corner of its box; PowerPoint wraps PPTX text itself by default, so line breaks may differ slightly from SVG and HTML (`--fixed-lines` keeps them identical, but then edited text does not re-wrap); warnings are estimates and the real rendering still has the last word; there is no PPTX import, video, Morph transition or native PDF writer (print the HTML to get a PDF).
