# 可选 Sledra 接入

`BaseWorkflowConfig.observability.enabled` 默认为 `false`。默认或显式关闭时，takflow 不读取 Sledra 契约、不导入 `jsonschema`，也不生成清单。原工作流定义、作业脚本和资源生成方式不变。

旧模式 `mode: legacy-v1` 启用时安装 `takflow[observability]`，并让 `spec_dir` 指向已发布的 Sledra `share/sledra/spec/1.0.0` 绝对目录。takflow 读取其中的 `definition_manifest.schema.json`，核对 1.0.0 契约摘要并校验导出的清单。缺失或不兼容会在保存流程定义前报 `ObservabilityConfigError`。未指定 mode 的既有配置仍使用该模式。

```yaml
observability:
  enabled: true
  spec_dir: /opt/sledra/share/sledra/spec/1.0.0
  application_revision: app-source-revision
  config_revision: config-revision
```

应用在构建完节点树后，为**每个 Task 节点**显式传入 `TaskMapping`：稳定 `task_key`、类型、阶段、参数 schema、静态依赖，以及可选的引擎路径模板。`task_key` 由应用维护，不从引擎路径推导。`export_definition_manifest` 要求映射完整、键唯一、依赖存在，返回内容寻址的 `DefinitionManifest`；`write_definition_manifest` 保存它。应用可使用 `expand_task_parameters` 在实际发起前展开默认值，并拒绝缺少必需参数、未声明参数或错误类型。`member`、`lead_seconds` 等实例参数必须显式声明，不能只靠 `task_key` 区分任务实例。

`examples/toyflow/src/toyflow/generate.py` 展示了接入位置：在 `save_suite` 前校验并生成静态清单，成功后保存 `definition_manifest.json`。配置中的 `application_revision` 和 `config_revision` 由应用提供，映射版本由应用代码维护。inline 和 external 脚本模式都可以导出，模式会写入清单扩展字段。生成期不登记 Run 或 Attempt，也不调用 recorder；实际发起和任务尝试属于后续集成阶段。

## Execution 公共配置（P3-01）

新版必须显式选择 `execution-v2`，同样默认关闭：

```yaml
observability:
  enabled: true
  mode: execution-v2
  recorder_bin: /opt/sledra/bin/sledra
  bash_library: /opt/sledra/share/sledra/integrations/bash/sledra-execution.sh
  root: /shared/observability/example
```

三个路径是记录节点上的绝对 POSIX 路径，启用新版时必填，不允许控制字符。
生成节点不检查目标文件是否存在，也不执行 recorder 或初始化记录根。
新版不要求 `spec_dir`、Manifest、`takflow[observability]`、手工 context／ID、Run 或后端。
旧定义导出入口遇到新版配置返回 `None`，不加载旧契约；其余旧配置行为保持。

应用适配器从公共函数获取需要装配的值：

```python
from takflow.toolkit import execution_environment

values = execution_environment(config.observability)
# 新版启用：SLEDRA_MODE、SLEDRA_BIN、SLEDRA_BASH_LIBRARY、SLEDRA_ROOT。
# 默认关闭、显式关闭或旧模式：空 dict，跳过新版适配器装配。
```

返回值是原始字符串数据。应用按所用 Shell／模板规则引用和转义，不能把值当命令执行。
该函数不写环境、不创建文件，不从节点名称推断逻辑任务、业务 cycle 或参数。
应用在公共任务入口调用已有 Bash `sledra_execution_begin`，实际参数确定后调用一次
`sledra_execution_context`，owner 保存原始 rc／signal 后结束；业务规则和引擎回调由应用适配器维护。
默认关闭时应完全跳过新版资源和钩子，不能通过继承环境意外启用。

部署者先用匹配的 recorder `execution init-root` 初始化独立根，显式提供 system、deployment、
partition-timezone；这些值由根的 `sledra.json` 保存，无需在每个任务或生成配置重复填写。
根必须位于业务清理目录之外，新旧根隔离；目标权限、实际路径与符号链接关系由部署检查确认。
关闭观测不会删除、迁移已记录历史。

P3-01 只交付公共配置和环境值接口。应用的源模板装配、稳定 task／参数映射及生成依赖检查
在对应接入阶段验证；设置本配置本身不证明任意应用已接入，GFS 装配留待 P3-02。
独立 Bash 接入仍直接使用 Sledra，无需安装 takflow。
