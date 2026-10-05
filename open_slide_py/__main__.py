import argparse
import json
from pathlib import Path
import sys


def starter_deck(lang=None):
    """A one-slide deck to edit: the original Chinese starter, or an English one for any other language tag."""
    if lang and not lang.lower().startswith("zh"):
        return {"schema_version": 1, "id": "my-deck", "title": "My deck", "width": 1920, "height": 1080, "lang": lang, "slides": [{"id": "welcome", "title": "Start here", "background": "#152c36", "notes": "Edit this JSON, check it with validate, then export it.", "elements": [{"id": "title", "type": "text", "x": 130, "y": 220, "width": 1660, "height": 180, "text": "open-slide-py", "font_family": "Arial", "font_size": 112, "bold": True, "color": "#ffffff"}, {"id": "body", "type": "text", "x": 140, "y": 470, "width": 1640, "height": 230, "text": "Offline slides, speaker notes and editable PowerPoint\nEdit this JSON, check it with validate, then export it", "font_family": "Arial", "font_size": 52, "color": "#97e8c8"}]}]}
    return {"schema_version": 1, "id": "my-deck", "title": "我的簡報", "width": 1920, "height": 1080, "slides": [{"id": "welcome", "title": "開始製作", "background": "#152c36", "notes": "修改這份 JSON 後，用 validate 檢查、用 export 匯出。", "elements": [{"id": "title", "type": "text", "x": 130, "y": 220, "width": 1660, "height": 180, "text": "open-slide-py", "font_family": "Arial", "font_size": 112, "bold": True, "color": "#ffffff"}, {"id": "body", "type": "text", "x": 140, "y": 470, "width": 1640, "height": 230, "text": "離線簡報、講者備註與可編輯 PowerPoint\n修改這份 JSON，再用 validate 檢查、export 匯出", "font_family": "Arial", "font_size": 52, "color": "#97e8c8"}]}]}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m open_slide_py", description="open-slide-py: JSON slide scenes to editable PPTX, SVG and offline HTML")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Create a new deck")
    init.add_argument("output", type=Path)
    init.add_argument("--lang", help="Language tag such as en-US; any non-Chinese tag starts an English deck")
    validate = sub.add_parser("validate", help="Check schema, geometry, assets and text bounds")
    validate.add_argument("deck", type=Path)
    export = sub.add_parser("export", help="Export editable PPTX, SVG, or offline HTML")
    export.add_argument("deck", type=Path)
    export.add_argument("output", type=Path)
    export.add_argument("--slide", type=int, default=1, help="1-based slide for SVG")
    export.add_argument("--interactive", action="store_true", help="Add the native offline player (HTML only)")
    export.add_argument("--fixed-lines", action="store_true", help="PPTX only: keep the SVG/HTML line breaks instead of letting PowerPoint wrap")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            from .storage import save_deck
            from .model import LANG_RE
            if args.output.exists():
                parser.error(f"File already exists: {args.output}")
            if args.lang is not None and (len(args.lang) > 35 or not LANG_RE.fullmatch(args.lang)):
                parser.error("--lang must be a language tag such as en-US")
            save_deck(args.output, starter_deck(args.lang))
            print(args.output.resolve())
        elif args.command == "validate":
            from .model import read_deck, validate_deck
            # Report every error and warning as JSON; load_deck would stop at the first invalid scene.
            diagnostics = validate_deck(read_deck(args.deck), args.deck.parent)
            print(json.dumps(diagnostics, ensure_ascii=False, indent=2))
            return int(any(d["severity"] == "error" for d in diagnostics))
        elif args.command == "export":
            from .model import load_deck
            extension = args.output.suffix.lower()
            if args.interactive and extension != ".html":
                parser.error("--interactive requires an .html output")
            if args.fixed_lines and extension != ".pptx":
                parser.error("--fixed-lines requires a .pptx output")
            deck = load_deck(args.deck)
            if extension == ".pptx":
                from .pptx import export_pptx
                export_pptx(deck, args.output, args.deck.parent, reflow=not args.fixed_lines)
            elif extension == ".html":
                from .export import export_html
                export_html(deck, args.output, args.deck.parent, interactive=args.interactive)
            elif extension == ".svg":
                from .export import export_svg
                export_svg(deck, args.slide - 1, args.output, args.deck.parent)
            else:
                parser.error("Output extension must be .pptx, .svg, or .html")
            print(args.output.resolve())
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, IndexError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
