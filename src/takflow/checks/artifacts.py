"""Check generated definitions, scripts, and recorded artifacts."""
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
from tempfile import TemporaryDirectory

from takflow._files import io_failure_reason
from takflow.checks.diagnostics import GenerationCheckError, GenerationCheckReport
from takflow.checks.preflight import check_input_file


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
        from takflow.flow.backends.ecflow.serializer import Defs

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
            from takflow.flow.backends.ecflow.serializer.attributes import _native_variable_quotes
            token = _native_variable_quotes.set(True)
            try:
                native_expected = Defs(suite.raw).to_def()
            finally:
                _native_variable_quotes.reset(token)
            if body(actual) != body(native_expected):
                report.fail("GEN_DEFINITION_INVALID", stage, str(path), "saved ecFlow body differs from the supported serializer encodings")
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
    except UnicodeError:
        report.fail("GEN_SCRIPT_INVALID", stage, str(path), "generated script is not valid UTF-8 text")
    except OSError as error:
        report.unchecked("GEN_INPUT_UNREADABLE", stage, str(path), io_failure_reason("could not read the script", error))
        return report
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
            filename = str(path.resolve())
            try:
                result = subprocess.run([executable_path, "-n", filename],
                                        env={"PATH": os.defpath, "LC_ALL": "C"},
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            except OSError as error:
                report.unchecked("GEN_SHELL_UNAVAILABLE", stage, str(path),
                                 io_failure_reason(f"could not start {shell} for the syntax check", error))
                return report
            if result.returncode:
                # Shells may echo the entire offending line. Keep only their numeric location.
                stderr = result.stderr.decode("utf-8", errors="replace")
                location = re.search(r"^(?:E: )?" + re.escape(filename) +
                                     r"(?:: (?:line |syntax error at line )?|\[)([0-9]+)\b", stderr, re.MULTILINE)
                if result.returncode in (1, 2, 3) and (location or "syntax error" in stderr.lower()):
                    where = f" at line {location[1]}" if location else ""
                    report.fail("GEN_SCRIPT_SYNTAX", stage, str(path), f"{shell} rejected script syntax{where}")
                report.unchecked("GEN_SHELL_INCOMPLETE", stage, str(path),
                                 f"{shell} did not complete the syntax check (return code {result.returncode})")
                return report
            report.passed("GEN_SHELL_SYNTAX_VALID", stage, str(path), f"{shell} syntax-only check completed; business commands were not run")
    return report


class Unavailable(ValueError):
    """The selected check needs an input or isolation capability that is unavailable."""


@dataclass
class CheckResult:
    checks: list[dict[str, str]] = field(default_factory=list)

    @property
    def passed(self):
        return bool(self.checks) and all(item["status"] == "passed" for item in self.checks)

    def check(self, scope, subject, operation, *, resolve=None):
        try:
            if resolve is None:
                operation()
            else:
                subject = resolve()
                operation(subject)
            status, reason = "passed", "selected check completed"
        except (ImportError, Unavailable) as error:
            status = "incomplete"
            reason = str(error) if isinstance(error, Unavailable) else "selected native engine is unavailable"
        except GenerationCheckError as error:
            status = "incomplete" if error.diagnostic.code == "GEN_INPUT_UNREADABLE" else "failed"
            reason = error.diagnostic.reason
        except InvalidArtifact as error:
            status, reason = "failed", str(error)
        except UnicodeError:
            status, reason = "failed", "generated artifact is not valid UTF-8"
        except OSError as error:
            status, reason = "incomplete", io_failure_reason("could not access files or run the selected check", error)
        except Exception:
            status, reason = "incomplete", "selected check could not complete"
        self.checks.append({"scope": scope, "object": str(subject), "status": status, "reason": reason})

    def as_dict(self):
        return {"passed": self.passed, **asdict(self)}


class InvalidArtifact(ValueError):
    """A controlled diagnostic about an output, without its contents."""


class Inventory:
    """Paths explicitly owned by the build. Never resolve provenance or external references."""

    def __init__(self, manifest):
        self.path = Path(manifest).absolute()
        data = json.loads(self.path.read_bytes())
        if not isinstance(data, dict) or not isinstance(data.get("artifacts"), list) or not data["artifacts"]:
            raise InvalidArtifact("invalid artifact inventory")
        self.root = self.path.parent
        self.original = Path(data["output_root"])
        if not self.original.is_absolute() or ".." in self.original.parts:
            raise InvalidArtifact("invalid recorded output root")
        self.files = {}
        for item in data["artifacts"]:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise InvalidArtifact("invalid artifact entry")
            if item.get("kind") == "reference":
                continue
            path = Path(item["path"])
            if not path.is_absolute() or ".." in path.parts:
                raise InvalidArtifact("invalid recorded artifact path")
            if not path.is_relative_to(self.original):
                # The definition can be explicitly written outside the output root.
                if item.get("role") == "definition" and path == Path(data["workflow_output"]):
                    self.files[path] = item
                    continue
                raise InvalidArtifact("artifact path is outside its output root")
            self.files[path] = item
        self.definition = Path(data["workflow_output"]) if data.get("workflow_output") else None
        self.mode = data.get("mode")

    def local(self, path):
        path = Path(path)
        if path not in self.files:
            raise Unavailable("required file is outside the recorded outputs: " + str(path))
        target = self.root / path.relative_to(self.original) if path.is_relative_to(self.original) else path
        base = self.root if path.is_relative_to(self.original) else target.parent
        if not target.resolve().is_relative_to(base.resolve()) or target.is_symlink():
            raise Unavailable("recorded file resolves outside the selected outputs or through a file link: " + str(path))
        if not target.is_file():
            raise InvalidArtifact("recorded output is missing: " + str(path))
        return target

    def select(self, candidates):
        for path in candidates:
            if path in self.files:
                return path
        raise Unavailable("required template or include is outside the recorded outputs: " +
                          str(next(iter(candidates), "(no local candidate)")))

    def integrity(self):
        if not self.files:
            raise Unavailable("inventory contains no local outputs to verify")
        for path, item in self.files.items():
            actual = self.local(path)
            if item.get("mutable"):
                continue
            if item.get("mode") != oct(stat.S_IMODE(actual.stat().st_mode)):
                raise InvalidArtifact("output permissions differ from the recorded mode: " + str(path))
            if not item.get("sensitive") and item.get("sha256") != hashlib.sha256(actual.read_bytes()).hexdigest():
                raise InvalidArtifact("output content differs from the recorded digest: " + str(path))


def _parse(path, mode):
    if mode == "ecflow":
        import ecflow
        try:
            return ecflow.Defs(str(path))
        except RuntimeError as error:
            # ecFlow uses RuntimeError for both open and parse failures.
            try:
                with path.open("rb"):
                    pass
            except FileNotFoundError:
                raise InvalidArtifact("selected definition was not found") from error
            except (IsADirectoryError, NotADirectoryError):
                raise InvalidArtifact("selected definition is not a regular file") from error
            message = str(error)
            location = re.search(r" around line number (\d+)\b", message)
            if message.startswith("Error: Expression node tree references failed"):
                reason = "ecFlow could not resolve a node reference"
            else:
                reason = "ecFlow rejected the definition"
            if location:
                reason += f" at line {location[1]}"
            raise InvalidArtifact(reason) from error
    if mode == "takler":
        from takler.schema.definition import DefinitionError
        from takler.serialization.builder import build_definition
        try:
            return build_definition(path.read_bytes())
        except FileNotFoundError as error:
            raise InvalidArtifact("selected definition was not found") from error
        except (IsADirectoryError, NotADirectoryError) as error:
            raise InvalidArtifact("selected definition is not a regular file") from error
        except DefinitionError as error:
            raise InvalidArtifact(f"takler rejected the definition: {error.code} at {error.document_path}") from error
    raise Unavailable("select ecflow or takler for a native definition check")


def _shell(path):
    report = check_shell_output(path)
    if not any(item.code == "GEN_SHELL_SYNTAX_VALID" for item in report.checks):
        raise Unavailable(next((item.reason for item in reversed(report.checks) if item.status == "unchecked"),
                               "concrete shell syntax could not be checked"))


def check_artifacts(*, manifest=None, definition=None, mode=None, parse=False, expand=(), shell=(), integrity=False):
    """Check only the requested scopes. Expand absolute task paths in private temporary directories."""
    result = CheckResult()
    inventory = None

    def get_inventory():
        nonlocal inventory
        if manifest is None:
            raise Unavailable("this check requires a build artifact inventory")
        if inventory is None:
            try:
                inventory = Inventory(manifest)
            except InvalidArtifact:
                raise
            except FileNotFoundError as error:
                raise InvalidArtifact("selected artifact inventory was not found") from error
            except (IsADirectoryError, NotADirectoryError) as error:
                raise InvalidArtifact("selected artifact inventory is not a regular file") from error
            except (ValueError, KeyError, TypeError) as error:
                raise InvalidArtifact("invalid artifact inventory") from error
        return inventory

    def definition_input():
        if definition is not None:
            return Path(definition)
        recorded = get_inventory()
        if not recorded.definition:
            raise Unavailable("a generated definition is required")
        return recorded.local(recorded.definition)

    def engine(path):
        return mode or (inventory.mode if inventory else None) or {".def": "ecflow", ".json": "takler"}.get(path.suffix)

    def read_definition(path):
        return _parse(path, engine(path))

    if parse:
        subject = definition or manifest or "definition"
        result.check("definition", subject, read_definition, resolve=definition_input)
    for task in expand:
        def expand_task():
            recorded = get_inventory()
            path = definition_input()
            from takflow.checks._native import expand_ecflow, expand_takler
            try:
                scratch = TemporaryDirectory(prefix="takflow-check-")
            except OSError as error:
                raise Unavailable(io_failure_reason("could not create the temporary directory for native expansion", error)) from error
            with scratch as directory:
                if engine(path) == "takler":
                    expand_takler(path, task, recorded, Path(directory))
                elif engine(path) == "ecflow":
                    expand_ecflow(_parse(path, "ecflow"), task, recorded, Path(directory))
                else:
                    raise Unavailable("native expansion requires ecflow or takler")
        result.check("expand", task, expand_task)
    for path in shell:
        result.check("shell", path, lambda: _shell(path))
    if integrity:
        def compare():
            get_inventory().integrity()
        result.check("integrity", manifest or "manifest", compare)
    if not result.checks:
        raise ValueError("select at least one artifact check")
    return result
