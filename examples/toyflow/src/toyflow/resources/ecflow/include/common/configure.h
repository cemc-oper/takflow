# =============================================================================
# BEGIN include toyflow:ecflow/include/common/configure.h
# =============================================================================
# 将 ecFlow 时次和输出路径传给 toyflow 的运行配置。
export OUTPUT_REPO_BASE=%OUTPUT_REPO_BASE%
export YMD=%YMD%
export HH=%HH%
export START_TIME=${YMD}${HH}
%include <config/config.h>
# =============================================================================
# END include toyflow:ecflow/include/common/configure.h
# =============================================================================
