"""Validate this standalone skill: core tests, content, four exports and determinism."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
def run(args, env=None, timeout=120):
    return subprocess.run([sys.executable, *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)


def normalize(text):
    return re.sub(r"\s+", "", text)


def content_check(path, deck):
    results = []
    with zipfile.ZipFile(path) as archive:
        if archive.testzip():
            raise ValueError("PPTX ZIP CRC failed")
        names = [p for p in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", p)]
        if len(names) != len(deck["slides"]):
            raise ValueError("Slide count differs from source")
        for i, slide in enumerate(deck["slides"], 1):
            def text(part):
                return "".join(e.text or "" for e in ET.fromstring(archive.read(part)).findall(".//a:t", NS))
            actual = text(f"ppt/slides/slide{i}.xml")
            expected = "".join(e.get("text", "") for e in slide["elements"])
            note_part = f"ppt/notesSlides/notesSlide{i}.xml"
            notes = text(note_part) if note_part in archive.namelist() else ""
            item = {"slide": i, "text_retained": normalize(actual) == normalize(expected), "notes_retained": normalize(notes) == normalize(slide.get("notes", ""))}
            if not item["text_retained"] or not item["notes_retained"]:
                raise ValueError(f"Source content mismatch on slide {i}")
            results.append(item)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gui", action="store_true", help="Enable actual Tcl/Tk GUI tests; requires wish and a display")
    parser.add_argument("--deck", type=Path, default=ROOT / "examples/demo.json")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/portable-validation.json")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["OPENSLIDE_GUI_TEST"] = "1" if args.gui else "0"
    tests = run(["-S", "-m", "unittest", "discover", "-s", "tests", "-v"], env)
    log = tests.stdout + tests.stderr
    args.output.with_suffix(".log").write_text(log, encoding="utf-8")
    count = re.search(r"Ran (\d+) tests?", log)
    skipped = re.search(r"skipped=(\d+)", log)
    report = {"schema_version": 1, "executed_at": datetime.now(timezone.utc).isoformat(), "gui_requested": args.gui, "test_exit_code": tests.returncode, "test_count": int(count[1]) if count else None, "skipped": int(skipped[1]) if skipped else 0, "python": sys.version, "platform": sys.platform, "checks": {}, "limits": ["Text and notes compare after whitespace normalization.", "This check does not replace independent Office schema validation, visual review or original-engine execution."]}
    report["inputs_sha256"] = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for folder in ("openslide_tk", "tests", "scripts", "examples")
        for path in sorted((ROOT / folder).rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }
    try:
        if tests.returncode:
            raise RuntimeError("Unit/integration tests failed; inspect the adjacent log")
        if args.gui and report["skipped"]:
            raise RuntimeError("Full GUI verification requested but some tests were skipped")
        deck_path = args.deck.resolve()
        deck = json.loads(deck_path.read_text(encoding="utf-8-sig"))
        report["source_sha256"] = hashlib.sha256(deck_path.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory(prefix="open-slide-release-") as temporary:
            destination = Path(temporary)
            hashes = []
            for i in range(2):
                if i:
                    time.sleep(2.1)
                output = destination / f"test-{i}.pptx"
                export = run(["-S", "-m", "openslide_tk", "export", str(deck_path), str(output)], dict(env, DISPLAY="", OPENSLIDE_WISH="/not-used"))
                if export.returncode:
                    raise RuntimeError(export.stderr or export.stdout)
                hashes.append(hashlib.sha256(output.read_bytes()).hexdigest())
            report["formats"] = {}
            for filename, extra in (("slide.svg", []), ("static.html", []), ("player.html", ["--interactive"])):
                output = destination / filename
                export = run(["-S", "-m", "openslide_tk", "export", str(deck_path), str(output), *extra], dict(env, DISPLAY="", OPENSLIDE_WISH="/not-used"))
                if export.returncode:
                    raise RuntimeError(export.stderr or export.stdout)
                content = output.read_text(encoding="utf-8")
                if filename.endswith(".html"):
                    if ("<script>" in content) != bool(extra):
                        raise RuntimeError("Static/interactive HTML script contract failed")
                    if content.count('<section ') != len(deck["slides"]):
                        raise RuntimeError("HTML slide count differs from source")
                else:
                    ET.fromstring(content)
                report["formats"][filename] = {"bytes": output.stat().st_size, "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
            report["checks"]["without_site_packages_all_four_formats"] = True
            report["checks"]["repeat_bytes_identical"] = hashes[0] == hashes[1]
            report["output_sha256"] = hashes[0]
            report["formats"]["deck.pptx"] = {"bytes": (destination / "test-0.pptx").stat().st_size, "sha256": hashes[0]}
            report["slides"] = content_check(destination / "test-0.pptx", deck)
            if hashes[0] != hashes[1]:
                raise RuntimeError("Repeat exports differ")
        report["passed"] = True
    except (OSError, ValueError, RuntimeError, KeyError, zipfile.BadZipFile, ET.ParseError, subprocess.SubprocessError) as exc:
        report["passed"] = False
        report["error"] = str(exc)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ["passed", "test_count", "skipped", "gui_requested", "error"]}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
