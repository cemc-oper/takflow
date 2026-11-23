"""Workflow-aware ORVIX rendering is a framework default, independent of apps."""

import re
import warnings
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

from takflow.build import BuildError, run_stage
from takflow.config import BaseWorkflowConfig
from takflow.config.workload import ResourceAliasWarning
from takflow.toolkit.job import (
    render_jobs_from_directory, render_orvix_resource_block, render_single_job_file, render_slurm_resource_block,
)

from test_build import application, data, put
from test_build import resources as resources


def test_shared_slurm_fields_and_local_defaults():
    fields = dict(job_type="parallel", queue="research", nodes=3, ntasks_per_node=11,
                  time="01:23:00", memory="0", project="project one", application="model",
                  job_name="trial forecast", output="/logs/trial %j.out", error="/logs/trial %j.err")
    lines = render_slurm_resource_block(**fields, requeue=False, exclusive=True).splitlines()
    assert lines == [
        '#SBATCH --job-name="trial forecast"', '#SBATCH --output="/logs/trial %j.out"',
        '#SBATCH --error="/logs/trial %j.err"', '#SBATCH --nodes=3', '#SBATCH --ntasks-per-node=11',
        '#SBATCH --time=01:23:00', '#SBATCH --partition=research', '#SBATCH --wckey="project one"',
        '#SBATCH --comment=model', '#SBATCH --exclusive', '#SBATCH --mem=0', '#SBATCH --no-requeue',
    ]
    for policy in (True, None):
        lines = render_slurm_resource_block(**fields, requeue=policy, exclusive=False).splitlines()
        assert not any("requeue" in line or "exclusive" in line for line in lines)
    assert "#SBATCH --exclusive=user" in render_slurm_resource_block(exclusive="user").splitlines()
    assert render_orvix_resource_block(scheduler="local", output="a.out").splitlines() == [
        "#ORVIX scheduler=local", "#ORVIX output=a.out",
    ]


@pytest.mark.parametrize("entry", ["job", "config", "directory", "single"])
def test_native_helper_at_template_entry_points(tmp_path, resources, entry):
    relative = Path("config/config.sh.j2" if entry == "config" else "jobs/on/task.sh.j2")
    put(resources, relative, '#!/bin/sh\n{{ render_slurm_resource_block(project="explicit", time="01:45:00") }}\ntrue\n')
    out = tmp_path / "out"
    raw = data(out, mode="shell", workload={"workload_type": "slurm", "project": "site-default"})
    output = out / "jobs/on/task.sh"
    if entry == "single":
        env = Environment(loader=FileSystemLoader(resources))
        render_single_job_file(relative, str(out), output.relative_to(out), BaseWorkflowConfig(**raw), env)
    elif entry == "directory":
        render_jobs_from_directory(BaseWorkflowConfig(**raw), str(resources), str(out),
                                   template_filter=lambda path: path.parts[0] == "on")
    else:
        with application(resources).prepare(raw) as context:
            run_stage(context, "resource")
            run_stage(context, "config")
            if entry == "job":
                run_stage(context, "job")
            else:
                output = context.paths.config_file
    lines = output.read_text().splitlines()
    assert [line for line in lines if line.startswith("#SBATCH --wckey=")] == ["#SBATCH --wckey=explicit"]
    assert lines.index("#SBATCH --time=01:45:00") < lines.index("true")


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
        assert "#ORVIX queue=%QUEUE:parallel-value%" in rendered
        assert "#ORVIX project=%WCKEY:project-value%" in rendered
        if label is not None:
            assert "#ORVIX application=%APPLICATION:configured-app%" in rendered
        elif template_default:
            assert "#ORVIX application=%APPLICATION:template-app%" in rendered
        else:
            assert "#ORVIX application=%APPLICATION%" in rendered
    else:
        if mode == "takler":
            assert "{{ NODES" in rendered
            rendered = Environment().from_string(rendered).render()
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
    assert "#ORVIX time=%WALLTIME%" in omitted
    for line in ("#ORVIX nodes=%NODES%", "#ORVIX ntasks-per-node=%TASKS_PER_NODE%"):
        assert (line in omitted) == (job_type == "parallel")
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
    with warnings.catch_warnings():
        warnings.simplefilter("error", ResourceAliasWarning)
        canonical = render_orvix_resource_block(**{name: "one", alias: None})
        assert f"#ORVIX {name}=one" in canonical.splitlines()
        for other in ("one", "two"):
            with pytest.raises(ValueError, match=f"{name}.*{alias}"):
                render_orvix_resource_block(**{name: "one", alias: other})
        with pytest.raises(ValueError):
            render_orvix_resource_block(**{alias: "one", "memory": " "})
        with pytest.raises(TypeError):
            render_slurm_resource_block(**{alias: "one"})
    with pytest.warns(ResourceAliasWarning, match=rf"render_orvix_resource_block\.{alias} is deprecated\. Use {name}\.") as notices:
        assert render_orvix_resource_block(**{name: None, alias: "one"}) == canonical
    assert len(notices) == 1


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
            assert lines.count("#ORVIX project=%WCKEY:p%") == lines.count("#ORVIX queue=%QUEUE:q%") == 1
