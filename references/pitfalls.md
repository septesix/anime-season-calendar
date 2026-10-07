# Pitfalls — every one hit in production

Do not re-derive these. Each cost a debugging cycle.

## Timezone / date

- **Install `tzdata` first.** Without it `TZ=America/New_York date` silently falls
  back to UTC — no error, just times 4 hours off. This corrupted an entire
  user-facing table before it was caught. `apk add tzdata`.
- **Busybox `date` rejects `"$d +1 day"`** and ISO strings with offsets. Always do
  epoch arithmetic: `date -u -d "@$(( $(date -u -d "$d" +%s) + 86400 ))"`.
  Note the `+8*86400` (8 days) for exclusive end params: `list --end` behaves as
  exclusive, so a 1-day probe can miss an event.
- **Octal hours.** `$(( ${tm%%:*} * 3600 ))` dies on `08`/`09`. Use `10#`.
- **`--recur-until` compares at midnight**, so the final occurrence is silently
  dropped. Use `last airdate + 1 day`. Caught only because a finale was missing.

## apple-calendar

- **`delete` on a recurring event returns `ok:true` and does nothing** unless you
  pass `--span all`. Same for `update`.
- **`update` ignores recurrence params** (`--recur*`) but **honours `--start`/
  `--end`** — so time-only edits are clean one-liners; changing the *pattern*
  requires delete + recreate. Preserve the original master start date so history
  is untouched.
- **Never trust `create`'s `ok:true`.** Re-read the calendar and assert the event
  exists with the expected time. A malformed `--start` still returned success.
- **`list` caps at 100 events — including within a single calendar and a single
  month.** October alone hit exactly 100, which made five correctly-created shows
  look "missing". Always pass `--calendar "<name>"` and probe in ≤7-day windows.

## Shell

- **Identifier greediness:** `--start "$dT10:00:00-04:00"` parses `$dT10`, not
  `$d` + `T10`. Silently empty. Always write `"${d}T10:00:00-04:00"`. This broke
  four of five updates that appeared to succeed.
- Comparison strings with embedded labels never match. Build the expected value
  and the actual value the same way; don't append `dur=` to one side.
- `set -u` plus `read` on a tab-delimited file: use a literal tab in `IFS`, not
  `\t`, in POSIX `sh`.

## Research sources

- **AniList GraphQL is same-origin gated.** Cross-origin `fetch` from a
  non-AniList page fails with "Load failed". Navigate to `anilist.co` first.
- **AniList field names:** `episodes` (not `episodeCount`), `externalLinks` (not
  `externalSites`), sort enum `POPULARITY_DESC` (not `POPULARITY_desc`). A bad
  enum returns a 400 that looks like a network error.
- Rate limit ~60/min; a 7-request loop can silently return all-errors. Batch into
  one `Page` query instead of N `search` queries.
- Crunchyroll `simulcastcalendar` shows "Schedule Coming Soon" until days before
  premiere. Its `/content/v1/cms/schedule/*` endpoints 404 unauthenticated. Don't
  burn calls probing them twice.
- Netflix `/search` and `/title` redirect to login; JSON-LD gives date only.

## Verification discipline

- Assert `count == 1` on the premiere date, not merely `count >= 1` — that is what
  catches a duplicate from a re-run.
- Spot-check a late occurrence (week 11) after any bulk time change: an `update`
  can apply to only the master and leave later occurrences stale.
- Dedupe against existing titles with **trim + lowercase**; real calendars carry
  trailing spaces (`"A Wild Last Boss Appeared "`), which defeats exact matching.
- Prefix any throwaway event `ZZZ_`, verify, then delete with `--span all`.
- `--dry` must be proven to write nothing. The first version parsed the flag but never
  branched on it, so "dry runs" created real events. After changing arg handling, always
  run `--dry` and then count test-prefixed events to confirm zero.

## Series crossing the Nov DST boundary drift by an hour

A recurring event has ONE wall-clock time, but JST−offset changes when the US falls back:
a Thursday-midnight-JST show is 11:00 EDT in October and 10:00 EST in November. Any weekly
series spanning Nov 1 is therefore an hour off for part of its run.

The engine anchors on the **first occurrence's** offset — getting the premiere exactly right
beats splitting a series in two. Only split if the user asks for November precision, and never
"fix" it by shifting a whole series to the post-DST time, which just makes October wrong.

## Renaming or retiming an existing series

`apple-calendar update --id X --span all --title "New"` works and **preserves** weekly
recurrence and Notes. Confirmed by re-listing a later occurrence, not by the response.
Same applies to shifting the **time** within the same weekday.

**But you cannot move a weekly series to a different weekday with `update`.** Tested on a
scratch series: updating `--start` from Fri 10-02 to Sun 09-27 reported `ok:true` and the
master record even stores the new Sunday start, yet every generated occurrence stayed on
Friday. Adding `--recur weekly --recur-days sun` to the same update changed nothing.
EventKit bakes BYDAY in at creation. **Wrong weekday => delete the series and recreate it.**
(Wrong *time*, same weekday => `update` is fine.)

**Trap:** the update response reports `recurrence: null` even when the recurrence is intact.
That is a serialization artifact. Never conclude a rename broke the pattern — re-read an
occurrence at first-date + 7 or + 14 days and count it.

**Never hand-copy an event id.** A transcribed 73-char id failed to delete with
`Event not found`; pipe it straight from `list | jq` into the delete call instead.

## Audit trail after a bulk rename

Verify three things, not one:
1. new title present exactly once on the premiere date,
2. old bare title present **zero** times (catches half-applied renames),
3. recurrence still weekly (binge drops are legitimately `single`).

Comparing only #1 hides failures where the update created a second event instead of renaming.

## Why shows slip through the sweep (Appraisal Skill S3, Fall 2026)

AniList's `streamingEpisodes` is **empty until someone adds episode entries**, so a show
that premiered yesterday can report no platform at all. `externalLinks` is the better
signal — but it is unreliable in **both** directions:

- false negative: Appraisal S3 had no `streamingEpisodes`, only a `crunchyroll.com/pt-pt/...`
  external link (locale prefix, still a US title) → a links-only sweep misses it.
- false positive the other way: "A Tale of the Secret Saint", "The Ramparts of Ice S2" and
  "Mission: Yozakura S2 Pt 2" all report **no** US link yet are genuinely on CR/Netflix.

Rules that follow:
1. Never conclude "unlicensed" from absent AniList links. Confirm with a web search
   (`<title> crunchyroll watch english`) before dropping a title.
2. **Re-run the sweep 1-2 weeks after the cour starts.** Entries are created late and a
   premiere can appear days after the season opens, not just at the lineup announcement.
3. A Crunchyroll URL with a non-US locale path (`/pt-pt/`, `/ja/`) is the same series id;
   do not read it as "not available in the US".

## Matching AniList titles to calendar titles

AniList `title.english` and MAL/calendar names diverge ("Ranma1/2 (2024) Season 3" vs
"Ranma 1/2 Season 3"). Token-Jaccard after stripping stop-words and the streamer suffix
catches most; **anything scoring 0.3-0.55 is a human eyeball list, not an auto-verdict** —
below 0.55 the script calls it missing when it is actually present.

## DST now splits cleanly (no more known limitation)

`scripts/dst_legs.py <ep1_jst_date> <jst_clock> <n_eps>` emits one weekly leg per
contiguous run sharing a US Eastern wall-clock time, with ready-made `--recur-until`
(last date + 1 day). A 12-ep Sunday 23:30 JST run becomes 5 eps at 10:30 EDT + 7 eps at
09:30 EST. Legs share one title; occurrence checks are per-window so dedupe is unaffected.

**Bug found and fixed here:** the first version used `datetime.weekday()` against a
Sunday-first name array, labelling every Sunday show `sat`. Python's `weekday()` is
Monday=0. Use `isoweekday() % 7` for a Sunday-first table.

## Row-value contamination (the Overgeared error, Fall 2026)

`Overgeared|2026-10-02|23:30|JST|Crunchyroll|high` — no id, and the value was copied from
the adjacent TOUGEN ANKI row, which genuinely does air Friday 23:30 JST. Overgeared actually
airs **Sunday 23:30 JST** (id 212888). The clock matched by luck, so only the weekday was
wrong: 13 events on the wrong day, and the real ep1 (already broadcast) missing entirely.

Why it survived review: a bare date+clock row *looks* like data. Nothing forced a link to
the show's own record, and `high` was typed, not earned.

Fix is structural, not vigilance: column 7 = AniList id, column 8 = SRC, and
`verify_provenance.sh check` fails the build when a row's weekday/clock/start disagree with
that id's `airingSchedules`. Two shows sharing a slot is normal (co-timed courses), so
`DUPCLOCK` only reports when one member already failed — otherwise the warning is noise.

## Official-site parsing (added Oct 2026 — the earliest source, and not free)

`scripts/official_slots.py` measured **13/18 sites parseable** on Fall 2026; of those 13, 8
agreed with AniList to ≤1 minute and 5 disagreed on *which slot*. Failure modes, all real:

* **Kanji clocks, not `HH:MM`.** `毎週水曜よる11時45分`, `深夜1:03`, `あさ5時00分`. A colon-only
  regex scores **0/1 on a perfectly parseable page** — it looks like the site publishes nothing.
  Prefixes: `よる|午後` → +12 h; `深夜` → +24 h (next calendar day); `あさ|午前` → as-is.
* **The homepage is often a shell; the slate is one hop away.** Rayearth's root returned 168
  characters of text and the schedule lived at `/onair/`. Probe root + `onair/ broadcast/ tv/
  information/ news/ staffcast/ intro/` before concluding anything.
* **Never pick "earliest broadcast".** Ramparts of Ice lists a Sun 07:30 再放送 that beats its
  real Thu 23:56 anchor. A single page can carry **31** time strings (Ranma).
* **The TV broadcast is not always the anchor.** Overgeared is a Korean-origin simulcast: its
  Japanese AT-X slot (Fri 23:30) is not the Sun 23:30 that governs the US drop.
* **JP `配信` slots are usually AnimeFesta/dアニメストア — domestic, not the anchor** — unless
  the show has no TV broadcast at all.
* `24:xx / 25:xx` must roll the *weekday*, not just the hour.

## Corroboration is not transcription (JPSLOT)

The provenance gate could only ever prove *"I copied AniList correctly"*. That is a weak claim
when AniList's own pre-air values are placeholders: Ramparts printed 11:56 for a show that
aired at 23:56, and was corrected silently after broadcast. A passing gate proved the mistake
was faithful.

So `season.txt` gained cols 9-11 (`JPSLOT`, `OFFICIAL_SLOT`, `EPS`) and the gate now fails
`CONF=high` without an independent source. When the two disagree the gate reports **WARN** and
instructs a re-pull after premiere — the site wins for the *slot*, AniList wins for the *row
set*, and neither wins forever.

## AniList minutes drift

Ranma S3: AniList `00:56`, official site `25:56` = **00:55** — a 1-minute error, invisible in
every aggregate check and still 1/60th of an hour wrong for every viewer. Don't defend a
minute just because it came from an API.

## 2-cour shows: EPS > AniList row count is normal

Rayearth is `連続2クール` (~24 eps) while AniList carries 12 rows: the second cour simply isn't
entered. `et_schedule.sh` used to hardcode 12 eps (85 days) for `--recur-until`, which truncated
every 20-22 episode show to mid-December. Now it takes col 11. The gate WARNs when EPS exceeds
row count and FAILs when it is smaller.

## Verification windows must COVER the range

Two independent false PASSes from the same mistake: querying `--start D --end D` (a zero-length
window, returns nothing) or `--end D+1` while stepping `D += 7 days` — which samples exactly one
weekday forever and reports "zero residue" for events that are still in the calendar. Always
`--end D+8`.

## Legs of one series are separate masters

A DST-split show is 2-3 *distinct* recurring masters sharing a title. `delete --id X --span all`
removes **one leg**, so a re-leg that deletes only the id found near the premiere leaves the
post-boundary leg alive. Collect ids by sweeping the entire span with covering windows, delete
each, then verify by re-sweeping — not by re-checking the first week.

## Within-file dedupe keys on title + date

`add_verified.sh` used to key `SKIP(dupe-in-file)` on the title alone, so a legitimate
2-or-3-leg season file built **leg 1 only** and reported no error: the show simply stopped
existing in the calendar after the boundary. Found by `--dry`-running a split file, which the
script had never been given. Any new "duplicates" guard must ask *duplicates of what exactly*.

## New streamer names must be added in two places

`OceanVeil` was missing from both trailing-suffix-stripping regexes in `add_verified.sh`, so
after a rename the bare old title never deduped and a re-run duplicated every OceanVeil show.
The list of known services is load-bearing in more than one file — grep for it before adding one.

## Crunchyroll's own calendar (the free win)

`?filter=premium` on `/simulcastcalendar` is **server-rendered and readable from the shell**
(≈150 KB). Without the param it is a 1.5 KB JS shell that reads as "CR publishes nothing".
Times are ET and are **not localized** (identical in 5 locales; no tz metadata anywhere).
`?date=` is ignored; future days say "Schedule Coming Soon" — verification, not planning.
Published minute sits 0…+45 min after the JST instant, varying per show, which is the honest
error bar on every derived Crunchyroll time in the calendar.
