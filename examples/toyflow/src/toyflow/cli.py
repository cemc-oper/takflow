"""toyflow 命令行接口。

用 ``takflow.toolkit`` 拼出与 mcv-workflow 同形态的 4 步生成管线 + credential 生成：

    toyflow resource copy   --config-file config/toyflow.yaml
    toyflow config generate --config-file config/toyflow.yaml
    toyflow job generate    --config-file config/toyflow.yaml
    toyflow workflow generate --config-file config/toyflow.yaml
    toyflow credential generate --config-file config/toyflow.yaml \
        --credential-file config/credential.yaml
"""
from pathlib import Path

import click

from takflow.toolkit import (
    copy_resources_to_output,
    render_credential,
    render_jobs_from_directory,
    set_build_info_provider,
)

from toyflow.config import ToyflowConfig, load_config_from_file
from toyflow.generate import generate_workflow, render_config, toyflow_build_info_lines
from toyflow.util import get_output_repo_base_dir, get_workflow_repo_base_dir

# 让 toolkit 渲染的文件头带上 toyflow 品牌（否则是通用 takflow 头）。
set_build_info_provider(toyflow_build_info_lines)


def _load_config(config_file: str) -> ToyflowConfig:
    # 先 import hooks，触发 @register_engine_hook / @register_credential_hook
    # 的 import 时注册（与 mcv-oper-workflow 的扩展模式一致）。
    import toyflow.hooks  # noqa: F401

    return load_config_from_file(config_file, config_class=ToyflowConfig)


@click.group()
def main():
    """toyflow —— 基于 takflow 的最小工作流生成器示例。"""
    pass


# ── resource ─────────────────────────────────────────────

@main.group()
def resource():
    """Resource management commands."""
    pass


@resource.command("copy")
@click.option("--config-file", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--output-repo-base", default=None, type=click.Path(dir_okay=True))
@click.option("--workflow-repo-base", default=None, type=click.Path(exists=True, dir_okay=True))
def resource_copy(config_file: str, output_repo_base: str, workflow_repo_base: str):
    """Copy static resources (scripts/, ecflow/include/) to OUTPUT_REPO_BASE."""
    config = _load_config(config_file)
    output_repo_base = get_output_repo_base_dir(config, output_repo_base)
    workflow_repo_base = get_workflow_repo_base_dir(config, workflow_repo_base)

    copy_resources_to_output(
        output_repo_base=Path(output_repo_base),
        src_base=Path(workflow_repo_base),
    )
    click.echo(f"Copied resources from: {workflow_repo_base}")
    click.echo(f"Copied resources to: {output_repo_base}")


# ── config ───────────────────────────────────────────────

@main.group("config")
def config_group():
    """Config management commands."""
    pass


@config_group.command("generate")
@click.option("--config-file", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--output-repo-base", default=None, type=click.Path(dir_okay=True))
@click.option("--workflow-repo-base", default=None, type=click.Path(exists=True, dir_okay=True))
def config_generate(config_file: str, output_repo_base: str, workflow_repo_base: str):
    """Generate config file (config.sh for shell/takler, config.h for ecflow)."""
    config = _load_config(config_file)
    output_path = render_config(
        config=config,
        workflow_repo_base=workflow_repo_base,
        output_repo_base=output_repo_base,
    )
    click.echo(f"Generated: {output_path}")


# ── job ──────────────────────────────────────────────────

@main.group()
def job():
    """Job management commands."""
    pass


@job.command("generate")
@click.option("--config-file", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--output-repo-base", default=None, type=click.Path(dir_okay=True))
@click.option("--workflow-repo-base", default=None, type=click.Path(exists=True, dir_okay=True))
def job_generate(config_file: str, output_repo_base: str, workflow_repo_base: str):
    """Generate job scripts from Jinja2 templates (jobs/**/*.j2)."""
    config = _load_config(config_file)
    output_repo_base = get_output_repo_base_dir(config, output_repo_base)
    workflow_repo_base = get_workflow_repo_base_dir(config, workflow_repo_base)

    render_jobs_from_directory(
        config=config,
        repo_base=str(workflow_repo_base),
        output_repo_base=str(output_repo_base),
    )


# ── workflow ─────────────────────────────────────────────

@main.group("workflow")
def workflow_group():
    """Workflow management commands."""
    pass


@workflow_group.command("generate")
@click.option("--config-file", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--output-repo-base", default=None, type=click.Path(dir_okay=True))
def workflow_generate(config_file: str, output_repo_base: str):
    """Generate workflow definition (ecflow .def / takler .json)."""
    config = _load_config(config_file)
    output_path = generate_workflow(config=config, output_repo_base=output_repo_base)
    click.echo(f"Generated: {output_path}")


# ── credential ───────────────────────────────────────────

@main.group()
def credential():
    """Credential management commands."""
    pass


@credential.command("generate")
@click.option("--credential-file", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--config-file", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--output-repo-base", default=None, type=click.Path(dir_okay=True))
def credential_generate(credential_file: str, config_file: str, output_repo_base: str):
    """Render config/credential.sh from credential.yaml via credential hooks."""
    config = _load_config(config_file)
    output_repo_base = get_output_repo_base_dir(config, output_repo_base)

    render_credential(
        credential_file=credential_file,
        config=config,
        output_repo_base=str(output_repo_base),
        build_info_lines=toyflow_build_info_lines(),
    )
    click.echo(f"Generated: {Path(output_repo_base, 'config', 'credential.sh')}")


if __name__ == "__main__":
    main()
