# 旧生成接口迁移

## 资源复制

标准应用在 `Application` 中声明 `ResourceEntry` 和有序 `ResourceLayer`。使用
`run_stage(context, "resource")` 复制资源并登记来源。相同的资源层顺序也用于配置和作业模板。
[标准构建](build.md)

独立复制用 `takflow.build.assets.copy_resource_entries`，传入
`(source, destination, executable)` 映射。两个路径分别相对于源根和目标根。
可选目录由调用方按存在情况声明。复制前核对路径、类型、权限和映射冲突，目标权限按条目设置为
`0755` 或 `0644`。采用旧 `copy_resources_to_output` 的调用方迁移至此入口。

## 运行配置与凭证

旧 `render_config_template` 的调用方通过 `Application.prepare()` 取得构建上下文，
再调用 `run_stage(context, "config")`。标准配置为 `0644`，额外模板使用声明的权限。
独立凭证渲染使用 `takflow.config.credentials.render_credential`，以 `0600` 写出文件。
[构建和资源 API](../reference/build.rst) · [配置和凭证 API](../reference/config.rst)
