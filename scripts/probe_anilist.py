#!/usr/bin/env python3
"""probe_anilist.py — AniList airingSchedules straight from the shell, no browser.

  usage: probe_anilist.py <season.txt> > actual.tsv
         probe_anilist.py --ids 178868,189123 > actual.tsv
         probe_anilist.py [--from YYYY-MM-DD] [--to YYYY-MM-DD] <season.txt>

Output (7 cols, tab-separated, byte-compatible with probe_schedules.js):
  id \t n_eps \t weekday \t HH:MM \t first_date \t last_date \t date1,date2,...
  "NONE" in col 3 when AniList has no rows for the id.

WHY THIS EXISTS: probe_schedules.js must be pasted into a browser tab, which makes the
gate a manual step and therefore skippable. This script has no browser dependency, so
`verify_provenance.sh check` can run unattended.

THE "the shell gets 403" NOTE WAS WRONG. It held on 2026-10-01 and was repeated in five
files until 2026-10-07, when a measured sweep (97 season titles -> 1067 rows in 7.8 s,
0 failures) showed plain POST from iSH works fine. Follow-ups found:
  * GET on that endpoint is 404 ("Use POST request") - never 403;
  * a 403 here is INTERMITTENT, not UA-dependent (4 UAs all passed) and not
    request-shape-dependent (a 100-id mediaId_in passed) - so treat it as transient
    rate-limiting and retry, not as a blocked host.
The browser route stays as the fallback (see references/anilist-cookbook.md), it is just
no longer the only route.

Output is deliberately IDENTICAL to probe_schedules.js, including the two non-obvious
rules that version was debugged into:
  1. WD is SUNDAY-FIRST (["Sun",...,"Sat"]) - a Mon-first table mislabels every Sunday.
  2. weekday/clock are the modal of rows 2..N, never row 1 - AniList stores ep1 as a
     midnight placeholder often enough to change the answer.
"""
import sys, os, json, time, datetime, urllib.request
from collections import Counter

WD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]   # Sunday-first; see docstring
ENDPOINT = os.environ.get("ANILIST_URL", "https://graphql.anilist.co")
Q = ("query($ids:[Int],$g:Int,$l:Int,$p:Int){Page(page:$p,perPage:50)"
     "{airingSchedules(mediaId_in:$ids,airingAt_greater:$g,airingAt_lesser:$l)"
     "{mediaId airingAt episode}}}")
RETRIES, CHUNK = 3, 25


def post(ids, g, l, page):
    body = json.dumps({"query": Q, "variables": {"ids": ids, "g": g, "l": l, "p": page}}).encode()
    last = None
    for n in range(RETRIES):
        try:
            req = urllib.request.Request(ENDPOINT, data=body, headers={
                "User-Agent": "anime-season-calendar/1.0",
                "Content-Type": "application/json", "Accept": "application/json"})
            d = json.load(urllib.request.urlopen(req, timeout=60))
            if d.get("errors"):
                raise RuntimeError("graphql: " + d["errors"][0]["message"][:80])
            return d["data"]["Page"]["airingSchedules"]
        except Exception as e:
            last = e
            code = getattr(e, "code", "")
            # 403/429/5xx are transient here (measured: not tied to UA or query shape).
            # Back off before hammering the same endpoint.
            if code in (403, 429) or str(code) >= "500":
                time.sleep(2 * (n + 1)); continue
            if isinstance(e, RuntimeError):
                raise RuntimeError("%s (ids %s..) - do NOT retry, fix the query" % (e, ids[:2]))
            time.sleep(1)
    raise RuntimeError("endpoint unreachable after %d tries: %s %s" % (RETRIES, code, last))


def ids_from(path):
    out = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("TITLE"):
                continue                     # '#' is a comment, not a malformed row
            p = line.split("|")
            if len(p) > 6 and p[6].strip().isdigit():
                out.add(int(p[6]))
    if not out:
        sys.exit("no numeric AniList ids in column 7 of %s" % path)
    return sorted(out)


def main():
    a = sys.argv[1:]
    ids, frm, to = None, None, None
    i = 0
    while i < len(a):
        if a[i] == "--ids": ids = [int(x) for x in a[i + 1].split(",") if x.strip()]; i += 2
        elif a[i] == "--from": frm = a[i + 1]; i += 2
        elif a[i] == "--to": to = a[i + 1]; i += 2
        else: ids = ids_from(a[i]); i += 1
    if ids is None:
        print(__doc__); sys.exit(2)
    y = datetime.date.today().year
    # The window is the whole point of the re-pull: AniList backfills and CORRECTS rows,
    # so a window that ends before the cour is over silently truncates EPS.
    g = int(datetime.datetime.fromisoformat(frm or "%d-06-01" % (y - 1)).timestamp())
    l = int(datetime.datetime.fromisoformat(to or "%d-06-01" % (y + 1)).timestamp())

    by = {}
    for c in range(0, len(ids), CHUNK):
        chunk = ids[c:c + CHUNK]
        for p in range(1, 21):
            rows = post(chunk, g, l, p)
            for r in rows:
                by.setdefault(int(r["mediaId"]), []).append(r)
            if len(rows) < 50:
                break
    for k in list(by):                       # a re-run across chunk boundaries can dupe
        seen = {}
        for r in by[k]:
            seen[r["episode"]] = r["airingAt"]
        by[k] = [{"episode": e, "airingAt": v} for e, v in seen.items()]

    print("# probe_anilist  ids=%d with_rows=%d empty=%d window=%s..%s"
          % (len(ids), sum(1 for k in ids if by.get(k)), sum(1 for k in ids if not by.get(k)),
             datetime.datetime.fromtimestamp(g).date(), datetime.datetime.fromtimestamp(l).date()),
          file=sys.stderr)
    for mid in ids:
        rows = sorted(by.get(mid, []), key=lambda r: r["episode"])
        if not rows:
            print("%d\t0\tNONE\tNONE\t\t\t" % mid); continue
        pool = rows[1:] if len(rows) > 1 else rows   # modal over rows 2..N, never ep1
        def k(r):                                    # JST wall clock, from UTC epoch
            dt = datetime.datetime.fromtimestamp(r["airingAt"] + 9 * 3600, datetime.UTC)
            return WD[(dt.weekday() + 1) % 7], dt.strftime("%H:%M"), dt.strftime("%Y-%m-%d")
        wd, clk = Counter(k(r)[:2] for r in pool).most_common(1)[0][0]
        dates = sorted({k(r)[2] for r in rows})
        print("%d\t%d\t%s\t%s\t%s\t%s\t%s" % (mid, len(rows), wd, clk, dates[0], dates[-1], ",".join(dates)))


main()
