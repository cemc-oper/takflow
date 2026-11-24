# 旧接口适配

本页是旧复制与配置渲染 Python 接口的行为归属页，集中说明尚未切换到标准 Application/build 生命周期的适配入口。新应用不要据此另建一套并行管线；标准行为见[标准构建](build.md)，命令与版本窗口见[CLI 迁移](cli-migration.md)，公共入口边界见[公共 API 与兼容策略](public-api.md)。

这些接口保留历史返回、权限和渲染行为，不发布标准成功清单，也不代表对应旧应用已经完成标准迁移。

## 旧复制接口的额外目录映射

标准阶段继续按 ResourceEntry 和 ResourceLayer 处理复制及来源；相同有序层同时供配置和作业模板读取。
旧 `takflow.toolkit.copy_resources_to_output` 可用 `additional_entries=((source, destination, executable), ...)`
声明额外目录，不再由应用补写 copytree。source/destination 均相对各自根目录，声明的目录必须存在，
统一进入类型、权限、重叠及目标冲突预检；可选目录由调用方在存在时才声明。同名目标冲突不能用此参数模拟覆盖，
标准多来源覆盖使用有序 ResourceLayer。

此旧接口沿用来源权限及 *.sh 补执行位的既有行为，映射目录的 executable 为 False 时不补执行位；
标准 `copy_resource_entries` 和构建阶段的精确权限策略不变。GFS base/oper 及旧 Execution 准备复用此机制，
其历史 include 布局、默认来源和 None 返回由兼容适配保留，不能将该低层映射当作完整标准构建或业务扩展的验收。

## 旧配置渲染适配

旧配置接口可以委托 `takflow.toolkit.render_config_template(config, template_path, output_path)`，
集中保留历史 Jinja 默认环境、写入和0755权限；返回 None，缺失模板抛出 TemplateNotFound，
可选/WARN策略由旧门面适配。此接口用于尚未切换的旧消费者，不发布成功清单，
随旧 toolkit 的[迁移窗口](cli-migration.md)退出。
标准应用继续通过 config 阶段使用同一严格环境、模板声明、0644角色权限和公共结果，
不调用该 legacy helper，也不添加应用环境 profile。
