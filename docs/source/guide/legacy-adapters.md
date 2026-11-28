# 旧生成接口迁移

TakFlow 0.3.0 移除了 `takflow.toolkit` 及其转发入口。标准应用从 `takflow.application` 准备上下文，从 `takflow.build` 调用完整构建或独立阶段。低层调用可按需求选择下列 API。[0.3.0 迁移对照](release-0.3.0.md)

## 资源复制

标准应用在 `Application` 中声明 `ResourceEntry` 和有序 `ResourceLayer`。使用
`run_stage(context, "resource")` 复制资源并登记来源。相同的资源层顺序也用于配置和作业模板。
[标准构建](build.md)

旧 `copy_resource_entries` 可直接改从 `takflow.build.assets` 导入，传入
`(source, destination, executable)` 映射，两个路径分别相对于源根和目标根。
复制前核对路径、类型、权限和映射冲突，目标权限按条目设置为 `0755` 或 `0644`。

旧 `copy_resources_to_output` 没有等价的独立公共替代。可选目录需要调用方按存在情况显式声明，
标准应用使用 `run_stage(context, "resource")`，独立复制则自行构造完整条目映射。旧
`make_scripts_executable` 也已移除；不要再用遍历 `*.sh` 补执行位模拟标准复制，而应声明
executable 条目或使用 `copy_resource_entries(..., executable=True)` 的精确权限规则。

## 运行配置与凭证

旧 `render_config_template` 的调用方通过 `Application.prepare()` 取得构建上下文，
再调用 `run_stage(context, "config")`。标准配置为 `0644`，额外模板使用声明的权限。
独立凭证渲染使用 `takflow.config.credentials.render_credential`，以 `0600` 写出文件。
旧 `file_mode` 关键字已移除，调用方必须删除该参数，不能依赖旧权限覆盖。
[构建和资源 API](../reference/build.rst) · [配置和凭证 API](../reference/config.rst)

## 作业渲染和文件头

从 `takflow.jobs.render` 导入 `render_jobs_from_directory`、`render_single_job_file` 或 `generate_output_log_data`。资源模板 helper 由 `takflow.jobs.headers` 提供。标准构建使用 `Application` 声明的品牌。独立调用在渲染外层使用 `with takflow.build_info.build_info_scope(lines):`，作用域退出后恢复原来的文件头；`lines` 是 `get_build_info_lines()` 返回的文件头映射。[作业 API](../reference/jobs.rst) · [公共 API](public-api.md)
