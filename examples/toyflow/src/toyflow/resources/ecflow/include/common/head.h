#! /usr/bin/env bash

set -e          # stop the shell on first error
set -u          # fail when using an undefined variable
set -x          # echo script lines as they are executed

date

# ecFlow 通信变量
export ECF_PORT=%ECF_PORT%    # The server port number
export ECF_HOST=%ECF_HOST%
export ECF_NODE=%ECF_HOST%
export ECF_NAME=%ECF_NAME%    # The name of this current task
export ECF_PASS=%ECF_PASS%    # A unique password
export ECF_TRYNO=%ECF_TRYNO%  # Current try number of the task

RID="${SLURM_JOB_ID:-0}"
if [[ "$RID" -eq 0 ]] ; then
  RID="$$"
fi
export ECF_RID="$RID"

# Tell ecFlow we have started
ecflow_client --init=$RID

# Define a error handler
ERROR() {
   set +e
   wait
   ecflow_client --abort=trap
   trap 0
   exit 1
}
trap ERROR 0
