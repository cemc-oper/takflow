#!/usr/bin/env bash
# Submit a job through Orvix and wait for a confirmed scheduler result.
# Source logger.sh before using submit_and_monitor_orvix_job SCRIPT [INTERVAL].

# Read the pinned ORVIX status JSON from stdin. Keep the four fields on one
# tab-separated line for Bash, including scheduler qualifiers in raw_state.
_orvix_status_fields() {
    python3 -c '
import json, sys

try:
    status = json.load(sys.stdin)
    scheduler, state, raw = (status[k] for k in ("scheduler", "state", "raw_state"))
    terminal = status["terminal"]
    if scheduler not in ("slurm", "donau", "local") or not isinstance(state, str) or not state.isalpha():
        raise ValueError("invalid scheduler or state")
    if type(terminal) is not bool or not isinstance(raw, str) or not raw.strip():
        raise ValueError("expected boolean terminal and nonempty raw_state")
    print(scheduler, state, str(terminal).lower(), " ".join(raw.split()), sep="\t")
except (ValueError, KeyError, TypeError) as error:
    sys.exit(str(error))
'
}

submit_and_monitor_orvix_job() {
    local script=${1:-} interval=${2:-10} scheduler=${ORVIX_SCHEDULER:-slurm}
    if [[ -z "$script" ]]; then
        log ERROR "orvix script path not provided to the function."
        return 1
    fi
    if [[ ! -f "$script" ]]; then
        log ERROR "orvix script not found: $script"
        return 2
    fi

    local name=${script##*/} info="${script}.info.yaml" job_id
    if ! rm -f -- "$info"; then
        log ERROR "[$name] failed to clear previous job info: $info"
        return 3
    fi
    # A local child may inherit stdout. Only read the ID line, while retaining
    # submit's exit status even when it has already printed an ID.
    if ! job_id=$(
        set -o pipefail
        orvix submit --scheduler "$scheduler" --output-info "$info" "$script" | head -n 1
    ) || [[ ! "$job_id" =~ [^[:space:]] ]]; then
        log ERROR "[$name] failed to submit."
        return 3
    fi
    local tag="[$name | $job_id]" response fields reported state terminal raw
    log INFO "$tag Submitted."
    while true; do
        if ! response=$(orvix status "$info" --format json); then
            log ERROR "$tag orvix status query failed."
            return 6
        fi
        if ! fields=$(_orvix_status_fields <<< "$response"); then
            log ERROR "$tag invalid orvix status JSON."
            return 6
        fi
        IFS=$'\t' read -r reported state terminal raw <<< "$fields"
        log INFO "$tag Scheduler=$reported State=$state terminal=$terminal raw_state=$raw"
        if [[ "$reported:$state:$terminal" == local:COMPLETED:true ]]; then
            log ERROR "$tag 无法确认业务结果 (local process ended; business exit code unknown)."
            return 6
        fi
        if [[ "$reported" != "$scheduler" ]]; then
            log ERROR "$tag unexpected scheduler $reported (submitted to $scheduler)."
            return 6
        fi
        case "$state:$terminal" in
            COMPLETED:true) return 0 ;;
            UNKNOWN:false)
                case "$reported:$raw" in
                    slurm:COMPLETING) ;;
                    slurm:REVOKED) log ERROR "$tag Failed. raw_state=$raw"; return 6 ;;
                    *) log ERROR "$tag unrecognized $reported state: $raw"; return 6 ;;
                esac
                ;;
            PENDING:false|RUNNING:false) ;;
            FAILED:true|CANCELLED:true|TIMEOUT:true)
                LOGGER_FATAL_NO_EXIT=1 log FATAL "$tag Failed. State=$state"
                return 6
                ;;
            *)
                log ERROR "$tag unrecognized or inconsistent orvix status."
                return 6
                ;;
        esac
        sleep "$interval" || return 6
    done
}
