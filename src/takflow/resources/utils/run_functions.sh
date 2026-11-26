#!/usr/bin/env bash
# Run jobs under OUTPUT_REPO_BASE/jobs in order and stop on the first failure.
# Source logger.sh and the submission helper selected by the application first.

check_function_return() {
    local status=${2:-$?}
    local task_name="${1:-unknown}"
    if (( status == 0 )); then
        log INFO "[$task_name] Finished successfully (Status 0)."
    else
        LOGGER_FATAL_NO_EXIT=1 log FATAL "[$task_name] FAILED (Status $status). Stop workflow."
        exit "$status"
    fi
}

run() {
    local run_type=$1 script_name=$2
    local script_path="${OUTPUT_REPO_BASE}/jobs/${script_name}"
    if [[ ! -x "$script_path" ]]; then
        log ERROR "script $script_path not found or not executable."
        return 1
    fi

    # Both runners set -e. Capture the status before logging the failed step.
    local status=0
    case "$run_type" in
        local) "$script_path" || status=$? ;;
        orvix) submit_and_monitor_orvix_job "$script_path" || status=$? ;;
        slurm)
            if ! declare -F submit_and_monitor_slurm_job >/dev/null; then
                log ERROR "run type is not supported: slurm (application helper not loaded)"
                return 2
            fi
            submit_and_monitor_slurm_job "$script_path" || status=$?
            ;;
        *)
            log ERROR "run type is not supported: $run_type"
            return 2
            ;;
    esac
    check_function_return "$script_name" "$status"
}
