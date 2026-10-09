# US drop-time rules by platform

Where each service's real US unlock time comes from, how much to trust it, and what its
**ANCHOR** is — the clock the show keeps *following*, which is the only thing that decides
whether the event drifts when US DST changes.

| Service | ANCHOR | Drifts at DST? | Source for the minute |
|---|---|---|---|
| Crunchyroll | JST instant | **yes → split legs** | `scripts/cr_calendar.py` (published), else derive |
| HIDIVE | JST instant | **yes → split legs** | their seasonal post prints exact ET |
| OceanVeil | JST instant, ~+1 h | **yes → split legs** | `oceanveil.net` catalog (plain HTML) |
| Netflix weekly simulcast | PT midnight | no | not published anywhere |
| Netflix full-season / original | PT-anchored one-shot | n/a | single event, never weekly |
| Prime Video | JP slot if any, else unknown | usually yes | not published; region-locked listings |

A JST-anchored show must be **two legs across the boundary**; a PT-anchored one must not be
split at all. `scripts/dst_audit.py` enforces exactly this and does not care how you built it.

## Crunchyroll — JST-anchored, but the MINUTE is published, so read it

True simulcasts unlock essentially when the Japan broadcast finishes, so
`ET = JST − 13h (EDT) / − 14h (EST after the first Sunday in Nov)`.

**Measured against CR's own calendar (2026-10-06, corrected 2026-10-09), the offset is not a
lag at all — CR publishes the JP STREAMING slot, which is usually *after* the TV slot, not at
it.** A TV slot ending at Fri 24:00 JST unlocks the stream at Sat 00:00 JST, so the US drop lands
a full hour later than `JST − 13h` of the TV time predicts:

| Show | CR published | JP **TV** slot | JP **配信** slot | Δ vs TV-slot instant |
|---|---|---|---|---|
| Hello, I Am a Witch | Mon 8:30am | AT-X 月曜 21:30 | = TV | 0 |
| The Cold Sato-san | Tue 9:30am | 22:00 | — | +30 |
| Laid-Off Cheat-Granting Mage | Tue 11:30am | Wed 00:00 | — | +30 |
| Super Psychic Policeman Chojo | Tue 10:45am | Fuji 23:00 | — | +45 |
| **The Apothecary Diaries S3** | **Fri 11:00am** | 金曜 23:00 | **土曜 0:00** | **+60** |
| **A Certain Dark Item** | **Fri 11:30am** | — | 土曜 0:30 | **+120** |
| Red River | Tue 13:35 | 14:00 | — | **−25** (CR before the TV slot) |

⇒ range is **−25 … +120 min**, and the +60/+120 cases are the streaming-slot ones. An entry built
from a 放送情報 **TV** slot can therefore be an hour or two early even when the hour looks clean.
The official site's 配信情報 block is what to copy, not the 放送情報 one — `official_slots.py`
tags slots `tv|stream`, so prefer the `stream` row when both exist.

Read the real times instead of deriving them:

```sh
python3 scripts/cr_calendar.py                 # or --diff YYYY-MM-DD to compare with the calendar
```

Note `--diff` compares the row's own date only. CR's page is a rolling ~1-week window, so a future
date returns **0 rows** — that is not a match, and it must not be read as "nothing scheduled".

Two hard constraints on that page, both verified:
* **The `?filter=premium` param is mandatory.** Without it (or with `filter=all`) the response
  is a ~1.5 KB JS shell and looks like "Crunchyroll publishes nothing".
* **Times are US Eastern and NOT localized** — identical across enUS/en-GB/de/es/pt-br, and
  there is no timezone metadata in the document. Do not hunt for a `--tz` or a locale flag.
* `?date=` is **ignored**: the page renders a rolling window and future days read "Schedule
  Coming Soon". So CR can *verify* a time, never *plan* a season. Check the day after premiere.

Episode counts and airing calendars: `airingSchedule` rows, counted — see pitfalls.

## HIDIVE — use their published times (highest confidence)

HIDIVE's seasonal announcement prints **exact ET clocks** (e.g. "Saturdays at 11:30 AM EDT").
The only platform that does. Prefer them over any derivation; record the show in `ET` mode.
Their `/schedule` page is a 3 KB JS shell — the *news post* is the parseable artifact.

## OceanVeil — JST-anchored, ~1 h after the JP slot, and easy to lose entirely

`oceanveil.net` (WWWave of America), "Exclusive Simulcast and English Dubs". AniList lists its
`site` value alongside Crunchyroll's, but because it was not in the mapper's known-service list
it mapped to *nothing* — which read as "no US license" and deleted 5 titles from a season
silently. Any unrecognised `site` string is a thing to look up, not noise.

Catalog is plain static HTML (≈45 KB, parseable from the shell); individual title pages are
login-gated. Because it is JST-anchored it **drifts at the DST boundary** — unlike Netflix.

## Netflix — two shapes, neither with a published clock (low confidence)

* **Weekly simulcast** (a Japan TV show Netflix carries): no per-episode time is published.
  Convention is `midnight PT = 03:00 ET` on the stated US date, which is **PT-anchored, so it
  does NOT need DST legs**. Flag the minute as a placeholder anyway.
* **Full-season / original drop** (*Cyberpunk: Edgerunners 2*, *Fool Night*): all episodes at
  once → **single event, never a weekly series** (a weekly recurrence invents 12 phantom eps).

Title pages expose JSON-LD `releaseDate` with **no clock time**; `/title` requires login.

## Prime Video — derive, flag (low-medium confidence)

No published per-episode times; listings region-locked behind login. Use the JP slot if there
is one, otherwise park a placeholder. Treat a Prime-only title's `NONE` link state as unverified,
not unlicensed — *Seven Knights* sat in that exact state for a week.

## No US license found → watch-list, never "skip"

Do not create events for titles with no announced US home, but **do not drop them either**:
write them to `/var/minis/shared/anime-calendar/watchlist.tsv` with the id and the date you
checked, and report the count ("40 added, 6 unverified, on watch-list"). Deleting the question
is what turns a data gap into a silent 14-title hole.

## Sources, by reliability

1. **The show's Japanese official site** — `放送情報` gives the exact JP weekday + clock, and is
   published months ahead (`scripts/official_slots.py`). The earliest source that exists.
2. **The licensor's own calendar/news** — CR's premium calendar (≤1 day), HIDIVE's post,
   OceanVeil's catalog.
3. **ANN** — `animenewsnetwork.com/all/rss.xml` (license announcements, dated) and the
   encyclopedia page per title (`Vintage:` + `(early streaming on X)`). Had Snow Widow's
   OceanVeil debut on **Sep 4**; AniList still showed no link three weeks later.
4. AniList `externalLinks` / `streamingEpisodes` — a *floor*, not a ceiling. Both lag the
   announcement, and neither is authoritative.
5. ~~finalweapon.net / mystiqora / "where to watch" aggregators~~ — derived from tier 1-3,
   stale, and the direct cause of a fabricated `Her Friend (Netflix)` entry. Do not cite.

### Third convention: the midnight-PT batch (CR 8:30/9:00/11:00am, offset 0 to a JP *date* boundary)

Several Fall 2026 titles post at a clean PT midnight rather than at the JST instant of any TV
slot. Confirmed by two independent sources agreeing (CR's published instant == AniList's own
airingAt converted to ET): Hello, I Am a Witch (Mon 8:30am), FX Fighter Kurumi-chan (Thu 8:30am),
Sasaki and Peeps (Wed 9:00am). For these the rule is simply `JP calendar date + 1 day, 00:00 PT`.

Corollary, and the reason three entries were an hour late: **when CR and AniList agree with each
other, trust them over a JST-TV derivation.** Where they disagree, neither is authority yet - the
disagreement usually means a 配信 slot past the TV slot, and needs the official site or
cal.syoboi.jp's flagship-station row. Nine Fall 2026 titles sat in that disagreement state on
2026-10-09 (PSYREN -30, Chojo -45, Laid-Off Mage -30, Sato-san -30, Returner's Magic +75,
Iceblade +32, Dandivine +90, Firefly Wedding +90, Prince of Tennis II +60).
