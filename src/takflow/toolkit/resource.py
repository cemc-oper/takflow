"""Generic resource-copy logic.

Copies the static resource subtrees (``scripts/``, ``utils/``,
``ecflow/include/``, ``takler/include/``) from a source resource directory into
an output repo. App-specific resource *location* (e.g. a package's ``resources``
dir) is resolved by the caller and passed as ``src_base``.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
from pathlib import Path
from typing import NoReturn
from collections.abc import Callable

from takflow.checks import (
    GenerationCheckError,
    GenerationCheckReport,
    GenerationInputError,
    check_input_file,
    check_output_path,
    check_relative_path,
)


def _check_directory(path: Path, report: GenerationCheckReport, *, source: bool) -> None:
    stage = "resource.preflight"
    if path.exists() or path.is_symlink():
        if not path.is_dir():
            report.fail("RESOURCE_SOURCE_TYPE" if source else "RESOURCE_OUTPUT_TYPE",
                        stage, str(path), "resource path must be a directory")
        access = os.R_OK | os.X_OK if source else os.X_OK
        mode = path.stat().st_mode
        if not mode & 0o111 or (source and not mode & 0o444) or not os.access(path, access):
            report.fail("RESOURCE_SOURCE_PERMISSION" if source else "RESOURCE_OUTPUT_PERMISSION",
                        stage, str(path), "resource directory is not accessible")
    elif source:
        report.fail("RESOURCE_SOURCE_MISSING", stage, str(path),
                    "resource source directory is missing", error_type=GenerationInputError)
    else:
        parent = path.parent
        while not parent.exists() and not parent.is_symlink():
            parent = parent.parent
        if not parent.is_dir():
            report.fail("RESOURCE_OUTPUT_TYPE", stage, str(parent),
                        "output ancestor must be a directory")
        mode = parent.stat().st_mode
        if not mode & 0o222 or not mode & 0o111 or not os.access(parent, os.W_OK | os.X_OK):
            report.fail("RESOURCE_OUTPUT_PERMISSION", stage, str(parent),
                        "output ancestor does not permit directory creation")


def _overlap(first: Path, second: Path) -> bool:
    return first == second or first.is_relative_to(second) or second.is_relative_to(first)


def _copy_plan(
    src_base: Path,
    output: Path,
    trees: list[tuple[Path, Path, bool]],
    report: GenerationCheckReport,
    *,
    keep: Callable[[Path], bool] | None = None,
    standard: bool = False,
    directories: list[Path] | None = None,
) -> list[list[tuple[Path, Path, str, int]]]:
    """Check every selected source/target before the first output mutation.

    copytree follows source links, so follow them here too, rejecting directory
    cycles and paths that would copy a tree into itself. An unrelated build
    directory beneath the resource root remains valid.
    """
    stage = "resource.preflight"
    _check_directory(src_base, report, source=True)
    _check_directory(output, report, source=False)
    for _, dst, _ in trees:
        check_relative_path(output, dst.relative_to(output), stage=stage,
                            report=report, object=str(dst))
    destinations = [dst.resolve() for _, dst, _ in trees]
    planned_targets: set[Path] = set()

    def walk(src: Path, dst: Path, executable: bool, ancestors: set[Path], files):
        real_source = src.resolve()
        if real_source in ancestors:
            report.fail("RESOURCE_SOURCE_CYCLE", stage, str(src),
                        "source directory links contain a cycle")
        if any(_overlap(real_source, target) for target in destinations):
            report.fail("RESOURCE_COPY_OVERLAP", stage, str(src),
                        "selected source and destination trees overlap")
        if src.is_dir() or not standard:
            _check_directory(src, report, source=True)
        else:
            check_input_file(src, stage=stage, report=report)
        check_relative_path(output, dst.relative_to(output), stage=stage,
                            report=report, object=str(dst))
        if src.is_dir() or not standard:
            _check_directory(dst, report, source=False)
        else:
            check_output_path(dst, stage=stage, report=report)
        if directories is not None and src.is_dir():
            directories.append(dst)
        for child in sorted(src.iterdir()) if src.is_dir() else [src]:
            if keep is not None and not keep(child.relative_to(src_base)):
                continue
            target = dst / child.name
            if not src.is_dir():
                target = dst
            if standard:
                check_relative_path(src_base, child.relative_to(src_base), stage=stage, report=report)
            if child.is_dir():
                walk(child, target, executable, ancestors | {real_source}, files)
                continue
            check_input_file(child, stage=stage, report=report, object=str(child))
            check_relative_path(output, target.relative_to(output), stage=stage,
                                report=report, object=str(target))
            check_output_path(target, stage=stage, report=report, object=str(target))
            real_target = target.resolve()
            if real_target in planned_targets:
                report.fail("RESOURCE_OUTPUT_COLLISION", stage, str(target),
                            "multiple resource files resolve to the same output")
            if any(child.resolve().is_relative_to(directory) for directory in destinations):
                report.fail("RESOURCE_COPY_OVERLAP", stage, str(child),
                            "resource input refers to a selected output tree")
            planned_targets.add(real_target)
            mode = stat.S_IMODE(child.stat().st_mode)
            if executable and child.suffix == ".sh":
                mode |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            if standard:
                mode = 0o755 if executable else 0o644
            digest = hashlib.sha256(child.read_bytes()).hexdigest()
            files.append((child, target, digest, mode))

    plans = []
    for src, dst, executable in trees:
        files: list[tuple[Path, Path, str, int]] = []
        walk(src, dst, executable, set(), files)
        plans.append(files)
    # Resolved names do not reveal hard links. Check existing file identities
    # across the whole plan so an earlier write cannot alter a later source.
    source_ids = set()
    for files in plans:
        for source, _, _, _ in files:
            metadata = source.stat()
            source_ids.add((metadata.st_dev, metadata.st_ino))
    target_ids = set()
    for files in plans:
        for _, target, _, _ in files:
            if not target.exists():
                continue
            metadata = target.stat()
            identity = (metadata.st_dev, metadata.st_ino)
            if identity in source_ids:
                report.fail("RESOURCE_COPY_OVERLAP", stage, str(target),
                            "an existing output is hard-linked to a resource source")
            if identity in target_ids:
                report.fail("RESOURCE_OUTPUT_COLLISION", stage, str(target),
                            "multiple outputs are hard-linked to the same existing file")
            target_ids.add(identity)
    report.passed("RESOURCE_PREFLIGHT", stage, str(src_base),
                  "selected resource sources and output paths checked before copying")
    return plans


def _check_copied_files(
    files: list[tuple[Path, Path, str, int]], report: GenerationCheckReport,
) -> None:
    stage = "resource.check"
    # Only files selected from this invocation's sources are recorded. A stale
    # output subtree can remain present without becoming a current artifact.
    for _, target, _, _ in files:
        if target.is_file():
            report.artifact(target, "resource", stage=stage)
    for _, target, digest, mode in files:
        if not target.is_file():
            report.fail("RESOURCE_OUTPUT_MISSING", stage, str(target),
                        "copied resource file is missing")
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            report.fail("RESOURCE_CONTENT_MISMATCH", stage, str(target),
                        "copied resource content differs from the checked source")
        if stat.S_IMODE(target.stat().st_mode) != mode:
            report.fail("RESOURCE_PERMISSION_MISMATCH", stage, str(target),
                        "copied resource permissions differ from the existing copy contract")
    report.passed("RESOURCE_ARTIFACTS", stage, "resources",
                  "this invocation's copied file contents and permissions checked")


def _fail_after_copy(
    report: GenerationCheckReport, code: str, stage: str, subject: Path,
    reason: str, copied: list[Path],
) -> NoReturn:
    # Record the primary failure first. Reporting files can itself fail after
    # concurrent deletion or a permission error; that must not replace it.
    try:
        report.fail(code, stage, str(subject), reason)
    except GenerationCheckError:
        for target in copied:
            try:
                report.artifact(target, "resource", stage=stage)
            except (GenerationCheckError, OSError):
                report.unchecked("RESOURCE_ARTIFACT_UNAVAILABLE", stage, str(target),
                                 "previously copied file could not be recorded after failure")
        raise


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
    *,
    check_report: GenerationCheckReport | None = None,
    additional_entries: tuple[tuple[str, str, bool], ...] = (),
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
    check_report : GenerationCheckReport, optional
        Collect preflight checks and files copied by this invocation. Dynamic
        and target-host references inside resource text are not evaluated.
    additional_entries : tuple, optional
        Extra (source, destination, executable) directory mappings relative to
        the declared roots. Explicit mappings require their directories. They use this
        helper's existing source-permission and ``*.sh`` executable-bit semantics.
    """
    report = check_report if check_report is not None else GenerationCheckReport()
    output_repo_base = Path(output_repo_base)
    src_base = Path(src_base)
    trees = []
    for enabled, relative, executable in (
        (include_scripts, "scripts", True),
        (include_utils, "utils", True),
        (include_ecflow, "ecflow/include", False),
        (include_takler, "takler/include", False),
    ):
        source = src_base / relative
        if enabled and source.exists():
            trees.append((source, output_repo_base / relative, executable))
        elif enabled:
            report.unchecked("RESOURCE_SUBTREE_ABSENT", "resource.preflight", str(source),
                             "optional resource subtree is absent")
    for source, destination, executable in additional_entries:
        src = check_relative_path(src_base, source, stage="resource.preflight", report=report)
        dst = check_relative_path(output_repo_base, destination, stage="resource.preflight", report=report)
        trees.append((src, dst, executable))
    plans = _copy_plan(src_base, output_repo_base, trees, report)
    output_repo_base.mkdir(parents=True, exist_ok=True)
    for (src, dst, executable), files in zip(trees, plans):
        dst.parent.mkdir(parents=True, exist_ok=True)
        copied: list[Path] = []

        def copy_file(source, target):
            result = shutil.copy2(source, target)
            copied.append(Path(target))
            return result

        try:
            shutil.copytree(src, dst, dirs_exist_ok=True, copy_function=copy_file)
            if executable:
                make_scripts_executable(dst)
        except (OSError, shutil.Error):
            _fail_after_copy(report, "RESOURCE_COPY_FAILED", "resource.copy", src,
                             "resource subtree could not be copied", copied)
        if set(copied) != {target for _, target, _, _ in files}:
            _fail_after_copy(report, "RESOURCE_SOURCE_CHANGED", "resource.check", src,
                             "resource file selection changed after preflight", copied)
        _check_copied_files(files, report)
    report.unchecked("RESOURCE_RUNTIME_REFERENCES", "resource.check", str(output_repo_base),
                     "dynamic and target-host references inside copied files were not evaluated")


def copy_resource_entries(
    output_repo_base: Path, src_base: Path,
    entries: list[tuple[str, str, bool]], *,
    keep: Callable[[Path], bool], check_report: GenerationCheckReport,
    check_target: Callable[[Path], None] | None = None,
    source_layer: str | None = None,
) -> None:
    """Copy declared selected mappings with exact standard permissions.

    Entries are source-relative, destination-relative and executable. The
    caller resolves optional/required entries across layers. Original copy
    exceptions and partial invocation artifacts survive failures.
    """
    from takflow._files import file_state, make_parents

    trees = []
    for source, destination, executable in entries:
        src = check_relative_path(src_base, source, stage="resource.preflight", report=check_report)
        dst = check_relative_path(output_repo_base, destination, stage="resource.preflight", report=check_report)
        trees.append((src, dst, executable))
    directories = []
    plans = _copy_plan(src_base, output_repo_base, trees, check_report, keep=keep, standard=True, directories=directories)
    if check_target is not None:
        for files in plans:
            for _, target, _, _ in files:
                check_target(target)
    for directory in directories:
        make_parents(directory / ".directory", output_repo_base)
    for files in plans:
        for source, target, _, mode in files:
            before = file_state(target)
            try:
                make_parents(target, output_repo_base)
                shutil.copy2(source, target)
                target.chmod(mode)
            except Exception:
                check_report.failed("RESOURCE_COPY_FAILED", "resource.copy", str(target),
                                    "resource copy failed; partial output is retained")
                try:
                    if file_state(target) != before and target.is_file():
                        check_report.artifact(target, "resource_partial", stage="resource.copy")
                except Exception:
                    check_report.unchecked("RESOURCE_PARTIAL_UNREADABLE", "resource.copy", str(target),
                                           "partial file metadata could not be collected")
                raise
            check_report.artifact(target, "resource", stage="resource.copy")
            check_report.artifacts[-1]["source"] = str(source)
            check_report.artifacts[-1]["layer"] = source_layer
        _check_copied_files(files, check_report)
        for source, target, _, _ in files:
            item = next(item for item in check_report.artifacts if item["path"] == str(target))
            item.update(source=str(source), layer=source_layer)


__all__ = ["copy_resources_to_output", "make_scripts_executable", "copy_resource_entries"]
