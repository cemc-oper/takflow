# 标准 CLI 决策（TC-12）

状态：已决定 · 日期：2026-11-08 · 替代 TF-09 的公共 CLI 禁令。

## 背景与替代关系

TF-09 针对原子 toolkit 与应用各自 renderer 作出不提供公共 CLI 的决定，原文保留为历史证据。TC-05 已建立 Application/BuildContext 的声明、初始化与路径规则，TC-06 已实现标准阶段和结果；现在不再需要以各应用 handler 注入重建第二套插件架构。本决定替代 TF-09 第 1、5、6 节中禁止 takflow.cli 和公共 console script 的限制；仍不建立 CLI 插件发现或统一历史选项超集。

## 责任与公共入口

框架提供 `takflow.cli.create_cli`、`load_application`、`ApplicationLoadError`，console script `takflow` 与 `python -m takflow`。显式 `module:attribute` 只允许 Application 或无参 Application 工厂，不扫描 entry points、配置目录或应用名称。绑定应用的命令组使用同一 create_cli，可保留应用名称。帮助和版本不加载应用、配置或可选引擎。

CLI 只解析参数、解析显式应用引用、进入一次 Application.prepare 并调用 build/run_stage，再展示受控结果。初始化、归一化、验证、资源选择、路径、阶段前置条件与成功清单均由 TC-05/06 实现。应用仅声明领域 config、构图、组件和模板上下文；不注册旧 resource/config/job/workflow handler。执行过程不 load 引擎、不提交任务、不执行 machine Shell。

## 命令与诊断契约

公共命令、选项位置、退出码与 JSON 格式以[标准命令契约](../guide/cli.md)为准。缺必需模板必须失败；单阶段调用不自动补跑前置阶段，也不产生完整成功标志。CLI 捕获应用导入、工厂、准备与构建中的 stdout/stderr、日志和 warning，不将任意文本混入报告；warning 仅报告数量。受控 TC-02/03 诊断及 BuildError 部分结果可展示，原始异常只由 Python API 保留。

## TYM 接入和迁移边界

本切片用生产包内声明 `cma_tym.application:make_application` 接入 `cma-tym-v4-workflow standard`，显式标准路径直接消费公共命令。旧根命令冻结在兼容窗口，TC-07 完成所有领域路径迁移后切换默认命令并用限期薄适配替代旧 handler。TC-12 不宣称旧 ecffiles 引用已经闭合、不将标准生成成功视为 HPC 运行资格。旧→新、最低版本和回退见[迁移公告](../guide/cli-migration.md)。

阶段清单 TC-12.5 的“旧命令/选项只做迁移映射”明确指标准入口不得调用旧 handler；旧默认入口的替换由已有 TC-07.7 承接。此交付顺序消除 TC-07 依赖 TC-12 命令验收的循环，保留整体阶段出口要求。
