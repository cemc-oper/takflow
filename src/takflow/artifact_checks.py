"""Read-only checks of generated files, independent of the generating application."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import stat
from tempfile import TemporaryDirectory

from takflow.checks import GenerationCheckError, check_shell_output


class Unavailable(ValueError):
    """The selected check needs an input or isolation capability that is unavailable."""


@dataclass
class CheckResult:
    checks: list[dict[str, str]] = field(default_factory=list)

    @property
    def passed(self):
        return bool(self.checks) and all(item["status"] == "passed" for item in self.checks)

    def check(self, scope, subject, operation):
        try:
            operation()
            status, reason = "passed", "selected check completed"
        except (ImportError, Unavailable) as error:
            status = "incomplete"
            reason = str(error) if isinstance(error, Unavailable) else "selected native engine is unavailable"
        except GenerationCheckError as error:
            status, reason = "failed", error.diagnostic.reason
        except (ValueError, RuntimeError, OSError, UnicodeError) as error:
            status = "failed"
            reason = str(error) if isinstance(error, InvalidArtifact) else "generated artifact could not be read or was rejected by the selected parser"
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
        return ecflow.Defs(str(path))
    if mode == "takler":
        from takler.serialization.builder import build_definition
        return build_definition(path.read_bytes())
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
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise InvalidArtifact("artifact inventory is missing or invalid") from error
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

    def read_definition():
        path = definition_input()
        return _parse(path, engine(path))

    if parse:
        subject = definition or manifest or "definition"
        result.check("definition", subject, read_definition)
    for task in expand:
        def expand_task():
            recorded = get_inventory()
            path = definition_input()
            from takflow._native_artifacts import expand_ecflow, expand_takler
            with TemporaryDirectory(prefix="takflow-check-") as directory:
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
