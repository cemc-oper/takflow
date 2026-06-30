"""Regenerate committed conformance vectors and goldens.

Run this when the contract or a case changes (and bump ``../VERSION``):

    ORVIX_BIN=/path/to/orvix python -m takflow.spec.jobspec.conformance.regen

It writes:
  - ``vectors/<name>.sh``                     (takflow-rendered #ORVIX scripts)
  - ``golden/<scheduler>/<name>.submit``      (orvix generate output)

The committed goldens are what ``tests/test_conformance.py`` diffs against.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from takflow.spec.jobspec.conformance import CASES, SCHEDULERS, build_script

HERE = Path(__file__).resolve().parent
VECTORS_DIR = HERE / "vectors"
GOLDEN_DIR = HERE / "golden"


def find_orvix() -> str | None:
    return os.environ.get("ORVIX_BIN") or shutil.which("orvix")


def write_vectors() -> dict[str, Path]:
    VECTORS_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, spec in CASES.items():
        path = VECTORS_DIR / f"{name}.sh"
        path.write_text(build_script(spec), encoding="utf-8")
        paths[name] = path
    return paths


def write_goldens(orvix: str, vectors: dict[str, Path]) -> None:
    for scheduler in SCHEDULERS:
        out_dir = GOLDEN_DIR / scheduler
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, vector in vectors.items():
            golden = out_dir / f"{name}.submit"
            with tempfile.TemporaryDirectory() as tmp:
                tmp_out = Path(tmp) / "out.submit"
                subprocess.run(
                    [orvix, "generate", "--scheduler", scheduler,
                     "--output-script", str(tmp_out), str(vector)],
                    check=True, capture_output=True, text=True,
                )
                golden.write_text(tmp_out.read_text(encoding="utf-8"), encoding="utf-8")


def main() -> int:
    vectors = write_vectors()
    print(f"wrote {len(vectors)} vector(s) to {VECTORS_DIR}")
    orvix = find_orvix()
    if not orvix:
        print("orvix not found (set ORVIX_BIN or add to PATH); skipped goldens.",
              file=sys.stderr)
        return 1
    write_goldens(orvix, vectors)
    print(f"wrote goldens for {', '.join(SCHEDULERS)} to {GOLDEN_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
