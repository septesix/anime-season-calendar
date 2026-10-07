# anime-season-calendar

A **skill** for the Minis iOS agent that builds and maintains an Apple `Anime Calendar`
from a season's lineup — with verified air times, correct episode counts, DST-safe recurrences, and
a provenance gate that refuses to write what it cannot corroborate.

It exists because the obvious approach doesn't work. AniList is the only clean season *index*, but
its per-show air times are **placeholders until the show has actually aired**. Crunchyroll's own
calendar is authoritative for US drop minutes but is **published less than a day ahead**. Derive one
from the other and you ship a season of shows that are each confidently, silently wrong.

> `SKILL.md` is the entry point an agent reads. This file is the human-facing overview of the same
> system. Nothing here is decoration — every rule in the scripts below traces to a failure that
> actually shipped and had to be cleaned up afterwards.

---

## The core idea: split source authority

Most bugs in this domain come from asking one source to answer four different questions.

| Question | Authoritative source | Lead time | Why not the others |
|---|---|---|---|
| What exists this season | AniList `season:` + `seasonYear` | months | ANN / official sites have no clean season index |
| JP weekday + JST clock | **the show's own official site** | **months** | AniList rows are absent or placeholder-valued before premiere |
| Which US platform | **ANN news/encyclopedia**, then licensor catalogs | weeks | AniList `externalLinks` is community-edited and appears *after* premiere |
| US drop **minute** | Crunchyroll's calendar (≤1 day); HIDIVE posts | hours–days | derivation is right at the hour, wrong by 0–45 min |

Measured on Fall 2026 (18 sites hand-picked for variety): **13/18 parse rate**, and of those parsed,
**7 matched AniList exactly, 1 within a minute, 5 disagreed on which slot governs**. Scraping the
timestamp was never the hard part — *adjudicating* it is. "Earliest broadcast" lands on a repeat;
"the TV slot" is wrong for Korean-origin simulcasts; one page legitimately contains 31 time strings.

So the parser **enumerates and tags, and never picks**:

```console
$ python3 scripts/official_slots.py https://rayearth-anime.com/ --expected "Wed 23:45"
=== rayearth-anime.com/                            page=/onair/      slots=6
    Wed 23:45 JST  tv     テレビ朝日        | イマニティーズ
    Sun 21:30 JST  tv     AT-X            |
    Sat 22:00 JST  tv     アニマックス      |
    Thu 01:03 JST  tv     ABCテレビ        |
    Sun 06:30 JST  repeat アニマックス      | 再放送
    Thu 00:15 JST  stream ドワンゴ・TMS     | 配信
    vs expected Wed 23:45 -> MATCH   (closest site slot Wed 23:45)
```

---

## Install

The skill must live at exactly `/var/minis/skills/<name>/SKILL.md` — Minis discovers skills by that
path, so the clone target matters:

```sh
git clone https://github.com/septesix/anime-season-calendar.git \
  /var/minis/skills/anime-season-calendar
```

Runtime prerequisites (checked every session, per `SKILL.md`):

```sh
apk info -e tzdata >/dev/null 2>&1 || apk add tzdata   # CRITICAL: without it, TZ=America/New_York
                                                       # silently falls back to UTC = a 4-hour error
which jq >/dev/null 2>&1 || apk add jq
```

Also required: an iOS device running Minis with the `apple-calendar` CLI (a local calendar named
`Anime Calendar`) and the `browser_use` tool.

**Why a browser for API calls:** `graphql.anilist.co` returns HTTP 403 from the iSH shell (Cloudflare
fingerprinting), so AniList queries must run same-origin in an `anilist.co` tab via
`browser_use execute_js`. Plain HTTP works fine for ANN, Crunchyroll, and official sites.

---

## Pipeline

```
season.txt ──► verify_provenance.sh ──► et_schedule.sh ──► add_verified.sh ──► Apple Calendar
                (gate: exit 1 = stop)    (JST → ET, legs)   (create + re-read
                                                             to confirm)
```

```sh
sh scripts/verify_provenance.sh prepare /var/minis/workspace/an/season.txt   # writes probe.js
#   → run probe.js in an anilist.co tab, save output to actual.tsv
sh scripts/verify_provenance.sh check  season.txt actual.tsv                # exit 1 = DO NOT WRITE
sh scripts/et_schedule.sh    season.txt > schedule.tsv
sh scripts/add_verified.sh   schedule.tsv "Anime Calendar"
```

`season.txt` is 11 columns; columns 7–11 exist purely to make confidence *checkable* rather than
asserted:

```
TITLE|YYYY-MM-DD|HH:MM|MODE|SERVICE|CONF|ANILIST_ID|SRC|JPSLOT|OFFICIAL_SLOT|EPS
```

`CONF=high` requires `SRC=sched` **and** `JPSLOT` corroborated by the official site or AniList. It
used to be a free-text field, which is how a guessed time got recorded as high confidence.

---

## Scripts

| Script | What it does |
|---|---|
| `official_slots.py` | Parses 放送情報 from a show's own site. Kanji clocks (`よる11時45分`, `深夜1:03`, `あさ5時`), 24/25/26-hour weekday roll, sub-path probing (`/onair/` …). Lists every slot tagged `tv\|stream\|repeat`; **picks nothing**. Exit 3 = JS-gated → browser fallback. |
| `probe_schedules.js` | Bulk AniList `airingSchedules` for a whole season, run in-browser. One row per episode: weekday, clock, date, count. |
| `verify_provenance.sh` | The gate. `prepare` writes the probe script, `check` diffs the data file against live AniList rows. |
| `cr_calendar.py` | Crunchyroll's *published* ET times (via the `?filter=premium` SSR path). `--diff YYYY-MM-DD` compares them against your calendar. |
| `et_schedule.sh` | Converts `season.txt` into an ET schedule table. Exact minutes, `EPS`-driven `--recur-until`. |
| `dst_legs.py` | Emits the 2–3 DST legs a single weekly series must be split into. |
| `add_verified.sh` | Writes to the calendar and **re-reads** to prove each event landed. Refuses unsplit DST legs. `--dry` supported. |
| `dst_audit.py` | Audits an existing calendar: every JST-anchored weekly must shift exactly 60 min across a DST boundary. |
| `_vp_check.py` | Comparison core used by the gate (not run directly). |

---

## Safety properties (each one is a scar)

- **Never trust a tool's success flag.** `apple-calendar create` returns `ok:true` for events that do
  not exist. `add_verified.sh` re-reads the calendar instead.
- **Never trust an empty query result.** A month-sized list query silently overflows a 100-event cap
  and reports nothing. Probes run in ≤7-day windows.
- **Verification windows must COVER the range.** A "zero residue" audit built from 1-day windows
  stepped by 7 days sampled only Thursdays — while the event under test aired on Wednesdays. It
  reported clean and was wrong.
- **Recurrences spanning Nov 1 need legs.** `apple-calendar` has no per-event timezone, so a weekly
  RRULE is a wall clock in the *device* zone and drifts an hour at the DST change. `dst_audit.py`
  found **38 Fall-2026 titles** shipped without the split.
- **The weekday of a recurring event cannot be changed in place.** EventKit bakes `BYDAY` at
  creation; `update` reports success and changes nothing. Delete and recreate.
- **Re-pull every id after a show premieres.** AniList corrects its own placeholder values afterwards
  — so a proof that you transcribed correctly is not a proof the source was right.
- **Unfamiliar streamer names are not noise.** One unrecognised `externalLinks.site` value
  (`OceanVeil`, a real service) mapped to nothing and 12 Fall-2026 titles were silently dropped from
  a season build — found 9 days later by a full-catalog diff, not by any check in the pipeline.
- **Bulk writes need an explicit human go-ahead**, after a grouped-by-weekday table and the gate's
  own summary line. `NEEDS-REVIEW` rows are never written silently.

---

## Repo layout

```
SKILL.md                        the operational procedure (what an agent loads)
assets/season.example.txt       annotated 11-column example, run it to see the guards fire
references/anilist-cookbook.md  working GraphQL queries + in-browser execution notes
references/platform-rules.md    per-platform derivation rules, with measured deltas
references/pitfalls.md          20+ production failure modes and their diagnostics
scripts/                        the pipeline above
```

---

## Maintaining it

Work in the clone, commit, push:

```sh
git pull --rebase
# ...edit...
git add -A && git commit -m "why, not what"
git push
```

Pushing from inside Minis uses a fine-grained PAT in the URL rather than stored credentials, so
nothing sensitive lands in `.git/config`. Note that a fine-grained token needs **Contents: Read and
write** — with Metadata-only access, reads succeed, `whoami` works, the repo API even reports
`permissions.push: true` (that describes your *account*, not the token's grants), and every write
fails with `403`.
