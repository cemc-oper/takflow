"""set_runtime 本地任务(shell workload)按载体分派的测试。"""
import subprocess

import pytest

from takflow.flow.backends.ecflow.backend import EcflowBackend
from takflow.config.workload import ShellWorkload, SlurmWorkload
from takflow.flow.node import WorkflowEngine
from takflow.jobs.submission import set_runtime


def _ecflow_engine() -> WorkflowEngine:
    return WorkflowEngine(EcflowBackend())


def _render_task_def(tmp_path, workload) -> str:
    """Build suite/task, apply set_runtime, and return the .def text."""
    engine = _ecflow_engine()
    suite = engine.Suite("s")
    task = suite.add_task("t")
    set_runtime(task, workload, engine=engine)
    out = tmp_path / "local.def"
    engine.save_suite(suite, out)
    return out.read_text()


def assert_command_argv(command, program, *expected):
    """Execute the engine command in sh with a recorder in place of the carrier."""
    recorder = program + r"""() { printf '%s\0' "$@"; }"""
    result = subprocess.run(["/bin/sh", "-ec", recorder + "\n" + command],
                            env={"PATH": "/dev/null"}, capture_output=True, check=True, timeout=5)
    assert result.stdout == b"".join(str(arg).encode() + b"\0" for arg in expected)


class TestForSuite:
    def test_orvix_suite_maps_to_orvix(self):
        suite_wl = SlurmWorkload(wckey="k", submit_carrier="orvix")
        assert ShellWorkload.for_suite(suite_wl).submit_carrier == "orvix"

    def test_slsubmit6_suite_maps_to_direct(self):
        suite_wl = SlurmWorkload(wckey="k", submit_carrier="slsubmit6")
        assert ShellWorkload.for_suite(suite_wl).submit_carrier == "direct"

    def test_shell_suite_maps_to_direct(self):
        assert ShellWorkload.for_suite(ShellWorkload()).submit_carrier == "direct"

    def test_default_is_direct(self):
        assert ShellWorkload().submit_carrier == "direct"


class TestLocalCarrierDispatch:
    def test_orvix_carrier_uses_orvix_local(self, tmp_path):
        defs = _render_task_def(tmp_path, ShellWorkload(submit_carrier="orvix"))
        assert 'orvix submit --scheduler "%ORVIX_SCHEDULER%" "%ECF_JOB%"' in defs
        assert 'orvix kill "%ECF_JOB%.info.yaml"' in defs
        assert "ORVIX_SCHEDULER 'local'" in defs
        assert "%ECF_JOBOUT%" not in defs

    def test_direct_carrier_keeps_plain_commands(self, tmp_path):
        defs = _render_task_def(tmp_path, ShellWorkload())
        assert '"%ECF_JOB%" 1> "%ECF_JOBOUT%" 2>&1' in defs
        assert "kill -15 %ECF_RID%" in defs
        assert "ORVIX" not in defs

    def test_invalid_local_carrier_cannot_select_direct(self, tmp_path):
        workload = ShellWorkload().model_copy(update={"submit_carrier": "slsubmit6"})
        with pytest.raises(ValueError, match="shell workload.*slsubmit6"):
            _render_task_def(tmp_path, workload)
