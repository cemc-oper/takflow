"""Application lifecycle, path provenance and declarative extension contracts."""
from pathlib import Path, PurePosixPath

import pytest
from jinja2 import Environment, FileSystemLoader
from pydantic import Field, model_validator
import yaml

from takflow.application import (
    Application, ApplicationBrand, ApplicationExtension, ComponentSelection,
    ResourceEntry, ResourceLayer, TemplateOutput,
)
from takflow.checks import GenerationCheckError
from takflow.config import BaseWorkflowConfig, ConfigValidationError
from takflow.flow.hook import BaseHookRegistry
from takflow.toolkit.credential import get_credential_registry
from takflow.toolkit.job import render_single_job_file
import takflow.toolkit.job as job_module


def config_data(**values):
    return {"project_base_dir": "/remote/program", "run_base_dir": "/remote/run",
            "workflow_mode": "ecflow", "output_repo_base_dir": "/tmp/application-output",
            "workload": {"workload_type": "shell"}, **values}


def application(tmp_path, **values):
    return Application(**{
        "config_type": BaseWorkflowConfig, "resources": tmp_path / "package",
        "brand": ApplicationBrand("sample", "1.2"),
        "suite_builder": lambda config, engine: engine.Suite(config.workflow_name),
        **values,
    })


def test_file_and_parameter_paths_use_different_bases(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    cwd = tmp_path / "caller"
    cwd.mkdir()
    file = source / "config.yaml"
    file.write_text(yaml.safe_dump(config_data(output_repo_base_dir="out", workflow_repo_base_dir="resources")))
    monkeypatch.chdir(cwd)
    app = application(tmp_path)
    with app.prepare(file, output="definitions/a.def") as context:
        assert context.paths.output_root == source / "out"
        assert context.paths.resource_layers[0].root == source / "resources"
        assert context.paths.workflow_output == source / "out/definitions/a.def"
        assert context.paths.config_file == source / "out/config/config.h"
        assert context.paths.jobs_dir == source / "out/jobs"
        assert context.paths.ecflow_include == source / "out/ecflow/include"
        assert context.config.run_base_dir == "/remote/run"
    with app.prepare(file, output_repo_base="cli-out", workflow_repo_base="cli-resources") as context:
        assert context.paths.output_root == cwd / "cli-out"
        assert context.paths.resource_layers[0].root == cwd / "cli-resources"
    assert not (source / "out").exists()
    assert not (cwd / "cli-out").exists()


def test_override_before_normalization_and_single_validation(tmp_path):
    events = []

    class DomainConfig(BaseWorkflowConfig):
        derived: str = ""

        @model_validator(mode="after")
        def derive(self):
            events.append("validate")
            self.derived = self.output_repo_base_dir + "/domain"
            return self

    def normalize(data):
        events.append(("normalize", data["output_repo_base_dir"]))
        return data

    app = application(tmp_path, config_type=DomainConfig, normalize_config=normalize,
                      extensions=(ApplicationExtension("domain", lambda: events.append("initialize")),))
    data = config_data(output_repo_base_dir="old")
    with app.prepare(data, output_repo_base=tmp_path / "new") as context:
        assert context.config.derived == str(tmp_path / "new/domain")
    assert events == ["initialize", ("normalize", str(tmp_path / "new")), "validate"]
    assert data["output_repo_base_dir"] == "old"


def test_alias_override_and_whole_mapping_replacement(tmp_path):
    class Aliased(BaseWorkflowConfig):
        output_repo_base_dir: str = Field(alias="old_output")

    app = application(tmp_path, config_type=Aliased)
    data = config_data(old_output="/old", workload={"workload_type": "shell", "submit_carrier": "orvix"})
    data.pop("output_repo_base_dir")
    with app.prepare(data, overrides={"output_repo_base_dir": "new", "workload": {"workload_type": "shell"}}, source_dir=tmp_path) as context:
        # Overrides are caller paths, even when a config source directory exists.
        assert context.paths.output_root == Path.cwd() / "new"
        assert context.config.workload.submit_carrier == "direct"
    assert data["old_output"] == "/old"
    assert data["workload"]["submit_carrier"] == "orvix"


@pytest.mark.parametrize("source_kind", ["mapping", "model"])
def test_relative_config_requires_source(tmp_path, source_kind):
    data = config_data(output_repo_base_dir="relative")
    source = BaseWorkflowConfig(**data) if source_kind == "model" else data
    with pytest.raises(ConfigValidationError, match="APPLICATION_SOURCE_REQUIRED"):
        with application(tmp_path).prepare(source):
            pass
    with application(tmp_path).prepare(source, source_dir=tmp_path) as context:
        assert context.paths.output_root == tmp_path / "relative"


def test_model_is_owned_and_not_dumped_or_revalidated(tmp_path, monkeypatch):
    model = BaseWorkflowConfig(**config_data(output_repo_base_dir="relative", machine_name="site"))
    original_fields = model.model_fields_set.copy()
    monkeypatch.setattr(BaseWorkflowConfig, "model_dump", lambda *a, **kw: pytest.fail("model dumped"))
    with application(tmp_path).prepare(model, source_dir=tmp_path) as context:
        assert context.config is not model
        assert context.config.output_repo_base_dir == str(tmp_path / "relative")
        assert not context.machine.external
    assert model.output_repo_base_dir == "relative"
    assert model.machine_dir is None
    assert model.model_fields_set == original_fields
    with pytest.raises(ConfigValidationError, match="APPLICATION_MODEL_OVERRIDES"):
        with application(tmp_path).prepare(model, output_repo_base="new"):
            pass


def test_layers_preserve_extension_order_and_explicit_base_replacement(tmp_path):
    extra = TemplateOutput("config/extra.j2", "config/extra.txt")
    app = application(tmp_path, resource_layers=(ResourceLayer("oper", tmp_path / "oper"),),
                      extensions=(ApplicationExtension("product", resource_layers=(ResourceLayer("product", tmp_path / "product"),), outputs=(extra,)),))
    with app.prepare(config_data(), workflow_repo_base=tmp_path / "replacement") as context:
        assert [(layer.name, layer.root) for layer in context.paths.resource_layers] == [
            ("base", tmp_path / "replacement"), ("oper", tmp_path / "oper"), ("product", tmp_path / "product")]
        assert context.outputs == (extra,)


def test_component_selection_once_and_context_contributions(tmp_path):
    calls = []

    def select(config):
        calls.append(config)
        return ComponentSelection(frozenset({"on"}),
                                  lambda path: path.parts[1] if path.parts[0] == "scripts" else None,
                                  lambda path: path.parts[0])

    app = application(tmp_path, select_components=select, context=lambda ctx: {"domain": {"output": str(ctx.paths.output_root)}},
                      extensions=(ApplicationExtension("oper", context=lambda ctx: {"oper": True}),))
    with app.prepare(config_data()) as context:
        assert context.components.keep_resource("scripts/on/a.sh")
        assert not context.components.keep_resource("scripts/off/a.sh")
        assert context.components.keep_resource("utils/shared.sh")
        assert context.components.keep_job("on/a.sh.j2")
        assert not context.components.keep_job("off/a.sh.j2")
        assert context.template_context()["oper"] is True
        assert context.template_context()["domain"]["output"] == "/tmp/application-output"
        with pytest.raises(TypeError):
            context.template_context()["config"] = None
    assert len(calls) == 1


@pytest.mark.parametrize("key", ["config", "paths", "build_info_detail", "invoke_script", "include_machine"])
def test_reserved_context_conflicts(tmp_path, key):
    with pytest.raises(ConfigValidationError, match="APPLICATION_CONTEXT_CONFLICT"):
        with application(tmp_path, context=lambda ctx: {key: "bad"}).prepare(config_data()):
            pass


def test_contributors_cannot_overwrite_each_other(tmp_path):
    app = application(tmp_path, context=lambda ctx: {"domain": 1},
                      extensions=(ApplicationExtension("other", context=lambda ctx: {"domain": 2}),))
    with pytest.raises(ConfigValidationError, match="APPLICATION_CONTEXT_CONFLICT"):
        with app.prepare(config_data()):
            pass


@pytest.mark.parametrize("failure", [None, "initialize", "validation", "body"])
def test_registries_restore_on_success_and_failure(tmp_path, failure):
    registry = BaseHookRegistry()
    credential = get_credential_registry()
    registry.register("point", lambda context: "outside")
    before = credential.list_hooks()
    calls = []

    def initialize():
        calls.append("initialize")
        registry.register("point", lambda ctx: "second", priority=50)
        registry.register("point", lambda ctx: "first", priority=10)
        credential.register("credential.render", lambda ctx: "build-only")
        if failure == "initialize":
            raise RuntimeError("original initializer exception")

    app = application(tmp_path, registries=(registry,),
                      extensions=(ApplicationExtension("extension", initialize, registries=(registry,)),))
    for _ in range(2):
        try:
            data = config_data()
            if failure == "validation":
                data.pop("run_base_dir")
            with app.prepare(data):
                assert registry.execute("point", None) == ["first", "second"]
                assert credential.count_hooks() == 1
                if failure == "body":
                    raise RuntimeError("original body exception")
        except (RuntimeError, ConfigValidationError):
            if failure is None:
                raise
        else:
            assert failure is None
        assert registry.execute("point", None) == ["outside"]
        assert credential.list_hooks() == before
    assert calls == ["initialize", "initialize"]


def test_scoped_brand_through_actual_job_renderer(tmp_path, monkeypatch):
    monkeypatch.setattr(job_module, "_build_info_provider", lambda: {"warning": "old", "info": "outside"})
    (tmp_path / "header.sh.j2").write_text("# {{ build_info_detail }}\n")
    env = Environment(loader=FileSystemLoader(tmp_path))
    for name in ("first", "second", "first"):
        app = application(tmp_path, brand=ApplicationBrand(name, "2.0", "domain 4.0"))
        with app.prepare(config_data()):
            render_single_job_file(Path("header.sh.j2"), str(tmp_path / "out"), Path(name + ".sh"),
                                   BaseWorkflowConfig(**config_data()), env)
        content = (tmp_path / "out" / (name + ".sh")).read_text()
        assert f"Generated by {name} v2.0" in content
        assert "target model: domain 4.0" in content
        assert "outside" not in content
    assert job_module._current_build_info_lines()["info"] == "outside"


@pytest.mark.parametrize("external", [None, "/unavailable/remote/$NAME/site"])
def test_machine_is_derived_or_external_without_local_probes(tmp_path, monkeypatch, external):
    monkeypatch.setattr(Path, "exists", lambda path: pytest.fail("target path probed"))
    app = application(tmp_path, require_machine=True)
    with app.prepare(config_data(machine_name="site", machine_dir=external), output_repo_base=tmp_path / "changed") as context:
        directory = external or str(tmp_path / "changed/machine/site")
        assert context.machine.directory == PurePosixPath(directory)
        assert context.machine.external == (external is not None)
        assert context.variables == {"MACHINE_NAME": "site", "MACHINE_DIR": directory}
        assert context.config.machine_dir == external
        assert any(item.status == "unchecked" and item.object == "machine_dir" for item in context.checks.checks)


@pytest.mark.parametrize("values,code", [
    ({"machine_dir": "/external"}, "APPLICATION_MACHINE_REQUIRED"),
    ({"machine_name": "../site"}, "APPLICATION_MACHINE_NAME"),
    ({"machine_name": "site", "machine_dir": "relative"}, "APPLICATION_MACHINE_DIR"),
    ({"machine_name": "site", "machine_dir": "/remote/\nsite"}, "APPLICATION_MACHINE_DIR"),
    ({"output_repo_base_dir": None}, "APPLICATION_OUTPUT_REQUIRED"),
])
def test_invalid_context_inputs(tmp_path, values, code):
    with pytest.raises(ConfigValidationError, match=code):
        with application(tmp_path).prepare(config_data(**values)):
            pass


@pytest.mark.parametrize("values,code", [
    ({"config_type": dict}, "APPLICATION_CONFIG_TYPE"),
    ({"resources": None}, "APPLICATION_INPUT_REQUIRED"),
    ({"suite_builder": None}, "APPLICATION_BUILDER_REQUIRED"),
    ({"supported_modes": ("shell",)}, "APPLICATION_RUNNER_REQUIRED"),
    ({"supported_modes": ("unknown",)}, "APPLICATION_MODES"),
    ({"extensions": (ApplicationExtension("same"), ApplicationExtension("same"))}, "APPLICATION_EXTENSION_DUPLICATE"),
])
def test_invalid_declarations(tmp_path, values, code):
    with pytest.raises(ConfigValidationError, match=code):
        application(tmp_path, **values)


@pytest.mark.parametrize("path", ["../escape", "/absolute", ".", "bad\npath", "windows\\path"])
def test_resource_and_extra_outputs_reject_escaping_paths(path):
    with pytest.raises(ConfigValidationError, match="APPLICATION_RELATIVE_PATH"):
        ResourceEntry("scripts", path)
    with pytest.raises(ConfigValidationError, match="APPLICATION_RELATIVE_PATH"):
        TemplateOutput(path, "config/extra")


def test_shell_paths_and_mode_restrictions(tmp_path):
    app = application(tmp_path, supported_modes=("shell",), shell_template="templates/runner.sh.j2")
    with app.prepare(config_data(workflow_mode="shell")) as context:
        assert context.paths.workflow_output == Path("/tmp/application-output/run_workflow.sh")
        assert context.paths.config_file.name == "config.sh"
    with pytest.raises(GenerationCheckError, match="GEN_MODE_UNSUPPORTED"):
        with app.prepare(config_data()):
            pass
    with pytest.raises(ConfigValidationError, match="APPLICATION_OUTPUT_UNSUPPORTED"):
        with app.prepare(config_data(workflow_mode="shell"), output="other.sh"):
            pass


def test_domain_errors_keep_safe_diagnostic_paths(tmp_path):
    with pytest.raises(ConfigValidationError) as captured:
        with application(tmp_path).prepare(config_data(scheduling={"scheduling_type": "RepeatDate", "start_date": 20260230, "end_date": 20260230})):
            pass
    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CONFIG_DATE_INVALID"
    assert diagnostic.path[:1] == ("scheduling",)
    assert diagnostic.stage == "config.validation"


def test_explicit_none_reaches_original_domain_validator(tmp_path):
    seen = []

    class DomainConfig(BaseWorkflowConfig):
        optional_value: str | None = None

        @model_validator(mode="after")
        def observe(self):
            seen.append("optional_value" in self.model_fields_set)
            return self

    app = application(tmp_path, config_type=DomainConfig)
    with app.prepare(config_data()):
        pass
    with app.prepare(config_data(), overrides={"optional_value": None}):
        pass
    assert seen == [False, True]


def test_default_and_canonical_aliased_paths_before_validators(tmp_path):
    seen = []

    class Config(BaseWorkflowConfig):
        model_config = {"populate_by_name": True}
        output_repo_base_dir: str = Field("default-out", alias="old_output")
        workflow_repo_base_dir: str = "default-resources"

        @model_validator(mode="after")
        def observe(self):
            seen.append((self.output_repo_base_dir, self.workflow_repo_base_dir))
            return self

    app = application(tmp_path, config_type=Config)
    data = config_data()
    data.pop("output_repo_base_dir")
    with app.prepare(data, source_dir=tmp_path):
        pass
    with app.prepare(config_data(output_repo_base_dir="canonical"), source_dir=tmp_path):
        pass
    assert seen == [(str(tmp_path / "default-out"), str(tmp_path / "default-resources")),
                    (str(tmp_path / "canonical"), str(tmp_path / "default-resources"))]


@pytest.mark.parametrize("values,code", [
    ({"overrides": ["invalid"]}, "CONFIG_OVERRIDES_TYPE"),
    ({"overrides": {"misspelled": 1}}, "CONFIG_UNKNOWN_FIELD"),
    ({"output_repo_base": ""}, "APPLICATION_PATH_TYPE"),
])
def test_invalid_public_parameters_have_controlled_errors(tmp_path, values, code):
    with pytest.raises(ConfigValidationError, match=code):
        with application(tmp_path).prepare(config_data(), **values):
            pass


def test_duplicate_resource_layer_and_reserved_variables(tmp_path):
    app = application(tmp_path, resource_layers=(ResourceLayer("base", tmp_path),))
    with pytest.raises(ConfigValidationError, match="APPLICATION_LAYER_DUPLICATE"):
        with app.prepare(config_data()):
            pass
    app = application(tmp_path, variables=lambda config: {"MACHINE_DIR": "wrong"})
    with pytest.raises(ConfigValidationError, match="APPLICATION_VARIABLE_CONFLICT"):
        with app.prepare(config_data(machine_name="site")):
            pass


def test_configured_extension_root_uses_source_and_override_bases(tmp_path, monkeypatch):
    class ExtendedConfig(BaseWorkflowConfig):
        oper_root: str | None = None

    source = tmp_path / 'source'
    caller = tmp_path / 'caller'
    source.mkdir()
    caller.mkdir()
    monkeypatch.chdir(caller)
    app = application(tmp_path, config_type=ExtendedConfig,
                      resource_layers=(ResourceLayer('oper', tmp_path / 'default', config_field='oper_root'),))
    raw = config_data(output_repo_base_dir=str(tmp_path / 'out'), oper_root='oper')
    with app.prepare(raw, source_dir=source) as context:
        assert context.paths.resource_layers[-1].root == source / 'oper'
        assert context.config.oper_root == str(source / 'oper')
    with app.prepare(raw, source_dir=source, overrides={'oper_root': 'override'}) as context:
        assert context.paths.resource_layers[-1].root == caller / 'override'
    with app.prepare({**raw, 'oper_root': None}, source_dir=source) as context:
        assert context.paths.resource_layers[-1].root == tmp_path / 'default'


def test_extension_layer_rejects_unknown_config_field(tmp_path):
    app = application(tmp_path, resource_layers=(ResourceLayer('oper', tmp_path, config_field='missing'),))
    with pytest.raises(ConfigValidationError, match='APPLICATION_LAYER_CONFIG_FIELD'):
        with app.prepare(config_data()):
            pass
