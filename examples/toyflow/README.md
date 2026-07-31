# toyflow —— takflow 最小完整示例

`toyflow` 是一个玩具天气预报系统的工作流生成器，演示如何用
[takflow](../../README.md) 从零构建一个领域工作流应用。它的角色相当于
`mcv-workflow` 的袖珍版：节点树只有 `obs → main → post` 三个任务，
但 takflow 的每一层都真实用到。

生成的流程结构（ecFlow 模式）：

```
toyflow/
├── admin/toggles            # 运维开关（defstatus complete）
├── time_triggers/00         # RepeatDate 调度 + 00:00 时间触发
├── obs/prepare              # 观测预处理（serial 作业）
├── main/forecast            # 预报（parallel 作业，trigger: obs/prepare）
│   └── verify               # 由 engine hook 注入的扩展任务
└── post/plot                # 后处理绘图（serial 作业，trigger: main/forecast）
```

## 这个示例演示了什么

| takflow 层 | toyflow 文件 | 演示点 |
|---|---|---|
| 配置层 `takflow.config` | `src/toyflow/config.py` | 子类化 `BaseWorkflowConfig`，只加领域字段 |
| 资源模型 `takflow.jobspec` | `config/toyflow.yaml` | YAML 里写 `TaskResource`（serial/parallel） |
| 抽象层 `takflow.flow` | `src/toyflow/flow.py` | 后端无关地搭节点树、trigger、变量 |
| 转换层 `takflow.backends` | `src/toyflow/generate.py` | 换 backend 输出 ecFlow `.def` / takler JSON |
| 资源载体 | `flow.py` 的 `setup()` + 作业模板 | `set_runtime()` + 模板里 `render_orvix_resource_block` |
| 工具层 `takflow.toolkit` | `src/toyflow/cli.py` | 拼出 4 步生成管线 + credential 生成 |
| hook 系统 | `src/toyflow/hooks.py` | 应用自有 engine hook 注册表 + takflow 共享 credential hook |

## 运行

要求 Python >= 3.10，先安装 takflow 和本示例：

```bash
cd framework/takflow
pip install -e .
pip install -e examples/toyflow
```

也可以不安装，直接用 `PYTHONPATH` 运行（下面命令以此为例）：

```bash
cd framework/takflow/examples/toyflow
export PYTHONPATH=$PWD/src

# 1. 复制静态资源（scripts/、ecflow/include/）
python -m toyflow.cli resource copy --config-file config/toyflow.yaml \
    --output-repo-base /tmp/toyflow_output

# 2. 生成配置文件（ecflow 模式生成 config/config.h）
python -m toyflow.cli config generate --config-file config/toyflow.yaml \
    --output-repo-base /tmp/toyflow_output

# 3. 从 Jinja2 模板生成作业脚本（jobs/**/*.sh.j2 → *.ecf）
python -m toyflow.cli job generate --config-file config/toyflow.yaml \
    --output-repo-base /tmp/toyflow_output

# 4. 生成工作流定义（toyflow.def）
python -m toyflow.cli workflow generate --config-file config/toyflow.yaml \
    --output-repo-base /tmp/toyflow_output

# 可选：生成凭证文件 config/credential.sh
python -m toyflow.cli credential generate --config-file config/toyflow.yaml \
    --credential-file config/credential.yaml \
    --output-repo-base /tmp/toyflow_output
```

整个生成过程是纯本地渲染，**不需要 ecFlow / Slurm / HPC 环境**；
只有提交运行生成的 `.def` 才需要 HPC。

## 生成的产物

```
/tmp/toyflow_output/
├── toyflow.def              # ecFlow 定义文件（含 #ORVIX 提交方式变量）
├── config/
│   ├── config.h             # 作业运行时加载的配置
│   └── credential.sh        # 凭证（credential hook 渲染）
├── jobs/
│   ├── obs/prepare.ecf      # 作业脚本（含 #ORVIX 资源指令）
│   ├── main/forecast.ecf
│   └── post/plot.ecf
├── scripts/                 # 静态脚本（resource copy 复制）
└── ecflow/include/common/   # head.h / configure.h / tail.h
```

可以打开 `toyflow.def` 和 `jobs/main/forecast.ecf` 对照源码看每一行
是从哪一层来的。

## 把它改成你自己的应用

1. 复制本目录，把包名 `toyflow` 改成你的应用名。
2. 在 `config.py` 里替换成你的领域字段（功能开关、组件配置、任务资源）。
3. 在 `flow.py` 里搭你的节点树；扩展点走 `hooks.py` 的注册表，
   业务扩展包（相当于 `mcv-oper-workflow`）只需 import 时注册 hook。
4. 替换 `resources/` 里的作业模板和静态脚本。
5. CLI 基本不用动——`cli.py` 已经是从 `takflow.toolkit` 拼好的通用形态。

真实的大规模例子见 `app/mcv/mcv-workflow`（takflow 的第一个用户）。
