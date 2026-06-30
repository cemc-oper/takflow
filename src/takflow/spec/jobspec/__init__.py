"""Accessors for the canonical jobspec contract artifacts.

The schema (``jobspec.schema.json``) is the single source of truth for the
job-run resource description. ``orvix`` vendors a copy of it; both sides are
kept honest by the conformance harness under ``conformance/``.
"""
from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, Dict

SCHEMA_FILENAME = "jobspec.schema.json"
VERSION_FILENAME = "VERSION"


def schema_path() -> str:
    """Absolute path to ``jobspec.schema.json`` (for vendoring/diffing)."""
    return str(files(__package__).joinpath(SCHEMA_FILENAME))


@lru_cache(maxsize=1)
def load_schema() -> Dict[str, Any]:
    """Return the parsed canonical jobspec JSON Schema."""
    text = files(__package__).joinpath(SCHEMA_FILENAME).read_text(encoding="utf-8")
    return json.loads(text)


@lru_cache(maxsize=1)
def contract_version() -> str:
    """Return the contract version string (semantic version)."""
    text = files(__package__).joinpath(VERSION_FILENAME).read_text(encoding="utf-8")
    return text.strip()


def schema_keys() -> list[str]:
    """Return the contract's property names, in declaration order (snake_case)."""
    return list(load_schema().get("properties", {}).keys())


__all__ = [
    "schema_path",
    "load_schema",
    "contract_version",
    "schema_keys",
    "SCHEMA_FILENAME",
    "VERSION_FILENAME",
]
