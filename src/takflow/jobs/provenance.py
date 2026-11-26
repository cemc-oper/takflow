"""Source comments for generated Shell jobs and embedded Shell fragments."""

from __future__ import annotations

import re
from pathlib import Path


SEPARATOR = "# " + "=" * 77
_SHEBANG_INCLUDE = re.compile(r"^%include(?:nopp|once)?\s+<(?:[^>]*/)?shebang_[^/>]+>")


def _layer_source(path: Path, name: str, root: Path) -> str:
    for directory in (root, *root.parents):
        package = directory.parent
        if directory.name == "resources" and package.name.isidentifier() and (package / "__init__.py").is_file():
            return f"{package.name}:{path.relative_to(directory).as_posix()}"
    return f"{name}:{path.relative_to(root).as_posix()}"


def resource_source(path: Path, layers: tuple[tuple[str, Path], ...]) -> str | None:
    """Name the selected file relative to its package or effective resource layer."""
    path = path.absolute()
    for name, root in reversed(layers):
        root = root.absolute()
        if path.is_relative_to(root):
            return _layer_source(path, name, root)
    return None


def prepared_source(path: Path, content: bytes, layers: tuple[tuple[str, Path], ...],
                    output: Path, entries: tuple[tuple[str, str], ...]) -> str:
    """Only attribute a staged prerequisite to a layer with identical bytes."""
    relative = path.relative_to(output)
    for name, root in reversed(layers):
        for source, destination in entries:
            if not relative.is_relative_to(destination):
                continue
            candidate = root / source / relative.relative_to(destination)
            try:
                if (candidate.resolve().is_relative_to(root.resolve()) and candidate.is_file()
                        and candidate.read_bytes() == content):
                    return _layer_source(candidate.absolute(), name, root.absolute())
            except OSError:
                # A separate job stage can use an already prepared file even if
                # its original resource layer is unavailable in this invocation.
                continue
    return f"output:{relative.as_posix()}"


def _comment(line: str, mode: str) -> str:
    if mode == "ecflow":
        return line.replace("%", "%%")
    if mode == "takler" and any(token in line for token in ("{{", "{%", "{#")):
        return "{{ " + repr(line) + " }}"
    return line


def job_source(text: str, source: str, mode: str) -> str:
    """Keep the marker after a literal or deferred machine shebang."""
    marker = _comment(f"# JOB {source}", mode) + "\n"
    offset = 0
    for line in text.splitlines(keepends=True):
        if line.strip():
            if line.startswith("#!") or (mode == "ecflow" and _SHEBANG_INCLUDE.match(line)):
                end = offset + len(line)
                return text[:end] + ("" if line.endswith("\n") else "\n") + marker + text[end:]
            break
        offset += len(line)
    return marker + text


def source_block(text: str, kind: str, source: str, mode: str = "shell") -> str:
    """Enclose an expanded statement without modifying its body."""
    if not text.strip():
        return text
    begin = _comment(f"# BEGIN {kind} {source}", mode)
    end = _comment(f"# END {kind} {source}", mode)
    trailing_newline = "\n" if text.endswith("\n") else ""
    body = text if trailing_newline else text + "\n"
    return f"{SEPARATOR}\n{begin}\n{SEPARATOR}\n{body}{SEPARATOR}\n{end}\n{SEPARATOR}{trailing_newline}"
