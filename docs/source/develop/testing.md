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
