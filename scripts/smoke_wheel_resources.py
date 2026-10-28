#!/usr/bin/env python3
"""Smoke-test jobspec resources from an installed takflow wheel."""
from __future__ import annotations

import importlib.util
from importlib.resources import files
from pathlib import Path

import takflow
import takflow.backends.ecflow  # noqa: F401
import takflow.backends.takler  # noqa: F401
from takflow.spec.jobspec import contract_version, schema_keys, schema_path
from takflow.spec.jobspec.conformance import (
    CASES,
    LEADING_BLANK_CASES,
    SCHEDULERS,
    build_script,
)


def main() -> None:
    if importlib.util.find_spec("takler") is not None:
        raise SystemExit("wheel smoke requires a clean environment without takler")

    root = files("takflow.spec.jobspec")
    vectors = [f"conformance/vectors/{name}.sh" for name in sorted(CASES)]
    goldens = [
        f"conformance/golden/{scheduler}/{name}.submit"
        for scheduler in SCHEDULERS
        for name in sorted(CASES)
    ]
    required = [
        "jobspec.schema.json",
        "VERSION",
        "ORVIX_VERSION",
        *vectors,
        *goldens,
    ]
    missing = [name for name in required if not root.joinpath(name).is_file()]
    if missing:
        raise SystemExit(
            "missing packaged jobspec resources: " + ", ".join(missing)
        )

    version = root.joinpath("VERSION").read_text(encoding="utf-8").strip()
    pin = root.joinpath("ORVIX_VERSION").read_text(encoding="utf-8").strip()
    assert Path(schema_path()).is_file()
    assert len(schema_keys()) == 19
    assert version and contract_version() == version
    assert pin

    for name in sorted(CASES):
        vector = root.joinpath(f"conformance/vectors/{name}.sh").read_text(
            encoding="utf-8"
        )
        assert build_script(
            CASES[name], leading_blank=name in LEADING_BLANK_CASES
        ) == vector, f"installed renderer does not reproduce vector {name}"
    for name in goldens:
        assert root.joinpath(name).read_text(encoding="utf-8").strip(), name

    print(f"Installed takflow: {takflow.__file__}")
    print(
        f"Wheel resources OK: schema/19 keys, VERSION={version}, "
        f"{len(vectors)} vectors, {len(goldens)} goldens; takler absent"
    )


if __name__ == "__main__":
    main()
