import base64
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import time

from .model import load_deck, resolve_image, validate_deck
from .fonts import canvas_font, document_fonts
from .navigation import Navigator
from .storage import save_deck


_COCOA_REPLY_DIAGNOSTIC = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+ "
    r"\S+\[\d+:\d+\] Error received in message reply handler: Connection interrupted$")


def tcl_word(value):
    encoded = str(value).encode("utf-8").hex()
    return "[encoding convertfrom utf-8 [binary decode hex {" + encoded + "}]]"


WISH_LOCATIONS = ("/opt/homebrew/bin/wish", "/usr/local/bin/wish", "/usr/bin/wish")


def tcl_version(tclsh):
    """(major, minor) of a Tcl interpreter, or None when it cannot be asked. Runs headless; never opens a window."""
    try:
        output = subprocess.run([tclsh], input="puts [info patchlevel]\n", capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.match(r"\s*(\d+)\.(\d+)", output)
    return (int(match.group(1)), int(match.group(2))) if match else None


def stop_process(process, timeout=5):
    """Ask the GUI to exit; kill it when it does not stop within timeout seconds."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)


def find_wish():
    """OPENSLIDE_WISH is used as given; otherwise the first wish whose Tcl is 8.6+ (macOS ships Tk 8.5 in /usr/bin)."""
    configured = os.environ.get("OPENSLIDE_WISH")
    if configured and Path(configured).is_file():
        return configured
    seen, too_old = set(), []
    for candidate in (shutil.which("wish"), *WISH_LOCATIONS):
        if not candidate or not Path(candidate).is_file() or os.path.realpath(candidate) in seen:
            continue
        seen.add(os.path.realpath(candidate))
        # wish cannot report its version without starting a GUI; the tclsh installed beside it can.
        tclsh = Path(candidate).with_name("tclsh")
        version = tcl_version(str(tclsh)) if tclsh.is_file() else None
        if version is not None and version < (8, 6):
            too_old.append(f"{candidate} (Tcl/Tk {version[0]}.{version[1]})")
            continue
        return candidate
    found = f" Found only {', '.join(too_old)}." if too_old else ""
    raise RuntimeError("Tcl/Tk 8.6+ is required for the viewer." + found + " Install Tcl/Tk 8.6+ (for example Homebrew tcl-tk) "
                       "and put wish on PATH, or set OPENSLIDE_WISH. Headless export needs only Python.")


class Viewer:
    def __init__(self, path, smoke_test=False):
        self.path = Path(path).resolve()
        self.deck = load_deck(self.path)
        self.navigation = self._navigator()
        self.modified = self.path.stat().st_mtime_ns
        self.events = queue.Queue()
        self.process = None
        self.smoke_test = smoke_test
        self.smoke_result = None
        self.diagnostics = deque(maxlen=100)
        self.stderr_lines = deque(maxlen=100)
        self.undo_stack = []
        self.redo_stack = []
        self.inspected = None
        self._raster_executor = None
        self._raster_waiters = {}
        self._raster_cache = OrderedDict()
        self._raster_cache_bytes = 0

    def _navigator(self, index=0):
        return Navigator([max((e.get("step", 0) for e in s["elements"]), default=0) for s in self.deck["slides"]], index)

    def send(self, command, *args):
        line = " ".join([command, *(tcl_word(a) for a in args)]) + "\n"
        self.process.stdin.write(line)
        self.process.stdin.flush()

    def render(self):
        slide = self.deck["slides"][self.navigation.index]
        limitations = []
        if any(e.get("opacity", 1) not in (0, 1) for e in slide["elements"]):
            limitations.append("半透明效果請以匯出檔為準")
        if any(e["type"] == "image" and Path(e["path"]).suffix.lower() in (".jpg", ".jpeg") for e in slide["elements"]):
            limitations.append("JPEG 預覽取決於本機 Tk 解碼器")
        if slide.get("transition") == "fade":
            limitations.append("桌面預覽使用即時換頁")
        if any(e["type"] == "text" and e.get("east_asian_font") and canvas_font(e) != e.get("font_family", "Arial") for e in slide["elements"]):
            limitations.append("中英混排文字框採同一中文字型；PPTX 分別指定中英字型")
        self.send("::os::fidelity", "；".join(limitations))
        latin, east_asian = document_fonts(self.deck)
        self.send("::os::notes_font", canvas_font({"font_family": latin, "east_asian_font": east_asian, "text": slide.get("notes", "")}))
        self.send("::os::begin", self.deck["width"], self.deck["height"], slide.get("background", "#ffffff"), self.deck["title"], self.navigation.index + 1, len(self.deck["slides"]), slide.get("title", ""), slide.get("notes", ""))
        for element in slide["elements"]:
            if element.get("step", 0) > self.navigation.revealed:
                continue
            if element.get("opacity", 1) == 0:
                continue
            self.send_element("::os::element", element)
        self.send("::os::finish")
        self.send("::os::catalog", *[s.get("title", s["id"]) for s in self.deck["slides"]])
        next_index = min(len(self.deck["slides"]) - 1, self.navigation.index + 1)
        following = self.deck["slides"][next_index]
        self.send("::os::next_begin", following.get("background", "#ffffff"), following.get("title", ""))
        for element in following["elements"]:
            self.send_element("::os::next_element", element)
        self.send("::os::next_finish")
        self.send("::os::history_state", int(bool(self.undo_stack)), int(bool(self.redo_stack)))
        if self.inspected and self.inspected[0] == slide["id"]:
            self._send_inspector(*self.inspected)
        else:
            self.inspected = None
            self.send("::os::clear_inspector")

    def send_element(self, command, element):
        e = dict(element)
        if e["type"] == "image":
            e["path"] = str((self.path.parent / e["path"]).resolve())
        elif e["type"] == "text":
            e["_display_font_family"] = canvas_font(e)
        args = []
        for k, v in e.items():
            args += [k, "" if v is None else "1" if v is True else "0" if v is False else v]
        self.send(command, *args)

    def _read_events(self):
        for line in self.process.stdout:
            parts = line.rstrip("\r\n").split("\t")
            try:
                self.events.put((parts[0], [bytes.fromhex(s).decode("utf-8") for s in parts[1:]]))
            except (ValueError, UnicodeError):
                self.events.put(("error", [line]))

    def _read_stderr(self):
        # stderr is a separate diagnostic channel, never a Tcl bridge event.
        # Keep every line for abnormal-exit reports, including allowed messages.
        for line in self.process.stderr:
            message = line.rstrip("\r\n")
            if message:
                self.stderr_lines.append(message)
                self.events.put(("stderr", [message]))

    def _check_process_exit(self, readers):
        for reader in readers:
            reader.join(timeout=1)
        if self.process.returncode:
            detail = "\n".join(self.stderr_lines)
            raise RuntimeError(f"Tcl/Tk exited with status {self.process.returncode}" + (":\n" + detail if detail else ""))
        # An error can arrive immediately before exit or after a smoke result.
        # Drain these events so successful shutdown cannot conceal that failure.
        while True:
            try:
                action, args = self.events.get_nowait()
            except queue.Empty:
                break
            if action in ("error", "stderr"):
                self.action(action, args)

    def _snapshot(self):
        return {"deck": copy.deepcopy(self.deck), "index": self.navigation.index,
                "revealed": self.navigation.revealed}

    def _validate(self, candidate):
        errors = [d for d in validate_deck(candidate, self.path.parent) if d["severity"] == "error"]
        if errors:
            raise ValueError("\n".join(f"{d['path']}: {d['message']}" for d in errors[:8]))

    def _write_state(self, state):
        self._validate(state["deck"])
        if self.path.stat().st_mtime_ns != self.modified:
            raise ValueError("檔案已在其他程式中變更。請等待重新載入，再套用編輯。")
        save_deck(self.path, state["deck"])
        self.deck = copy.deepcopy(state["deck"])
        self.modified = self.path.stat().st_mtime_ns
        self.navigation = self._navigator(state["index"])
        self.navigation.revealed = min(state["revealed"], self.navigation.steps[self.navigation.index])

    def _commit(self, candidate, index=None, notice="已儲存到本機"):
        if candidate == self.deck:
            self.send("::os::editor_notice", "沒有需要儲存的變更")
            return False
        previous = self._snapshot()
        target_index = self.navigation.index if index is None else index
        revealed = previous["revealed"] if target_index == previous["index"] else max(
            (element.get("step", 0) for element in candidate["slides"][target_index]["elements"]), default=0)
        self._write_state({"deck": candidate, "index": target_index, "revealed": revealed})
        self.undo_stack.append(previous)
        del self.undo_stack[:-100]
        self.redo_stack.clear()
        self.render()
        self.send("::os::editor_notice", notice)
        return True

    def _history(self, undo):
        source = self.undo_stack if undo else self.redo_stack
        target = self.redo_stack if undo else self.undo_stack
        if not source:
            return False
        current = self._snapshot()
        self._write_state(source[-1])
        source.pop()
        target.append(current)
        self.render()
        self.send("::os::editor_notice", "已復原並儲存" if undo else "已重做並儲存")
        return True

    def _locate(self, slide_id, element_id):
        for si, slide in enumerate(self.deck["slides"]):
            if slide["id"] == slide_id:
                for ei, element in enumerate(slide["elements"]):
                    if element["id"] == element_id:
                        return si, ei
        raise ValueError("這個元素已不存在，請重新選取。")

    def _send_inspector(self, slide_id, element_id):
        try:
            si, ei = self._locate(slide_id, element_id)
        except ValueError:
            self.inspected = None
            self.send("::os::clear_inspector")
            return
        element = self.deck["slides"][si]["elements"][ei]
        values = []
        for key, value in element.items():
            values.extend((key, "" if value is None else "1" if value is True else "0" if value is False else value))
        self.send("::os::inspect", slide_id, element_id, json.dumps(element, ensure_ascii=False, indent=2), *values)

    @staticmethod
    def _json(value):
        def unique(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError(f"Duplicate JSON property: {key}")
                result[key] = item
            return result
        return json.loads(value, object_pairs_hook=unique)

    def _save_form(self, args):
        if len(args) < 2 or len(args) % 2:
            raise ValueError("Invalid editor field data")
        slide_id, element_id, *pairs = args
        si, ei = self._locate(slide_id, element_id)
        updated = copy.deepcopy(self.deck)
        element = updated["slides"][si]["elements"][ei]
        numeric = {"x", "y", "width", "height", "font_size", "stroke_width"}
        strings = {"text", "font_family", "east_asian_font", "color", "align", "alt"}
        allowed = numeric | strings | {"fill", "stroke", "bold"}
        seen = set()
        for key, value in zip(pairs[::2], pairs[1::2]):
            if key not in allowed or key in seen:
                raise ValueError(f"Invalid or duplicate editor field: {key}")
            seen.add(key)
            if key == "east_asian_font" and value == "":
                element.pop(key, None)
                continue
            if key in numeric:
                try:
                    number = float(value)
                    element[key] = int(number) if number.is_integer() else number
                except (ValueError, OverflowError):
                    raise ValueError(f"{key} 必須是數字。") from None
            elif key == "bold":
                if value not in ("0", "1"):
                    raise ValueError("bold 必須是 0 或 1。")
                element[key] = value == "1"
            elif key in ("fill", "stroke"):
                element[key] = value.strip() or None
            else:
                element[key] = value
        self._commit(updated, si)

    @staticmethod
    def _unused_id(base, used):
        stem = base + "-copy"
        candidate, counter = stem, 2
        while candidate in used:
            candidate = f"{stem}-{counter}"
            counter += 1
        return candidate

    def _duplicate_slide(self):
        updated = copy.deepcopy(self.deck)
        index = self.navigation.index
        duplicate = copy.deepcopy(updated["slides"][index])
        original_id = duplicate["id"]
        duplicate["id"] = self._unused_id(original_id, {slide["id"] for slide in updated["slides"]})
        duplicate["title"] = duplicate.get("title", original_id) + " 副本"
        used_elements = {element["id"] for slide in updated["slides"] for element in slide["elements"]}
        for element in duplicate["elements"]:
            element["id"] = self._unused_id(element["id"], used_elements)
            used_elements.add(element["id"])
            if element.get("href") == "#" + original_id:
                element["href"] = "#" + duplicate["id"]
        updated["slides"].insert(index + 1, duplicate)
        self._commit(updated, index + 1, "已複製投影片")

    def _delete_slide(self):
        if len(self.deck["slides"]) == 1:
            raise ValueError("簡報至少需要一張投影片。")
        updated = copy.deepcopy(self.deck)
        removed = updated["slides"].pop(self.navigation.index)
        removed_links = 0
        for slide in updated["slides"]:
            for element in slide["elements"]:
                if element.get("href") == "#" + removed["id"]:
                    element.pop("href")
                    removed_links += 1
        notice = "已刪除投影片" + (f"，並移除 {removed_links} 個指向該頁的連結" if removed_links else "")
        index = min(self.navigation.index, len(updated["slides"]) - 1)
        self._commit(updated, index, notice)

    def _move_slide(self, delta):
        if delta not in (-1, 1):
            raise ValueError("投影片只能向上或向下移動一格。")
        old_index = self.navigation.index
        new_index = old_index + delta
        if not 0 <= new_index < len(self.deck["slides"]):
            return False
        updated = copy.deepcopy(self.deck)
        slide = updated["slides"].pop(old_index)
        updated["slides"].insert(new_index, slide)
        return self._commit(updated, new_index, "已調整投影片順序")

    def _image_request(self, args):
        token, filename, raw_width, raw_height = args
        try:
            width, height = int(raw_width), int(raw_height)
            if min(width, height) < 1 or width * height > 4_000_000:
                raise ValueError("Preview exceeds the 4 megapixel limit")
            root = self.path.parent.resolve()
            relative = Path(filename).resolve().relative_to(root)
            _, mime, payload = resolve_image(relative.as_posix(), root)
            if mime != "image/png":
                self.send("::os::raster_unavailable", token, "unsupported", "使用 Tk 原生圖片預覽")
                return
            cache_key = (hashlib.sha256(payload).hexdigest(), width, height)
            if cache_key in self._raster_cache:
                encoded = self._raster_cache[cache_key]
                self._raster_cache.move_to_end(cache_key)
                self.send("::os::raster_ready", token, encoded)
                return
            if cache_key in self._raster_waiters:
                self._raster_waiters[cache_key].add(token)
                return
            self._raster_waiters[cache_key] = {token}
            if self._raster_executor is None:
                self._raster_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="openslide-preview")
            from .raster import resize_png
            future = self._raster_executor.submit(resize_png, payload, width, height)
            future.add_done_callback(lambda completed: self.events.put(("_image_result", (cache_key, completed))))
        except (OSError, ValueError) as exc:
            self.send("::os::raster_unavailable", token, "invalid", str(exc))

    def _image_result(self, cache_key, future):
        tokens = self._raster_waiters.pop(cache_key, set())
        try:
            payload = future.result()
            encoded = base64.b64encode(payload).decode("ascii")
            self._raster_cache[cache_key] = encoded
            self._raster_cache_bytes += len(encoded)
            while self._raster_cache_bytes > 32 * 1024 * 1024 or len(self._raster_cache) > 24:
                _, removed = self._raster_cache.popitem(last=False)
                self._raster_cache_bytes -= len(removed)
            for token in tokens:
                self.send("::os::raster_ready", token, encoded)
        except Exception as exc:
            from .raster import UnsupportedPNG
            kind = "unsupported" if isinstance(exc, UnsupportedPNG) else "invalid"
            for token in tokens:
                self.send("::os::raster_unavailable", token, kind, str(exc))

    def action(self, action, args):
        if action == "image_request":
            self._image_request(args)
        elif action == "_image_result":
            self._image_result(*args)
        elif action in ("next", "previous"):
            getattr(self.navigation, action)()
            self.render()
        elif action == "jump":
            self.navigation.jump(int(args[0]))
            self.render()
        elif action == "source":
            self.send("::os::source_editor", json.dumps(self.deck, ensure_ascii=False, indent=2))
        elif action == "save_source":
            self._commit(self._json(args[0]))
        elif action == "edit":
            slide_id = self.deck["slides"][self.navigation.index]["id"]
            self._locate(slide_id, args[0])
            self.inspected = (slide_id, args[0])
            self._send_inspector(*self.inspected)
        elif action == "save_form":
            self._save_form(args)
        elif action in ("save_element", "save_element_at"):
            if action == "save_element_at":
                slide_id, element_id, raw = args
            else:
                element_id, raw = args
                slide_id = self.deck["slides"][self.navigation.index]["id"]
            si, ei = self._locate(slide_id, element_id)
            updated = copy.deepcopy(self.deck)
            updated["slides"][si]["elements"][ei] = self._json(raw)
            self._commit(updated, si)
        elif action == "notes":
            updated = copy.deepcopy(self.deck)
            updated["slides"][self.navigation.index]["notes"] = args[0]
            self._commit(updated)
        elif action == "undo":
            self._history(True)
        elif action == "redo":
            self._history(False)
        elif action == "duplicate_slide":
            self._duplicate_slide()
        elif action == "delete_slide":
            self._delete_slide()
        elif action == "move_slide":
            self._move_slide(int(args[0]))
        elif action == "export":
            from .pptx import export_pptx
            from .export import export_html
            kind, target = args
            {"pptx": export_pptx, "html": export_html}[kind](self.deck, target, self.path.parent)
            self.send("::os::message", "Export complete", str(target))
        elif action == "open":
            candidate_path = Path(args[0]).resolve()
            candidate_deck = load_deck(candidate_path)
            candidate_mtime = candidate_path.stat().st_mtime_ns
            self.path, self.deck, self.modified = candidate_path, candidate_deck, candidate_mtime
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.inspected = None
            self.navigation = self._navigator()
            self.render()
        elif action == "new":
            from .__main__ import starter_deck
            candidate_path = Path(args[0]).resolve()
            candidate = starter_deck()
            save_deck(candidate_path, candidate)
            self.path, self.deck = candidate_path, candidate
            self.modified = candidate_path.stat().st_mtime_ns
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.inspected = None
            self.navigation = self._navigator()
            self.render()
        elif action == "smoke":
            self.smoke_result = json.loads(args[0])
        elif action == "error":
            raise RuntimeError(" ".join(args))
        elif action == "stderr":
            message = " ".join(args)
            if sys.platform == "darwin" and _COCOA_REPLY_DIAGNOSTIC.fullmatch(message):
                # Cocoa can emit this while Tk continues to process/render
                # correctly. Match the complete system format, not "Error" or
                # "Connection interrupted" in arbitrary Tcl error messages.
                self.diagnostics.append(message)
                print("Tcl/Tk system diagnostic: " + message, file=sys.stderr)
            else:
                raise RuntimeError("Tcl/Tk stderr: " + message)

    def reload(self, reset=False):
        candidate = load_deck(self.path)
        modified = self.path.stat().st_mtime_ns
        self.deck = candidate
        self.navigation = self._navigator(0 if reset else self.navigation.index)
        self.modified = modified
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.inspected = None
        self.render()

    def run(self):
        command = [find_wish(), str(Path(__file__).parent / "ui" / "viewer.tcl")]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        readers = [threading.Thread(target=self._read_events, daemon=True),
                   threading.Thread(target=self._read_stderr, daemon=True)]
        for reader in readers:
            reader.start()
        start = time.monotonic()
        ready = False
        try:
            while self.process.poll() is None:
                try:
                    action, args = self.events.get(timeout=.15)
                    if action == "ready":
                        ready = True
                        self.render()
                        if self.smoke_test:
                            self.send("::os::smoke")
                    else:
                        self.action(action, args)
                except queue.Empty:
                    pass
                except Exception as exc:
                    if self.smoke_test:
                        raise
                    self.send("::os::message", "Open Slide", str(exc))
                if self.smoke_result:
                    self.send("exit")
                    self.process.wait(timeout=5)
                    self._check_process_exit(readers)
                    self.smoke_result["startup_seconds"] = round(time.monotonic() - start, 4)
                    if self.diagnostics:
                        self.smoke_result["system_diagnostics"] = list(self.diagnostics)
                    return self.smoke_result
                if self.smoke_test and time.monotonic() - start > 20:
                    raise RuntimeError("Viewer smoke test timed out")
                if ready and self.path.exists() and self.path.stat().st_mtime_ns != self.modified:
                    try:
                        self.reload()
                    except Exception as exc:
                        self.modified = self.path.stat().st_mtime_ns
                        self.send("::os::message", "Reload failed", str(exc))
            self._check_process_exit(readers)
            if self.smoke_test:
                raise RuntimeError(f"Viewer exited before smoke verification: {self.process.returncode}")
        finally:
            if self._raster_executor is not None:
                self._raster_executor.shutdown(wait=False, cancel_futures=True)
            stop_process(self.process)
            for reader in readers:
                reader.join(timeout=1)
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                if stream is not None:
                    stream.close()
