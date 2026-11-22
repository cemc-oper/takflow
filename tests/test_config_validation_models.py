"""Public config validation, with domain rules and flat jobspec strings preserved."""
from __future__ import annotations

import warnings

import pytest
from pydantic import BaseModel, ValidationError

from takflow.config.scheduling import SchedulingConfig
from takflow.config.workload import ResourceAliasWarning, SlurmWorkload
from takflow.jobspec import ResourceSpec, TaskResource, to_orvix_directives
from takflow.spec.jobspec import load_schema


def assert_error(error: ValidationError, location: tuple, code: str, reason: str):
    details = error.errors(include_url=False)
    for detail in details:
        # Pydantic 2.0's errors() has no include_input keyword. Discard raw
        # inputs before asserting diagnostics, including on assertion failure.
        detail.pop("input", None)
    assert details == [
        {"type": code, "loc": location, "msg": reason},
    ]


@pytest.mark.parametrize("field", ["start_date", "end_date"])
@pytest.mark.parametrize(
    "invalid",
    [20240230, 20230229, 19000229, 20241301, 20240001, 20240100, 20240132,
     2024111, 202401010, -20240101],
)
def test_scheduling_rejects_invalid_calendar_endpoint(field, invalid):
    values = {"start_date": 20240101, "end_date": 20241231, field: invalid}
    with pytest.raises(ValidationError) as caught:
        SchedulingConfig(**values)
    assert_error(
        caught.value, (field,), "config_date_invalid",
        "must be a real calendar date in YYYYMMDD format",
    )


@pytest.mark.parametrize(
    "start,end", [(20240229, 20240229), (20000229, 20000301), (10000101, 99991231)],
)
def test_scheduling_accepts_leap_day_equal_endpoints_and_calendar_boundaries(start, end):
    config = SchedulingConfig(start_date=start, end_date=end)
    assert config.start_date == start
    assert config.end_date == end


def test_scheduling_rejects_reversed_dates_at_end_date():
    with pytest.raises(ValidationError) as caught:
        SchedulingConfig(start_date=20240301, end_date=20240229)
    assert_error(
        caught.value, ("end_date",), "config_date_order",
        "end_date must be on or after start_date",
    )


def test_invalid_start_date_does_not_create_spurious_order_error():
    with pytest.raises(ValidationError) as caught:
        SchedulingConfig(start_date=20240230, end_date=20240229)
    assert_error(
        caught.value, ("start_date",), "config_date_invalid",
        "must be a real calendar date in YYYYMMDD format",
    )


def test_nested_schedule_preserves_consumer_field_path():
    class Consumer(BaseModel):
        scheduling: SchedulingConfig

    with pytest.raises(ValidationError) as caught:
        Consumer(scheduling={"start_date": 20240301, "end_date": 20240229})
    assert_error(
        caught.value, ("scheduling", "end_date"), "config_date_order",
        "end_date must be on or after start_date",
    )


@pytest.mark.parametrize("field", ["nodes", "ntasks_per_node"])
@pytest.mark.parametrize("value", [0, -1])
@pytest.mark.parametrize("job_type", ["serial", "parallel"])
def test_task_resource_rejects_nonpositive_explicit_counts(field, value, job_type):
    with pytest.raises(ValidationError) as caught:
        TaskResource(job_type=job_type, **{field: value})
    assert_error(
        caught.value, (field,), "resource_positive",
        "must be a positive integer or None",
    )


@pytest.mark.parametrize("job_type", ["serial", "parallel"])
@pytest.mark.parametrize("counts", [{}, {"nodes": None, "ntasks_per_node": None}])
def test_task_resource_none_and_omission_keep_scheduler_defaults(job_type, counts):
    resource = TaskResource(job_type=job_type, **counts)
    workload = SlurmWorkload(wckey="project")
    spec = resource.compile(workload)
    assert spec.nodes is None
    assert spec.ntasks_per_node is None
    assert spec.queue == ("serial" if job_type == "serial" else "normal")


def test_parallel_resource_accepts_smallest_positive_counts():
    spec = TaskResource(job_type="parallel", nodes=1, ntasks_per_node=1).compile(
        SlurmWorkload(wckey="project"),
    )
    assert spec.nodes == "1"
    assert spec.ntasks_per_node == "1"


@pytest.mark.parametrize("model", [TaskResource, ResourceSpec])
@pytest.mark.parametrize("field", ["queue", "time", "memory"])
@pytest.mark.parametrize("value", ["", " \t"])
def test_blank_resource_text_is_rejected_at_the_field(model, field, value):
    with pytest.raises(ValidationError) as caught:
        model(**{field: value})
    assert caught.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize("field", ["default_serial_queue", "default_parallel_queue"])
def test_blank_global_queue_is_rejected_even_if_unused(field):
    with pytest.raises(ValidationError) as caught:
        SlurmWorkload(wckey="p", **{field: " \t"})
    assert caught.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize("values", [
    {"project": "p"}, {"wckey": "p"}, {"project": None, "wckey": "p"},
    {"project": "p", "wckey": None},
])
def test_workload_project_round_trip_and_legacy_access(values):
    with warnings.catch_warnings(record=True) as notices:
        warnings.simplefilter("always", ResourceAliasWarning)
        workload = SlurmWorkload(**values)
        assert workload.project == workload.wckey == "p"
        assert workload.model_dump(exclude_unset=True) == {"project": "p"}
        assert SlurmWorkload(**workload.model_dump()) == workload
        workload.wckey = "q"
        spec = TaskResource(queue=None, time="0", memory="0", requeue=False).compile(workload)
    expected = 1 if values.get("wckey") is not None else 0
    assert len(notices) == expected
    if expected:
        assert notices[0].category is ResourceAliasWarning and "Use workload.project." in str(notices[0].message)
    assert (spec.project, spec.queue, spec.time, spec.memory, spec.requeue) == (
        "q", "serial", "0", "0", False,
    )


@pytest.mark.parametrize("values", [
    {}, {"wckey": None}, {"project": None}, {"project": None, "wckey": None},
    {"project": "p", "wckey": "p"}, {"project": "p", "wckey": "q"},
    {"wckey": []}, {"wckey": "p", "default_serial_queue": " "},
])
def test_workload_requires_one_project_spelling(values):
    with warnings.catch_warnings():
        warnings.simplefilter("error", ResourceAliasWarning)
        with pytest.raises(ValidationError):
            SlurmWorkload(**values)


def test_flat_resource_keeps_runtime_expressions_and_metadata():
    spec = ResourceSpec(queue="%QUEUE%", time="{{ TIME }}", memory="0", application="", project="")
    assert (spec.queue, spec.time, spec.memory, spec.application, spec.project) == ("%QUEUE%", "{{ TIME }}", "0", "", "")


def test_valid_serial_counts_remain_ignored_when_compiled():
    spec = TaskResource(job_type="serial", nodes=99, ntasks_per_node=64).compile(
        SlurmWorkload(wckey="project"),
    )
    assert spec.nodes is None
    assert spec.ntasks_per_node is None


def test_existing_integer_coercion_remains_available():
    scheduling = SchedulingConfig(start_date="20240229", end_date=20240301.0)
    assert scheduling.start_date == 20240229
    assert scheduling.end_date == 20240301
    # This task rejects nonpositive counts without globally changing Pydantic's
    # existing int coercion: True and integral floats still normalize to 1.
    resource = TaskResource(nodes=True, ntasks_per_node=1.0)
    assert resource.nodes == 1
    assert resource.ntasks_per_node == 1
    with pytest.raises(ValidationError) as caught:
        TaskResource(nodes=False)
    assert_error(
        caught.value, ("nodes",), "resource_positive",
        "must be a positive integer or None",
    )


@pytest.mark.parametrize("field", ["nodes", "ntasks", "ntasks_per_node", "cpus_per_task"])
@pytest.mark.parametrize("value", ["0", "-1", "1-4", "%NODES%", "{{ TASK_COUNT }}"])
def test_flat_resource_strings_preserve_the_authoritative_contract(field, value):
    # The vendored orvix contract declares strings, not a scheduler-independent
    # numeric grammar. Do not accidentally apply TaskResource's integer policy
    # to ranges, expressions, or flat directive strings.
    assert load_schema()["properties"][field]["type"] == "string"
    spec = ResourceSpec(**{field: value})
    assert getattr(spec, field) == value
    assert any(field.replace("_", "-") + "=" in line for line in to_orvix_directives(spec))
