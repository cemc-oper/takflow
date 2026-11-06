"""Safe public loading, explicit field strictness and final-value validation."""
from copy import deepcopy
import inspect
import traceback

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, model_validator
import pytest

from takflow.config import (
    BaseWorkflowConfig,
    ConfigValidationError,
    load_config_from_file,
    load_validated_config,
    validate_config,
    validation_diagnostics,
)


SECRET = "synthetic-credential-must-not-be-reported"
strict_config = pytest.mark.skipif(
    "extra" not in inspect.signature(BaseModel.model_validate).parameters,
    reason="positive strict-fields cases require takflow[strict-config] (Pydantic >= 2.12)",
)


class Resource(BaseModel):
    queue: str = "serial"
    slots: int = Field(default=1, ge=1)


class ApplicationConfig(BaseWorkflowConfig):
    model_config = ConfigDict(populate_by_name=True)
    output_repo_base_dir: str | None = Field(default=None, alias="output_workflow_base")
    resource: Resource = Field(default_factory=Resource)
    resources: list[Resource] = Field(default_factory=list)
    by_cycle: dict[str, Resource] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    credential: str | None = None
    derived_path: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_and_derive(cls, values):
        resource = values.get("resource")
        if isinstance(resource, dict) and "partition" in resource:
            resource["queue"] = resource.pop("partition")
        output = values.get("output_repo_base_dir") or values.get("output_workflow_base")
        if values.get("derived_path") is None and output is not None:
            values["derived_path"] = f"{output}/machine/site"
        return values

    @model_validator(mode="after")
    def domain_rule(self):
        if self.credential is not None:
            # Application exceptions are untrusted diagnostic data too.
            raise ValueError(f"credential rejected: {self.credential}")
        return self


def raw_config(**updates):
    return {"project_base_dir": "/program", "run_base_dir": "/run",
            "workload": {"workload_type": "shell"}, **updates}


def only_diagnostic(error, code, path=(), stage="config.validation"):
    assert len(error.diagnostics) == 1
    diagnostic = error.diagnostics[0]
    assert diagnostic.code == code
    assert diagnostic.path == path
    assert diagnostic.stage == stage
    assert diagnostic.reason
    assert diagnostic.as_dict() == {
        "code": code, "path": list(path), "reason": diagnostic.reason, "stage": stage,
    }
    return diagnostic


def test_compatibility_ignores_extra_without_mutating_input():
    raw = raw_config(unknown=SECRET, resource={"partition": "long", "ignored": SECRET})
    original = deepcopy(raw)
    config = validate_config(raw, ApplicationConfig)
    assert type(config) is ApplicationConfig
    assert config.resource.queue == "long"
    assert not hasattr(config, "unknown")
    assert not hasattr(config.resource, "ignored")
    assert raw == original


@strict_config
@pytest.mark.parametrize("updates,path", [
    ({"workflow_nam": SECRET}, ("workflow_nam",)),
    ({"resource": {"slost": SECRET}}, ("resource", "slost")),
    ({"resources": [{"slost": SECRET}]}, ("resources", 0, "slost")),
    ({"by_cycle": {"00": {"slost": SECRET}}}, ("by_cycle", "00", "slost")),
    ({"workload": {"workload_type": "shell", "submit_carrer": SECRET}},
     ("workload", "shell", "submit_carrer")),
])
def test_strict_fields_rejects_unknown_at_each_nested_shape(updates, path):
    with pytest.raises(ConfigValidationError) as caught:
        validate_config(raw_config(**updates), ApplicationConfig, strict_fields=True)
    only_diagnostic(caught.value, "CONFIG_UNKNOWN_FIELD", path)
    assert SECRET not in str(caught.value)


@strict_config
def test_strict_fields_runs_normalizer_and_keeps_lax_type_conversion():
    raw = raw_config(resource={"partition": "legacy", "slots": "2"}, labels={"business-key": "x"})
    original = deepcopy(raw)
    config = validate_config(raw, ApplicationConfig, strict_fields=True)
    assert config.resource.queue == "legacy"
    assert config.resource.slots == 2
    assert config.labels == {"business-key": "x"}
    assert raw == original


@pytest.mark.parametrize("name", ["output_repo_base_dir", "output_workflow_base"])
def test_loader_accepts_model_field_aliases_and_canonical_names(name):
    config = validate_config(raw_config(**{name: "/output"}), ApplicationConfig)
    assert config.output_repo_base_dir == "/output"
    assert config.derived_path == "/output/machine/site"


@pytest.mark.parametrize("strict", [False, pytest.param(True, marks=strict_config)])
def test_canonical_override_wins_over_both_input_spellings_before_derivation(strict):
    raw = raw_config(output_workflow_base="/alias", output_repo_base_dir="/canonical")
    overrides = {"output_repo_base_dir": "/overridden"}
    original, original_overrides = deepcopy(raw), deepcopy(overrides)
    config = validate_config(raw, ApplicationConfig, overrides=overrides, strict_fields=strict)
    assert config.output_repo_base_dir == "/overridden"
    assert config.derived_path == "/overridden/machine/site"
    assert "output_repo_base_dir" in config.model_fields_set
    assert raw == original
    assert overrides == original_overrides


def test_invalid_input_can_be_repaired_by_final_override():
    raw = raw_config(resource={"slots": 0})
    config = validate_config(raw, ApplicationConfig, overrides={"resource": {"slots": 2}})
    assert config.resource.slots == 2
    assert raw["resource"]["slots"] == 0


def test_invalid_final_override_is_validated():
    with pytest.raises(ConfigValidationError) as caught:
        validate_config(raw_config(), ApplicationConfig, overrides={"resource": {"slots": 0}})
    only_diagnostic(caught.value, "CONFIG_RANGE", ("resource", "slots"))


def test_mapping_override_replaces_entire_field():
    config = validate_config(raw_config(resource={"queue": "original", "slots": 7}),
                             ApplicationConfig, overrides={"resource": {"slots": 3}})
    assert config.resource.slots == 3
    assert config.resource.queue == "serial"
    assert config.resource.model_fields_set == {"slots"}


def test_omitted_fields_and_explicit_none_remain_distinct():
    omitted = validate_config(raw_config(), ApplicationConfig)
    explicit = validate_config(raw_config(), ApplicationConfig, overrides={"credential": None})
    assert omitted.credential is explicit.credential is None
    assert "credential" not in omitted.model_fields_set
    assert "credential" in explicit.model_fields_set
    assert omitted.resource.model_fields_set == set()


def test_none_override_clears_aliased_value_before_derivation():
    config = validate_config(raw_config(output_workflow_base="/old"), ApplicationConfig,
                             overrides={"output_repo_base_dir": None})
    assert config.output_repo_base_dir is None
    assert config.derived_path is None
    assert "output_repo_base_dir" in config.model_fields_set


@pytest.mark.parametrize("name", ["output_workflow_base", "not_a_field"])
def test_override_requires_canonical_field_name(name):
    with pytest.raises(ConfigValidationError) as caught:
        validate_config(raw_config(), ApplicationConfig, overrides={name: SECRET})
    only_diagnostic(caught.value, "CONFIG_UNKNOWN_FIELD", (name,), "config.overrides")
    assert SECRET not in str(caught.value)


def test_alias_choices_override_fails_explicitly():
    class ChoicesConfig(ApplicationConfig):
        option: str = Field(default="x", validation_alias=AliasChoices("option", "old_option"))

    with pytest.raises(ConfigValidationError) as caught:
        validate_config(raw_config(), ChoicesConfig, overrides={"option": SECRET})
    only_diagnostic(caught.value, "CONFIG_OVERRIDE_ALIAS", ("option",), "config.overrides")


@pytest.mark.parametrize("raw", [None, [], SECRET, 3])
def test_root_must_be_mapping(raw):
    with pytest.raises(ConfigValidationError) as caught:
        validate_config(raw, ApplicationConfig)
    only_diagnostic(caught.value, "CONFIG_ROOT_TYPE")
    assert SECRET not in str(caught.value)


def test_model_instance_is_not_dumped_and_revalidated():
    model = validate_config(raw_config(), ApplicationConfig)
    with pytest.raises(ConfigValidationError) as caught:
        validate_config(model, ApplicationConfig)
    only_diagnostic(caught.value, "CONFIG_ROOT_TYPE")


def test_overrides_must_be_mapping():
    with pytest.raises(ConfigValidationError) as caught:
        validate_config(raw_config(), ApplicationConfig, overrides=[SECRET])
    only_diagnostic(caught.value, "CONFIG_OVERRIDES_TYPE", stage="config.overrides")


def test_domain_message_and_exception_chain_do_not_expose_credentials():
    with pytest.raises(ConfigValidationError) as caught:
        validate_config(raw_config(credential=SECRET), ApplicationConfig)
    only_diagnostic(caught.value, "CONFIG_DOMAIN_RULE")
    assert SECRET not in str(caught.value)
    assert SECRET not in repr(caught.value.diagnostics[0].as_dict())
    assert SECRET not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("updates,code,path", [
    ({"resource": {"slots": SECRET}}, "CONFIG_TYPE", ("resource", "slots")),
    ({"workload": {"workload_type": SECRET}}, "CONFIG_CHOICE", ("workload",)),
])
def test_builtin_diagnostics_are_safe_and_located(updates, code, path):
    with pytest.raises(ConfigValidationError) as caught:
        validate_config(raw_config(**updates), ApplicationConfig)
    only_diagnostic(caught.value, code, path)
    assert SECRET not in str(caught.value)


def test_required_field_diagnostic():
    raw = raw_config()
    del raw["project_base_dir"]
    with pytest.raises(ConfigValidationError) as caught:
        validate_config(raw, ApplicationConfig)
    only_diagnostic(caught.value, "CONFIG_REQUIRED", ("project_base_dir",))


def test_existing_forbid_policy_is_preserved_without_strict_option():
    class ForbidConfig(ApplicationConfig):
        model_config = ConfigDict(extra="forbid", populate_by_name=True)

    with pytest.raises(ConfigValidationError) as caught:
        validate_config(raw_config(misspelled=SECRET), ForbidConfig)
    only_diagnostic(caught.value, "CONFIG_UNKNOWN_FIELD", ("misspelled",))


def test_strict_unavailable_is_explicit_while_compatibility_still_works():
    class OlderConfig(ApplicationConfig):
        @classmethod
        def model_validate(cls, obj):
            return super().model_validate(obj)

    config = validate_config(raw_config(ignored=True), OlderConfig)
    assert isinstance(config, OlderConfig)
    with pytest.raises(ConfigValidationError) as caught:
        validate_config(raw_config(), OlderConfig, strict_fields=True)
    only_diagnostic(caught.value, "CONFIG_STRICT_UNAVAILABLE")


def test_error_adapter_supports_explicit_stage_without_raw_messages():
    with pytest.raises(ValidationError) as caught:
        ApplicationConfig.model_validate(raw_config(credential=SECRET))
    diagnostics = validation_diagnostics(caught.value, stage="application.configuration")
    assert diagnostics[0].stage == "application.configuration"
    assert diagnostics[0].code == "CONFIG_DOMAIN_RULE"
    assert SECRET not in repr(diagnostics)


def test_safe_file_loader_passes_overrides_before_domain_derivation(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("project_base_dir: /program\nrun_base_dir: /run\n"
                    "workload: {workload_type: shell}\noutput_workflow_base: /old\n", encoding="utf-8")
    config = load_validated_config(path, ApplicationConfig,
                                   overrides={"output_repo_base_dir": "/new"})
    assert config.derived_path == "/new/machine/site"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("content,code", [
    (f"credential: {SECRET}\nresource: [\n".encode(), "CONFIG_YAML_SYNTAX"),
    (SECRET.encode() + b"\xff", "CONFIG_READ_ERROR"),
])
def test_file_parse_errors_do_not_report_source_lines(tmp_path, content, code):
    path = tmp_path / "config.yaml"
    path.write_bytes(content)
    with pytest.raises(ConfigValidationError) as caught:
        load_validated_config(path, ApplicationConfig)
    only_diagnostic(caught.value, code, stage="config.read")
    assert SECRET not in "".join(traceback.format_exception(caught.value))


def test_unreadable_file_reports_no_raw_os_error_path(tmp_path):
    with pytest.raises(ConfigValidationError) as caught:
        load_validated_config(tmp_path / SECRET, ApplicationConfig)
    only_diagnostic(caught.value, "CONFIG_READ_ERROR", stage="config.read")
    assert SECRET not in str(caught.value)


def test_yaml_scalar_has_safe_root_diagnostic(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(SECRET)
    with pytest.raises(ConfigValidationError) as caught:
        load_validated_config(path, ApplicationConfig)
    only_diagnostic(caught.value, "CONFIG_ROOT_TYPE")
    assert SECRET not in str(caught.value)


def test_historical_loader_keeps_return_and_exception_contract(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("project_base_dir: /program\nrun_base_dir: /run\n"
                    "workload: {workload_type: shell}\nignored: legacy\n")
    assert isinstance(load_config_from_file(str(path), ApplicationConfig), ApplicationConfig)
    path.write_text("project_base_dir: /program\nrun_base_dir: /run\n"
                    "workload: {workload_type: shell}\ncredential: secret\n")
    with pytest.raises(ValidationError):
        load_config_from_file(str(path), ApplicationConfig)
