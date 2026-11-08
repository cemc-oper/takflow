# 标准命令契约

本契约执行 [TC-12 决策](../develop/standard-cli-decision.md)。应用 CLI 可通过 `create_cli(application, name=...)` 绑定 Application、无参工厂或显式引用；通用入口需要 `--application module:attribute`。不提供自动发现。

```bash
takflow --application cma_tym.application:make_application --format json build --config-file config.yaml --machine-name hpc2023 --output-repo-base ./output
cma-tym-v4-workflow standard --format json resource copy --config-file config.yaml --machine-name hpc2023
python -m takflow --help
```

## 命令与参数

根参数必须放在命令之前：`--application module:attribute`、`--format text|json`（默认 text）、`--version`、`--help`。绑定入口拒绝 `--application`，防止误选其他应用。help/version 不执行应用工厂或读取配置。

| 命令 | 操作 | 特有参数 |
| --- | --- | --- |
| build | 完整 resource→config→credential→job→workflow→check→report | --output、--credential-file |
| resource copy | 仅 resource | 无 |
| config generate | 仅 config | 无 |
| credential generate | 仅 credential，可选未启用则 skipped | --credential-file |
| job generate | 仅 job | 无 |
| workflow generate | 仅 workflow | --output |

每个叶命令接受 `--config-file`（必需）、`--output-repo-base`、`--workflow-repo-base`（资源根）、`--machine-name`、`--machine-dir`。模式由配置选择，不新增模式覆盖参数、通用 --set 或 oper 历史参数超集。命令未声明的参数被拒绝。machine 覆盖先于领域归一化与路径派生；冲突由应用受控校验。shell 不支持 --output，固定根 run_workflow.sh，传入时受控失败。其余路径与来源优先级直接遵循 [Application](application.md)，CLI 不预先检查目标机路径。

完整 build 使用 build；五个分步命令调用同名 run_stage，每次独立 prepare 一次。分步不补跑前置阶段，未选择阶段为 not_run，成功不等于 complete。任何改写入口按公共管线规则撤销旧成功清单，只有完整验证后才原子发布 generation_manifest.json。

## 结果与退出码

执行成功退出 0；应用引用/工厂、配置、准备、模板、写入、验证失败退出 1；命令语法、缺参、非法选项或非法选择退出 2；执行中用户中断退出 130。帮助/版本退出 0。语法错误使用 Click 的 stderr 提示（包括所给参数），不输出 JSON；`--format` 只控制已正确解析的执行报告，不应在命令行参数中传递凭证内容。

JSON 在 stdout 输出一个对象：`schema_version: 1`、`status: success|failed`、`result: BuildResult.as_dict()|null`、`diagnostics: []`、`warnings: []`。构建失败保留部分 result，其诊断和阶段包含 passed/skipped/failed/not_run；准备失败没有 result。warnings 只包含受控代码和数量，不含原 warning 文本。text 输出相同状态、各阶段原因、诊断及全部产物路径/角色/权限，完整成功时显示清单位置。JSON 的 artifacts 包含同一管线记录的来源与摘要，敏感产物遵循 BuildResult 的摘要省略规则。

框架捕获执行期间应用任意打印、日志、warning 和原异常，禁止 traceback 与原异常正文进入 CLI；初始化和工厂失败使用 CLI_APPLICATION_LOAD/PREPARE_FAILED，配置/检查沿用受控诊断，BuildError 保留公共部分结果。显式 module 引用会执行该 Python 模块，须使用可信的已安装应用。调用命令期间不要并行改变进程日志或标准流；Python 并行与 hook 的限制与 Application 一致。

## 发布与迁移

参见[迁移公告](cli-migration.md)。TYM 默认根命令已由 TC-07 切换到公共实现；standard 子命令仅作临时转发别名，0.4.0 移除。当前发布状态仍为未发布 R1 候选，依赖配套见迁移公告。
