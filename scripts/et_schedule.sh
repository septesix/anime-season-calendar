#!/bin/sh
# et_schedule.sh — convert a season data file into an ET schedule table.
#   in : TITLE|YYYY-MM-DD|HH:MM|MODE|SERVICE|CONF|ANILIST_ID|SRC|JPSLOT|OFFICIAL_SLOT|EPS
#        (MODE = JST|ET|JST_SINGLE|ET_SINGLE; cols 7-11 optional, but EPS missing = 12 assumed)
#   out: date \t time \t wd \t service \t title \t until        (tab-separated)
#
# Why this is a script and not inline shell: the epoch math below has three separate
# silent-failure traps (missing tzdata, busybox date dialect, octal hours). Do not
# reimplement it freehand. See references/pitfalls.md.
#
# Requires tzdata. Japanese late-night notation (24:xx / 25:xx / 26:xx) is accepted and
# rolled forward to the real next-day instant.

set -u
IN="${1:?usage: et_schedule.sh <season.txt>}"

[ -f /usr/share/zoneinfo/America/New_York ] || {
  echo "et_schedule: tzdata missing -> TZ would silently fall back to UTC. Run: apk add tzdata" >&2
  exit 1
}

while IFS='|' read -r name d tm mode svc conf aid src jpslot off eps; do
  # Skip blanks and '#' comments (example/reference files carry them).
  case "${name:-}" in ''|'#'*) continue ;; esac
  case "$name" in ' '*) name="${name# }";; esac
  [ -z "$d" ] && continue
  # Skip a column-header row ("TITLE|YYYY-MM-DD|..."). The format is documented with a
  # header, so without this guard the header reaches the arithmetic below and dies with
  # an opaque "arithmetic syntax error" naming no line.
  case "$d" in [0-9][0-9][0-9][0-9]-*) ;; *) continue ;; esac
  case "$tm" in [0-9][0-9]:[0-9][0-9]) ;; *) continue ;; esac

  # 10# forces decimal: an hour of "08" is otherwise read as invalid octal.
  H=$((10#${tm%%:*}))
  M=$((10#${tm##*:}))

  base=$(date -u -d "$d" +%s) || { echo "bad date: $d  ($name)" >&2; continue; }

  # busybox date does not understand "$d +1 day"; add seconds directly.
  if [ "$H" -ge 24 ]; then
    H=$((H - 24))
    base=$((base + 86400))
  fi

  if [ "${mode#*_}" = "SINGLE" ]; then
    # already a US instant (ET_SINGLE) or a JP slot to convert (JST_SINGLE); no recurrence
    if [ "${mode%_*}" = "JST" ]; then
      ep=$((base + H*3600 + M*60 - 32400))          # JST = UTC+9
      ts=$(TZ=America/New_York date -d "@$ep" '+%Y-%m-%d %H:%M')
    else
      ts="$d $(printf '%02d:%02d' "$H" "$M")"
    fi
    printf '%s\t%s\t%s\t%s\t%s\tSINGLE\n' \
      "${ts% *}" "${ts#* }" "$(date -d "${ts% *}" +%a)" "$svc" "$name"
    continue
  fi

  if [ "$mode" = "JST" ]; then
    ep=$((base + H*3600 + M*60 - 32400))
    sd=$(TZ=America/New_York date -d "@$ep" +%Y-%m-%d)
    # Force decimal NOW. Passing a zero-padded "09" to printf %d below makes ash's
    # printf parse it as octal, silently yielding 0 instead of 9.
    hh=$((10#$(TZ=America/New_York date -d "@$ep" +%H)))
    mm=$((10#$(TZ=America/New_York date -d "@$ep" +%M)))
  else
    sd="$d"; hh=$(printf '%02d' "$H"); mm=$(printf '%02d' "$M")
  fi

  # v1 snapped every minute to :00/:30 as "house style". REMOVED: that is how a
  # Wed 23:45 JST show (Rayearth) became Wed 11:00 ET - a 15-minute error replicated
  # across 40+ titles, and invisible later because a round number looks deliberate.
  # The exact minute is what AniList/official sites actually agree on.
  mm=$((10#$mm))
  r=$(printf '%02d' "$mm")

  # Recurrence end = eps*7 days out, +1 day, because --recur-until compares at midnight
  # and would otherwise drop the final occurrence. v1 hardcoded 12 eps (85 days), which
  # silently truncated every 2-cour show (20-22 eps) to Dec 19.
  case "${eps:-}" in ''|*[!0-9]*) eps=12; epsbad=1 ;; *) epsbad=0 ;; esac
  [ "$epsbad" = 1 ] && echo "!! ${name}: no EPS column -> assuming 12 eps (wrong for 2-cour; add ANILIST_ID's row count)" >&2
  end=$(date -u -d "@$(( $(date -u -d "$sd" +%s) + (10#$eps-1)*7*86400 + 86400 ))" +%Y-%m-%d)

  printf '%s\t%s:%s\t%s\t%s\t%s\t%s\n' "$sd" "$(printf '%02d' "$hh")" "$r" \
    "$(date -d "$sd" +%a)" "$svc" "$name" "$end"
done < "$IN" | sort
