# =============================================================================
# BEGIN include takflow:ecflow/include/common/requeue.h
# =============================================================================
# 按 REQUEUE 的当前值选择 Slurm 重排队配置片段。
# INCLUDE [ecflow] <common/requeue-%%REQUEUE:unset%%.h>
%include <common/requeue-%REQUEUE:unset%.h>
# =============================================================================
# END include takflow:ecflow/include/common/requeue.h
# =============================================================================
