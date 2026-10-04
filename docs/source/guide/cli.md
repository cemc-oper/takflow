# 构建命令行接口

`takflow.toolkit` 提供构建 CLI 的原子能力。典型业务应用 CLI 如下（对应 toyflow 的
`src/toyflow/cli.py`，省略了 click 选项声明）：

```python
from pathlib import Path

import click

from takflow.toolkit import (
    copy_resources_to_output,
    render_credential,
    render_jobs_from_directory,
    set_build_info_provider,
)

from toyflow.config import ToyflowConfig, load_config_from_file
from toyflow.generate import toyflow_build_info_lines

# 让 toolkit 渲染的文件头带上应用品牌(否则是通用 takflow 头)
set_build_info_provider(toyflow_build_info_lines)


def _load_config(config_file: str) -> ToyflowConfig:
    # 先 import hooks,触发 @register_engine_hook / @register_credential_hook
    # 的 import 时注册(与 mcv-oper-workflow 的扩展模式一致)
    import toyflow.hooks  # noqa: F401

    return load_config_from_file(config_file, config_class=ToyflowConfig)


@click.group()
def main():
    pass


@main.group()
def resource():
    pass


@resource.command("copy")
@click.option("--config-file", required=True, type=click.Path(exists=True, dir_okay=False))
def resource_copy(config_file: str):
    """Copy static resources (scripts/, ecflow/include/) to OUTPUT_REPO_BASE."""
    config = _load_config(config_file)
    copy_resources_to_output(
        output_repo_base=Path(config.output_repo_base_dir),
        src_base=Path(config.workflow_repo_base_dir),
    )


@main.group()
def job():
    pass


@job.command("generate")
@click.option("--config-file", required=True, type=click.Path(exists=True, dir_okay=False))
def job_generate(config_file: str):
    """Generate job scripts from Jinja2 templates (jobs/**/*.j2)."""
    config = _load_config(config_file)
    render_jobs_from_directory(
        config=config,
        repo_base=config.workflow_repo_base_dir,
        output_repo_base=config.output_repo_base_dir,
    )


@main.group()
def credential():
    pass


@credential.command("generate")
@click.option("--credential-file", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--config-file", required=True, type=click.Path(exists=True, dir_okay=False))
def credential_generate(credential_file: str, config_file: str):
    """Render config/credential.sh from credential.yaml via credential hooks."""
    config = _load_config(config_file)
    render_credential(
        credential_file=credential_file,
        config=config,
        output_repo_base=config.output_repo_base_dir,
        build_info_lines=toyflow_build_info_lines(),
    )


if __name__ == "__main__":
    main()
```

资源/输出目录的解析优先级（CLI 参数 > 配置字段 > 包内 `resources/` 或报错）由应用侧的小工具
函数实现，见 toyflow 的 `src/toyflow/util.py`。`config generate` 与 `workflow generate` 两步
由应用自己实现（takflow 刻意留给应用），见 toyflow 的 `src/toyflow/generate.py`。

## 凭证渲染 Hook

`takflow.toolkit.credential` 提供共享的凭证渲染钩子注册表（对应 toyflow `hooks.py` 的
credential 部分）：

```python
from takflow.toolkit.credential import (
    CredentialContext,
    CredentialHookPoint,
    register_credential_hook,
)


@register_credential_hook(CredentialHookPoint.RENDER, priority=10)
def render_toyflow_credential(context: CredentialContext) -> str:
    """把 credential.yaml 中的应用段渲染为 credential.sh 片段。"""
    toyflow = context.credential.get("toyflow", {})
    return "\n".join(
        [
            "# toyflow API 凭证",
            f'export TOYFLOW_API_HOST="{toyflow.get("api_host", "")}"',
            f'export TOYFLOW_API_KEY="{toyflow.get("api_key", "")}"',
        ]
    )
```

`render_credential()` 按优先级收集所有注册片段并写入 `config/credential.sh`。业务扩展包
（如 `mcv-oper-workflow`）在**同一个 takflow 全局注册表**上以更高优先级注册自己的渲染器。
