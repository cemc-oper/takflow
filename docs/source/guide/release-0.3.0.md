# TakFlow 0.3.0 发布说明

0.3.0 重组了应用准备、构建、流程后端、作业渲染和产物检查。旧 Python 导入路径的移除属于不兼容变更。MCV、GFS Post、RA2 和 TYM 的配套版本依赖 `takflow>=0.3.0`。部署时使用同批框架、基础应用和所需 oper 扩展。[应用 CLI 与配套](cli-migration.md) · [架构设计](../develop/architecture.md)

## 已移除的入口

| 旧入口 | 迁移位置 |
|---|---|
| `takflow.toolkit.job` 和 `takflow.toolkit` 上的作业渲染函数 | 从 `takflow.jobs.render` 导入 `render_jobs_from_directory`、`render_single_job_file` 或 `generate_output_log_data`。从 `takflow.jobs.headers` 导入资源头函数和 `RESOURCE_TEMPLATE_HELPERS`。 |
| `takflow.toolkit.util` 和 `takflow.toolkit` 上的引擎辅助函数 | 从 `takflow.flow.backend` 导入 `common_setting`、`script_cmd_value` 和 `script_cmd_var_name`，从 `takflow.flow.scheduling` 导入 `set_scheduling`，从 `takflow.jobs.submission.direct` 导入 `shell_job`。 |
| `takflow.toolkit.resource.copy_resource_entries` 及根部转发 | 改从 `takflow.build.assets` 导入；`keep` 和 `check_report` 仍为可选参数。 |
| `takflow.toolkit.resource.copy_resources_to_output` | 没有直接替换的独立函数。标准路径使用 `Application` 与 `run_stage(context, "resource")`；独立复制需显式构造 `copy_resource_entries` 映射。旧可选目录发现和权限行为不能靠机械改名保留。 |
| `takflow.toolkit.resource.make_scripts_executable` | 已移除，无独立公共替代。声明 executable 资源条目或使用 `copy_resource_entries(..., executable=True)`，由标准复制设置精确权限。 |
| `takflow.toolkit.config.render_config_template` | 已移除，无等价的独立公共渲染器。标准迁移使用 `Application.prepare()` 和 `run_stage(context, "config")`；独立应用可像 toyflow 一样维护自己的 Jinja 渲染器。 |
| `takflow.toolkit.credential` | 从 `takflow.config.credentials` 导入凭证上下文、钩子注册和渲染函数。`render_credential(file_mode=...)` 参数已移除，独立渲染固定写出 `0600`。 |
| `takflow.toolkit.observability` 和 `takflow.toolkit.execution_environment` | 从 `takflow.observability` 导入运行环境、任务映射和定义清单导出。从 `takflow.config.workflow` 导入 `ObservabilityConfig`。 |
| `takflow.backends.ecflow` 和 `takflow.backends.takler` | 从 `takflow.flow.backends.ecflow` 导入 `EcflowBackend`，从 `takflow.flow.backends.takler` 导入 `TaklerBackend`。ecFlow serializer 位于 `takflow.flow.backends.ecflow.serializer`。 |
| `takflow.backends.runtime` 及载体模块 | 使用 `takflow.jobs.submission.set_runtime`。资源变量由 `takflow.jobs.submission.variables` 提供，载体命令位于 `.direct`、`.orvix` 和 `.slsubmit6`。从 `takflow.jobspec` 导入 `to_orvix_directives`、`render_resource_block` 和 `MARKER`。载体专用 `set_runtime` 及 `set_orvix_runtime`／`set_slsubmit_runtime` 已删除，不在新载体模块中提供同名函数。 |
| `takflow.generation` | 从 `takflow.flow.generate` 导入 `generate_workflow`、`GenerationContext` 和 `GenerationResult`。 |
| `takflow.artifact_checks` | 从 `takflow.checks` 导入 `check_artifacts` 和 `CheckResult`。 |
| `takflow._native_artifacts` 和 `takflow._job_paths` | 使用 `takflow.checks.check_artifacts` 或 `takflow check` 执行原生任务展开和产物校验，不提供私有实现模块的直接迁移入口。 |
| `takflow.flow.register_hook` | 从 `takflow.flow` 或 `takflow.flow.hook` 导入 `create_hook_decorator`。 |
| `takflow.toolkit`、`takflow.toolkit.job` 和 `takflow.build_info` 上的 `set_build_info_provider` | 全部移除。标准应用通过 `ApplicationBrand` 声明品牌；独立渲染用 `with takflow.build_info.build_info_scope(lines):` 包裹调用。 |

`takflow.application` 提供应用声明及准备，`takflow.build` 提供 `build`、`run_stage`、结果和异常，`takflow.checks` 保留原根部诊断与检查入口并增加产物检查。三个包的内部模块拆分不要求应用改用实现路径，继续从包根部导入公共符号。[公共 API](public-api.md) · [旧复制和配置接口迁移](legacy-adapters.md)

## 标准应用示例

安装同批 MCV 与 TakFlow 后，在独立目录放入有效的 MCV `config.yaml`。应用声明负责选择资源和流程，标准构建负责写出产物与清单。[MCV S1 应用声明](application.md)

```python
from mcv_workflow.application import make_application
from takflow.build import build

application = make_application()
with application.prepare("config.yaml", output_repo_base="mcv-output") as context:
    result = build(context)

print(result.manifest_path)
```

在同一目录核对生成物。

```bash
takflow check --integrity --manifest mcv-output/generation_manifest.json
```

## 验收与配套切换

七个配套包从各自的 sdist 构建 wheel，并通过源码树外的正常依赖解析。Python 3.12 和最低依赖组合 Python 3.10、Pydantic 2.0、Click 8.0 均通过六应用构建及安装检查。MCV S1 的 ecFlow 和 Shell 在同输入对照中通过各自清单的完整性检查，归一化已知的路径、版本和生成时间后，输出内容、权限和来源一致。[契约测试](../develop/testing.md)

对每个部署保留完整的环境锁、各包版本、制品摘要和配套配置。切换时在新环境安装同批包，在新输出根生成并检查清单。回退时用上一批完整组合和对应配置重建。实际业务资料、调度提交和预报产品按目标站点的流程验收。[CLI 迁移与回退](cli-migration.md)
