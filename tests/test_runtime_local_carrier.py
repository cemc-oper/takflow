"""set_runtime 本地任务(shell workload)按载体分派的测试。"""
from pathlib import Path

from takflow.backends.ecflow.backend import EcflowBackend
from takflow.backends.runtime import set_runtime
from takflow.config.workload import ShellWorkload, SlurmWorkload
from takflow.flow.node import WorkflowEngine


def _ecflow_engine() -> WorkflowEngine:
    return WorkflowEngine(EcflowBackend())


def _render_task_def(workload) -> str:
    """Build suite/task, apply set_runtime, and return the .def text."""
    engine = _ecflow_engine()
    suite = engine.Suite("s")
    task = suite.add_task("t")
    set_runtime(task, workload, engine=engine)
    out = Path("/tmp/takflow_test_local_carrier.def")
    engine.save_suite(suite, out)
    return out.read_text()


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
    def test_orvix_carrier_uses_orvix_local(self):
        defs = _render_task_def(ShellWorkload(submit_carrier="orvix"))
        assert "orvix submit --scheduler %ORVIX_SCHEDULER% %ECF_JOB%" in defs
        assert "orvix kill %ECF_JOB%.info.yaml" in defs
        assert "ORVIX_SCHEDULER 'local'" in defs
        assert "%ECF_JOB% 1> %ECF_JOBOUT%" not in defs

    def test_direct_carrier_keeps_plain_commands(self):
        defs = _render_task_def(ShellWorkload())
        assert "%ECF_JOB% 1> %ECF_JOBOUT% 2>&1" in defs
        assert "kill -15 %ECF_RID%" in defs
        assert "ORVIX" not in defs
