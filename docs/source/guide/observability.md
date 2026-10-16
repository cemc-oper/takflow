# 可选 Sledra 定义导出

`BaseWorkflowConfig.observability.enabled` 默认为 `false`。默认或显式关闭时，takflow 不读取 Sledra 契约、不导入 `jsonschema`，也不生成清单。原工作流定义、作业脚本和资源生成方式不变。

启用时安装 `takflow[observability]`，并让 `spec_dir` 指向已发布的 Sledra `share/sledra/spec/1.0.0` 绝对目录。takflow 读取其中的 `definition_manifest.schema.json`，核对 1.0.0 契约摘要并校验导出的清单。缺失或不兼容会在保存流程定义前报 `ObservabilityConfigError`。

```yaml
observability:
  enabled: true
  spec_dir: /opt/sledra/share/sledra/spec/1.0.0
  application_revision: app-source-revision
  config_revision: config-revision
```

应用在构建完节点树后，为**每个 Task 节点**显式传入 `TaskMapping`：稳定 `task_key`、类型、阶段、参数 schema、静态依赖，以及可选的引擎路径模板。`task_key` 由应用维护，不从引擎路径推导。`export_definition_manifest` 要求映射完整、键唯一、依赖存在，返回内容寻址的 `DefinitionManifest`；`write_definition_manifest` 保存它。应用可使用 `expand_task_parameters` 在实际发起前展开默认值，并拒绝缺少必需参数、未声明参数或错误类型。`member`、`lead_seconds` 等实例参数必须显式声明，不能只靠 `task_key` 区分任务实例。

`examples/toyflow/src/toyflow/generate.py` 展示了接入位置：在 `save_suite` 前校验并生成静态清单，成功后保存 `definition_manifest.json`。配置中的 `application_revision` 和 `config_revision` 由应用提供，映射版本由应用代码维护。inline 和 external 脚本模式都可以导出，模式会写入清单扩展字段。生成期不登记 Run 或 Attempt，也不调用 recorder；实际发起和任务尝试属于后续集成阶段。
