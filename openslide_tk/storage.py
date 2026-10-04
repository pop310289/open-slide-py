import json
import os
from pathlib import Path
import secrets
import stat


def atomic_write(path, content):
    """Atomically save bytes or UTF-8 text without broadening file permissions.

    New files use the effective mode of an ordinary 0666 creation under the
    caller's umask. Replacements preserve the destination's POSIX mode bits.
    The process-wide umask is never changed, including in threaded callers.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = content.encode("utf-8") if isinstance(content, str) else content
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    for _ in range(100):
        temporary = path.parent / ("." + path.name + "." + secrets.token_hex(12) + ".tmp")
        try:
            fd = os.open(temporary, flags, 0o666)
            break
        except FileExistsError:
            continue
    else:
        raise FileExistsError("Could not allocate an exclusive temporary output")

    def set_mode(descriptor, mode):
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, mode)
        else:  # Windows exposes its supported permission bits through chmod.
            os.chmod(temporary, mode)

    try:
        creation_mode = stat.S_IMODE(os.fstat(fd).st_mode)
        # No payload is exposed while it is incomplete. Remember the kernel's
        # umask-filtered mode before narrowing this still-empty temporary file.
        set_mode(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            fd = None  # The context manager now owns the descriptor.
            stream.write(payload)
            stream.flush()
            try:
                final_mode = stat.S_IMODE(path.stat().st_mode)
            except FileNotFoundError:
                final_mode = creation_mode
            set_mode(stream.fileno(), final_mode)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd is not None:
            os.close(fd)
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def save_deck(path, deck):
    atomic_write(path, json.dumps(deck, ensure_ascii=False, indent=2) + "\n")
