#!/usr/bin/env bash
# Sample MySQL connection counters every N seconds into a CSV (read-only user, SHOW STATUS only).
#   MYSQL_TEST_HOST/PORT/RO_USER/RO_PASS from the environment
#   bash scripts/monitor_db.sh <interval_s> <out.csv> [service_db_user]
set -u
INT="${1:-5}"; OUT="$2"; SVC_USER="${3:-}"
H="${MYSQL_TEST_HOST:?}"; P="${MYSQL_TEST_PORT:-3306}"; U="${MYSQL_TEST_RO_USER:?}"; PW="${MYSQL_TEST_RO_PASS:-}"
Q="SELECT
 (SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME='Threads_connected'),
 (SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME='Threads_running'),
 (SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME='Max_used_connections'),
 (SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME='Aborted_connects'),
 (SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME='Connection_errors_max_connections'),
 (SELECT VARIABLE_VALUE FROM performance_schema.global_variables WHERE VARIABLE_NAME='max_connections'),
 (SELECT COUNT(*) FROM information_schema.processlist ${SVC_USER:+WHERE user='$SVC_USER'})"
echo "ts,threads_connected,threads_running,max_used_connections,aborted_connects,conn_errors_max,max_connections,svc_user_connections" > "$OUT"
while true; do
  TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  ROW=$(mysql -h "$H" -P "$P" -u "$U" ${PW:+-p"$PW"} -N -B -e "$Q" 2>/dev/null | tr '\t' ',')
  echo "$TS,${ROW:-,,,,,,}" >> "$OUT"
  sleep "$INT"
done
