"""Conformance cases shared between vector generation and tests.

Each case is a :class:`~takflow.jobspec.model.ResourceSpec` describing generic,
scheduler-neutral resources (``scheduler`` is left at the default so it is not
pinned in the vector — the backend is chosen by ``orvix generate --scheduler``).

The harness:  render a case to a ``#ORVIX`` script  ->  ``orvix generate
--scheduler X``  ->  diff against ``golden/X/<name>.submit``.
"""
from __future__ import annotations

from typing import Dict

from takflow.jobspec.model import ResourceSpec
from takflow.backends.runtime.orvix import to_orvix_directives

#: Schedulers exercised by the conformance harness.
SCHEDULERS = ("slurm", "donau", "local")

SHEBANG = "#!/bin/bash"

#: A trivial body appended after the directive block, shared by all cases.
BODY = 'echo "running ${0##*/}"\n'

#: name -> ResourceSpec. Covers the keys actually used by mcv / gfs / meso:
#: job_name, nodes, ntasks_per_node, time, queue, project, application, memory,
#: requeue.
CASES: Dict[str, ResourceSpec] = {
    # Parallel forecast task (mcv-style).
    "fcst_parallel": ResourceSpec(
        job_name="mcv_fcst",
        nodes="24",
        ntasks_per_node="64",
        time="00:30:00",
        queue="normal",
        project="op_mcv",
        application="mcv",
        memory="25G",
        requeue=False,
    ),
    # Serial post-processing task.
    "post_serial": ResourceSpec(
        job_name="mcv_post",
        time="00:15:00",
        queue="serial",
        project="op_mcv",
        application="mcv",
    ),
    # Memory-heavy graphics task (meso-style).
    "graph_mem": ResourceSpec(
        job_name="meso_graph",
        time="01:30:00",
        queue="normal",
        project="op_meso",
        application="op_grapes_meso_3km",
        memory="70G",
        requeue=False,
    ),
    # Regression (mcv 2.5 HPC run): ecFlow-created job files may start with
    # blank line(s) before the shebang — orvix must still hoist the shebang
    # ahead of the scheduler preamble. Serial task, mcv-style short walltime.
    "serial_leading_blank": ResourceSpec(
        time="5:00",
        queue="serial",
        project="op_mcv",
        application="mcv",
    ),
}

#: Cases whose vector starts with blank line(s) before the shebang.
LEADING_BLANK_CASES = frozenset({"serial_leading_blank"})


def build_script(spec: ResourceSpec, leading_blank: bool = False) -> str:
    """Render a full vector script (shebang + #ORVIX block + body) for ``spec``.

    ``leading_blank=True`` prepends a blank line before the shebang, mimicking
    ecFlow-created job files.
    """
    lines = [SHEBANG, *to_orvix_directives(spec), "", BODY.rstrip("\n"), ""]
    if leading_blank:
        lines.insert(0, "")
    return "\n".join(lines)


__all__ = ["SCHEDULERS", "CASES", "build_script", "SHEBANG", "BODY", "LEADING_BLANK_CASES"]
