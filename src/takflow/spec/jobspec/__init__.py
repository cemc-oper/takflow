"""Accessors for the vendored jobspec contract artifacts.

The schema (``jobspec.schema.json``), ``VERSION`` and ``conformance/`` are a
**read-only vendored copy** of the jobspec contract owned by the ``orvix``
repo (``spec/jobspec/`` there), pinned to the orvix ref recorded in
``ORVIX_VERSION``. Do not edit them here — change the contract in orvix, then
re-vendor with ``scripts/sync_jobspec.py``. Both sides are kept honest by the
conformance harness under ``conformance/`` and the CI vendored-vs-pin check.
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
