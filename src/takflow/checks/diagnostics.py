"""Generation diagnostics and invocation-scoped artifact reports."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
from pathlib import Path
import stat
from traceback import walk_tb
from typing import Any, NoReturn

from jinja2 import TemplateNotFound, TemplateSyntaxError, UndefinedError
from pydantic import ValidationError
from pydantic_core import PydanticCustomError

from takflow._files import io_failure_reason
from takflow.config.validation import validation_diagnostics, validation_reason


def template_failure(template, env, error):
    """Report the selected Jinja source and line without rendering its text or values."""
    subject = str(template)
    line = None
    for frame, number in walk_tb(error.__traceback__):
        if frame.f_globals.get("__jinja_exception__") is error:
            filename = Path(frame.f_code.co_filename)
            for root in getattr(env.loader, "searchpath", ()):
                if filename.is_relative_to(root):
                    subject, line = str(filename.relative_to(root)), number
                    break
    if isinstance(error, TemplateSyntaxError):
        reason = "invalid Jinja template syntax"
        if type(error.lineno) is int:
            line = error.lineno
    elif isinstance(error, TemplateNotFound):
        reason = "required template was not found"
    elif isinstance(error, UndefinedError):
        reason = "template uses an undefined value"
    elif isinstance(error, ValidationError):
        items = validation_diagnostics(error)
        reason = "template input failed validation"
        if items:
            item = items[0]
            reason = f"{'.'.join(map(str, item.path)) or '$'}: {item.reason}"
    elif isinstance(error, PydanticCustomError):
        _, reason = validation_reason(error.type)
    elif isinstance(error, UnicodeError):
        reason = "template input is not valid UTF-8"
    elif isinstance(error, OSError):
        reason = io_failure_reason("template input could not be read", error)
    else:
        reason = "template evaluation failed"
    if line is not None:
        reason = f"line {line}: {reason}"
    return subject, reason


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
        from takflow.checks.preflight import check_input_file

        path = check_input_file(path, stage=stage, report=self)
        record = {"path": str(path), "role": role, "mode": oct(stat.S_IMODE(path.stat().st_mode)),
                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        # A later overlay updates this invocation's record for the same file.
        self.artifacts[:] = [item for item in self.artifacts if item["path"] != str(path)]
        self.artifacts.append(record)

    def as_dict(self) -> dict[str, Any]:
        return {"checks": [asdict(item) for item in self.checks],
                "artifacts": [dict(item) for item in self.artifacts]}
