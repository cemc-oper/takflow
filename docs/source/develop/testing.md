# 测试

```bash
pytest
```

## orvix 一致性测试（对拍）

针对 `orvix` 的 jobspec 契约一致性测试需要 `orvix` 二进制文件：

```bash
ORVIX_BIN=/path/to/orvix pytest tests/test_conformance.py
```

如果未找到 `orvix`，一致性测试会被跳过。

## 重新生成 golden 基线

修改契约（schema、`#ORVIX` 词汇表或对拍向量）后，重新生成 golden 输出：

```bash
python -m takflow.spec.jobspec.conformance.regen
```

注意：golden 基线由真实 `orvix generate` 产生，因此 regen 也需要 `ORVIX_BIN` 可用。
