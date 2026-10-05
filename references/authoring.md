# Authoring and layout

For each slide, first define the one point the reader should understand, then choose native text, shapes, lines or images that explain it. Numbers, units, periods and sources in data charts must be checkable; for new research findings, check the primary source rather than inheriting scores or performance claims from the examples.

## Storyline

Write the storyline before laying anything out:

1. Each slide title is a one-line conclusion: at most about 8 English words or 16 Chinese characters (a rule of thumb; adjust to the topic). Write the conclusion, not the topic ("Q3 sales grew because of new clients", not "Q3 sales"). The titles alone should carry the main line; the details of the story go into the slide order, transitions and speaker notes, not into the titles. Outside the cover, a title that wraps needs cutting.
2. Open with a hook: the first slide starts with a question, contrast or concrete situation the audience recognises, so the main claim that follows answers it; do not open with "Welcome" or an agenda. The last slide or its notes call back to the hook.
3. Choose one structure: answer the reader's questions in order, or "problem → turn → solution → evidence → action". Include one turn the reader did not expect, and state one limitation honestly.
4. Carry one example through the whole deck. Keep the timeline consistent; if it jumps, say so on the slide, not only in the notes.
5. Link the slides: end each slide's notes with a question that the next slide answers.
6. Close: the last slide summarises the points listed at the start, with one takeaway action per point, and its title or notes call back to the opening hook. Do not end on a bare "Summary" or "Thank you", and do not repeat earlier slides word for word.
7. Swap test: if the middle slides could be swapped without losing anything, you have a list, not a story; reorder them so that each slide uses the result of the one before.

## Word budget

- About three short points per slide besides the title; a checklist slide may have more, one line each. Prefer phrases to full sentences.
- Reasoning, details and the sources of numbers go into the speaker notes; the slide keeps only what the audience should remember.
- Do not repeat a sentence on two slides; a footer line should add something new (a test, a rule), not restate the title. `validate` warns about sentences below 18 pt and sentences repeated across slides.
- When it does not fit, cut words or split the slide; do not shrink the font.

## Key-point cards and emphasis

- Use cards for 2–4 parallel points on a slide: one point per card, at most four, all the same size and spacing.
- Inside a card, top to bottom: a numbered label (01, 02) → a one-sentence heading → a short accent-coloured rule → one or two lines of explanation; icons or illustrations go to one side.
- Glass cards on a dark background: a rect with a white fill at `fill_opacity` 0.04–0.08, a thin border at `stroke_opacity` 0.15–0.3 and a `radius` of 24–40, optionally with a `gradient` fading from top left to bottom right; only the most important card gets a `glow`. The fields are under "Styles" in [Scene and API](scene.md).
- Cards on a light background: translucent white disappears on white, so use a white-to-light-grey (about `#F3F3F5`) `gradient`, a thin dark border (`stroke_opacity` 0.1–0.15) and a soft `shadow` (opacity about 0.1); the focal card gets an accent border and a faint glow (about 0.15).
- Emphasise only the real key words: use `highlights` to colour one or two phrases, never a whole sentence; at most one big number per slide; one accent colour per deck.
- Keep text and cards native and editable; use images only for illustrations, 3D logos and background textures, with alt text and sources.

## Colour

- Colour is a parameter: the program that writes the JSON first defines one palette (background, main text, secondary text, accent, a neutral colour for lines and borders, card gradient and border, shadow, and the focal card's border and glow), and elements refer only to its roles, never to literal colours; a new style is a new palette and a regenerated JSON. `THEMES` in `open_slide_py/kit.py` is that palette and `Kit("light-red")` applies it; when you add a palette, the tests check its text contrast.
- Text, accent text included, keeps at least 4.5:1 contrast with the background and with card fills; only deliberate "low contrast" examples are exempt.
- Two tested palettes (the same six-slide deck, October 2026):

| Role | Dark orange | White red |
|---|---|---|
| Background | `#0E0F12` | `#FFFFFF` |
| Main text | `#EDE7DF` (15.6:1) | `#1B1B1F` (17.2:1) |
| Secondary text | `#A9A39B` (7.7:1) | `#5F6368` (6.0:1) |
| Accent | `#FF7A3D` (7.4:1) | `#D0202E` (5.3:1 on white, 4.8:1 on cards) |
| Neutral (lines, borders) | `#FFFFFF` | `#1B1B1F` |
| Card | white gradient 0.10→0.03, border 0.18, no shadow | `#FFFFFF`→`#F3F3F5`, border 0.12, shadow 0.10 |
| Focal card | border 0.55, glow 0.28 | border 0.7, glow 0.16 |

## Layout

Write generators with `open_slide_py/kit.py`: text boxes are sized from real font widths, and cards, number badges, headers and bar charts follow the palette; see `examples/build_good_slides.py`. Afterwards check with `kit.check` (text leaving its card, elements past the margins) and `validate`.

Use one canvas, margins, type scale and set of colour roles throughout. On the standard 1920×1080 canvas, font sizes are in pixels and PPTX uses half as many points: 40 px is 20 pt. Footnotes meant for projection must be read at the real playback size; thumbnails and estimated widths are not enough. Leave room for line height in text boxes and keep text off the edges; put diagram labels next to the lines or structures they describe.

Keep the deck editable with native text and shapes. Quantitative charts can be built from rectangles, lines and text; images suit key visuals, photos and real screenshots, but never replace text and data with a whole-slide image. Image assets must live in the JSON's folder, with alt text, licence and source.

When editing an existing deck, keep slide and element ids, internal links and their relation to the notes. After adding slides or changing figures, recheck the related links, speaker notes and the story of the neighbouring slides. The examples only demonstrate the format; they are not evidence for cross-platform or application acceptance.
