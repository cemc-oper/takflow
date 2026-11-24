# 测试

```bash
pytest
```

## orvix 一致性测试（对拍）

jobspec 契约的消费侧验收门，针对 vendor 副本（同步自 orvix @
`spec/jobspec/ORVIX_VERSION` pin）做两层断言：

1. **渲染稳定性**：takflow 渲染器（`build_script(CASES[name])`）必须逐字节复现
   vendor 的 `conformance/vectors/<name>.sh`——即渲染器仍遵守契约的标准向量；
2. **翻译对拍**：pin 版本的 `orvix generate --scheduler X` 作用于 vendor 向量，
   输出必须等于 vendor 的 `golden/X/<name>.submit`。

第 2 层需要 `orvix` 二进制（CI 从 pin 的 orvix 源码构建）：

```bash
ORVIX_BIN=/path/to/orvix pytest tests/test_conformance.py
```

如果未找到 `orvix`，第 2 层测试会被跳过。

普通 `pytest` 的可选依赖跳过不代表 CI 契约通过。声明必测的专用 CI job 改用下述严格门禁，缺依赖、漏收集或跳过会失败。

## 固定依赖与必测门禁

`scripts/run_contract_tests.py` 是 CI 和本地复查共用入口。测试文件必须存在，指定检查必须实际收集并通过；专用契约线还校验 case 数量，拒绝 skip、xfail、xpass 和 deselection。基础线只允许非必测的可选测试跳过，必要测试在 setup/call/teardown 任一阶段被禁用都会失败。普通 pytest 的原有 skip 语义保留。

| CI job | 固定来源与环境 | 必测内容及失败条件 |
|---|---|---|
| `test` | Python 3.10/3.11/3.12/3.13；消费本仓库 uv.lock 安装 takflow 与 dev 依赖，不安装 takler/ecFlow | 导入时确认两个可选引擎均不存在，运行完整测试。必测入口覆盖公共配置、jobspec、serializer、标准 CLI／管线、有效配置／扩展组合、可选输入、失败恢复及 Bash 外部脚本的字面路径与参数 |
| `conformance` | `spec/jobspec/ORVIX_VERSION` 的完整 commit，使用该源码的 go.mod；Python 依赖消费框架 uv.lock | 18 个契约文件的 vendor 对照，16 项向量与 golden 检查，3 项 ORVIX 转换与公共原生 Slurm 头的逐行对照。缺少 binary、用例、实际执行或发生漂移均失败 |
| `takler` | `spec/takler/TAKLER_VERSION` 的完整 commit、该修订自身 uv.lock、Python 3.13 及 conformance job 的 orvix artifact | 17 项用例核对父级资源调整、标准构建、定义加载、原生 job 创建、inline／external 的 Bash 执行，以及本地 direct 执行、拒绝串行／并行直接 Slurm。连续两次 attempt 用命令替身核对 ORVIX 提交、元数据取消参数和父级 scheduler。公共头尾用例核对当前 attempt 的身份和退出码 |
| `native-ecflow` | Ubuntu 24.04 的 `python3-ecflow=5.12.0-1build3`、系统 Python 3.12 和 `ksh93u+m` | 16 项原生用例覆盖同一任务两次 try 的 ORVIX、历史 Slurm 命令参数与本地直接执行、三态 requeue、定义读取、job 展开、缺 include、同目录撤下组件覆盖、ORVIX 资源继承、machine 更新、inline／external 的 Bash 调用，以及 Ksh93 前台调用和两处 wait 收到 SIGTERM 的处理 |
| `build` | 从 sdist 构建 wheel，隔离环境安装 wheel 与 toyflow | 三个冒烟脚本检查公共API/包数据、标准CLI及toyflow生成；必须来自当前site-packages，拒绝editable或PYTHONPATH源码遮蔽 |

orvix artifact 仅在 vendor 和严格对拍通过后上传；takler job 依赖其成功，下载后核对 pin、SHA-256 并恢复执行权限。没有改用当前 runtime 工作树或浮动 main。升级 pin 必须在权威仓库修复并验收合同，框架不增加一套模拟 runtime 来取得通过。

当前 takler pin 为 `3dd79bebe2cc854215bf1e45c1fc4860aefa1034`，orvix pin 为 `59855f64e3c21e2b6e361ccee695e4ddd4d22dbf`。实际来源始终读取包内TAKLER_VERSION/ORVIX_VERSION；升级后重新核对vendor与对拍，不能沿用旧binary结果。takler的依赖按该修订权威lock安装，包含与其生成代码匹配的grpcio1.83.0；不要只在已有环境中随意安装一个takler包，再忽略导入失败。

takler自身的lock不必包含框架独有依赖，例如Click。锁定安装takler后，正常解析并安装框架所需依赖，再运行uv pip check；不能用--no-deps留下缺失依赖。记录实际安装版本，并核对原takler锁定包未被无意升级。

必测入口和用例数量见 `scripts/run_contract_tests.py`。基础线从标准 Shell runner 执行业务，takler 专用线通过固定版本的 `create_job_script()` 创建最终脚本并在本地执行，两者共用业务输入和退出断言。完整基础线的通过和可选跳过总数随测试增长，验收应记录实际收集结果。启用可选的观测 schema 检查时，需安装声明的 jsonschema 依赖并实际运行。

### 本地复查

在 takflow 仓库运行，`ORVIX_BIN` 指向从现有 pin 编译的真实可执行文件，`TAKLER_REPO` 指向按 pin 检出的干净源码：

```bash
# 无可选引擎的独立环境
uv sync --locked --no-default-groups --group dev --python 3.13
.venv/bin/python scripts/run_contract_tests.py base

# 保留既有 vendor 检查，再运行严格对拍
python scripts/sync_jobspec.py --check --orvix-repo /path/to/pinned-orvix-source
ORVIX_BIN=/path/to/pinned-orvix python scripts/run_contract_tests.py orvix

# 使用该 takler 修订自己的锁定环境；不修改共享 venv
uv sync --project /path/to/pinned-takler --locked --no-default-groups --group test --python 3.13
uv pip install --python /path/to/pinned-takler/.venv/bin/python -e .
uv pip check --python /path/to/pinned-takler/.venv/bin/python
TAKLER_REPO=/path/to/pinned-takler ORVIX_BIN=/path/to/pinned-orvix /path/to/pinned-takler/.venv/bin/python scripts/run_contract_tests.py takler

# 安装上述 Ubuntu native 包后，使用与其 ABI 一致的系统 Python
uv venv --python /usr/bin/python3 --system-site-packages /tmp/native-ecflow
uv pip install --python /tmp/native-ecflow/bin/python -e . pytest
/tmp/native-ecflow/bin/python scripts/run_contract_tests.py native

# build/twine 不在 dev 依赖组中，安装到本次使用的 .venv
uv pip install --python .venv/bin/python build twine
# build 默认先创建 sdist，再从它构建 wheel
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
.venv/bin/python -m venv /tmp/takflow-wheel-smoke
/tmp/takflow-wheel-smoke/bin/python -m pip install dist/takflow-*.whl examples/toyflow
```

三个安装冒烟脚本使用绝对路径并在源码树外运行；如当前仓库为 `/path/to/takflow`：

```bash
cd /tmp
/tmp/takflow-wheel-smoke/bin/python /path/to/takflow/scripts/smoke_wheel_resources.py
/tmp/takflow-wheel-smoke/bin/python /path/to/takflow/scripts/smoke_cli_wheel.py
/tmp/takflow-wheel-smoke/bin/python /path/to/takflow/scripts/smoke_toyflow_wheel.py
```

native 包需要匹配的 Python ABI 和 Ubuntu build，CI 升级版本时需重新验证。原生门禁先通过 `check_job_creation()` 创建 `.job0`，再用 Bash 验业务调用，用 Ksh93 验信号与等待。替身客户端记录回调顺序，测试核对作业进程退出码。真实服务回调、调度提交及业务 modules／MPI、资料和 C3／C4 资格由对应消费者及现场验收负责。takler 的 submit／kill 命令和 `orvix generate` 各自验证命令或转换结果。

## 同步 vendor 副本

契约内容（schema、`#ORVIX` 词汇表、对拍向量与 golden 基线）一律在 orvix 仓库修改
（golden 由 orvix 侧 `make regen-golden` 重新生成）。orvix 侧合并后，在本仓库升 pin
同步：

```bash
git -C /path/to/pinned-orvix-source rev-parse '<tag-or-ref>^{commit}'
python scripts/sync_jobspec.py --orvix-ref <40位完整commit>
```

同步脚本原样保存输入 ref，CI 的 conformance job 只接受完整 commit，并用
`scripts/sync_jobspec.py --check` 校验 vendor 副本与 pin 完全一致，不一致即红。输出含 `(stale)` 时，上游删除对应的本地副本仍需在变更中显式处理并复核；同步脚本不会自动删除它们，不能把返回 0 当作同步完成。本地提交 orvix 改动前也可用
`python scripts/sync_jobspec.py --check --worktree` 预检未提交的工作树。
