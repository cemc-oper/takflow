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
| `test` | Python 3.10/3.11/3.12/3.13；消费本仓库 uv.lock 安装 takflow 与 dev 依赖，不安装 takler/ecFlow | 导入时确认两个可选引擎均不存在，运行完整测试；公共配置、jobspec、serializer、ecFlow 生成和缺 takler 行为，以及应用路径/注册恢复、完整与分步等价、复制失败保留和清单发布失败共10项必须通过 |
| `conformance` | `spec/jobspec/ORVIX_VERSION` 的完整 commit，使用该源码的 go.mod；Python 依赖消费框架 uv.lock | 原有18文件 vendor 对照与全部向量/golden 对拍；没有 binary、少 case、skip 或漂移均失败 |
| `takler` | `spec/takler/TAKLER_VERSION` 的完整 commit、该修订自身 uv.lock、Python3.13；复用本次 conformance job 的已验证 orvix artifact | 核对 checkout HEAD/clean、实际模块原点与 Scheduler 导入；9函数12case覆盖完整管线、定义 export/parse/build/load、job render、orvix/direct/slsubmit6 的 submit/kill 命令合同；全数执行，零skip/xfail |
| `native-ecflow` | ubuntu-24.04 的 `python3-ecflow=5.12.0-1build3`，系统 Python3.12 ABI；API5.12.0 | 真 `ecflow.Defs(file)` 和 `check_job_creation`、include/变量替换、缺 include 负例及标准管线的machine更新；4case全数执行；包缺失或版本变化直接失败 |
| `build` | 从 sdist 构建 wheel，隔离环境安装 wheel 与 toyflow | 检查公共 API、schema/VERSION/两个 source pin、vector/golden 包数据与实际生成；必须来自当前 site-packages，拒绝 editable 或 PYTHONPATH 源码遮蔽 |

orvix artifact 仅在 vendor 和严格对拍通过后上传；takler job 依赖其成功，下载后核对 pin、SHA-256 并恢复执行权限。没有改用当前 runtime 工作树或浮动 main。升级 pin 必须在权威仓库修复并验收合同，框架不增加一套模拟 runtime 来取得通过。

本轮 takler pin 为 `3dd79bebe2cc854215bf1e45c1fc4860aefa1034`，orvix pin 为 `ab4916131c78c2d2e491d30de61968078c0353d4`。takler 的依赖按该修订权威 lock 安装，包含与其生成代码匹配的 grpcio1.83.0；不要只在已有环境中随意安装一个 takler 包，再忽略导入失败。

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
uv pip install --python /path/to/pinned-takler/.venv/bin/python --no-deps -e .
TAKLER_REPO=/path/to/pinned-takler ORVIX_BIN=/path/to/pinned-orvix /path/to/pinned-takler/.venv/bin/python scripts/run_contract_tests.py takler

# 安装上述 Ubuntu native 包后，使用与其 ABI 一致的系统 Python
uv venv --python /usr/bin/python3 --system-site-packages /tmp/native-ecflow
uv pip install --python /tmp/native-ecflow/bin/python -e . pytest
/tmp/native-ecflow/bin/python scripts/run_contract_tests.py native

# build 默认先创建 sdist，再从它构建 wheel
python -m build
twine check dist/*
python -m venv /tmp/takflow-wheel-smoke
/tmp/takflow-wheel-smoke/bin/python -m pip install dist/takflow-*.whl examples/toyflow
```

两个安装冒烟脚本使用绝对路径并在源码树外运行；如当前仓库为 `/path/to/takflow`：

```bash
cd /tmp
/tmp/takflow-wheel-smoke/bin/python /path/to/takflow/scripts/smoke_wheel_resources.py
/tmp/takflow-wheel-smoke/bin/python /path/to/takflow/scripts/smoke_toyflow_wheel.py
```

native 包不能与另一 Python ABI 混用；安装不到精确 Ubuntu build 时应报告缺依赖并修复环境，不以 serializer 或 mock 填补 native 结果。CI 的 runner/包版本升级需要显式复验。原生 `.job0` 创建只证明测试夹具的预处理，既没有连接 ecFlow server，也不执行脚本或提交 scheduler。takler 的 submit/kill 字符串合同和 `orvix generate` 同样不代表真实提交；业务 modules/MPI、资料、程序与 C3/C4 资格仍由对应消费者及现场验收负责。

## 同步 vendor 副本

契约内容（schema、`#ORVIX` 词汇表、对拍向量与 golden 基线）一律在 orvix 仓库修改
（golden 由 orvix 侧 `make regen-golden` 重新生成）。orvix 侧合并后，在本仓库升 pin
同步：

```bash
python scripts/sync_jobspec.py --orvix-ref <新版 orvix ref>
```

CI 的 conformance job 会用 `scripts/sync_jobspec.py --check` 校验 vendor 副本与
pin 完全一致，不一致即红。本地提交 orvix 改动前也可用
`python scripts/sync_jobspec.py --check --worktree` 预检未提交的工作树。
