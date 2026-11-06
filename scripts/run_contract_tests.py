#!/usr/bin/env python3
"""Run a declared CI contract suite and reject missing or disabled checks."""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "base": (
        "tests/test_serialize_ecflow.py::test_suite_family_task_round_trip",
        "tests/test_jobspec.py::test_pydantic_fields_match_schema",
        "tests/test_config_validation.py::test_compatibility_ignores_extra_without_mutating_input",
        "tests/test_generation.py::test_definition_default_output_and_result[ecflow]",
        "tests/test_generation.py::test_missing_takler_dependency_is_not_wrapped",
    ),
    "orvix": tuple(f"tests/test_conformance.py::{name}" for name in (
        "test_rendered_script_matches_committed_vector",
        "test_orvix_generate_matches_golden",
    )),
    "takler": tuple(f"tests/test_takler_current_contract.py::{name}" for name in (
        "test_backend_does_not_create_legacy_application_bunch",
        "test_suite_name_is_caller_supplied",
        "test_saved_suite_builds_and_loads_current_definition",
        "test_rendered_orvix_commands_bind_attempt_and_quote_paths",
        "test_real_orvix_generate_accepts_rendered_job_without_submit",
        "test_scheduler_orvix_commands_render_without_submission",
        "test_legacy_carrier_commands_render_without_submission",
        "test_unsupported_attributes_fail_with_stable_errors",
    )),
    "native": tuple(f"tests/test_native_ecflow_contract.py::{name}" for name in (
        "test_native_ecflow_parses_takflow_definition",
        "test_native_ecflow_preprocesses_job_without_running_it",
        "test_native_ecflow_rejects_missing_job_include",
    )),
}


def matches(nodeid: str, required: str) -> bool:
    return nodeid == required or nodeid.startswith(required + "[")


class ContractGate:
    """A green pytest exit is insufficient when required tests did not pass."""

    def __init__(self, required, *, allow_optional_skips=False, expected_count=None):
        self.required = tuple(required)
        self.allow_optional_skips = allow_optional_skips
        self.expected_count = expected_count
        self.passed = set()
        self.disabled = set()
        self.collected = 0
        self.deselected = 0
        self.errors = []

    def pytest_collection_finish(self, session):
        self.collected = len(session.items)
        ids = [item.nodeid for item in session.items]
        self.errors.extend(f"required test not collected: {name}" for name in self.required
                           if not any(matches(nodeid, name) for nodeid in ids))
        if self.expected_count is not None and self.collected != self.expected_count:
            self.errors.append(f"expected {self.expected_count} cases, collected {self.collected}")

    def pytest_deselected(self, items):
        self.deselected += len(items)

    def pytest_collectreport(self, report):
        if report.skipped:
            self.disabled.add(report.nodeid)

    def pytest_runtest_logreport(self, report):
        if report.skipped or hasattr(report, "wasxfail"):
            self.disabled.add(report.nodeid)
        elif report.when == "call" and report.passed:
            self.passed.add(report.nodeid)

    def pytest_sessionfinish(self, session, exitstatus):
        self.errors.extend(f"required test did not pass: {name}" for name in self.required
                           if not any(matches(nodeid, name) for nodeid in self.passed))
        self.errors.extend(f"required test was disabled: {nodeid}" for nodeid in sorted(self.disabled)
                           if any(matches(nodeid, name) for name in self.required))
        if not self.allow_optional_skips and self.disabled:
            self.errors.append("required suite contains skipped or xfailed checks: " + ", ".join(sorted(self.disabled)))
        if not self.collected or self.deselected:
            self.errors.append(f"invalid collection: {self.collected} collected, {self.deselected} deselected")
        if self.errors and exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_terminal_summary(self, terminalreporter):
        for error in self.errors:
            terminalreporter.write_line("CONTRACT GATE FAILED: " + error, red=True)
        if not self.errors:
            terminalreporter.write_line(
                f"Contract gate: {len(self.required)} required checks passed; "
                f"{self.collected} collected; {len(self.disabled)} optional skips/xfails recorded"
            )


def preflight(suite):
    if suite == "base":
        for module in ("takler", "ecflow"):
            if importlib.util.find_spec(module) is not None:
                raise RuntimeError(f"base suite requires {module} to be absent")
    if suite in ("orvix", "takler"):
        binary = shutil.which(os.environ.get("ORVIX_BIN", "orvix"))
        if binary is None:
            raise RuntimeError("required orvix executable is unavailable; set ORVIX_BIN")
        os.environ["ORVIX_BIN"] = str(Path(binary).resolve())
        print(f"Required orvix binary: {os.environ['ORVIX_BIN']}", flush=True)
    if suite == "takler":
        repository = os.environ.get("TAKLER_REPO")
        if not repository:
            raise RuntimeError("set TAKLER_REPO to the checkout installed with its locked dependencies")
        repository = Path(repository).resolve()
        pin = (ROOT / "src/takflow/spec/takler/TAKLER_VERSION").read_text().strip()
        revision = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()
        if revision != pin:
            raise RuntimeError(f"takler checkout does not match TAKLER_VERSION: {revision}")
        if subprocess.check_output(["git", "-C", str(repository), "status", "--porcelain", "--untracked-files=no"], text=True):
            raise RuntimeError("takler checkout contains tracked changes")
        takler = importlib.import_module("takler")
        importlib.import_module("takler.server.scheduler")
        if not Path(takler.__file__).resolve().is_relative_to(repository / "src"):
            raise RuntimeError("imported takler does not originate from TAKLER_REPO")
        print(f"Required takler revision: {revision}; import: {takler.__file__}", flush=True)
    if suite == "native":
        ecflow = importlib.import_module("ecflow")
        if ecflow.__version__ != "5.12.0":
            raise RuntimeError(f"native suite requires ecFlow 5.12.0, got {ecflow.__version__}")
        print(f"Required native ecFlow: {ecflow.__file__}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=REQUIRED)
    args = parser.parse_args()
    os.chdir(ROOT)
    try:
        preflight(args.suite)
        required = REQUIRED[args.suite]
        for name in required:
            if not (ROOT / name.split("::", 1)[0]).is_file():
                raise RuntimeError(f"required test file is missing: {name}")
    except (ImportError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"CONTRACT DEPENDENCY FAILED: {error}", file=sys.stderr)
        return 2
    expected = None
    if args.suite == "orvix":
        from takflow.spec.jobspec.conformance import CASES, SCHEDULERS
        expected = len(CASES) * (1 + len(SCHEDULERS))
    elif args.suite == "takler":
        expected = 11
    elif args.suite == "native":
        expected = 3
    targets = ["tests"] if args.suite == "base" else sorted({name.split("::", 1)[0] for name in required})
    gate = ContractGate(required, allow_optional_skips=args.suite == "base", expected_count=expected)
    return int(pytest.main([*targets, "-v", "-ra"], plugins=[gate]))


if __name__ == "__main__":
    raise SystemExit(main())
