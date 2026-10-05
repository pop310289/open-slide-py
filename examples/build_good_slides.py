#!/usr/bin/env python3
"""Build the six-slide English example deck "How to make good slides" with the kit, in either theme.

usage (from the skill folder):  python3 examples/build_good_slides.py [--theme dark-orange|light-red] [OUT.json]
Then: python3 -m open_slide_py validate OUT.json, and export it to .pptx / .html as usual.
"""
import argparse
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_slide_py.kit import THEMES, Kit, bottom  # noqa: E402
from open_slide_py.model import validate_deck  # noqa: E402

HOOK = "Ever watched a speaker read every slide aloud?"
HABITS = ["One message per slide", "Less text, more meaning", "Easy to see from the back", "Check before you present"]
NOTES = [
    ('Have you ever watched a speaker read every slide aloud, word for word? It is hard to keep listening. If this is your '
     'first presentation at work, the most useful idea to hold on to is this: your audience came to hear you, and the slides'
     ' are there to help them follow you. A slide is not a document and it is not your script. In the next four slides we '
     'will cover four habits: one message per slide, less text, slides that are easy to see, and a short check before you '
     'present. Each one takes minutes, not hours.'),
    ('Habit one: give every slide a single job. The easiest way is to write the title as a short sentence that states your '
     "point. Compare the two cards. 'Q3 Sales' is only a topic, so people must work out what matters. 'Q3 sales grew because"
     " of new clients' tells them the conclusion immediately, and the rest of the slide becomes evidence. This is an "
     'invented example, not real data. A useful test: read only your slide titles from start to finish. If they tell your '
     'story on their own, your structure is working. If one slide needs two titles, split it into two slides. Once each '
     'slide has one message, how much text should it carry?'),
    ('Habit two: cut the text. When a slide is full of sentences, people start reading and stop listening. On the left is '
     'the typical first draft: everything we know, in paragraphs. On the right is the same update reduced to one headline '
     'and three short phrases. The date and percentage are an invented example. Nothing is lost: the details move into your '
     'speaker notes, so you still have them when you speak, or into a handout or email you send afterwards. About three '
     'short points per slide is a guideline, not a law. The real goal is that people can take in the slide in a few seconds '
     'and then look back at you. With less text on the slide, how do you make what is left easy to see?'),
    ('Habit three: design for the person in the last row, or the colleague watching on a small laptop screen in a video '
     'call. Big text: a common rule of thumb is to keep body text at 24 points or larger. If you need smaller text to fit '
     'everything, that is a sign to cut or split the slide. Notice the small grey line in the first column: that is what '
     'tiny text looks like from the back. Strong contrast: dark text on a light background, or light on dark. Grey on grey '
     'and text over busy photos are hard to read, especially on projectors. Same layout: pick one font and two or three '
     'colors, and keep titles in the same place on every slide. Consistency lets people stop noticing the design and focus '
     'on the content. If your company has a slide template, use it; it already solves most of this. Last question: how do '
     'you know the deck is ready?'),
    ('Habit four: before the meeting, run through this five-point list. First, read your titles in order: does each one '
     'state a single message? Second, scan for text-heavy slides and move the details into your notes. Third, show the deck '
     'at full screen and step back from your monitor, or ask a colleague, to check it can be read. Fourth, check that fonts,'
     ' colors and title positions are consistent. Finally, practice out loud at least once with a timer. Saying it aloud '
     'shows you where slides are unclear and whether you fit your time slot. So what do the four habits add up to?'),
    ('To sum up the four habits: one message per slide, so each title states your point; about three short points, with the '
     'details in your notes; big text, strong contrast and the same layout, so the last row can read it; and a five-minute '
     'check before you present, including one practice out loud. Remember the speaker who read every slide aloud? Clear '
     'slides plus a practiced story is what makes a first presentation feel confident, and that speaker will not be you. '
     'Thank you, and good luck.'),
]


def build(theme):
    k = Kit(theme)
    left, width = k.left, k.content_width
    slides = []

    # 1 · Cover: a hook question, the claim that answers it, then the four habits as a row of cards.
    cover = [k.text("label1", left, 84, 1100, "YOUR FIRST WORK PRESENTATION", k.label, color="accent", bold=True),
             k.rule("rule1", left, 136, 420, opacity=0.6, width=2), k.text("hook1", left, 172, width, HOOK, 52, font=k.serif, color="muted")]
    cover.append(k.text("title1", left, bottom(cover[-1]) + 16, width, "Your slides support you.\nThey don't replace you.", 88,
                        font=k.serif, accent=["support you"]))
    top = bottom(cover[-1]) + 92
    cover.append(k.text("roadmap", left, top, 600, "FOUR HABITS", k.label, color="muted", bold=True))
    cw = (width - 3 * 32) // 4
    for i, habit in enumerate(HABITS):
        x, y = left + i * (cw + 32), top + 56
        name = k.text(f"habit{i + 1}", x + 36, y + 116, cw - 72, habit, 44, font=k.serif)
        cover += [k.card(f"habit{i + 1}-card", x, y, cw, bottom(name) - y + 40), *k.badge(f"habit{i + 1}-no", x + 36, y + 36, f"0{i + 1}"), name]
    slides.append(k.slide(1, "Slides support you", cover, NOTES[0]))

    # 2 · Habit 1: a topic title next to a message title; the message card is the focal one.
    head, top = k.header(2, "HABIT 1 OF 4", "One slide, one message", "Write the title as the point you want people to remember.")
    half = (width - 40) // 2
    body = []
    for key, x, label, example, size, marks, note, focal in (
            ("weak", left, "WEAK: A TOPIC", "Q3 Sales", 64, [], "People must guess what matters.", False),
            ("strong", left + half + 40, "STRONG: A MESSAGE", "Q3 sales grew because of new clients", 56, ["because of new clients"],
             "The point is clear before you speak.", True)):
        body += [k.text(f"{key}-label", x + 48, top + 44, half - 96, label, k.label, color="accent" if focal else "muted", bold=True),
                 k.text(f"{key}-title", x + 48, top + 96, half - 96, example, size, font=k.serif, accent=marks),
                 k.rule(f"{key}-rule", x + 48, top + 268, color="accent" if focal else "neutral", opacity=1.0 if focal else 0.35),
                 k.text(f"{key}-note", x + 48, top + 300, half - 96, note, color="ink" if focal else "muted")]
    card_h = max(bottom(e) for e in body if e["type"] == "text") - top + 44
    body = [k.card("weak-card", left, top, half, card_h), k.card("strong-card", left + half + 40, top, half, card_h, focal=True)] + body
    test = k.text("test", left, top + card_h + 40, width, "Quick test: if people read only your slide titles, do they get your story?",
                  accent=["read only your slide titles"])
    slides.append(k.slide(2, "One slide, one message", head + body + [test], NOTES[1]))

    # 3 · Habit 2: a wall of text becomes one headline and three short points.
    head, top = k.header(3, "HABIT 2 OF 4", "Less text, more meaning", "People either read or listen. A wall of text makes them read.")
    left_w, arrow_w = 680, 160
    right_x, right_w = left + left_w + arrow_w, width - left_w - arrow_w
    after = [k.text("after-label", right_x + 56, top + 48, right_w - 112, "AFTER: ONE CLEAR POINT", k.label, color="accent", bold=True),
             k.text("after-title", right_x + 56, top + 104, right_w - 112, "Launch moves to May 12 to finish testing", 52, font=k.serif,
                    accent=["May 12"])]
    y = bottom(after[-1]) + 28
    for i, (point, lead) in enumerate((("Testing: 80% done", "Testing:"), ("Risk: payment step", "Risk:"), ("Ask: one more tester", "Ask:"))):
        after += [{"id": f"after-dot{i + 1}", "type": "ellipse", "x": right_x + 56, "y": y + 18, "width": 14, "height": 14, "fill": k.theme["accent"]},
                  k.text(f"after-b{i + 1}", right_x + 92, y, right_w - 148, point, strong=[lead])]
        y = bottom(after[-1]) + 8
    card_h = y - top + 36
    before = [k.text("before-label", left + 48, top + 48, left_w - 96, "BEFORE: EVERYTHING ON THE SLIDE", k.label, color="muted", bold=True),
              k.text("before-title", left + 48, top + 104, left_w - 96, "Project update", 40, font=k.serif, color="muted")]
    widths = itertools.cycle([560, 500, 548, 440, 560, 480, 530, 420])
    lines_top = bottom(before[-1]) + 24
    before += [k.pill(f"before-line{i + 1}", left + 48, lines_top + i * 34, next(widths)) for i in range((top + card_h - 44 - lines_top) // 34 + 1)]
    arrow = k.text("arrow", left + left_w, top + card_h // 2 - 50, arrow_w, "→", 80, color="accent", align="center")
    body = [k.card("before-card", left, top, left_w, card_h), *before, arrow, k.card("after-card", right_x, top, right_w, card_h, focal=True), *after]
    aim = k.text("aim", left, top + card_h + 40, width, "Aim for about 3 short points. Details go in your speaker notes.", accent=["3 short points"])
    slides.append(k.slide(3, "Less text, more meaning", head + body + [aim], NOTES[2]))

    # 4 · Habit 3: three cards, each a demonstration over its one tip. The weak examples are deliberate.
    head, top = k.header(4, "HABIT 3 OF 4", "Make it easy to see from the back", "Big text, strong contrast and a consistent layout.")
    cw = (width - 2 * 40) // 3
    xs = [left + i * (cw + 40) for i in range(3)]
    inner, demo_top = cw - 96, top + 128
    weak_fill, weak_text = k.theme["weak"]
    demos = [
        [k.text("size-big", xs[0] + 48, demo_top, inner, "Readable", 72, bold=True),
         k.text("size-small", xs[0] + 48, demo_top + 104, inner, "Too small to read from far away", 22, color="muted", ignore_warnings=["small_text"])],
        [{"id": "good-swatch", "type": "rect", "x": xs[1] + 48, "y": demo_top, "width": inner, "height": 72, "radius": 12, "fill": k.theme["ink"]},
         k.text("good-text", xs[1] + 72, demo_top + 14, inner - 48, "Dark vs light: clear", 36, color="bg", bold=True),
         {"id": "bad-swatch", "type": "rect", "x": xs[1] + 48, "y": demo_top + 88, "width": inner, "height": 72, "radius": 12, "fill": weak_fill},
         k.text("bad-text", xs[1] + 72, demo_top + 102, inner - 48, "Grey on grey: weak", 36, color=weak_text, bold=True, ignore_warnings=["low_contrast"])],
        [*[part for n in range(2) for part in (
            {"id": f"grid{n + 1}", "type": "rect", "x": xs[2] + 48 + n * (inner // 2 + 8), "y": demo_top, "width": inner // 2 - 8, "height": 116,
             "radius": 10, "stroke": k.theme["neutral"], "stroke_opacity": 0.3, "stroke_width": 2},
            k.pill(f"grid{n + 1}-title", xs[2] + 64 + n * (inner // 2 + 8), demo_top + 16, inner // 2 - 72, h=16, opacity=0.85),
            k.pill(f"grid{n + 1}-line1", xs[2] + 64 + n * (inner // 2 + 8), demo_top + 52, inner // 2 - 56, h=10, opacity=0.25),
            k.pill(f"grid{n + 1}-line2", xs[2] + 64 + n * (inner // 2 + 8), demo_top + 74, inner // 2 - 96, h=10, opacity=0.25))],
         k.text("grid-caption", xs[2] + 48, demo_top + 128, inner, "Titles always in the same spot", 36, color="muted")],
    ]
    columns = [("Big text", "Keep body text at 24 pt or larger. Make titles bigger.", ["24 pt or larger"]),
               ("Strong contrast", "Avoid text on busy photos. Use color to highlight, not to decorate.", []),
               ("Same layout", "One font, two or three colors, and aligned edges on every slide.", [])]
    tip_top = max(bottom(e) for demo in demos for e in demo) + 36
    body = []
    for i, ((title, tip, marks), demo) in enumerate(zip(columns, demos)):
        body += [k.text(f"col{i + 1}-head", xs[i] + 48, top + 44, inner, title, 48, font=k.serif), *demo,
                 k.rule(f"col{i + 1}-rule", xs[i] + 48, tip_top - 18, color="accent" if i == 0 else "neutral", opacity=1.0 if i == 0 else 0.35),
                 k.text(f"col{i + 1}-tip", xs[i] + 48, tip_top, inner, tip, accent=marks)]
    card_h = max(bottom(e) for e in body if e["type"] == "text") - top + 40
    body = [k.card(f"col{i + 1}", xs[i], top, cw, card_h, focal=(i == 0)) for i in range(3)] + body
    slides.append(k.slide(4, "Make it easy to see", head + body, NOTES[3]))

    # 5 · Habit 4: the five-point check.
    head, top = k.header(5, "HABIT 4 OF 4", "Check before you present", "A five-minute check catches the most common problems.")
    checks = ["Each title states one message", "About 3 short points per slide, details in notes", "Text is readable at full screen from a few steps back",
              "One font, two or three colors, aligned layout", "Practice out loud at least once, with a timer"]
    pitch = 88
    body = [k.card("check-card", left, top, width, len(checks) * pitch + 40)]
    for i, item in enumerate(checks):
        y = top + 28 + i * pitch
        if i:
            body.append(k.rule(f"check-sep{i + 1}", left + 48, y + (68 - pitch) // 2, width - 96, color="neutral", opacity=0.08, width=2))
        body += [*k.badge(f"check-no{i + 1}", left + 48, y + 6, f"0{i + 1}"), k.text(f"check{i + 1}", left + 168, y + 10, width - 216, item)]
    slides.append(k.slide(5, "Check before you present", head + body, NOTES[4]))

    # 6 · Summary: the cover's claim again, each habit with one action, and the closing line in the focal card.
    head, top = k.header(6, "SUMMARY", "Your slides support you", "Four habits, one action each.", accent=["support you"])
    actions = ["Write each title as the point.", "About 3 short points per slide.", "Big text, contrast, one layout.", "Run the check; practice out loud."]
    half = (width - 40) // 2
    card_h = 120 + max(k.text("probe", 0, 0, half - 80, a)["height"] for a in actions) + 36
    body, cards = [], []
    for i, (habit, action) in enumerate(zip(HABITS, actions)):
        x, y = left + (i % 2) * (half + 40), top + (i // 2) * (card_h + 32)
        cards.append(k.card(f"sum-card{i + 1}", x, y, half, card_h))
        body += [*k.badge(f"sum-no{i + 1}", x + 40, y + 36, f"0{i + 1}"),
                 k.text(f"sum-habit{i + 1}", x + 148, y + 38, half - 188, habit, 40, font=k.serif, ignore_warnings=["repeated_text"]),
                 k.text(f"sum-action{i + 1}", x + 40, y + 120, half - 80, action, color="muted")]
    close_top = top + 2 * card_h + 32 + 32
    close = k.text("close", left + 48, close_top + 28, width - 96, "Clear slides + a practiced story = a confident first presentation.", 48,
                   font=k.serif, accent=["a confident first presentation"])
    body += [k.card("close-card", left, close_top, width, bottom(close) - close_top + 24, focal=True), close]
    slides.append(k.slide(6, "Summary", head + cards + body, NOTES[5]))

    deck = k.deck("good-slides", "How to Make Good Presentation Slides", slides)
    problems = [p for s in slides for p in k.check(s)] + [f'{d["path"]}: {d["code"]}' for d in validate_deck(deck)]
    if problems:
        raise SystemExit("layout problems: " + "; ".join(problems))
    return deck


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--theme", choices=sorted(THEMES), default="dark-orange")
    parser.add_argument("output", nargs="?", type=Path, default=Path(__file__).with_name("good-slides.json"))
    args = parser.parse_args()
    args.output.write_text(json.dumps(build(args.theme), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(args.output)
