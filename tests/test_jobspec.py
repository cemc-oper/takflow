"""Unit tests for the takflow jobspec contract layer."""
from __future__ import annotations

import pytest

from takflow.config.workload import SlurmWorkload
from takflow.jobspec import ResourceSpec, TaskResource, to_orvix_directives
from takflow.jobspec.model import CANONICAL_KEYS
from takflow.spec.jobspec import contract_version, load_schema, schema_keys


def test_contract_version_is_semver():
    parts = contract_version().split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)


def test_pydantic_fields_match_schema():
    """ResourceSpec fields must be exactly the contract's properties."""
    assert set(ResourceSpec.model_fields) == set(schema_keys())


def test_canonical_keys_match_schema():
    """CANONICAL_KEYS (render order) must cover exactly the contract keys."""
    assert set(CANONICAL_KEYS) == set(schema_keys())


def test_schema_forbids_additional_properties():
    assert load_schema().get("additionalProperties") is False


def test_render_basic_directives():
    spec = ResourceSpec(scheduler="slurm", queue="normal", nodes="24", time="00:30:00")
    lines = to_orvix_directives(spec)
    assert "#ORVIX scheduler=slurm" in lines
    assert "#ORVIX queue=normal" in lines
    assert "#ORVIX nodes=24" in lines
    assert "#ORVIX time=00:30:00" in lines


def test_local_scheduler_not_emitted():
    """The default scheduler 'local' should not be pinned in the script."""
    spec = ResourceSpec(queue="normal")
    assert not any("scheduler=" in line for line in to_orvix_directives(spec))


def test_requeue_false_emitted_lowercase():
    spec = ResourceSpec(requeue=False)
    assert to_orvix_directives(spec) == ["#ORVIX requeue=false"]


def test_exclusive_true_is_bare_flag():
    spec = ResourceSpec(exclusive=True)
    assert to_orvix_directives(spec) == ["#ORVIX exclusive"]


def test_exclusive_false_omitted():
    spec = ResourceSpec(exclusive=False)
    assert to_orvix_directives(spec) == []


def test_value_with_space_is_quoted():
    spec = ResourceSpec(dependency="afterok:1 afterok:2")
    assert '#ORVIX dependency="afterok:1 afterok:2"' in to_orvix_directives(spec)


def test_render_order_is_canonical():
    spec = ResourceSpec(scheduler="slurm", memory="25G", queue="normal", nodes="2")
    lines = to_orvix_directives(spec)
    keys = [line.split()[1].split("=")[0].replace("-", "_") for line in lines]
    # keys must appear in CANONICAL_KEYS order
    assert keys == sorted(keys, key=CANONICAL_KEYS.index)


def test_taskresource_parallel_compiles():
    wl = SlurmWorkload(wckey="op_mcv", default_parallel_queue="normal", application="mcv")
    tr = TaskResource(job_type="parallel", nodes=24, ntasks_per_node=64,
                      time="00:30:00", memory="25G", requeue=False)
    spec = tr.compile(wl)
    assert spec.scheduler == "slurm"
    assert spec.queue == "normal"
    assert spec.nodes == "24"
    assert spec.ntasks_per_node == "64"
    assert spec.project == "op_mcv"
    assert spec.application == "mcv"
    assert spec.memory == "25G"
    assert spec.requeue is False


def test_taskresource_serial_uses_serial_queue_and_no_nodes():
    wl = SlurmWorkload(wckey="op_mcv", default_serial_queue="serial")
    tr = TaskResource(job_type="serial", nodes=99, time="00:15:00")
    spec = tr.compile(wl)
    assert spec.queue == "serial"
    # serial jobs must not carry node/task layout
    assert spec.nodes is None
    assert spec.ntasks_per_node is None


def test_high_level_job_type_never_emitted():
    """The serial/parallel selector must NOT become the orvix job-type directive."""
    wl = SlurmWorkload(wckey="op_mcv")
    for jt in ("serial", "parallel"):
        spec = TaskResource(job_type=jt).compile(wl)
        assert spec.job_type is None
        assert not any("job-type" in line for line in to_orvix_directives(spec))


def test_explicit_queue_overrides_default():
    wl = SlurmWorkload(wckey="op_mcv", default_parallel_queue="normal")
    spec = TaskResource(job_type="parallel", queue="largemem").compile(wl)
    assert spec.queue == "largemem"


def test_resourcespec_rejects_unknown_field():
    with pytest.raises(Exception):
        ResourceSpec(partition="normal")  # 'partition' is not a contract key
