"""Exercise the CI gate against real pytest sessions, including green skips."""
from pathlib import Path
import os
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_contract_tests.py"


def run_probe(tmp_path, body, required, options=(), *, allow_optional_skips=False, expected_count=None):
    (tmp_path / "test_probe.py").write_text(body + "\n")
    code = (
        "import importlib.util, pytest\n"
        f"spec = importlib.util.spec_from_file_location('contract_gate', {str(SCRIPT)!r})\n"
        "module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)\n"
        f"gate = module.ContractGate(['test_probe.py::{required}'], "
        f"allow_optional_skips={allow_optional_skips!r}, expected_count={expected_count!r})\n"
        f"raise SystemExit(pytest.main({['test_probe.py', '-q', *options]!r}, plugins=[gate]))\n"
    )
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_ADDOPTS": ""}
    return subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, text=True, capture_output=True)


@pytest.mark.parametrize("body,required,options,expected", [
    ("def test_required(): pass", "test_required", [], 0),
    ("def test_other(): pass", "test_required", [], 1),
    ("import pytest\n@pytest.mark.skip\ndef test_required(): pass", "test_required", [], 1),
    ("import pytest\npytest.skip('dependency missing', allow_module_level=True)", "test_required", [], 5),
    ("import pytest\n@pytest.mark.xfail\ndef test_required(): assert False", "test_required", [], 1),
    ("import pytest\n@pytest.mark.xfail\ndef test_required(): pass", "test_required", [], 1),
    ("def test_required(): pass\ndef test_other(): pass", "test_required", ["-k", "required"], 1),
    ("def test_required(): assert False", "test_required", [], 1),
])
def test_contract_gate_requires_actual_execution(tmp_path, body, required, options, expected):
    result = run_probe(tmp_path, body, required, options)
    assert result.returncode == expected, result.stdout + result.stderr
    assert ("CONTRACT GATE FAILED" in result.stdout) == bool(expected)


def test_base_gate_allows_only_nonrequired_skips(tmp_path):
    body = "import pytest\ndef test_required(): pass\n@pytest.mark.skip\ndef test_optional(): pass"
    result = run_probe(tmp_path, body, "test_required", allow_optional_skips=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("disabled", ["skip", "xfail"])
def test_base_gate_rejects_required_teardown_disabled_after_passing_call(tmp_path, disabled):
    body = ("import pytest\n@pytest.fixture\ndef teardown():\n    yield\n"
            f"    pytest.{disabled}('required teardown was not checked')\n"
            "def test_required(teardown): pass")
    result = run_probe(tmp_path, body, "test_required", allow_optional_skips=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "required test was disabled" in result.stdout


def test_contract_gate_rejects_missing_parameter_cases(tmp_path):
    result = run_probe(tmp_path, "def test_required(): pass", "test_required", expected_count=2)
    assert result.returncode == 1
    assert "expected 2 cases, collected 1" in result.stdout


def test_required_orvix_is_a_dependency_failure_before_collection():
    env = {**os.environ, "ORVIX_BIN": "/nonexistent/tc04-required-orvix", "PYTEST_ADDOPTS": ""}
    result = subprocess.run([sys.executable, str(SCRIPT), "orvix"], env=env, text=True, capture_output=True)
    assert result.returncode == 2
    assert "CONTRACT DEPENDENCY FAILED" in result.stderr
    assert "required orvix executable is unavailable" in result.stderr
