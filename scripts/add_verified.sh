#!/bin/sh
# add_verified.sh — create each event, then independently verify it landed.
#   in : schedule.tsv from et_schedule.sh
#        date \t time \t wd \t service \t title \t until|SINGLE
# Prints one line per show (OK/FAIL/SKIP) and a tally. Exit 1 if anything failed.
#
# Every guard below corresponds to a real failure seen in production:
#   - create's ok:true does not mean the event exists  -> re-read the calendar
#   - a month-sized list query overflows the 100-event cap and hides events
#                                          -> probe in <=7-day windows
#   - titles in the calendar carry stray whitespace   -> compare trimmed+lowercased
#   - "$d T10:00" style strings: shell identifiers    -> always brace variables
#     greedily consume letters AND digits, so "$dT10" silently expanded to empty

set -u
# Scan ALL args for flags. Positional-only parsing silently ignored --dry in an
# earlier version, which turned a "dry run" into real writes.
IN=""; CAL="${ANIME_CALENDAR:-Anime Calendar}"; LOG="/tmp/an_add.log"; DRY=0
for a in "$@"; do
  case "$a" in
    --dry) DRY=1 ;;
    --calendar=*) CAL="${a#*=}" ;;
    --log=*) LOG="${a#*=}" ;;
    *) [ -z "$IN" ] && IN="$a" || { [ -z "${_L2:-}" ] && _L2="$a" || _L3="$a"; } ;;
  esac
done
[ -n "${_L2:-}" ] && CAL="$_L2"
[ -n "${_L3:-}" ] && LOG="$_L3"
[ -n "${IN:-}" ] || { echo "usage: add_verified.sh <schedule.tsv> [calendar] [logfile] [--dry]" >&2; exit 2; }
: > "$LOG"; : > /tmp/an_added.tsv; : > /tmp/an_thisrun.txt

# --- build the set of existing titles once, via week-sized windows ---------------
: > /tmp/an_existing.raw
d=$(date -u -d "today -120 days" +%Y-%m-%d) 2>/dev/null || d=$(date -u -d "@$(( $(date -u +%s) - 10368000 ))" +%Y-%m-%d)
k=0
while [ "$k" -lt 44 ]; do
  nx=$(date -u -d "@$(( $(date -u -d "$d" +%s) + 8*86400 ))" +%Y-%m-%d)
  apple-calendar list --calendar "$CAL" --start "$d" --end "$nx" --compact 2>/dev/null \
    | jq -r '.data.events[]?.title' >> /tmp/an_existing.raw
  d=$(date -u -d "@$(( $(date -u -d "$d" +%s) + 7*86400 ))" +%Y-%m-%d)
  k=$((k+1))
done
# Strip a trailing streamer suffix so LEGACY bare titles and the new
# "Title (Service)" form both dedupe to the same key. Without this, re-running
# after a rename duplicates every single show.
awk '{$1=$1};1' /tmp/an_existing.raw | grep -v '^$' | tr 'A-Z' 'a-z' \
  | sed -E 's/ \((crunchyroll|netflix|hidive|prime video|max|disney plus|hulu|oceanveil)\)$//' \
  | sort -u > /tmp/an_existing.norm

# --- DST-boundary guard -------------------------------------------------------------
# apple-calendar has NO per-event timezone and EventKit stores a weekly RRULE as a
# wall clock in the DEVICE zone, so any JST-anchored series whose single leg spans the
# DST change goes an hour off at the boundary. 39 Fall-2026 shows were shipped this way
# and it took a user question to find out. Refusing the build is cheaper than the audit.
python3 - > /tmp/an_bounds.txt <<'PY'
import datetime
t = datetime.date.today()
for y in (t.year, t.year + 1):
    for m in (11, 3):
        d = datetime.date(y, m, 1)
        d += datetime.timedelta(days=(6 - d.weekday()) % 7)
        print(d.isoformat())
PY
cut -f5 "$IN" 2>/dev/null | sort | uniq -c | sed 's/^ *//' > /tmp/an_legcount.txt
ok=0; bad=0; skip=0; n=0; i=0
while IFS='	' read -r sd hm wd svc name end; do
  [ -z "${name:-}" ] && continue
  n=$((n+1)); i=$((i+1))

  # Canonical display title = "Show (Streamer)". Strip any suffix already present
  # so the script stays idempotent if a season file already carries one.
  # OceanVeil was absent from both regexes below: after a rename it stops being one of
  # the "known services", so the OLD bare title never deduped and every re-run created
  # a duplicate series. Any new streamer must be added to BOTH lists.
  base=$(printf '%s' "$name" | sed -E 's/ \((Crunchyroll|Netflix|HIDIVE|Prime Video|Max|Disney plus|Hulu|OceanVeil)\)$//')
  title="$base ($svc)"

  key=$(printf '%s' "$base" | awk '{$1=$1};1' | tr 'A-Z' 'a-z' \
        | sed -E 's/ \((crunchyroll|netflix|hidive|prime video|max|disney plus|hulu|oceanveil)\)$//')
  if grep -qxF "$key" /tmp/an_existing.norm; then
    # Title-only cache: one existing occurrence suppresses EVERY leg in this file.
    echo "$n  SKIP(exists) $base  <- to rebuild/re-leg: apple-calendar delete --id <id> --span all, then re-run"
    skip=$((skip+1)); continue
  fi
  # Guard against duplicate lines WITHIN the season file. The existing-title cache is
  # built once before the loop, so a show listed twice would otherwise be created twice.
  # The key MUST include the start date: a DST-split series is legitimately TWO or THREE
  # rows with the same title and different dates. Keying on the title alone silently
  # dropped every leg after the first - 2 of 3 events never created, no error, and the
  # show just stopped airing in the calendar at the boundary. Found 2026-10-06 by
  # --dry-running a split file this script had never been given before.
  dupekey="$key|$sd|$hm"
  if grep -qxF "$dupekey" /tmp/an_thisrun.txt 2>/dev/null; then
    echo "$n  SKIP(dupe-in-file) $base $sd"; skip=$((skip+1)); continue
  fi
  printf '%s\n' "$dupekey" >> /tmp/an_thisrun.txt

  # Refuse an unsplit JST-anchored weekly leg that spans a DST boundary (see guard above).
  if [ "$end" != "SINGLE" ]; then
    case "$svc" in Crunchyroll|HIDIVE|OceanVeil) jst=1 ;; *) jst=0 ;; esac
    if [ "$jst" = 1 ]; then
      legs=$(awk -F'\t' -v n="$name" '$5==n' "$IN" | wc -l | tr -d ' ')
      cross=0
      for b in $(cat /tmp/an_bounds.txt); do
        if [ "$sd" \< "$b" ] && [ "$b" \< "$end" ]; then cross=1; fi
      done
      if [ "$cross" = 1 ] && [ "${legs:-1}" -lt 2 ]; then
        echo "$n  FAIL(DST-leg) $base  one weekly leg $sd..$end crosses a DST boundary"
        printf '%s\t%s\t%s\tDST-leg\n' "$name" "$sd" "$hm" >> "$LOG"
        bad=$((bad+1)); continue
      fi
    fi
  fi

  st="${sd}T${hm}:00"
  eh=$((10#${hm%%:*})); em=$((10#${hm##*:})); em=$((em+30))
  if [ "$em" -ge 60 ]; then em=$((em-60)); eh=$((eh+1)); fi
  [ "$eh" -ge 24 ] && { eh=$((eh-24)); eto=1; } || eto=0
  en="${sd}T$(printf '%02d:%02d' "$eh" "$em"):00"

  if [ "$DRY" = 1 ]; then
    printf '%-3s DRY  %s %s  %-52s %s\n' "$i" "$sd" "$hm" "$title" "$svc" >> "$LOG"
    echo "$i  DRY  $hm $sd  $title"
    continue
  fi

  if [ "$end" = "SINGLE" ]; then
    res=$(apple-calendar create --title "$title" --start "$st" --end "$en" \
            --calendar "$CAL" --notes "$svc" 2>&1 | jq -r '.ok // false')
  else
    res=$(apple-calendar create --title "$title" --start "$st" --end "$en" \
            --calendar "$CAL" --notes "$svc" \
            --recur weekly --recur-days "$wd" --recur-until "$end" 2>&1 | jq -r '.ok // false')
  fi

  # --- verify by re-reading, not by trusting the create response ---
  # Window is EXACTLY the premiere date. An 8-day window sees 2 weekly occurrences
  # and makes every recurring event look like a duplicate.
  nx=$(date -u -d "@$(( $(date -u -d "$sd" +%s) + 86400 ))" +%Y-%m-%d)
  got=$(apple-calendar list --calendar "$CAL" --start "$sd" --end "$nx" --compact 2>/dev/null \
        | jq -r --arg t "$title" '[.data.events[]|select(.title==$t)|.start[11:16]]|.[0]')
  cnt=$(apple-calendar list --calendar "$CAL" --start "$sd" --end "$nx" --compact 2>/dev/null \
        | jq -r --arg t "$title" '[.data.events[]|select(.title==$t)]|length')

  if [ "$got" = "$hm" ] && [ "$cnt" = 1 ]; then
    echo "$n  OK   $hm $sd  $title"; ok=$((ok+1))
    printf '%s\t%s\t%s\n' "$name" "$sd" "$hm" >> /tmp/an_added.tsv
  else
    echo "$n  FAIL $name  want=$hm got='${got:-}' count='${cnt:-?}' create_ok=$res"
    printf '%s\t%s\t%s\t%s\n' "$name" "$sd" "$hm" "${got:-none}" >> "$LOG"
    bad=$((bad+1))
  fi
done < "$IN"

echo "-----------------------------------------"
echo "OK=$ok  SKIP=$skip  FAIL=$bad  total=$n"
echo "existing-title cache: $(wc -l < /tmp/an_existing.norm) titles"
[ -s "$LOG" ] && echo "failures logged to $LOG"
[ "$bad" -eq 0 ] || exit 1
