---
name: open-slide-py
description: Create or edit slide decks as scene JSON with open-slide-py (a Python standard-library port of open-slide) and export editable PPTX, SVG, static HTML or an offline web player. Use for "make slides or a presentation with OpenSlide", "export to PowerPoint" or "turn the deck into a phone-friendly web page". Not for importing existing PPTX files, comparing with the original open-slide, or deploying services.
---

# open-slide-py native slides

This skill only creates, edits and checks native slide decks. The folder holds the whole runtime and works when copied on its own; it needs only the Python 3.10+ standard library, with nothing to install. There is no visual editor: edit the scene JSON directly. Run every command below from this skill's root folder, with absolute output paths in the user's project.

## Workflow

1. Write the storyline first: from the audience, content and purpose, give each slide a one-line conclusion as its title, so the titles alone carry the main line, and put the details into the slide order, transitions and speaker notes. Open the first slide with a hook (a question, a contrast or a situation) and end with a takeaway that calls back to the opening; keep about three short points per slide besides the title. Use cards for parallel points and colour only the key words; keep colours in one palette instead of writing them into elements. See "Storyline", "Word budget", "Key-point cards and emphasis" and "Colour" in [Authoring and layout](references/authoring.md). When editing, work from the existing JSON; never rebuild an output and pass it off as the original.
2. Start with `python3 -m open_slide_py init /path/to/my-deck.json` (add `--lang en-US` for an English deck), or copy `examples/demo.json` into the new project. For more than a few slides, or for cards and charts, write a generator with `open_slide_py/kit.py`: text boxes are sized from real font widths, colours come from the palette and bar charts start at zero; see `examples/build_good_slides.py`. A deck that is not in Chinese needs a top-level language tag such as `"lang": "en-US"` (see "Language" in [Scene and API](references/scene.md)). Keep images in the same project folder as the JSON.
3. Validate, then export the formats you need. `validate` must report zero errors; handle every warning (text overflow, overlap, low contrast, small sentences, sentences repeated across slides), and mark a deliberate exception with `ignore_warnings` on the element and say why (see "Warnings" in [Scene and API](references/scene.md)). PowerPoint wraps PPTX text itself by default; add `--fixed-lines` to keep exactly the line breaks of the web exports. Keep the scene JSON and assets, and use native elements for text, data charts and geometric diagrams.
4. Check the real outputs as described in [Verification](references/verification.md). Report tests, visual checks, device interaction and Office round trips separately; only checks rerun this time may be called passed.

```sh
python3 -m open_slide_py validate /path/to/my-deck.json
python3 -S -m open_slide_py export /path/to/my-deck.json /path/to/my-deck.pptx
python3 -S -m open_slide_py export /path/to/my-deck.json /path/to/reading.html
python3 -S -m open_slide_py export /path/to/my-deck.json /path/to/player.html --interactive
```

## Contracts to keep

- The core and the authoring scripts use only the Python standard library. Do not bring in React, ReactDOM, Next.js or JSX/TSX, and do not wrap React in an embedded browser. Native `.js` only handles web interaction; Python exports never need Node.
- The default HTML is static and contains no JavaScript; `--interactive` uses the bundled native player. Keep regression coverage for both. Scene text and notes are escaped text or SVG and never run through `innerHTML`; the interactive version's inline CSS and JS are pinned by CSP hashes computed from the content (the static version sets no CSP meta).
- `font_family` and `east_asian_font` each name one font. PPTX writes the Latin and East Asian faces separately; the CSS fallback is for HTML and SVG only. Declaring a font is not embedding it, substituting it or verifying it on Windows.
- Keep atomic writes, input validation and never overwriting the original on failure. After changing the runtime, recheck the content and rendering of new outputs.

## Scope and maintenance

PPTX has no web step-by-step animation. For a PDF, print the HTML or convert with an Office application; there is no native PDF writer. Arbitrary PPTX import, video, Morph and full browser CSS are not supported.

This skill deploys nothing and changes no service or route. It does not include the upstream React version's adapters, cases or deployment scripts. The relationship with the upstream open-slide, what is included, and what is and is not verified are in [Provenance and scope](references/provenance.md).
