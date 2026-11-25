"""Validate workflow capabilities, structure, and local file inputs."""
from __future__ import annotations

import os
from pathlib import Path
import re

from takflow.checks.diagnostics import GenerationCheckReport, GenerationInputError


def check_relative_path(
    root: str | Path, relative: str | Path, *, stage: str,
    report: GenerationCheckReport, object: str | None = None,
) -> Path:
    """Resolve a declared local relative path without escaping its root."""
    root, relative = Path(root), Path(relative)
    subject = object if object is not None else str(relative)
    if any(ord(char) < 32 or ord(char) == 127 for char in str(root) + str(relative)):
        report.fail("GEN_PATH_INVALID", stage, object or "path", "file paths must not contain control characters")
    if relative.is_absolute() or ".." in relative.parts or relative == Path("."):
        report.fail("GEN_PATH_INVALID", stage, subject, "a nonempty relative path without '..' is required")
    path = root / relative
    try:
        contained = path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        contained = False
    if not contained:
        report.fail("GEN_PATH_ESCAPE", stage, subject, "path or symbolic link escapes the declared root")
    report.passed("GEN_PATH_VALID", stage, subject, "relative path remains within the declared root")
    return path


def check_input_file(
    path: str | Path, *, stage: str, report: GenerationCheckReport,
    object: str | None = None, executable: bool = False,
) -> Path:
    """Check an explicitly local file, without executing or sourcing it."""
    path = Path(path)
    subject = object if object is not None else str(path)
    if any(ord(char) < 32 or ord(char) == 127 for char in str(path)):
        report.fail("GEN_PATH_INVALID", stage, object or "path", "file paths must not contain control characters")
    if not path.is_file():
        report.fail("GEN_INPUT_MISSING", stage, subject, "required local file is missing or is not a regular file",
                    error_type=GenerationInputError)
    mode = path.stat().st_mode
    if not mode & 0o444 or not os.access(path, os.R_OK):
        report.fail("GEN_INPUT_UNREADABLE", stage, subject, "required local file is not readable")
    if executable and (not mode & 0o111 or not os.access(path, os.X_OK)):
        report.fail("GEN_INPUT_NOT_EXECUTABLE", stage, subject, "directly invoked local script is not executable")
    report.passed("GEN_INPUT_VALID", stage, subject, "local file and required permissions are available")
    return path


def check_output_path(
    path: str | Path, *, stage: str, report: GenerationCheckReport,
    object: str | None = None,
) -> Path:
    """Check a file destination and existing parent before creating anything."""
    path = Path(path)
    subject = object if object is not None else str(path)
    if any(ord(char) < 32 or ord(char) == 127 for char in str(path)):
        report.fail("GEN_PATH_INVALID", stage, object or "path", "file paths must not contain control characters")
    if path.exists() or path.is_symlink():
        if not path.is_file():
            report.fail("GEN_OUTPUT_NOT_FILE", stage, subject, "file output collides with a non-file destination")
        if not path.stat().st_mode & 0o222 or not os.access(path, os.W_OK):
            report.fail("GEN_OUTPUT_NOT_WRITABLE", stage, subject, "existing output file is not writable")
    parent = path.parent
    while not parent.exists() and not parent.is_symlink():
        parent = parent.parent
    if not parent.is_dir():
        report.fail("GEN_OUTPUT_PARENT_INVALID", stage, subject, "an existing output parent is not a directory")
    if not parent.stat().st_mode & 0o222 or not parent.stat().st_mode & 0o111 or not os.access(parent, os.W_OK | os.X_OK):
        report.fail("GEN_OUTPUT_NOT_WRITABLE", stage, subject, "output parent is not writable and searchable")
    report.passed("GEN_OUTPUT_VALID", stage, subject, "file destination is writable without a type conflict")
    return path


def preflight_generation(
    config, *, supported_modes: tuple[str, ...] = ("ecflow", "takler", "shell"),
    required_operations: tuple[str, ...] = (),
    check_report: GenerationCheckReport | None = None,
) -> GenerationCheckReport:
    """Check known mode/carrier/operation declarations, never infer domains."""
    report = check_report if check_report is not None else GenerationCheckReport()
    stage = "generation.preflight"
    mode = config.workflow_mode
    if mode not in ("ecflow", "takler", "shell"):
        report.fail("GEN_MODE_UNSUPPORTED", stage, "workflow_mode", f"Unsupported workflow_mode: {mode}")
    if mode not in supported_modes:
        report.fail("GEN_MODE_UNSUPPORTED", stage, "workflow_mode", "mode is not supported by this consumer entry point")
    if config.script_invoke_mode not in ("inline", "external"):
        report.fail("GEN_SCRIPT_MODE_UNSUPPORTED", stage, "script_invoke_mode", "script invocation mode is not supported")
    workload = config.workload
    kind = workload.workload_type
    carriers = {"shell": ("direct", "orvix"), "slurm": ("orvix", "slsubmit6")}
    if kind not in carriers:
        report.fail("GEN_WORKLOAD_UNSUPPORTED", stage, "workload.workload_type", "workload type is not supported")
    if workload.submit_carrier not in carriers[kind]:
        report.fail("GEN_CARRIER_UNSUPPORTED", stage, "workload.submit_carrier", "carrier is not supported for this workload")
    if kind == "slurm":
        if workload.scheduler not in ("slurm", "donau"):
            report.fail("GEN_SCHEDULER_UNSUPPORTED", stage, "workload.scheduler", "scheduler is not supported")
        if workload.submit_carrier == "slsubmit6":
            if mode == "takler":
                report.fail("GEN_COMBINATION_UNSUPPORTED", stage, "workload.submit_carrier",
                            "takler does not support slsubmit6. Use orvix for scheduled jobs.")
            if workload.scheduler != "slurm":
                report.fail("GEN_COMBINATION_UNSUPPORTED", stage, "workload", "slsubmit6/sbatch requires the slurm scheduler")
    if mode != "shell":
        from takflow.flow import WorkflowBackend
        if mode == "takler":
            from takflow.flow.backends.takler import TaklerBackend
            unsupported = TaklerBackend.unsupported_operations
        else:
            unsupported = WorkflowBackend.unsupported_operations
        required = set(required_operations)
        if getattr(getattr(config, "scheduling", None), "scheduling_type", None) == "RepeatDay":
            required.add("add_repeat_day")
        for operation in sorted(required):
            if operation not in WorkflowBackend.__abstractmethods__:
                report.fail("GEN_OPERATION_UNKNOWN", stage, operation, "operation is not part of the backend contract")
            if operation in unsupported:
                report.fail("GEN_OPERATION_UNSUPPORTED", stage, operation, "operation is unsupported by the selected backend")
    elif required_operations:
        report.fail("GEN_OPERATION_UNSUPPORTED", stage, "shell", "shell generation does not instantiate a workflow backend")
    report.passed("GEN_CAPABILITIES_VALID", stage, "configuration", "declared generation combination and operations are supported")
    return report


def check_node_name(name, *, report=None, subject="node"):
    if not name or name in (".", "..") or re.search(r"[\s/\\\x00-\x1f\x7f]", name):
        (report or GenerationCheckReport()).fail("GEN_NODE_NAME_INVALID", "definition.preflight", subject,
                                                 "node name is empty or contains path separators, whitespace or controls")


def check_workflow_structure(suite, *, engine=None, check_report: GenerationCheckReport | None = None) -> GenerationCheckReport:
    """Inspect the public node tree, without interpreting scheduling expressions."""
    from takflow.flow import Node, NodeType

    report = check_report if check_report is not None else GenerationCheckReport()
    stage = "definition.preflight"
    if not isinstance(suite, Node) or suite.node_type != NodeType.SUITE or suite.parent is not None:
        report.fail("GEN_SUITE_INVALID", stage, "suite", "builder must return a detached suite Node")
    if engine is not None and suite.engine is not engine:
        report.fail("GEN_TREE_INVALID", stage, "suite", "builder returned a suite from a different engine")
    seen = set()
    stack = [(suite, None, "")]
    while stack:
        node, parent, prefix = stack.pop()
        if id(node) in seen:
            report.fail("GEN_TREE_INVALID", stage, prefix or "suite", "node is cyclic or attached more than once")
        seen.add(id(node))
        name = node.name
        check_node_name(name, report=report, subject=prefix or "suite")
        path = f"{prefix}/{name}"
        if node.parent is not parent or node.engine is not suite.engine:
            report.fail("GEN_TREE_INVALID", stage, path, "node parent or engine does not match its public tree")
        children = node.children
        if node.node_type == NodeType.TASK and children:
            report.fail("GEN_TREE_INVALID", stage, path, "task nodes cannot contain child nodes")
        names = [child.name for child in children]
        if len(names) != len(set(names)):
            report.fail("GEN_NODE_DUPLICATE", stage, path, "sibling node names must be unique")
        stack.extend((child, node, path) for child in reversed(children))
    report.passed("GEN_TREE_VALID", stage, suite.name, "public node names, parents, engines and sibling uniqueness checked")
    report.unchecked("GEN_EXPRESSIONS_UNCHECKED", stage, suite.name, "trigger, complete, event and repeat semantics belong to the native engine; no generic DAG assumption is applied")
    return report
