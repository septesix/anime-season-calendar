#!/bin/sh
# verify_prompt_delivery.sh — prove a scheduled job will receive its FULL instructions.
#   usage: verify_prompt_delivery.sh            # audit every job
#          verify_prompt_delivery.sh <label>    # audit one, and report its payload files
#
# WHY: minis-scheduled --prompt is truncated to 200 characters with no error and no
# warning, and `list` echoes the mutilated text, so a job looks healthy until it fires
# mid-sentence. Length alone is NOT proof of delivery - this script checks three things:
#   1. stored length < 200          (a job AT exactly 200 is truncated, not long)
#   2. every /path in the prompt    (a pointer to a file that moved is a silent no-op)
#   3. the pointer's own tail        (does it end in a sentence, or in mid-word?)
# Then, to prove delivery rather than storage, fire a VERBATIM probe:
#   minis-scheduled create --label vp-1 --after 2m --target child-of-current \
#     --prompt 'VERBATIM mode: output your own received prompt text exactly, nothing else.'
# A fired job can only be deleted by its UUID, not by label:
#   minis-scheduled delete --id "$(minis-scheduled list | jq -r '.data.tasks[]|select(.title=="vp-1")|.id')"

set -u
WANT="${1:-}"
LIST=$(minis-scheduled list 2>&1)
if ! printf '%s' "$LIST" | grep -q '"ok" *: *true'; then
  echo "could not read scheduler state: $(printf '%s' "$LIST" | head -c 120)"; exit 2
fi

n=$(printf '%s' "$LIST" | jq -r '.data.count')
printf 'jobs: %s\n\n' "$n"
bad=0
for i in $(seq 0 $((n > 0 ? n - 1 : 0))); do
  [ "$n" -gt 0 ] || break
  title=$(printf '%s' "$LIST" | jq -r ".data.tasks[$i].title")
  state=$(printf '%s' "$LIST" | jq -r ".data.tasks[$i].state")
  trig=$(printf '%s' "$LIST"  | jq -r ".data.tasks[$i].trigger")
  pr=$(printf '%s' "$LIST"    | jq -r ".data.tasks[$i].prompt")
  [ -n "$WANT" ] && [ "$title" != "$WANT" ] && continue
  len=$(printf '%s' "$pr" | wc -m | tr -d ' ')
  if [ "$len" -ge 200 ]; then verdict="TRUNCATED"; bad=$((bad + 1));
  elif [ "$len" -gt 170 ]; then verdict="at-limit"; bad=$((bad + 1));
  else verdict="ok"; fi
  printf '  %-16s %-8s %-26s %4s chars  %s\n' "$title" "$state" "$trig" "$len" "$verdict"
  printf '%s\n' "$pr" | grep -oE '/[A-Za-z0-9_./-]+' | sort -u | while read -r p; do
    case "$p" in
      */*) [ -e "$p" ] && printf '      path  OK    %s\n' "$p" \
                 || { printf '      path  MISSING %s\n' "$p"; } ;;
    esac
  done
  printf '      tail  %s\n' "$(printf '%s' "$pr" | tail -c 46 | tr '\n' ' ')"
done

echo
if [ "$bad" -gt 0 ]; then echo "RESULT: $bad job(s) need attention"; exit 1; fi
echo "RESULT: all stored prompts are intact. Storage != delivery - see header for the VERBATIM probe."
