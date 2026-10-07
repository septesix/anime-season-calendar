#!/bin/sh
# verify_provenance.sh — gate between building season.txt and writing the calendar.
#   prepare <season.txt>   -> emits /tmp/an/probe.js, run that in an anilist.co tab
#   check   <season.txt> <actual.tsv> -> verdicts; exit 1 unless every row is OK
# season.txt: TITLE|YYYY-MM-DD|HH:MM|MODE|SERVICE|CONF|ANILIST_ID|SRC
set -u
MODE="${1:?usage: verify_provenance.sh prepare|check ...}"
IN="${2:?season.txt}"
CAL=/var/minis/skills/anime-season-calendar/scripts/probe_schedules.js

if [ "$MODE" = prepare ]; then
  HASID=$(awk -F'|' 'NR>1 && $7 ~ /^[0-9]+$/ {print $7}' "$IN" | sort -un)
  n=$(printf '%s\n' "$HASID" | grep -c '[0-9]')
  ids="[$(printf '%s,' $HASID | sed 's/,$//')]"
  rows=$(awk 'NR>1 && NF>0' "$IN" | grep -c .)
  missing=$(awk -F'|' 'NR>1 { if (NF<7 || $7 !~ /^[0-9]+$/) c++ } END {print c+0}' "$IN")
  y=$(date +%Y)
  f=$(date -u -d "$y-06-01" +%s)
  l=$(date -u -d "$((y+1))-06-01" +%s)
  mkdir -p /tmp/an
  sed -e "s/__IDS__/$ids/" -e "s/__FROM__/$f/" -e "s/__TO__/$l/" "$CAL" > /tmp/an/probe.js
  echo "ids=$n  window=[$f,$l]  (AniList airingSchedules perPage caps at 50 -> the probe paginates)"
  echo "season rows=$rows  with_ids=$n  MISSING_ID=$missing"
  [ "$missing" != 0 ] && echo "!! $missing row(s) have no AniList id -> unverifiable; add column 7 (diff 2)"
  echo "next: run /tmp/an/probe.js in an anilist.co tab, save output to /tmp/an/actual.tsv, then:"
  echo "      sh scripts/verify_provenance.sh check $IN /tmp/an/actual.tsv"
  exit 0
fi

# --- check mode ---------------------------------------------------------------
ACT="${3:?usage: verify_provenance.sh check <season.txt> <actual.tsv>}"
D=$(dirname "$0")
python3 "$D/_vp_check.py" "$IN" "$ACT"
rc=$?
echo "verdict: $([ $rc = 0 ] && echo 'ALL VERIFIED - safe to build' || echo 'BLOCKED - fix rows before any calendar write')"
exit $rc
