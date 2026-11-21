"""Workflow-aware ORVIX rendering is a framework default, independent of apps."""

import re

import pytest

from takflow.build import BuildError, run_stage
from takflow.config import BaseWorkflowConfig
from takflow.toolkit.job import render_jobs_from_directory, render_orvix_resource_block

from test_build import application, data, put
from test_build import resources as resources


@pytest.mark.parametrize("entry", ["directory", "job", "config"])
@pytest.mark.parametrize("mode", ["ecflow", "shell", "takler"])
@pytest.mark.parametrize(("label", "template_default"), [
    (None, False), ("configured-app", False), (None, True),
])
def test_orvix_helper_uses_workflow_resource_policy(
    tmp_path, resources, entry, mode, label, template_default,
):
    label_expression = (
        'config.workload.application | default("template-app", true)'
        if template_default else "config.workload.application"
    )
    template = (
        '#!/bin/sh\n{{ render_orvix_resource_block(job_type="parallel", '
        'queue=config.workload.default_parallel_queue, nodes=2, ntasks_per_node=4, '
        'time="00:30:00", wckey=config.workload.wckey, application='
        + label_expression + ') }}\n'
    )
    relative = "config/config.sh.j2" if entry == "config" else "jobs/on/task.sh.j2"
    put(resources, relative, template)
    output = tmp_path / "out"
    raw = data(output, mode=mode, workload={
        "workload_type": "slurm", "wckey": "project-value", "application": label,
        "default_serial_queue": "serial-value", "default_parallel_queue": "parallel-value",
    })
    suffix = "ecf" if mode == "ecflow" else "sh"
    if entry == "directory":
        render_jobs_from_directory(
            BaseWorkflowConfig(**raw), str(resources), str(output),
            template_filter=lambda path: path.parts[0] == "on",
        )
        rendered = (output / f"jobs/on/task.{suffix}").read_text()
    else:
        with application(resources).prepare(raw) as context:
            run_stage(context, "resource")
            if entry == "job":
                run_stage(context, "config")
            run_stage(context, entry)
            path = context.paths.config_file if entry == "config" else output / f"jobs/on/task.{suffix}"
            rendered = path.read_text()

    if mode == "ecflow":
        assert "#ORVIX nodes=%NODES:2%" in rendered
        assert "#ORVIX ntasks-per-node=%TASKS_PER_NODE:4%" in rendered
        assert "#ORVIX time=%WALLTIME:00:30:00%" in rendered
        assert "#ORVIX queue=%QUEUE%" in rendered
        assert "#ORVIX project=%WCKEY%" in rendered
        if label is not None:
            assert "#ORVIX application=%APPLICATION%" in rendered
        elif template_default:
            assert "#ORVIX application=%APPLICATION:template-app%" in rendered
        else:
            assert "#ORVIX application=" not in rendered
    else:
        assert "#ORVIX nodes=2" in rendered
        assert "#ORVIX ntasks-per-node=4" in rendered
        assert "#ORVIX time=00:30:00" in rendered
        assert "#ORVIX queue=parallel-value" in rendered
        assert "#ORVIX project=project-value" in rendered
        if label is not None or template_default:
            assert f"#ORVIX application={label or 'template-app'}" in rendered
        else:
            assert "#ORVIX application=" not in rendered


@pytest.mark.parametrize("job_type", ["serial", "parallel"])
def test_ecflow_optional_layout_and_walltime_alias(job_type):
    omitted = render_orvix_resource_block(job_type=job_type, workflow_mode="ecflow")
    assert "#ORVIX time=" not in omitted
    assert "#ORVIX nodes=" not in omitted
    assert "#ORVIX ntasks-per-node=" not in omitted
    explicit = render_orvix_resource_block(
        job_type=job_type, nodes=2, ntasks_per_node=8,
        walltime="00:45:00", workflow_mode="ecflow",
    )
    assert "#ORVIX time=%WALLTIME:00:45:00%" in explicit
    if job_type == "serial":
        assert "#ORVIX nodes=" not in explicit
        assert "#ORVIX ntasks-per-node=" not in explicit
    else:
        assert "#ORVIX nodes=%NODES:2%" in explicit
        assert "#ORVIX ntasks-per-node=%TASKS_PER_NODE:8%" in explicit


@pytest.mark.parametrize(("name", "alias"), [
    ("queue", "partition"), ("time", "walltime"), ("project", "wckey"),
])
def test_resource_helper_resolves_one_name_per_pair(name, alias):
    canonical = render_orvix_resource_block(**{name: "one", alias: None})
    assert f"#ORVIX {name}=one" in canonical.splitlines()
    assert render_orvix_resource_block(**{name: None, alias: "one"}) == canonical
    for other in ("one", "two"):
        with pytest.raises(ValueError, match=f"{name}.*{alias}"):
            render_orvix_resource_block(**{name: "one", alias: other})


@pytest.mark.parametrize(("name", "alias"), [("queue", "partition"), ("time", "walltime")])
def test_resource_helper_reports_blank_spelling_before_fallback(name, alias):
    for blank, other in ((name, alias), (alias, name)):
        with pytest.raises(ValueError, match=blank):
            render_orvix_resource_block(**{blank: "  ", other: "valid"})


def test_optional_resource_values_reach_directives():
    lines = render_orvix_resource_block(time="0", memory="0", requeue=False).splitlines()
    assert {"#ORVIX time=0", "#ORVIX memory=0", "#ORVIX requeue=false"} <= set(lines)
    assert not any(line.startswith("#ORVIX project=") for line in lines)
    assert "#ORVIX project=" in render_orvix_resource_block(project="").splitlines()
    with pytest.raises(ValueError, match="memory"):
        render_orvix_resource_block(memory=" ")
    with pytest.raises(ValueError):
        render_orvix_resource_block(nodes=1.5)


@pytest.mark.parametrize(("arguments", "error"), [
    ('queue="q", partition="q"', "queue.*partition"),
    ('time="a", walltime="b"', "time.*walltime"),
    ('project="p", wckey="p"', "project.*wckey"),
    ('queue=" "', "queue"), ('partition=""', "partition|queue"),
    ('project="p", partition="q"', None),
])
def test_ecflow_template_validates_inputs_before_binding_node_variables(tmp_path, resources, arguments, error):
    put(resources, "jobs/on/task.sh.j2", "#!/bin/sh\n{{ render_orvix_resource_block(" + arguments + ") }}\n")
    output = tmp_path / "out"
    raw = data(output, mode="ecflow", workload={"workload_type": "slurm", "wckey": "p"})
    with application(resources).prepare(raw) as context:
        run_stage(context, "resource")
        run_stage(context, "config")
        if error:
            with pytest.raises(BuildError) as caught:
                run_stage(context, "job")
            assert isinstance(caught.value.original, ValueError)
            assert re.search(error, str(caught.value.original))
        else:
            run_stage(context, "job")
            lines = (output / "jobs/on/task.ecf").read_text().splitlines()
            assert lines.count("#ORVIX project=%WCKEY%") == lines.count("#ORVIX queue=%QUEUE%") == 1
