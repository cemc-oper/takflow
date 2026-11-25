"""Generation checks, diagnostics, and read-only artifact verification."""
from takflow.checks.artifacts import CheckResult, check_artifacts, check_definition_output, check_shell_output
from takflow.checks.diagnostics import (
    GenerationCheckError, GenerationCheckReport, GenerationDiagnostic, GenerationInputError,
)
from takflow.checks.preflight import (
    check_input_file, check_output_path, check_relative_path, check_workflow_structure, preflight_generation,
)


__all__ = [
    "GenerationDiagnostic", "GenerationCheckReport", "GenerationCheckError", "GenerationInputError",
    "check_relative_path", "check_input_file", "check_output_path", "preflight_generation",
    "check_workflow_structure", "check_definition_output", "check_shell_output", "CheckResult", "check_artifacts",
]
