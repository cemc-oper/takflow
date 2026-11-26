#!/usr/bin/env bash
#
# 统一日志级别、终端颜色和日志文件输出。
#
# 用法:
#   source logger.sh
#
#   # 使用通用函数
#   log INFO  "this is an info message"
#   log ERROR "something went wrong"
#
#   # 使用便捷函数
#   log_info  "this is an info message"
#   log_error "something went wrong"
#   log_fatal "critical failure"          # 会自动 exit 1
#
#   # 设置日志级别 (DEBUG/INFO/WARN/ERROR/FATAL)
#   set_log_level DEBUG
#
# 环境变量:
#   LOG_LEVEL - 初始日志级别数值 (0=DEBUG, 1=INFO, 2=WARN, 3=ERROR, 4=FATAL)
#   LOG_FILE  - 设置后日志同时写入该文件 (纯文本, 无颜色)
#
# 特性:
#   - 自动检测终端, 非 TTY 时关闭颜色输出
#   - FATAL 级别日志会自动 exit 1(LOGGER_FATAL_NO_EXIT=1 前缀可改为只打印,
#     供需要保留自身退出码的调用方使用)
#   - 防止重复 source
#   - 需要 Bash 4.0+
#

# Require Bash 4+ for associative arrays
if ((BASH_VERSINFO[0] < 4)); then
    echo "logger.sh requires Bash 4.0 or later" >&2
    return 1 2>/dev/null || exit 1
fi

# Guard against multiple sourcing
[[ -n "${_LOGGER_LOADED:-}" ]] && return 0
_LOGGER_LOADED=1

# ── Log levels ──────────────────────────────────────────────
declare -A LOG_LEVELS=(
    [DEBUG]=0
    [INFO]=1
    [WARN]=2
    [ERROR]=3
    [FATAL]=4
)

# Default log level (can be overridden via set_log_level or LOG_LEVEL env var)
LOG_LEVEL="${LOG_LEVEL:-${LOG_LEVELS[INFO]}}"

# Optional log file (set LOG_FILE to enable file logging)
LOG_FILE="${LOG_FILE:-}"

# ── Colors (auto-disabled when output is not a terminal) ───
# NO_COLOR=1 强制关闭(https://no-color.org/);调用方需捕获日志做
# 文本断言(如冒烟对 $out 做 grep)时务必 export NO_COLOR=1,
# 否则 tty 下 [FATAL] 会被 ANSI 颜色码包裹导致匹配失败。
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    _RED='\033[0;31m'
    _YELLOW='\033[1;33m'
    _GREEN='\033[0;32m'
    _CYAN='\033[0;36m'
    _MAGENTA='\033[0;35m'
    _NC='\033[0m'
else
    _RED='' _YELLOW='' _GREEN='' _CYAN='' _MAGENTA='' _NC=''
fi

# ── Public API ──────────────────────────────────────────────

set_log_level() {
    local level="$1"
    if [[ -n "${LOG_LEVELS[$level]+x}" ]]; then
        LOG_LEVEL=${LOG_LEVELS[$level]}
    else
        log WARN "Unknown log level: $level (valid: ${!LOG_LEVELS[*]})"
    fi
}

log() {
    local level_name="$1"; shift
    local msg="$*"

    local level=${LOG_LEVELS[$level_name]:-1}
    (( level < LOG_LEVEL )) && return

    local ts
    printf -v ts '%(%Y-%m-%d %H:%M:%S)T' -1   # Bash built-in, no fork

    local color="$_NC"
    case "$level_name" in
        DEBUG) color="$_CYAN"    ;;
        INFO)  color="$_GREEN"   ;;
        WARN)  color="$_YELLOW"  ;;
        ERROR) color="$_RED"     ;;
        FATAL) color="$_MAGENTA" ;;
    esac

    # Console output
    echo -e "[$ts] [${color}${level_name}${_NC}] $msg"

    # File output (plain text, no color codes)
    if [[ -n "$LOG_FILE" ]]; then
        echo "[$ts] [$level_name] $msg" >> "$LOG_FILE"
    fi

    # FATAL: send to stderr and exit with error
    # LOGGER_FATAL_NO_EXIT=1 时只打印不退出:调用方需要按自身状态码
    # exit/return 时使用(如 check_function_return 需保留任务退出码,
    # orvix/slurm 监控需 return 4/6),此时不打印 "Exiting" 行(名不副实)。
    if [[ "$level_name" == "FATAL" ]]; then
        if [[ "${LOGGER_FATAL_NO_EXIT:-0}" == "1" ]]; then
            return 0
        fi
        echo -e "[$ts] [${color}FATAL${_NC}] Exiting due to fatal error." >&2
        exit 1
    fi
}

# ── Convenience wrappers ───────────────────────────────────
log_debug() { log DEBUG "$@"; }
log_info()  { log INFO  "$@"; }
log_warn()  { log WARN  "$@"; }
log_error() { log ERROR "$@"; }
log_fatal() { log FATAL "$@"; }
