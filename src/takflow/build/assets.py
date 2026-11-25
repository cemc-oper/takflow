"""Plan and copy declared static workflow resources in layer order."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from collections.abc import Callable

from takflow.checks import (
    GenerationCheckReport,
    GenerationInputError,
    check_input_file,
    check_output_path,
    check_relative_path,
)

_CopyFile = tuple[Path, Path, int]


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
    keep: Callable[[Path], bool] | None,
    directories: list[Path],
    destinations: set[Path],
) -> list[list[_CopyFile]]:
    """Check every selected source/target before the first output mutation.

    Resolve source links within their resource root. Reject directory cycles
    and overlapping selected trees before copying.
    """
    stage = "resource.preflight"
    _check_directory(src_base, report, source=True)
    _check_directory(output, report, source=False)
    for _, dst, _ in trees:
        check_relative_path(output, dst.relative_to(output), stage=stage,
                            report=report, object=str(dst))
    planned_targets: set[Path] = set()

    def walk(src: Path, dst: Path, executable: bool, ancestors: set[Path], files):
        real_source = src.resolve()
        if real_source in ancestors:
            report.fail("RESOURCE_SOURCE_CYCLE", stage, str(src),
                        "source directory links contain a cycle")
        if any(_overlap(real_source, target) for target in destinations):
            report.fail("RESOURCE_COPY_OVERLAP", stage, str(src),
                        "selected source and destination trees overlap")
        if src.is_dir():
            _check_directory(src, report, source=True)
        else:
            check_input_file(src, stage=stage, report=report)
        check_relative_path(output, dst.relative_to(output), stage=stage,
                            report=report, object=str(dst))
        if src.is_dir():
            _check_directory(dst, report, source=False)
        else:
            check_output_path(dst, stage=stage, report=report)
        if src.is_dir():
            directories.append(dst)
        for child in sorted(src.iterdir()) if src.is_dir() else [src]:
            if keep is not None and not keep(child.relative_to(src_base)):
                continue
            target = dst / child.name
            if not src.is_dir():
                target = dst
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
            files.append((child, target, 0o755 if executable else 0o644))

    plans = []
    for src, dst, executable in trees:
        files: list[_CopyFile] = []
        walk(src, dst, executable, set(), files)
        plans.append(files)
    report.passed("RESOURCE_PREFLIGHT", stage, str(src_base),
                  "selected resource sources and output paths checked before copying")
    return plans


def _check_copy_targets(plans: list[list[_CopyFile]], report: GenerationCheckReport,
                        directories: tuple[Path, ...] = ()) -> None:
    # Resolved names do not reveal hard links. Check existing file identities
    # across the whole plan so an earlier write cannot alter a later source.
    stage = "resource.preflight"
    source_ids = set()
    targets = set()
    for files in plans:
        for source, target, _ in files:
            metadata = source.stat()
            source_ids.add((metadata.st_dev, metadata.st_ino))
            targets.add(target)  # successive layers can write the same named target
    file_paths = {target.resolve() for target in targets}
    for directory in directories:
        if directory.resolve() in file_paths:
            report.fail("RESOURCE_OUTPUT_COLLISION", stage, str(directory),
                        "resource layers map a file and a directory to the same output")
    target_ids = set()
    for target in sorted(targets):
        if any(parent in file_paths for parent in target.resolve().parents):
            report.fail("RESOURCE_OUTPUT_COLLISION", stage, str(target),
                        "a resource output needs a directory occupied by another selected file")
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


def copy_resource_entries(
    output_repo_base: Path, src_base: Path,
    entries: list[tuple[str, str, bool]], *,
    keep: Callable[[Path], bool] | None = None,
    check_report: GenerationCheckReport | None = None,
    check_target: Callable[[Path], None] | None = None,
    source_layer: str | None = None,
) -> None:
    """Copy declared selected mappings with exact standard permissions.

    Entries are source-relative, destination-relative and executable. The
    caller resolves optional/required entries across layers. Original copy
    exceptions and partial invocation artifacts survive failures.
    """
    report = check_report if check_report is not None else GenerationCheckReport()
    _copy_resource_layers(output_repo_base, [(source_layer, src_base, entries)], keep=keep,
                          check_report=report, check_target=check_target)


def _copy_resource_layers(
    output_repo_base: Path, layers: list[tuple[str | None, Path, list[tuple[str, str, bool]]]], *,
    keep: Callable[[Path], bool] | None, check_report: GenerationCheckReport,
    check_target: Callable[[Path], None] | None = None,
    after_layer: Callable[[], None] | None = None,
) -> None:
    """Plan every selected layer before writing any of its override targets."""
    layer_trees = []
    destinations = set()
    for name, root, entries in layers:
        trees = []
        for source, destination, executable in entries:
            src = check_relative_path(root, source, stage="resource.preflight", report=check_report)
            dst = check_relative_path(output_repo_base, destination, stage="resource.preflight", report=check_report)
            trees.append((src, dst, executable))
            destinations.add(dst.resolve())
        layer_trees.append((name, root, trees))

    layer_plans = []
    for name, root, trees in layer_trees:
        directories = []
        groups = _copy_plan(root, output_repo_base, trees, check_report, keep=keep,
                            directories=directories, destinations=destinations)
        layer_plans.append((name, directories, groups))
    all_groups = [files for _, _, groups in layer_plans for files in groups]
    _check_copy_targets(all_groups, check_report, tuple(path for _, dirs, _ in layer_plans for path in dirs))
    if check_target is not None:
        for files in all_groups:
            for _, target, _ in files:
                check_target(target)
    for name, directories, groups in layer_plans:
        _copy_entry_plan(output_repo_base, directories, groups, check_report, name)
        if after_layer is not None:
            after_layer()


def _copy_entry_plan(output_repo_base: Path, directories: list[Path], plans: list[list[_CopyFile]],
                     check_report: GenerationCheckReport, source_layer: str | None) -> None:
    from takflow._files import file_state, io_failure_reason, make_parents

    for directory in directories:
        make_parents(directory / ".directory", output_repo_base)
    for files in plans:
        for source, target, mode in files:
            before = file_state(target)
            try:
                make_parents(target, output_repo_base)
                shutil.copy2(source, target)
                target.chmod(mode)
            except Exception as error:
                check_report.failed("RESOURCE_COPY_FAILED", "resource.copy", str(target),
                                    io_failure_reason("could not copy resource or set its permissions", error))
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


__all__ = ["copy_resource_entries"]
