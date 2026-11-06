"""Generation-time checks with explicit runtime and native-tool boundaries.

Reports describe one invocation. They do not scan a directory to invent a build
manifest, submit jobs, or qualify an application for operational execution.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
from typing import Any, NoReturn


@dataclass(frozen=True)
class GenerationDiagnostic:
    code: str
    stage: str
    object: str
    reason: str
    status: str


class GenerationCheckError(ValueError):
    """An actionable generation failure retaining its invocation's report."""

    def __init__(self, diagnostic: GenerationDiagnostic, report: GenerationCheckReport):
        self.diagnostic = diagnostic
        self.report = report
        super().__init__(f"[{diagnostic.code}] {diagnostic.stage} {diagnostic.object}: {diagnostic.reason}")


class GenerationInputError(GenerationCheckError, FileNotFoundError):
    """A missing generation input, also compatible with FileNotFoundError."""


@dataclass
class GenerationCheckReport:
    """Checks and actual output files; collectors may span several stages."""

    checks: list[GenerationDiagnostic] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    def passed(self, code: str, stage: str, object: str, reason: str) -> None:
        self.checks.append(GenerationDiagnostic(code, stage, str(object), reason, "passed"))

    def unchecked(self, code: str, stage: str, object: str, reason: str) -> None:
        self.checks.append(GenerationDiagnostic(code, stage, str(object), reason, "unchecked"))

    def failed(self, code: str, stage: str, object: str, reason: str) -> GenerationDiagnostic:
        diagnostic = GenerationDiagnostic(code, stage, str(object), reason, "failed")
        self.checks.append(diagnostic)
        return diagnostic

    def fail(
        self, code: str, stage: str, object: str, reason: str,
        *, error_type: type[GenerationCheckError] = GenerationCheckError,
    ) -> NoReturn:
        diagnostic = self.failed(code, stage, object, reason)
        raise error_type(diagnostic, self) from None

    def artifact(self, path: str | Path, role: str, *, stage: str = "generation.output") -> None:
        path = check_input_file(path, stage=stage, report=self)
        record = {"path": str(path), "role": role, "mode": oct(stat.S_IMODE(path.stat().st_mode)),
                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        # A later overlay updates this invocation's record for the same file.
        self.artifacts[:] = [item for item in self.artifacts if item["path"] != str(path)]
        self.artifacts.append(record)

    def as_dict(self) -> dict[str, Any]:
        return {"checks": [asdict(item) for item in self.checks],
                "artifacts": [dict(item) for item in self.artifacts]}


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
        if workload.submit_carrier == "slsubmit6" and workload.scheduler != "slurm":
            report.fail("GEN_COMBINATION_UNSUPPORTED", stage, "workload", "slsubmit6/sbatch requires the slurm scheduler")
    if mode != "shell":
        from takflow.flow import WorkflowBackend
        if mode == "takler":
            from takflow.backends.takler import TaklerBackend
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
    report.unchecked("GEN_RUNTIME_UNCHECKED", stage, "runtime", "scheduler, programs, libraries and remote paths are not executed or probed")
    return report


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
        if not name or name in (".", "..") or re.search(r"[\s/\\\x00-\x1f\x7f]", name):
            report.fail("GEN_NODE_NAME_INVALID", stage, prefix or "suite", "node name is empty or contains path separators, whitespace or controls")
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


def check_definition_output(
    suite, path: str | Path, *, check_report: GenerationCheckReport | None = None,
) -> GenerationCheckReport:
    """Check the file just saved using its serializer/native definition contract."""
    report = check_report if check_report is not None else GenerationCheckReport()
    stage = "definition.output"
    path = check_input_file(path, stage=stage, report=report)
    report.artifact(path, "definition", stage=stage)
    mode = suite.engine.backend_type
    if mode == "ecflow":
        from takflow.backends.ecflow.serializer import Defs

        # Branding callbacks may prepend/append full-line comments. This is a
        # serializer comparison, deliberately not a second ecFlow parser.
        def body(text):
            return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#")).strip("\n")

        try:
            actual = path.read_text(encoding="utf-8")
            expected = Defs(suite.raw).to_def()
        except (OSError, UnicodeError):
            report.fail("GEN_DEFINITION_INVALID", stage, str(path), "definition is not readable UTF-8 text")
        if body(actual) != body(expected):
            report.fail("GEN_DEFINITION_INVALID", stage, str(path), "saved ecFlow body differs from the current serializer output")
        report.passed("GEN_SERIALIZER_VALID", stage, str(path), "saved ecFlow body matches the serializer; full-line branding comments excluded")
        if importlib.util.find_spec("ecflow") is None:
            report.unchecked("GEN_NATIVE_ECFLOW_UNAVAILABLE", stage, str(path), "native ecFlow parsing and job preprocessing were not run")
        else:
            import ecflow
            try:
                ecflow.Defs(str(path))
            except Exception:
                report.fail("GEN_NATIVE_ECFLOW_INVALID", stage, str(path), "native ecFlow rejected the definition")
            report.passed("GEN_NATIVE_ECFLOW_VALID", stage, str(path), "native ecFlow definition parsing completed")
            report.unchecked("GEN_ECFLOW_JOB_UNCHECKED", stage, str(path), "native definition parsing does not create or preprocess task jobs")
    elif mode == "takler":
        from takler.schema.definition import parse_definition
        from takler.serialization.builder import build_definition
        from takler.serialization.definition import export_definition

        try:
            parsed = parse_definition(path.read_bytes())
            rebuilt = build_definition(parsed)
            expected = export_definition(suite.raw).model_dump(mode="json")
        except Exception:
            report.fail("GEN_DEFINITION_INVALID", stage, str(path), "takler definition parse/build rejected the saved file")
        if rebuilt.name != suite.name or json.loads(path.read_bytes()) != expected:
            report.fail("GEN_DEFINITION_INVALID", stage, str(path), "saved takler definition differs from the current exported suite")
        report.passed("GEN_TAKLER_DEFINITION_VALID", stage, str(path), "actual takler definition parse/build completed")
        report.unchecked("GEN_TAKLER_JOB_UNCHECKED", stage, str(path), "definition parsing does not render, submit or schedule runtime jobs")
    else:
        report.fail("GEN_MODE_UNSUPPORTED", stage, "backend", "definition backend is unsupported")
    return report


def check_shell_output(
    path: str | Path, *, check_report: GenerationCheckReport | None = None,
    executable: bool = False, stage: str = "job.output", role: str = "job",
) -> GenerationCheckReport:
    """Run an available declared shell's syntax-only mode on concrete scripts."""
    report = check_report if check_report is not None else GenerationCheckReport()
    path = check_input_file(path, stage=stage, report=report, executable=executable)
    report.artifact(path, role, stage=stage)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        report.fail("GEN_SCRIPT_INVALID", stage, str(path), "generated script is not readable UTF-8 text")
    if not text.strip():
        report.fail("GEN_SCRIPT_INVALID", stage, str(path), "generated script is empty")
    if path.suffix == ".ecf" or "{{" in text or "{%" in text:
        report.unchecked("GEN_RUNTIME_TEMPLATE_UNCHECKED", stage, str(path), "engine directives or runtime template placeholders require native job creation before shell syntax checks")
    else:
        first = text.splitlines()[0]
        try:
            words = shlex.split(first[2:]) if first.startswith("#!") else []
        except ValueError:
            words = []
        if words and Path(words[0]).name == "env":
            words = words[1:]
            if words and words[0] == "-S":
                words = words[1:]
        if len(words) > 1:
            report.unchecked("GEN_SHELL_OPTIONS_UNCHECKED", stage, str(path),
                             "declared interpreter options may change parsing; no startup or command options are executed")
            return report
        shell = Path(words[0]).name if words else ""
        executable_path = shutil.which(shell) if shell in {"sh", "bash", "dash", "ksh", "ksh93", "mksh"} else None
        wrong_ksh_dialect = False
        if executable_path is not None and shell in {"ksh", "ksh93"} and Path(executable_path).resolve().name in {"mksh", "lksh"}:
            # Debian's ksh alternative may be mksh, which cannot parse the
            # Ksh93 syntax used by target applications. It is not a substitute.
            executable_path = shutil.which("ksh93")
            wrong_ksh_dialect = executable_path is None
        if executable_path is None:
            if wrong_ksh_dialect:
                report.unchecked("GEN_SHELL_DIALECT_UNAVAILABLE", stage, str(path), "installed ksh resolves to mksh/lksh; target Ksh93 syntax was not checked")
            else:
                report.unchecked("GEN_SHELL_UNAVAILABLE", stage, str(path), "a supported declared shell interpreter is not available; script was not executed")
        else:
            result = subprocess.run([executable_path, "-n", str(path.resolve())],
                                    env={"PATH": os.defpath, "LC_ALL": "C"},
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if result.returncode:
                report.fail("GEN_SCRIPT_SYNTAX", stage, str(path), "declared shell rejected generated script syntax")
            report.passed("GEN_SHELL_SYNTAX_VALID", stage, str(path), f"{shell} syntax-only check completed; business commands were not run")
    return report


__all__ = ["GenerationDiagnostic", "GenerationCheckReport", "GenerationCheckError",
           "GenerationInputError", "check_relative_path", "check_input_file",
           "check_output_path", "preflight_generation", "check_workflow_structure",
           "check_definition_output", "check_shell_output"]
