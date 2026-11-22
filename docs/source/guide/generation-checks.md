# 检查已生成的产物

标准 `build` 校验配置和调用契约，按所选资源渲染、写出并登记本轮文件。完整构建成功后发布 `generation_manifest.json`。定义解析、Shell 语法和原生 job 展开可用 `takflow check` 单独运行。这个入口只接收已有文件和所选范围，可以在没有应用包、原配置及资源源码的环境中运行。

```bash
takflow check --definition output/suite.def --parse-definition
takflow check --shell output/scripts/main/forecast.sh
takflow --format json check --manifest output/generation_manifest.json --integrity
takflow check --manifest output/generation_manifest.json --expand /forecast_test/main/00/fcst/forecast
```

| 选项 | 输入与检查内容 |
| --- | --- |
| `--parse-definition` | 只读指定定义，使用 ecFlow 的 `Defs` 或 takler 的 `build_definition`。也可从清单选择定义。用 `--mode ecflow` 或 `--mode takler` 指定无法从文件名推断的格式。 |
| `--expand TASK` | 按绝对任务路径在私有临时目录创建一个原生 job。需要清单定位本轮模板与实际选中的 include。可以重复。 |
| `--shell FILE` | 对具体 Shell 脚本使用声明的解释器和受控环境运行 `-n`。可以重复。仍需引擎处理的模板或缺少解释器会报告未完成。 |
| `--integrity` | 按清单核对登记的输出是否存在、固定文件的权限和摘要。敏感文件只比对权限，可更新的 machine 文件允许内容和权限变化。外部 reference 不参与读取。 |

清单随输出树一起移动后，检查按原相对位置读取文件。显式保存到输出根之外的定义仍使用其登记路径。单选 `--definition … --parse-definition` 或 `--shell …` 可以检查失败构建留下的具体文件，无需完整成功清单。检查不会发布或改写清单。

## 原生展开

ecFlow 从任务及其父节点的有效变量定位已登记模板。支持框架生成的静态 `cat <已引用的绝对路径>`，包括定义没有 `ECF_FILES` 的情形，也支持按 `ECF_FILES` 查找。检查把所选模板和 include 准备到临时目录，在内存中移除原取模板命令，再调用 `check_job_creation`。任意取模板命令、未登记的外部 include 或不能解析的路径会报告未完成。

takler 在单独的进程中解析定义。它将所选任务的脚本、实际读取的 Jinja include、`TAKLER_HOME` 以及显式 `TAKLER_JOB`／`TAKLER_JOBOUT` 定位到临时目录，核实引擎解析的实际 job 路径，再调用原生 `check_job_creation()` 并核对新文件执行位。检查到临时 job 写出为止，不运行其中的 source、业务程序、调度命令或客户端回调。

## 结果与 Python 入口

每个所选范围都有 `scope`、`object`、`status`、`reason`。全部 `passed` 时 CLI 退出 0。产物损坏或原生解析器拒绝时为 `failed`。缺工具、所需输入超出产物集或写入无法隔离时为 `incomplete`。后两者均退出 1，命令语法错误退出 2。组合多个范围时各自报告结果。

```python
from takflow.artifact_checks import check_artifacts

result = check_artifacts(
    manifest="output/generation_manifest.json",
    parse=True,
    expand=["/forecast_test/main/00/fcst/forecast"],
)
print(result.as_dict())
```

## 生成时仍执行的契约

应用在 `prepare` 期间校验 Pydantic 配置和支持的模式、载体、调度器。已声明的必需来源、组件选择、输出冲突、路径边界及实际读取或写入错误由负责的生成阶段处理。Jinja 只读取实际选中的模板和引用。完整 ecFlow 构建按本轮渲染记录核对启用任务声明的本地作业，分步 `workflow generate` 可以消费已准备的作业。

低层调用可传入 `GenerationCheckReport` 收集本次操作的诊断及写出。标准构建的失败和部分产物见[构建结果](build.md)。独立检查和任务的实际运行结果各有自己的记录。
