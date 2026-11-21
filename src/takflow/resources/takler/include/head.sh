{% macro shell_word(value) -%}'{{ value | replace("'", "'\\''") }}'{%- endmacro -%}
set -eu

export TAKLER_HOST={{ shell_word(TAKLER_HOST | default('localhost', true)) }}
export TAKLER_PORT={{ shell_word(TAKLER_PORT | default('33083', true)) }}
export TAKLER_NAME={{ shell_word(TAKLER_NAME) }}
export TAKLER_ATTEMPT_ID={{ shell_word(TAKLER_ATTEMPT_ID) }}
export TAKLER_RID=$$

# A job can enable shell tracing before including this head.
takler_shell_flags=$-
set +vx
{% if TAKLER_PASS %}
export TAKLER_PASS={{ shell_word(TAKLER_PASS) }}
{% else %}
unset TAKLER_PASS
{% endif %}
case $takler_shell_flags in *v*) set -v ;; esac
case $takler_shell_flags in *x*) set -x ;; esac

takler_phase=init
takler_signals='1 2 3 4 5 6 7 8 10 12 13 15'
takler_error() {
    takler_rc=$?
    trap - 0
    set +e
    for takler_signal in $takler_signals; do
        trap "echo 'received signal $takler_signal during error handling' >&2" "$takler_signal"
    done
    if [ "$takler_rc" -eq 0 ]; then
        takler_rc=1
    fi
    echo "job failed: phase=$takler_phase status=$takler_rc" >&2
    wait
    if [ "$takler_phase" = running ]; then
        takler_client abort --reason trap || echo "takler abort failed: status=$?" >&2
    fi
    exit "$takler_rc"
}
trap takler_error 0
for takler_signal in $takler_signals; do
    trap "echo 'received signal $takler_signal' >&2; exit $((128 + takler_signal))" "$takler_signal"
done

takler_client init --task-id "$TAKLER_RID"
takler_phase=running
