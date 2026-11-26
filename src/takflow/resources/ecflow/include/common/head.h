# =============================================================================
# BEGIN include takflow:ecflow/include/common/head.h
# =============================================================================
# 初始化 ecFlow 作业，登记运行进程并安排异常回调。
set -eu

export ECF_PORT="%ECF_PORT%"
export ECF_HOST="%ECF_HOST%"
export ECF_NODE="$ECF_HOST"
export ECF_NAME="%ECF_NAME%"
export ECF_PASS="%ECF_PASS%"
export ECF_TRYNO="%ECF_TRYNO%"
export ECF_JOBOUT="%ECF_JOBOUT%"
export ECF_RID="${SLURM_JOB_ID:-$$}"
if [ "$ECF_RID" = 0 ]; then
    ECF_RID=$$
fi
if [ -n "${HOME:-}" ]; then
    PATH="$PATH:$HOME/bin"
fi

# --- 安装异常和信号处理 ---
ecf_phase=init
ecf_signals='1 2 3 4 5 6 7 8 10 12 13 15'
ecf_error() {
    ecf_rc=$?
    trap - 0
    set +e
    for ecf_signal in $ecf_signals; do
        trap "echo 'received signal $ecf_signal during error handling' >&2" "$ecf_signal"
    done
    if [ "$ecf_rc" -eq 0 ]; then
        ecf_rc=1
    fi
    echo "job failed: phase=$ecf_phase status=$ecf_rc" >&2
    wait
    if [ "$ecf_phase" = running ]; then
        ecflow_client --abort=trap || echo "ecFlow abort failed: status=$?" >&2
    fi
    exit "$ecf_rc"
}
trap ecf_error 0
for ecf_signal in $ecf_signals; do
    trap "echo 'received signal $ecf_signal' >&2; exit $((128 + ecf_signal))" "$ecf_signal"
done

ecflow_client --init="$ECF_RID"
ecf_phase=running
# =============================================================================
# END include takflow:ecflow/include/common/head.h
# =============================================================================
