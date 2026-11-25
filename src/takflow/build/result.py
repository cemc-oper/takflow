"""Public build results, artifact metadata, and failure reporting."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from takflow.flow.generate import GenerationResult


STAGES = ("resource", "config", "credential", "job", "workflow", "report")


@dataclass
class StageResult:
    name: str
    status: str = "not_run"
    reason: str | None = None
    skipped_outputs: list[str] = field(default_factory=list)


@dataclass
class BuildArtifact:
    path: str
    role: str
    stage: str
    kind: str = "generated"
    mode: str | None = None
    sha256: str | None = None
    mutable: bool = False
    sensitive: bool = False
    sources: list[dict[str, str]] = field(default_factory=list)


@dataclass
class BuildResult:
    mode: str
    output_root: Path
    workflow_output: Path
    scope: str
    build_id: str = field(default_factory=lambda: uuid4().hex)
    complete: bool = False
    manifest_path: Path | None = None
    stages: list[StageResult] = field(default_factory=lambda: [StageResult(name) for name in STAGES])
    artifacts: list[BuildArtifact] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    generation: GenerationResult | None = field(default=None, repr=False)

    def as_dict(self) -> dict[str, Any]:
        """A controlled report: no raw config, credential data or exception text."""
        return {
            "build_id": self.build_id, "scope": self.scope, "complete": self.complete,
            "mode": self.mode, "output_root": str(self.output_root),
            "workflow_output": str(self.workflow_output),
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
            "stages": [asdict(value) for value in self.stages],
            "artifacts": [{key: value for key, value in asdict(item).items()
                           if not (item.sensitive and key == "sha256")} for item in self.artifacts],
            "diagnostics": list(self.diagnostics),
        }


class BuildError(RuntimeError):
    """Safe message with a partial result and the unchanged original exception."""

    def __init__(self, result: BuildResult, original: Exception):
        self.result = result
        self.original = original
        stage = next((item.name for item in result.stages if item.status == "failed"), "build")
        super().__init__(f"[BUILD_FAILED] {stage}: generation failed; partial result and original exception retained")
