"""examples/toyflow 的端到端冒烟测试。

在 tmp_path 中跑通 toyflow 的完整生成管线（resource copy → config generate →
job generate → workflow generate → credential generate），断言生成物的关键内容。

这个测试保证示例与 takflow API 同步：takflow API 一旦变动导致示例失效，
这里会立刻变红。
"""
from __future__ import annotations

import sys
import json
import os
from pathlib import Path

import pytest
import yaml

TAKFLOW_ROOT = Path(__file__).resolve().parents[1]
TOYFLOW_ROOT = TAKFLOW_ROOT / "examples" / "toyflow"
TOYFLOW_SRC = TOYFLOW_ROOT / "src"

pytestmark = pytest.mark.skipif(
    not TOYFLOW_SRC.exists(), reason="examples/toyflow not found"
)


@pytest.fixture()
def toyflow(tmp_path, monkeypatch):
    """导入 toyflow（examples 不安装，直接加 sys.path）并返回配置/路径。"""
    monkeypatch.syspath_prepend(str(TOYFLOW_SRC))

    import toyflow.hooks  # noqa: F401  # import 时注册 engine/credential hook
    from toyflow.config import ToyflowConfig

    output_repo_base = tmp_path / "output"
    config_data = yaml.safe_load((TOYFLOW_ROOT / "config" / "toyflow.yaml").read_text())
    config_data["project_base_dir"] = str(tmp_path / "project")
    config_data["run_base_dir"] = str(tmp_path / "run")
    config_data["output_repo_base_dir"] = str(output_repo_base)
    config = ToyflowConfig(**config_data)

    return config, output_repo_base


def test_toyflow_full_pipeline(toyflow, tmp_path):
    config, output_repo_base = toyflow

    from takflow.toolkit import copy_resources_to_output, render_jobs_from_directory
    from toyflow.generate import generate_workflow, render_config
    from toyflow.util import get_resources_path

    resources = get_resources_path()

    # 1. resource copy
    copy_resources_to_output(output_repo_base=output_repo_base, src_base=resources)
    assert (output_repo_base / "scripts" / "main" / "run_forecast.sh").exists()
    assert (output_repo_base / "ecflow" / "include" / "common" / "head.h").exists()

    # 2. config generate（ecflow 模式 -> config.h）
    config_path = render_config(config=config)
    assert config_path.name == "config.h"
    assert "FORECAST_LENGTH=24" in config_path.read_text()

    # 3. job generate（jobs/**/*.sh.j2 -> *.ecf）
    render_jobs_from_directory(
        config=config,
        repo_base=str(resources),
        output_repo_base=str(output_repo_base),
    )
    forecast_ecf = output_repo_base / "jobs" / "main" / "forecast.ecf"
    assert forecast_ecf.exists()
    forecast_text = forecast_ecf.read_text()
    # TaskResource(parallel, nodes=2, ntasks_per_node=16) 编译为 #ORVIX 指令
    assert "#ORVIX nodes=2" in forecast_text
    assert "#ORVIX ntasks-per-node=16" in forecast_text
    assert "#ORVIX queue=normal" in forecast_text
    # hook 注入任务对应的作业模板也被渲染
    assert (output_repo_base / "jobs" / "main" / "verify.ecf").exists()

    # 4. workflow generate（-> toyflow.def）
    def_path = generate_workflow(config=config)
    assert def_path.name == "toyflow.def"
    def_text = def_path.read_text()
    assert "suite toyflow" in def_text
    for node_name in ("family obs", "task prepare", "family main", "task forecast",
                      "family post", "task plot"):
        assert node_name in def_text, f"{node_name} missing in toyflow.def"
    # engine hook 注入的 verify 任务（连同它的作业脚本变量）
    assert "task verify" in def_text
    assert "main/verify.ecf" in def_text
    # forecast 依赖 obs/prepare
    assert "/toyflow/obs/prepare == complete" in def_text

    # 5. credential generate（credential hook 渲染片段）
    from takflow.toolkit import render_credential
    from toyflow.generate import toyflow_build_info_lines

    render_credential(
        credential_file=str(TOYFLOW_ROOT / "config" / "credential.yaml"),
        config=config,
        output_repo_base=str(output_repo_base),
        build_info_lines=toyflow_build_info_lines(),
    )
    credential_text = (output_repo_base / "config" / "credential.sh").read_text()
    assert "TOYFLOW_API_KEY" in credential_text


def test_toyflow_explicitly_disabled_needs_no_sledra(toyflow):
    from takflow.config import ObservabilityConfig
    from toyflow.generate import generate_workflow

    config, output_repo_base = toyflow
    baseline = generate_workflow(config).read_bytes()
    config.observability = ObservabilityConfig(enabled=False, spec_dir="/missing-sledra")
    assert generate_workflow(config).read_bytes() == baseline
    assert not (output_repo_base / "definition_manifest.json").exists()


def test_toyflow_shell_mode_remains_unsupported(toyflow):
    from toyflow.generate import generate_workflow

    config, output_repo_base = toyflow
    config.workflow_mode = "shell"

    with pytest.raises(ValueError, match="^Unsupported workflow_mode: shell$"):
        generate_workflow(config)
    assert not output_repo_base.exists()


@pytest.mark.parametrize("invoke_mode", ["external", "inline"])
def test_toyflow_optional_definition_manifest(toyflow, invoke_mode, tmp_path):
    from takflow.config import ObservabilityConfig
    from takflow.toolkit import copy_resources_to_output, render_jobs_from_directory
    from takflow.toolkit.observability import ObservabilityConfigError
    from toyflow.generate import generate_workflow
    from toyflow.util import get_resources_path

    config, output_repo_base = toyflow
    config.script_invoke_mode = invoke_mode
    resources = get_resources_path()
    copy_resources_to_output(output_repo_base, resources)
    render_jobs_from_directory(config, str(resources), str(output_repo_base))
    baseline = generate_workflow(config).read_bytes()
    generated = {
        str(path.relative_to(output_repo_base)): path.read_bytes()
        for directory in ("jobs", "scripts", "ecflow")
        for path in (output_repo_base / directory).rglob("*") if path.is_file()
    }
    spec_dir = os.environ.get("SLEDRA_SPEC_DIR")
    if not spec_dir:
        pytest.skip("set SLEDRA_SPEC_DIR to a published Sledra 1.0.0 spec directory")
    pytest.importorskip("jsonschema")

    config.observability = ObservabilityConfig(
        enabled=True, spec_dir=str(tmp_path / "missing"),
        application_revision="toyflow-source-1", config_revision="toyflow-config-1",
    )
    with pytest.raises(ObservabilityConfigError, match="unavailable"):
        generate_workflow(config)
    assert not (output_repo_base / "definition_manifest.json").exists()
    assert (output_repo_base / "toyflow.def").read_bytes() == baseline

    config.observability.spec_dir = spec_dir
    copy_resources_to_output(output_repo_base, resources)
    render_jobs_from_directory(config, str(resources), str(output_repo_base))
    assert generate_workflow(config).read_bytes() == baseline
    assert {str(path.relative_to(output_repo_base)): path.read_bytes()
            for directory in ("jobs", "scripts", "ecflow")
            for path in (output_repo_base / directory).rglob("*") if path.is_file()} == generated
    manifest_path = output_repo_base / "definition_manifest.json"
    first = manifest_path.read_bytes()
    manifest = json.loads(first)
    assert manifest["definition_id"].startswith("def_")
    assert "main.forecast" in {task["task_key"] for task in manifest["tasks"]}
    generate_workflow(config)
    assert manifest_path.read_bytes() == first

    config.observability.enabled = False
    generate_workflow(config)
    assert (output_repo_base / "toyflow.def").read_bytes() == baseline
