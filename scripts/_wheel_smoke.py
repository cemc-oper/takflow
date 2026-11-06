"""Shared assertions for smoke scripts that must exercise installed wheels."""
from __future__ import annotations

from importlib.metadata import distribution
import json
from pathlib import Path
import sys


def check_installed_package(module, name: str) -> None:
    installed = distribution(name)
    source = Path(module.__file__).resolve()
    expected = Path(installed.locate_file(f"{module.__name__}/__init__.py")).resolve()
    direct_url = json.loads(installed.read_text("direct_url.json") or "{}")
    if direct_url.get("dir_info", {}).get("editable"):
        raise SystemExit(f"wheel smoke rejects editable distribution: {name}")
    if source != expected or not source.is_relative_to(Path(sys.prefix).resolve()):
        raise SystemExit(f"wheel smoke imported {name} outside its installed distribution: {source}")
    print(f"Installed {name} {installed.version}: {source}")
