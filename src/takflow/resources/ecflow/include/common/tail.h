# Let ksh93 run a pending signal trap before errexit acts on wait.
wait || exit $?
ecf_phase=complete
ecflow_client --complete
trap - 0
exit 0
