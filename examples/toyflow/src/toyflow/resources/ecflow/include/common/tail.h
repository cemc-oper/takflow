# =============================================================================
# BEGIN include toyflow:ecflow/include/common/tail.h
# =============================================================================
# 等待后台进程并结束 toyflow 示例作业。
date
wait                      # wait for background process to stop
ecflow_client --complete  # Notify ecFlow of a normal end
trap 0                    # Remove all traps
exit 0                    # End the shell
# =============================================================================
# END include toyflow:ecflow/include/common/tail.h
# =============================================================================
