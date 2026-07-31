"""toyflow 流程定义。

用 ``takflow.flow`` 的后端无关抽象 API 搭建节点树：

    toyflow/
    ├── admin/toggles            # 运维开关（defstatus complete）
    ├── time_triggers/00         # 时间调度（RepeatDate + time）
    ├── obs/prepare              # 观测预处理（serial）
    ├── main/forecast            # 预报（parallel，trigger: obs）
    │   └── verify               # 由 engine hook 注入
    └── post/plot                # 后处理绘图（serial，trigger: forecast）

同一套代码通过 ``WorkflowEngine(backend)`` 换后端即可输出 ecFlow ``.def``
或 takler JSON。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from takflow.backends.runtime import (
    common_setting,
    script_cmd_var_name,
    script_cmd_value,
    set_runtime,
    set_scheduling,
)

from toyflow.config import ToyflowConfig
from toyflow.hooks import (
    EngineHookContext,
    EngineHookPoint,
    get_engine_hook_registry,
)
from toyflow.util import get_output_repo_base_dir, get_workflow_repo_base_dir

if TYPE_CHECKING:
    from takflow.flow import Node, WorkflowEngine


class ToyflowSystem:
    """toyflow 工作流系统：负责把配置翻译成节点树。

    Attributes
    ----------
    name : str
        Suite / Flow 名称。
    config : ToyflowConfig
        工作流配置。
    engine : WorkflowEngine
        takflow 工作流引擎（后端由调用方注入）。
    """

    def __init__(self, config: ToyflowConfig, engine: "WorkflowEngine"):
        self.name = config.workflow_name
        self.config = config
        self.engine = engine

        self.workflow_repo_base_dir = get_workflow_repo_base_dir(config)
        self.output_repo_base_dir = get_output_repo_base_dir(config)
        self.jobs_dir = Path(self.output_repo_base_dir, "jobs")

    def build_suite(self) -> "Node":
        suite = self.engine.Suite(self.name)
        self.setup(suite)
        self.admin(suite)
        self.time_triggers(suite)
        if self.config.enable_obs:
            self.obs(suite)
        if self.config.enable_main:
            self.main(suite)
        if self.config.enable_post:
            self.post(suite)
        return suite

    # ------------------------------------------------------------------
    # Suite 级设置
    # ------------------------------------------------------------------
    def setup(self, suite: "Node") -> None:
        """Suite 变量：提交命令（资源载体）、引擎公共设置、路径变量。"""
        # 资源载体：orvix -> ECF_JOB_CMD=orvix submit ...；slsubmit6 -> %CLASS% 等变量
        set_runtime(suite, self.config.workload, engine=self.engine)
        suite.add_variables(common_setting(engine=self.engine))

        suite_vars = {
            "WORKFLOW_REPO_BASE": str(self.workflow_repo_base_dir),
            "OUTPUT_REPO_BASE": str(self.output_repo_base_dir),
        }
        if self.engine.backend_type == "ecflow":
            suite_vars["ECF_INCLUDE"] = ":".join(
                [
                    str(self.output_repo_base_dir),
                    str(Path(self.output_repo_base_dir, "ecflow/include")),
                ]
            )
        suite.add_variables(suite_vars)

    # ------------------------------------------------------------------
    # 节点树
    # ------------------------------------------------------------------
    def admin(self, suite: "Node") -> "Node":
        fm_admin = suite.add_family("admin")
        fm_admin.set_defstatus_complete()
        fm_admin.add_task("toggles")
        return fm_admin

    def time_triggers(self, suite: "Node") -> "Node":
        fm = suite.add_family("time_triggers")
        if self.config.scheduling is not None:
            set_scheduling(fm, self.config.scheduling, engine=self.engine)
        for cycle_name, cycle_config in (self.config.cycles or {}).items():
            tk = fm.add_task(cycle_name)
            if cycle_config.time is not None:
                tk.add_time(cycle_config.time)
            else:
                tk.set_defstatus_complete()
        return fm

    def obs(self, suite: "Node") -> "Node":
        fm_obs = suite.add_family("obs")
        tk = fm_obs.add_task("prepare")
        self._set_script(tk, "obs/prepare")
        return fm_obs

    def main(self, suite: "Node") -> "Node":
        fm_main = suite.add_family("main")
        tk = fm_main.add_task("forecast")
        if self.config.enable_obs:
            tk.add_trigger(f"/{self.name}/obs/prepare == complete")
        self._set_script(tk, "main/forecast")

        # engine hook：扩展包可在预报之后注入任务（toyflow 自带演示 hook 会加 verify）
        context = EngineHookContext(
            node=fm_main,
            engine=self.engine,
            kwargs={"jobs_dir": self.jobs_dir},
        )
        get_engine_hook_registry().execute(EngineHookPoint.AFTER_FORECAST, context)
        return fm_main

    def post(self, suite: "Node") -> "Node":
        fm_post = suite.add_family("post")
        tk = fm_post.add_task("plot")
        if self.config.enable_main:
            tk.add_trigger(f"/{self.name}/main/forecast == complete")
        self._set_script(tk, "post/plot")
        return fm_post

    # ------------------------------------------------------------------
    def _set_script(self, task: "Node", relative_path: str) -> None:
        """把任务指向生成的作业脚本（ecflow: cat xxx.ecf；takler: xxx.sh 路径）。"""
        suffix = ".ecf" if self.engine.backend_type == "ecflow" else ".sh"
        task.add_variable(
            script_cmd_var_name(self.engine),
            script_cmd_value(self.engine, self.jobs_dir, f"{relative_path}{suffix}"),
        )


def create_suite(config: ToyflowConfig, engine: "WorkflowEngine") -> "Node":
    """构建 toyflow suite，返回根节点。"""
    system = ToyflowSystem(config, engine)
    return system.build_suite()
