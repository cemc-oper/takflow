#!/usr/bin/env python3
"""Sync takflow's vendored jobspec contract from the orvix repository.

The jobspec contract (schema / VERSION / conformance vectors and goldens) is
owned by ``cemc-oper/orvix`` (``spec/jobspec/`` there). takflow keeps a
read-only vendored copy under ``src/takflow/spec/jobspec/``, pinned to an
orvix git ref recorded in the ``ORVIX_VERSION`` file next to it.

Usage:

    # Sync to a new orvix ref (tag or SHA) and update the pin file:
    python scripts/sync_jobspec.py --orvix-ref v0.3.0

    # CI consistency check: vendored copy must equal orvix @ the pinned ref:
    python scripts/sync_jobspec.py --check

    # Pre-commit preview against an uncommitted orvix working tree
    # (no pin is written):
    python scripts/sync_jobspec.py --check --worktree

The orvix repo location is taken from ``--orvix-repo``, else ``$ORVIX_REPO``,
else auto-detected as ``<workspace>/runtime/orvix-devel/repo/orvix``.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

TAKFLOW_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = TAKFLOW_ROOT / "src" / "takflow" / "spec" / "jobspec"
PIN_FILE = VENDOR_DIR / "ORVIX_VERSION"

#: Prefix of the contract tree inside the orvix repo.
ORVIX_SPEC_PREFIX = "spec/jobspec"


def find_orvix_repo(arg: str | None) -> Path:
    if arg:
        return Path(arg).resolve()
    env = os.environ.get("ORVIX_REPO")
    if env:
        return Path(env).resolve()
    # Workspace layout: <workspace>/framework/takflow -> <workspace>/runtime/...
    candidate = TAKFLOW_ROOT.parent.parent / "runtime" / "orvix-devel" / "repo" / "orvix"
    if candidate.is_dir():
        return candidate
    sys.exit("error: cannot locate the orvix repo; pass --orvix-repo or set ORVIX_REPO")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout


def list_contract_files(repo: Path, ref: str) -> list[str]:
    """Contract files at ``ref``: everything under spec/jobspec except Go sources."""
    out = git(repo, "ls-tree", "-r", "--name-only", ref, "--", ORVIX_SPEC_PREFIX)
    return [
        line for line in out.splitlines()
        if line.strip() and not line.endswith(".go")
    ]


def read_at_ref(repo: Path, ref: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), "show", f"{ref}:{path}"],
        check=True, capture_output=True,
    ).stdout


def read_worktree(repo: Path, path: str) -> bytes:
    return (repo / path).read_bytes()


def collect(repo: Path, ref: str | None) -> dict[str, bytes]:
    """Return {repo-relative path: content} for the contract tree."""
    if ref:
        files = list_contract_files(repo, ref)
        return {p: read_at_ref(repo, ref, p) for p in files}
    root = repo / ORVIX_SPEC_PREFIX
    if not root.is_dir():
        sys.exit(f"error: {root} not found; wrong orvix repo?")
    return {
        str(p.relative_to(repo)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.suffix != ".go"
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--orvix-repo", help="path to the orvix git repo "
                                         "(default: $ORVIX_REPO or workspace autodetect)")
    ap.add_argument("--orvix-ref", help="orvix git ref (tag/SHA) to sync from; "
                                        "writes the ORVIX_VERSION pin. "
                                        "Omit to read the working tree instead.")
    ap.add_argument("--worktree", action="store_true",
                    help="explicitly read the orvix working tree (no pin written)")
    ap.add_argument("--check", action="store_true",
                    help="verify only: vendored copy must equal the source; "
                         "with a pin file, the source is the pinned ref")
    args = ap.parse_args()

    repo = find_orvix_repo(args.orvix_repo)

    ref = args.orvix_ref
    if args.worktree:
        ref = None
    if args.check and not args.worktree and not ref:
        # CI path: check against the pinned ref recorded in the pin file.
        if not PIN_FILE.exists():
            sys.exit(f"error: pin file {PIN_FILE} missing; run a sync first")
        ref = PIN_FILE.read_text(encoding="utf-8").strip()
    if not ref and not args.worktree and not args.check:
        sys.exit("error: pass --orvix-ref to sync, or --worktree to read the "
                 "working tree (no pin written)")

    source = collect(repo, ref)
    source_label = ref if ref else f"worktree of {repo}"
    if ref:
        resolved = git(repo, "rev-parse", ref).strip()
        source_label = f"{ref} ({resolved[:12]})"

    drift: list[str] = []
    for rel, content in sorted(source.items()):
        vendored = VENDOR_DIR / Path(rel).relative_to(ORVIX_SPEC_PREFIX)
        if not vendored.exists() or vendored.read_bytes() != content:
            drift.append(str(vendored.relative_to(TAKFLOW_ROOT)))
    # Vendored files that no longer exist at the source.
    for p in sorted(VENDOR_DIR.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        if p.suffix in (".py", ".pyc") or p.name in ("ORVIX_VERSION", "README.md"):
            continue
        rel = str(Path(ORVIX_SPEC_PREFIX) / p.relative_to(VENDOR_DIR))
        if rel not in source:
            drift.append(str(p.relative_to(TAKFLOW_ROOT)) + " (stale)")

    if drift:
        print(f"vendored jobspec drifted from orvix @ {source_label}:")
        for d in drift:
            print(f"  {d}")
        if args.check:
            print("run: python scripts/sync_jobspec.py --orvix-ref <ref>")
            return 1

    if args.check:
        if drift:
            return 1  # unreachable, handled above
        print(f"OK: vendored jobspec == orvix @ {source_label} "
              f"({len(source)} files)")
        return 0

    # Sync mode: overwrite the vendored copy.
    for rel, content in sorted(source.items()):
        dest = VENDOR_DIR / Path(rel).relative_to(ORVIX_SPEC_PREFIX)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        print(f"synced {dest.relative_to(TAKFLOW_ROOT)}")
    if ref:
        PIN_FILE.write_text(ref + "\n", encoding="utf-8")
        print(f"pinned ORVIX_VERSION -> {ref}")
    else:
        print("worktree sync: pin file left unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
