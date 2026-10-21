#!/usr/bin/env bash
# The whole history import, in order. Re-running it adds nothing. Arguments: <decisions.json> [--apply]
set -euo pipefail
D="$1"; APPLY="${2:-}"; R=${REPORT_DIR:-/tmp}
SURAJ=suraj-group; RABS=rabs-industries-india-private-limited
run() { echo "== $1"; shift; python "$@" $APPLY; }
cd "$(dirname "$0")/.."
export PYTHONPATH=src:scripts
run "Suraj punches"          scripts/migrate_exim_punch_history.py   --tenant $SURAJ --report $R/s-punch.json
run "Suraj leave"            scripts/migrate_exim_leave_history.py   --tenant $SURAJ --report $R/s-leave.json
run "Suraj regularizations"  scripts/migrate_exim_regularizations.py --tenant $SURAJ --report $R/s-reg.json
run "RABS people"            scripts/migrate_exim_rabs_people.py     --tenant $RABS --decisions $D --report $R/r-people.json
run "RABS punches"           scripts/migrate_exim_punch_history.py   --tenant $RABS --company rabs --decisions $D --report $R/r-punch.json
run "RABS leave"             scripts/migrate_exim_leave_history.py   --tenant $RABS --company rabs --decisions $D --report $R/r-leave.json
run "RABS regularizations"   scripts/migrate_exim_regularizations.py --tenant $RABS --company rabs --decisions $D --report $R/r-reg.json
