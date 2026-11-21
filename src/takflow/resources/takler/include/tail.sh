# Let ksh93 run a pending signal trap before errexit acts on wait.
wait || exit $?
takler_phase=complete
takler_client complete
trap - 0
exit 0
