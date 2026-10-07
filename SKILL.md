---
name: anime-season-calendar
description: Build and maintain a seasonal anime watch list in the user's Apple "Anime Calendar", with correct US Eastern air times. Use when the user asks about a anime season (新番 / "what's airing this season"), to add or update anime in their calendar, to fix anime air times, or to find where shows stream in the US. Covers Fall/Winter/Spring/Summer cours, Crunchyroll, HIDIVE, Netflix, Prime Video, OceanVeil, episode counts, recurrence, DST legs, and dedupe.
---

# Anime Season → Apple Calendar

Turn "what's new this season" into verified, recurring calendar events at real US Eastern
air times. Two phases: **research** (high freedom) then **write** (fragile — follow the scripts).

## Prerequisites (run first, every session)

```sh
apk info -e tzdata >/dev/null 2>&1 || apk add tzdata     # CRITICAL: without it TZ=America/New_York
                                                         # silently falls back to UTC = 4h error
which jq >/dev/null 2>&1 || apk add jq
```

Confirm the target calendar exists and is writable (see `references/pitfalls.md` §1):
`apple-calendar calendars` → look for `Anime Calendar`, `type=local`.

## What each script is for

Run `sh|python3 scripts/<name>` with no arguments for its usage line — the strings below are
transcribed from those, not from memory.

| File | Entry point | Called by |
|---|---|---|
| `official_slots.py <url>… [--expected "Wed 23:45"]` | manual, Phase 1 | — |
| `cr_calendar.py [--days 7] [--grep RE] [--diff D]` | manual, Phase 1 + 5 | — |
| `dst_audit.py [--boundary 2026-11-01]` | manual, Phase 5 | — |
| `verify_provenance.sh prepare\|check` | the gate, Phase 2 | `_vp_check.py`, `probe_schedules.js` |
| `et_schedule.sh <season.txt>` | Phase 2 | — |
| `dst_legs.py <ep1-date> <jst-clock> <n_eps>` | leg generator | you, pasting into `add_verified.sh` input |
| `add_verified.sh <sched.tsv> [calendar] [log] [--dry]` | Phase 4 | — |
| `probe_schedules.js` | **template — never run directly** | `verify_provenance.sh prepare` |
| `_vp_check.py <season.txt> <actual.tsv>` | **internal comparator** | `verify_provenance.sh check` |

The two files marked internal are not referenced anywhere else in this document on purpose: if you
find yourself invoking either one by hand, you have skipped the gate. `probe_schedules.js` contains
`__IDS__`/`__FROM__`/`__TO__` placeholders and silently returns nothing useful until `prepare`
substitutes them.

`README.md` is the human-facing overview (design rationale, install, measured failure rates). This
file is the operational procedure and wins on any conflict — the README is not read by the agent.

## Phase 1 — Research the lineup

**No single source answers everything, and each source is early for a different question.**
AniList is the master *list*; it is not the authority on the time, and not the authority on
the platform. Asking it the wrong question is what produced a 14-title miss and a calendar
full of round-number guesses.

| Question | Source | Lead time | Why not the others |
|---|---|---|---|
| What exists this season | AniList `season:`+`seasonYear` | months | ANN/official sites have no clean season index |
| JP weekday + JST clock | **the show's own official site** | **months** | AniList rows are absent or placeholder-valued until the show actually airs |
| Which US platform | **ANN news/encyclopedia**, then licensor catalogs | weeks | AniList `externalLinks` is community-edited and appears *after* premiere |
| US drop **minute** | Crunchyroll's own calendar (≤1 day); HIDIVE posts | hours–days | derivation is right at the hour, wrong by 0–45 min |

```sh
# 1. enumerate (needs same-origin -> browser_use execute_js in an anilist.co tab; the shell
#    gets HTTP 403 from graphql.anilist.co. Query + pitfalls: references/anilist-cookbook.md)
# 2. JP anchor, per title, from its own site. URL is already in externalLinks site="Official Site":
python3 scripts/official_slots.py https://rayearth-anime.com/ --expected "Wed 23:45"
#    -> prints EVERY 放送/配信/リピート slot tagged, picks nothing. Choosing is a judgment:
#       "earliest broadcast" hits repeats; "the TV slot" is wrong for Korean-origin simulcasts.
#       With --expected it also prints `col10 ->`, paste-ready for season.txt column 10.
#       Paste it; do not retype the slot — retyped claims carry no @host and the gate
#       treats them as unproven (which is exactly how a wrong row used to buy itself a WARN).
#    exit 3 = JS-gated page -> use the BROWSER FALLBACK in the script's docstring. Never
#    conclude "no schedule published" from a shell page; that is how guessed times are born.
# 3. platform evidence: poll ANN (plain HTTP, no key) and the licensor's own catalog
python3 -c "import urllib.request;print(urllib.request.urlopen('https://www.animenewsnetwork.com/all/rss.xml').read().decode()[:200000])" | grep -ioE '[A-Z][^<]{0,80}(licens|stream|simulcast|debut)[^<]{0,80}'
sh  scripts/cr_calendar.py                      # Crunchyroll's published ET times, today +/-
```

**Never drop a title for lack of a streamer link.** This sentence was already in this file,
was already correct, and 14 Fall-2026 titles were still lost by acting as if it weren't —
12 of them because one unrecognised `site` value (OceanVeil) mapped to nothing. So:

* Any `externalLinks.site` you do not recognise is a **finding to verify**, not noise.
* `NONE` is a state, not a verdict. Unlicensed-looking titles go to
  `/var/minis/shared/anime-calendar/watchlist.tsv` and stay there until a human or a
  re-sweep resolves them. **Never silently omitted from the season.**
* Do not use aggregator/"where to watch" content farms. They are how a nonexistent
  `Her Friend (Netflix)` entry got invented. ANN or the licensor only.

**Schedule the re-sweep instead of vowing to remember it.** The rule "re-run 1-2 weeks after
the cour starts" existed in prose here and went unexecuted for 6 days:

```sh
minis-scheduled create --label season-sweep --time 10:00 --repeat custom --days sun \
  --target new --prompt "Re-pull season:<CURRENT> from AniList, diff against the Anime Calendar and watchlist.tsv, report new licenses + shows whose AniList slot changed since premiere. Report only; do not write the calendar."
```

Tag each title with a confidence level. Platform drop-time rules: `references/platform-rules.md`.

## Phase 2 — Build the data file

One line per show, pipe-delimited, into a working file (e.g. `/var/minis/workspace/an/season.txt`
— **not** `/tmp`, which is not guaranteed to survive a session):

```
TITLE|YYYY-MM-DD|HH:MM|MODE|SERVICE|CONF|ANILIST_ID|SRC|JPSLOT|OFFICIAL_SLOT|EPS
The Apothecary Diaries Season 3|2026-10-02|23:00|JST|Crunchyroll|high|195516|sched|official|Fri 23:00|12
Magic Knight Rayearth|2026-10-07|23:45|JST|Crunchyroll|high|178868|sched|official|Wed 23:45|24
Ranma 1/2 Season 3|2026-10-03|03:00|ET|Netflix|slate|209872|slate|anilist||12
```

`MODE`: `JST`/`ET` for weekly (converts, then recurs); `*_SINGLE` for one-shots (binge drops —
**never** make these recur). Date/time = the Japanese slot for `JST`, the US instant for `ET`.
Accept `24:30`/`25:45` Japanese late-night notation as-is.

**`CONF` is derived, never typed — and it is *advisory* everywhere but the gate.** Columns 7-8 are
the transcription axis, 9-11 the corroboration axis:

| Col | Field | Values | Rule |
|---|---|---|---|
| 7 | `ANILIST_ID` | digits | mandatory — no id, no verification |
| 8 | `SRC` | `sched` `next` `slate` `guess` | `high` requires `sched`; **`guess` always FAILs** |
| 9 | `JPSLOT` | `official` `anilist` `guess` | `high` requires one of the first two |
| 10 | `OFFICIAL_SLOT` | `"Wed 23:45 @rayearth-anime.com"` | paste `official_slots.py`'s `col10 ->` line verbatim; **the `@host` is the proof** |
| 11 | `EPS` | AniList **row count**, not `Media.episodes` | drives `--recur-until` |

`et_schedule.sh` reads column 6 and ignores it; `add_verified.sh` never sees it. Write "park the
low-confidence rows" as an instruction to *you*, not as a property of the pipeline.

A row that agrees with AniList has only proven *I copied it correctly* — AniList's own
pre-air values have been wrong (12 h off, silently corrected after broadcast). Where the
official site and AniList genuinely disagree **on the clock**, the gate reports WARN and the
site wins, but the row must be re-pulled after the show has actually aired. That downgrade
requires `SRC=sched` **and** an `@host` in col 10 — i.e. evidence someone did not type. A
weekday conflict is never downgraded: both sources state the day, and a wrong day moves the
event by six days, not minutes. `EPS` larger than AniList's row count is normal for
`連続2クール` shows (2 cours, ~24 eps): the second cour simply isn't entered yet.

### Gate — run before generating any schedule

```sh
sh scripts/verify_provenance.sh prepare /var/minis/workspace/an/season.txt   # writes probe.js
#   -> run probe.js in an anilist.co tab (browser_use execute_js), save output to .../actual.tsv
sh scripts/verify_provenance.sh check  <season.txt> <actual.tsv>
```

Exit 1 = **do not write the calendar.** Checks: `WEEKDAY`, `CLOCK`, `START` on the true
lattice, `EPS` vs row count, `SRC`/`JPSLOT` corroboration, and a `DUPCLOCK` advisory that
only fires when a co-timed row also failed (two shows sharing a slot is normal). Every
failure message names the command that would resolve it — read it instead of guessing.

The gate is adversarial by design: a claim must cost something to produce. It used to honour
a hand-typed `OFFICIAL_SLOT`, so writing down a made-up slot turned a `FAIL` into a `WARN`
while *omitting* the claim left the same row `FAIL` — the check paid out for lying, and also
"downgraded" rows that agreed with AniList, where there was no conflict to resolve at all.

Generate the ET schedule:

```sh
sh scripts/et_schedule.sh <season.txt> > <schedule.tsv>
# -> date \t time \t wd \t service \t title \t until
```

Times are **exact minutes** now. The script used to snap every row to :00/:30 as "house
style", which is how a Wed 23:45 JST show became Wed 11:00 ET — 15 minutes of error, in
40+ titles, wearing the costume of a deliberate choice.

**Runs straddling a US DST change need two or three legs.** `apple-calendar` has no per-event
timezone, so a weekly RRULE stores a wall clock in the *device* zone and drifts an hour when
the offset changes:

```sh
python3 scripts/dst_legs.py 2026-10-07 23:45 24     # ep1 JST date, JST clock, ep count
```

Gives both legs the **same title** — one title, multiple legs, is the correct shape.
`add_verified.sh` now refuses a single JST-anchored leg that crosses a boundary, so this is
no longer a rule you have to remember.

## Phase 3 — Confirm with the user before writing

Always show a grouped-by-weekday table first: date, time ET, service, title, anilist_id,
SRC, JPSLOT, and the gate verdict. Paste the gate's own summary line (`rows=N failures=M`)
rather than restating it. Any row not `OK` is listed under NEEDS-REVIEW and is **not**
written silently. Call out low-confidence rows explicitly. Wait for an explicit go-ahead —
this is a bulk write into the user's real calendar.

## Phase 4 — Add one at a time, verifying each

```sh
sh scripts/add_verified.sh <schedule.tsv>
```

Creates each event, then independently re-reads the calendar to confirm the title exists
exactly once at the right time on the right day. Never report success from the create call's
`ok` flag alone — it lies (see pitfalls).

Rules baked into the script that you must not reimplement ad hoc:

- 30-minute events, English official title, `--recur weekly`, `--recur-until` = last airdate **+ 1 day**.
- **Event title = `<Show> (<Streamer>)`**, e.g. `The Apothecary Diaries Season 3 (Crunchyroll)`.
  Titles that legitimately carry their own parenthetical (`Magic Knight Rayearth (2026)`)
  simply get the streamer appended. A **new streamer must be added to both suffix-stripping
  regexes** in the script, or re-runs duplicate the whole show.
- Verification windows must **COVER** the range: query `--start D --end D+8`. A 1-day window
  stepped by 7 days samples one weekday only and reports a clean "zero residue" for events
  that are still in the calendar. This has produced a false PASS twice.
- Within-file dedupe keys on title **+ start date**, because a DST-split show legitimately has
  2-3 rows with one title. (Keying on title alone silently built leg 1 only — no error, the
  show just stopped existing after the boundary.)
- Re-legging an existing show: **delete every leg first.** Each leg is its own recurring master,
  so `delete --id <one id> --span all` removes only that leg. Collect master ids with a covering
  sweep across the whole span, delete each, then verify by re-sweeping.
- Binge drops (Netflix full-season) are **single** events, never weekly.

## Phase 5 — Closing the loop

Run the invariants, in this order. Each is a *check*, not advice, and each has caught a bug
in something that had already "passed":

```sh
python3 scripts/dst_audit.py                        # every JST-anchored weekly title must shift 60 min at the boundary
sh   scripts/et_schedule.sh <season.txt> > /tmp/a; awk -F'\t' '{print $5}' /tmp/a | sort | uniq -c | sort -rn | head
python3 scripts/cr_calendar.py --diff 2026-10-07     # published CR times vs what the calendar says
```

- Placeholder times (platforms with no published clock — Netflix weekly simulcasts, Prime)
  get an explicit `PLACEHOLDER` note in Notes, and a `minis-scheduled` follow-up dated ~4
  days after premiere. Prose promises to re-check do not survive; scheduled jobs do.
- Save state via `memory_write`: which titles are placeholders, which sit in `watchlist.tsv`,
  the calendar's title count, and the job/reminder ids, so a future session can resume.

## Correcting times later

Time-only change: `apple-calendar update --id X --span all --start ... --end ...` works and
**preserves** the weekly pattern. Any change to the *weekday or recurrence* requires
`delete --id X --span all` then recreate on the original anchor date — EventKit bakes BYDAY
in at creation, and `--recur-until` on `update` is silently ignored.
Full details and the rest of the traps: `references/pitfalls.md`.
