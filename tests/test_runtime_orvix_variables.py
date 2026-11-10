"""ORVIX resource variables must remain adjustable through ecFlow inheritance."""

import pytest

from takflow.backends.ecflow.backend import EcflowBackend
from takflow.backends.runtime import set_runtime
from takflow.config import SlurmWorkload
from takflow.flow import WorkflowEngine
from takflow.jobspec import TaskResource


@pytest.mark.parametrize("scheduler", ["slurm", "donau"])
@pytest.mark.parametrize("application", [None, "GRAPES"])
@pytest.mark.parametrize(("job_type", "queue", "expected_queue"), [
    ("serial", None, "serial_queue"),
    ("parallel", None, "parallel_queue"),
    ("serial", "custom", "custom"),
    ("parallel", "largemem", "largemem"),
])
def test_ecflow_resource_defaults_and_task_overrides(
    tmp_path, scheduler, application, job_type, queue, expected_queue,
):
    engine = WorkflowEngine(EcflowBackend())
    workload = SlurmWorkload(
        wckey="105-00-01", application=application, scheduler=scheduler,
        default_serial_queue="serial_queue", default_parallel_queue="parallel_queue",
    )
    suite = engine.Suite("s")
    set_runtime(suite, workload, engine)
    task = suite.add_task("t")
    set_runtime(task, workload, engine, TaskResource(
        job_type=job_type, queue=queue, time="01:00:00", nodes=2, ntasks_per_node=8,
    ))
    output = tmp_path / "s.def"
    engine.save_suite(suite, output)

    defaults, task_definition = output.read_text().split("task t\n", 1)
    assert "edit QUEUE 'serial_queue'" in defaults
    assert "edit WCKEY '105-00-01'" in defaults
    assert f"edit QUEUE '{expected_queue}'" in task_definition
    assert f"edit ORVIX_SCHEDULER '{scheduler}'" in task_definition
    assert "edit WALLTIME '01:00:00'" in task_definition
    if job_type == "parallel":
        assert "edit NODES '2'" in task_definition
        assert "edit TASKS_PER_NODE '8'" in task_definition
    else:
        assert "edit NODES " not in task_definition
        assert "edit TASKS_PER_NODE " not in task_definition
    assert "edit WCKEY " not in task_definition
    assert "edit APPLICATION " not in task_definition
    if application is None:
        assert "edit APPLICATION " not in defaults
    else:
        assert "edit APPLICATION 'GRAPES'" in defaults


def test_unset_task_resources_preserve_inherited_or_script_defaults(tmp_path):
    engine = WorkflowEngine(EcflowBackend())
    suite = engine.Suite("s")
    set_runtime(suite, SlurmWorkload(wckey="project"), engine, TaskResource())
    output = tmp_path / "s.def"
    engine.save_suite(suite, output)
    text = output.read_text()
    for variable in ("WALLTIME", "NODES", "TASKS_PER_NODE"):
        assert f"edit {variable} " not in text
