#!/usr/bin/env bash
# The whole history import, in order. Re-running it adds nothing. Arguments: <decisions.json> [--apply]
set -euo pipefail
D="$1"; APPLY="${2:-}"; R=${REPORT_DIR:-/tmp}
SURAJ=suraj-group; RABS=rabs-industries-india-private-limited
run() { echo "== $1"; shift; python "$@" $APPLY; }
# The regularization history needs its own export; skip those steps when it was not supplied.
reg() { if [ -f "$ROOT/exim.regularizationrequests.json" ]; then run "$@"; else echo "== $1: skipped, no exim.regularizationrequests.json"; fi; }
cd "$(dirname "$0")/.."
export PYTHONPATH=src:scripts
ROOT="$(cd ../.. && pwd)"
run "Suraj punches"          scripts/migrate_exim_punch_history.py   --tenant $SURAJ --report $R/s-punch.json
run "Suraj leave"            scripts/migrate_exim_leave_history.py   --tenant $SURAJ --report $R/s-leave.json
reg "Suraj regularizations"  scripts/migrate_exim_regularizations.py --tenant $SURAJ --report $R/s-reg.json
run "RABS people"            scripts/migrate_exim_rabs_people.py     --tenant $RABS --decisions $D --report $R/r-people.json
run "RABS punches"           scripts/migrate_exim_punch_history.py   --tenant $RABS --company rabs --decisions $D --report $R/r-punch.json
run "RABS leave"             scripts/migrate_exim_leave_history.py   --tenant $RABS --company rabs --decisions $D --report $R/r-leave.json
reg "RABS regularizations"   scripts/migrate_exim_regularizations.py --tenant $RABS --company rabs --decisions $D --report $R/r-reg.json
