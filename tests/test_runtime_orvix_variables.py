"""ORVIX resource variables must remain adjustable through ecFlow inheritance."""

import pytest

from takflow.backends.ecflow.backend import EcflowBackend
from takflow.backends.runtime import set_runtime
from takflow.config import SlurmWorkload
from takflow.flow import WorkflowEngine
from takflow.jobspec import TaskResource


def test_ecflow_resource_edits_contain_only_supplied_scalars():
    from takflow.backends.runtime import ecflow_resource_variables

    assert ecflow_resource_variables({
        "QUEUE": "normal", "WCKEY": "project", "APPLICATION": None, "MEMORY": "0",
        "NODES": 4, "TASKS_PER_NODE": 64, "REQUEUE": False, "JOB_NAME": "trial forecast",
        "JOB_OUTPUT": "%ECF_JOBOUT%.%j", "JOB_ERROR": "/log/%A_%a.err", "HH": "00",
    }) == {
        "QUEUE": "normal", "WCKEY": "project", "MEMORY": "0", "NODES": 4,
        "TASKS_PER_NODE": 64, "REQUEUE": "false", "JOB_NAME": "trial forecast",
        "JOB_OUTPUT": "%ECF_JOBOUT%.%%j", "JOB_ERROR": "/log/%%A_%%a.err", "HH": "00",
    }


@pytest.mark.parametrize("scheduler", ["slurm", "donau"])
@pytest.mark.parametrize("application", [None, "GRAPES"])
@pytest.mark.parametrize(("job_type", "queue", "expected_queue"), [
    ("serial", None, None),
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
    if expected_queue is None:
        assert "edit QUEUE " not in task_definition
    else:
        assert f"edit QUEUE '{expected_queue}'" in task_definition
    assert f"edit ORVIX_SCHEDULER '{scheduler}'" in defaults
    assert "edit ORVIX_SCHEDULER " not in task_definition
    assert "edit ECF_JOB_CMD " not in task_definition
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
    assert "edit ECF_JOB_CMD " in text
    assert "edit WCKEY 'project'" in text
    for variable in ("WALLTIME", "NODES", "TASKS_PER_NODE"):
        assert f"edit {variable} " not in text


@pytest.mark.parametrize("carrier", ["orvix", "slsubmit6"])
def test_carrier_scope_and_explicit_local_declarations(tmp_path, carrier):
    from takflow.backends.runtime import set_resource_variables

    engine = WorkflowEngine(EcflowBackend())
    suite = engine.Suite("suite")
    set_runtime(suite, SlurmWorkload(project="forecast", submit_carrier=carrier), engine)
    family = suite.add_family("model")
    set_resource_variables(family, TaskResource(
        job_type="parallel", queue="batch", nodes=4, ntasks_per_node=32,
        time="02:00:00", memory="8G",
    ))
    set_resource_variables(family.add_task("inherited"), TaskResource(time="00:40:00", memory=None))
    set_resource_variables(family.add_task("fixed"), TaskResource(
        job_type="parallel", queue="batch", nodes=4, requeue=True,
    ))
    path = tmp_path / "suite.def"
    engine.save_suite(suite, path)
    parents, children = path.read_text().split("task inherited\n")
    inherited, fixed = children.split("task fixed\n")
    assert "edit ECF_JOB_CMD " in parents and "edit WCKEY 'forecast'" in parents
    assert "edit QUEUE 'batch'" in parents and "edit MEMORY '8G'" in parents
    assert "edit WALLTIME '00:40:00'" in inherited
    assert "edit QUEUE 'batch'" in fixed and "edit NODES '4'" in fixed
    assert "edit REQUEUE 'true'" in fixed and "edit REQUEUE " not in inherited
    for key in ("QUEUE", "MEMORY", "NODES", "TASKS_PER_NODE"):
        assert f"edit {key} " not in inherited
    for key in ("ECF_JOB_CMD", "ECF_KILL_CMD", "WCKEY", "ORVIX_SCHEDULER"):
        assert f"edit {key} " not in children
