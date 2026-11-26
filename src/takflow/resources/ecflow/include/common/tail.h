# =============================================================================
# BEGIN include takflow:ecflow/include/common/tail.h
# =============================================================================
# 等待后台进程并向 ecFlow 报告作业完成。
# Let ksh93 run a pending signal trap before errexit acts on wait.
wait || exit $?
ecf_phase=complete
ecflow_client --complete
trap - 0
exit 0
# =============================================================================
# END include takflow:ecflow/include/common/tail.h
# =============================================================================
