#!/bin/bash
# One night, fully local: plain "What it does / Why it matters now" for every company,
# then re-render every thesis (plain English + leadership) and build one combined report per market.
# US first (its report is next). Resumable: run it again the next night to finish.
cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python
DATE=${DATE:-$(cat data/NIGHT_RUN_DATE)}
STOP_AT=${STOP_AT:-07:00}
LOG="data/$DATE/describe_$(date +%F_%H%M).log"
caffeinate -ims -w $$ &
exec > >(tee -a "$LOG") 2>&1
$PY -m mahgic check || { echo "check failed: is the Ollama app running?"; exit 1; }
for r in us:us_top100 asx:asx200; do
  mkt=${r%%:*}; uni=${r##*:}
  echo "$(date '+%T') == describe $mkt / $uni"
  $PY -m mahgic describe --market "$mkt" --universe "$uni" --date "$DATE" --until "$STOP_AT"
  [ $? -eq 3 ] && STOPPED=1
  $PY -m mahgic run --market "$mkt" --universe "$uni" --date "$DATE" --stages review
  $PY -m mahgic combine --market "$mkt" --universe "$uni" --date "$DATE"
  [ -n "$STOPPED" ] && { echo "$(date '+%T') stopped at $STOP_AT; run again tomorrow night to finish"; exit 0; }
done
echo "$(date '+%F %T') describe done for $DATE"
