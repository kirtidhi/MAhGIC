#!/bin/bash
# MA(h)GIC night run: works 23:00-07:00 and resumes the next night where it stopped.
#
#   scripts/night_run.sh            # continue the current multi-night run (or start one)
#   scripts/night_run.sh --new      # start a new run dated today (e.g. the next 6-monthly deep run)
#   scripts/night_run.sh --status   # what is done so far
#
# Each night: start it (or let launchd start it at 23:00, see scripts/com.mahgic.nightrun.plist),
# keep the Mac plugged in with the lid open. It stops itself at STOP_AT; every finished step is
# saved, and the same run date is reused until every market is complete.
# Measured on the 16 GB M5 (Oct 2026): ASX 200 + US top 100 is ~34-40 h, i.e. ~5 nights.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
STOP_AT="${STOP_AT:-07:00}"
RUNS="${RUNS:-asx:asx200 us:us_top100}"     # market:universe pairs, in order
STATE=data/NIGHT_RUN_DATE
PY=.venv/bin/python
mkdir -p data
[ -f .env ] && { set -a; . ./.env; set +a; }

if [ "${1:-}" = "--new" ] || [ ! -f "$STATE" ]; then date +%F > "$STATE"; rm -f data/NIGHT_RUN_DONE; fi
RUN_DATE=$(cat "$STATE")
LOG="data/$RUN_DATE/night_$(date +%F_%H%M).log"; mkdir -p "data/$RUN_DATE"

if [ "${1:-}" = "--status" ]; then
  for r in $RUNS; do echo "== ${r%%:*} / ${r##*:} (run date $RUN_DATE)"; $PY -m mahgic status --market "${r%%:*}" --universe "${r##*:}" --date "$RUN_DATE"; done
  exit 0
fi
if [ -f data/NIGHT_RUN_DONE ] && [ "$(cat data/NIGHT_RUN_DONE)" = "$RUN_DATE" ]; then
  echo "Run $RUN_DATE is complete. Use --new to start the next one."; exit 0
fi
if pgrep -f "mahgic run" >/dev/null; then echo "A MA(h)GIC run is already in progress"; exit 1; fi

caffeinate -ims -w $$ &           # Mac stays awake while this runs; the display may sleep (lid must stay open)
exec > >(tee -a "$LOG") 2>&1
echo "$(date '+%F %T') night run, run date $RUN_DATE, stop at $STOP_AT"
$PY -m mahgic check || { echo "check failed: is the Ollama app running?"; exit 1; }

for r in $RUNS; do
  mkt=${r%%:*}; uni=${r##*:}
  echo "$(date '+%T') == $mkt / $uni"
  $PY -m mahgic run --market "$mkt" --universe "$uni" --date "$RUN_DATE" --until "$STOP_AT"
  rc=$?
  if [ $rc -eq 3 ]; then echo "$(date '+%T') stopped at $STOP_AT; resumes next night"; exit 0; fi
  [ $rc -ne 0 ] && { echo "$(date '+%T') $mkt failed (exit $rc); continuing with the next market"; }
done
echo "$RUN_DATE" > data/NIGHT_RUN_DONE
echo "$(date '+%F %T') all markets complete for run $RUN_DATE"
