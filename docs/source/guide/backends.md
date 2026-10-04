# 后端与资源载体

## 选择后端

`takflow` 通过 `backends/` 提供具体后端实现。应用通常按 `workflow_mode` 从映射表中取后端类，
切换后端只需更换 `WorkflowEngine` 构造参数（对应 toyflow 的 `src/toyflow/generate.py`）：

```python
from pathlib import Path

from takflow.flow import WorkflowEngine
from takflow.backends.ecflow import EcflowBackend
from takflow.backends.takler import TaklerBackend

_BACKEND_MAP = {
    "ecflow": EcflowBackend,
    "takler": TaklerBackend,
}
_DEFAULT_SUFFIX = {
    "ecflow": ".def",
    "takler": ".json",
}

mode = config.workflow_mode
engine = WorkflowEngine(_BACKEND_MAP[mode]())
suite = create_suite(config, engine=engine)  # 节点树构建见"流程与钩子"

output_path = Path(
    config.output_repo_base_dir,
    f"{config.workflow_name}{_DEFAULT_SUFFIX[mode]}",
)
engine.save_suite(suite, output_path)
```

## 资源载体

在 slurm workload 下，任务资源通过 `submit_carrier` 决定如何抵达调度器。suite 构建时调用一次
`set_runtime` 即可（对应 toyflow `flow.py` 的 `setup()`）：

```python
from takflow.backends.runtime import set_runtime

set_runtime(suite, config.workload, engine=engine)
# slsubmit6 carrier 还需要任务级资源:set_runtime(node, workload, engine=engine, task_resource=tr)
```

| Carrier | 生成内容 | 适用场景 |
|---------|----------|----------|
| `orvix` | `#ORVIX key=value` 指令 + `orvix submit` | `mcv-workflow` 默认 |
| `slsubmit6` | `%QUEUE%` / `%NODES%` / `%WCKEY%` 变量 + `slsubmit6` | `gfs-post` / `meso-post` 默认 |

两种 carrier 使用相同的 `TaskResource` 输入，切换只需改 YAML 中的 `workload.submit_carrier`。
