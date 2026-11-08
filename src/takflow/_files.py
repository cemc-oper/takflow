"""Small POSIX output helpers for the standard generation path."""
from pathlib import Path
import os


def file_state(path: Path):
    try:
        value = path.stat()
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns
    except FileNotFoundError:
        return None


def make_parents(path: Path, root: Path, *, private: bool = False) -> None:
    missing = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700 if private else 0o755)
        directory.chmod(0o700 if private else 0o755)
    if not private:
        parent = path.parent
        while parent == root or root in parent.parents:
            parent.chmod(0o755)
            if parent == root:
                break
            parent = parent.parent


def write_text(path: Path, text: str, mode: int, root: Path) -> None:
    make_parents(path, root, private=mode == 0o600)
    # Set private permissions before truncating an existing credential file.
    if mode == 0o600 and path.exists():
        path.chmod(mode)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        os.fchmod(stream.fileno(), mode)
        stream.write(text.replace("\r\n", "\n").replace("\r", "\n"))
