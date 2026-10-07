# AniList GraphQL cookbook

AniList is the workhorse: season lineups, episode counts, and per-episode airing
timestamps. It replaces guesswork with facts.

## Hard constraint: same-origin

`fetch()` to `graphql.anilist.co` only works while a tab is on `anilist.co`.
From any other origin the CORS preflight fails with an opaque `Load failed`.

1. `browser_use navigate` → `https://anilist.co/search/anime?season=FALL&seasonYear=2026`
2. THEN `browser_use execute_js` with the fetch.

## Rate limit

~60 requests/min. Batch with a paginated season query; never loop a `search`
per title. Sleep 400-900 ms between page fetches.

## 1. Whole season, popularity-ordered

```js
const q={query:"query($p:Int){Page(page:$p,perPage:50){media(season:FALL,seasonYear:2026,type:ANIME,sort:POPULARITY_DESC){title{romaji english native}format episodes startDate{month day}popularity}}}",variables:{p:1}};
const r=await fetch("https://graphql.anilist.co",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(q)});
const j=await r.json();
return j.data.Page.media.map(m=>`${m.popularity}|${m.startDate.month}/${m.startDate.day}|${m.format}|${m.title.romaji}`).join("\n");
```

Enum names are strict: `POPULARITY_DESC` (not `POPULARITY_desc`), and the field is
`episodes` (not `episodeCount`). A typo returns HTTP 400 with a `data:null` body,
so always branch on `j.data`.

## 2. Which US service carries a title

```js
{ media(...) { isLicensed externalLinks{site url} } }
```

Filter `externalLinks[].url` for `crunchyroll`, `netflix`, `hidive`, `primevideo`,
`youtube`. A link whose path is `/search?q=` or `/title/0` is an **unfilled
placeholder, not a licence** — see pitfalls.md.

## 3. Exact per-episode air timestamps

```js
{ Media(id:ID){ episodes airingSchedule(perPage:40){nodes{episode airingAt}} } }
```

`airingAt` is epoch **seconds**. Convert with `new Date(airingAt*1000)` and read it
in `Asia/Tokyo` to get the Japan slot, or in `America/New_York` for the US drop.
This is the single most reliable way to recover a true ET clock, and it also
answers "is this still airing, and when does it end?" via `status` + `episodes`.

## 4. Episode count for a known title

Use the season query (#1) and match on `title.romaji`; do not `search` per title.

## 5. Bulk ground truth for the whole cour in ONE call

```js
query($ids:[Int],$g:Int,$l:Int,$p:Int){Page(page:$p,perPage:50){
  airingSchedules(mediaId_in:$ids,airingAt_greater:$g,airingAt_lesser:$l){mediaId episode airingAt}}}
```

`mediaId_in` accepts an array, so the entire season's slots come back in a handful of
paginated requests instead of one query per title. `perPage` caps at **50** — paginate.
Argument names are `mediaId` / `mediaId_in` / `airingAt_greater` / `airingAt_lesser`;
`media_ids`, `notAiring` and `airedAt` do **not** exist and error out.
`Page.airingSchedules` returns rows directly (no `nodes` wrapper), whereas
`Media.airingSchedule{nodes{...}}` **is** wrapped — both forms are valid, don't mix them.

Row 1 caveat: for a show that just premiered, AniList frequently stores ep1 as
`00:00` on the *following* date (a placeholder, not the slot). Take weekday+clock from the
mode of rows 2..N. Overgeared's ep1 was a real `Sun 23:30`; Appraisal S3's was a fake
`Mon 00:00` whose true date was `Sun 09-27` — one week before the earliest clean row.
