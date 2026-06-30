"""Generic resource-copy logic.

Copies the static resource subtrees (``scripts/``, ``utils/``,
``ecflow/include/``, ``takler/include/``) from a source resource directory into
an output repo. App-specific resource *location* (e.g. a package's ``resources``
dir) is resolved by the caller and passed as ``src_base``.
"""
from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path


def make_scripts_executable(directory: Path) -> None:
    """Mark every ``*.sh`` under ``directory`` executable (ugo+x)."""
    for path in directory.rglob("*.sh"):
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def copy_resources_to_output(
    output_repo_base: Path,
    src_base: Path,
    include_scripts: bool = True,
    include_utils: bool = True,
    include_ecflow: bool = True,
    include_takler: bool = True,
) -> None:
    """Copy static resource subtrees from ``src_base`` into ``output_repo_base``.

    Parameters
    ----------
    output_repo_base : Path
        Target directory (OUTPUT_REPO_BASE).
    src_base : Path
        Source resource directory (e.g. an app's packaged ``resources`` dir).
    include_scripts, include_utils, include_ecflow, include_takler : bool
        Which subtrees to copy.
    """
    output_repo_base = Path(output_repo_base)
    output_repo_base.mkdir(parents=True, exist_ok=True)
    src_base = Path(src_base)

    if include_scripts:
        src = src_base / "scripts"
        if src.exists():
            dst = output_repo_base / "scripts"
            shutil.copytree(src, dst, dirs_exist_ok=True)
            make_scripts_executable(dst)

    if include_utils:
        src = src_base / "utils"
        if src.exists():
            dst = output_repo_base / "utils"
            shutil.copytree(src, dst, dirs_exist_ok=True)
            make_scripts_executable(dst)

    if include_ecflow:
        src = src_base / "ecflow" / "include"
        if src.exists():
            dst = output_repo_base / "ecflow" / "include"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst, dirs_exist_ok=True)

    if include_takler:
        src = src_base / "takler" / "include"
        if src.exists():
            dst = output_repo_base / "takler" / "include"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst, dirs_exist_ok=True)


__all__ = ["copy_resources_to_output", "make_scripts_executable"]
