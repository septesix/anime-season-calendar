#!/usr/bin/env python3
"""cr_calendar.py — read Crunchyroll's OWN published US drop times.

  usage: cr_calendar.py [--days 7] [--grep PATTERN] [--diff YYYY-MM-DD] [--calendar NAME]

The finding that makes this possible: the page is server-rendered, from the shell,
ONLY when a filter param is present -

  https://www.crunchyroll.com/simulcastcalendar?filter=premium   -> ~150 KB of HTML
  https://www.crunchyroll.com/simulcastcalendar                  ->  1.5 KB JS shell

Times are US EASTERN and are NOT localized (identical across enUS/en-GB/de/es/pt-br;
there is no timezone metadata anywhere in the document). Future days read
"Schedule Coming Soon", so this is a VERIFICATION source covering today and the recent
past - it can never be used to plan a season.

Why verify at all: the skill's derivation rule (ET = JST instant) is correct at the
HOUR but the published minute varies per show. Measured 2026-10-07 from the ISO fields
below, offset vs the JST instant runs **-25 to +45 min** (Red River is posted BEFORE its
JP TV slot, so the low end is negative): never derive the minute, read it here.

The page carries each drop as `<time datetime="2026-10-07T11:15:00-04:00">11:15am</time>`
- an exact instant with offset. Parse THAT, not the displayed text: v1 stripped all tags
and rebuilt the date from positional heading matching, and CR labels today as `Today`
with no date and tomorrow as `Fri 10/9` (weekday FIRST). Neither matched its MM/DD-then-
weekday regex, so all of today's rows silently inherited yesterday's date.

--diff DATE joins the parsed rows against that day's Apple Calendar events by
normalized title and reports MATCH / MISMATCH / NOT-IN-CAL.
"""
import urllib.request, socket, re, html, sys, json, subprocess, unicodedata, datetime

socket.setdefaulttimeout(30)
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")
URL = "https://www.crunchyroll.com/simulcastcalendar?filter=premium"
# One row = an ISO <time> followed (within the same card) by the series <cite>.
TIME_EL = re.compile(r'datetime="(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[^"]*)"')
CITE_EL = re.compile(r'<cite itemprop="name">(.{3,90}?)\s+Season \d', re.S)
PREM_EL = re.compile(r'class="premiere-flag"')

def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"\((Crunchyroll|Netflix|HIDIVE|Prime Video|OceanVeil|streamer TBC)\)\s*$", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return " ".join(s.split())

ET = datetime.timezone(datetime.timedelta(hours=-4))     # EDT; CR's own offsets are ET

def parse():
    raw = urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": UA})).read()
    body = raw.decode("utf-8", "ignore")
    if len(body) < 20000:
        sys.exit("!! got a %d-byte JS shell, not the SSR page. The ?filter=premium param "
                 "is mandatory - do not conclude CR publishes nothing from this." % len(body))
    times = [(m.start(), m.group(1)) for m in TIME_EL.finditer(body)]
    rows = []
    for m in CITE_EL.finditer(body):
        prev = [t for t in times if t[0] < m.start()]
        if not prev:
            continue
        iso = prev[-1][1]
        try:
            dt = datetime.datetime.fromisoformat(iso)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ET)
        dt = dt.astimezone(ET)                             # some rows carry -07:00
        # 500-char lookahead: the premiere flag sits between <time> and <cite>, but a
        # card boundary must not let a PREVIOUS row's flag leak onto this one.
        gap = body[prev[-1][0]:m.start()]
        rows.append(dict(dt=dt,
                         time=dt.strftime("%-I:%M%p").lower(),
                         date=dt.date().isoformat(),
                         day=dt.date().strftime("%-m/%-d"),
                         wd=dt.strftime("%a"),
                         premiere=bool(PREM_EL.search(gap)),
                         title=html.unescape(re.sub(r"\s+", " ", m.group(1)).strip(" -–"))))
    return sorted(rows, key=lambda r: r["dt"])

SEASONISH = re.compile(r"\s*(?:season\s*\d+|cour\s*\d+|\b(?:ii|iii|iv|v|vi)\b)\s*$", re.I)

def stem(t):
    """Join key: strip (Platform), punctuation and a trailing Season/Cour marker, so
    CR's 'LINK CLICK' matches the calendar's 'LINK CLICK Season 3 (Crunchyroll)'. The old
    fixed 12-char prefix test broke the moment either side carried such a suffix."""
    x = norm(t)
    for _ in range(3):
        y = SEASONISH.sub("", x)
        if y == x: break
        x = y
    return x.strip()


def cal_on(date, calendar):
    nx = (datetime.date.fromisoformat(date) + datetime.timedelta(days=1)).isoformat()
    r = subprocess.run(["apple-calendar", "list", "--calendar", calendar, "--start", date,
                        "--end", nx, "--compact"], capture_output=True, text=True)
    try: ev = json.loads(r.stdout)["data"]["events"]
    except Exception: sys.exit("!! could not read the calendar for %s: %s" % (date, r.stdout[:120]))
    return {stem(e.get("title") or ""): (e.get("start") or "")[11:16] for e in ev}

def main():
    a = sys.argv[1:]
    grep = a[a.index("--grep") + 1] if "--grep" in a else None
    diff = a[a.index("--diff") + 1] if "--diff" in a else None
    cal = a[a.index("--calendar") + 1] if "--calendar" in a else "Anime Calendar"
    days = int(a[a.index("--days") + 1]) if "--days" in a else None
    rows = [r for r in parse() if (not grep or re.search(grep, r["title"], re.I))]
    if days:                                              # --days N: today +/- N
        t0 = datetime.date.today()
        rows = [r for r in rows if abs((datetime.date.fromisoformat(r["date"]) - t0).days) <= days]
    if diff:
        c = cal_on(diff, cal)
        rows = [r for r in rows if r["date"] == diff]      # THIS day only - v1 compared
        print("== CR published vs calendar on %s (%d rows) ==" % (diff, len(rows)))   # every day's
        seen = set()
        for r in rows:
            k = stem(r["title"])
            if k in seen: continue
            seen.add(k)
            mine = c.get(k)
            want = r["dt"].hour * 60 + r["dt"].minute      # was int(s[:-2])*60: minutes dropped
            if mine is None:
                print("  NOT-IN-CAL  %-52s CR %s %s" % (r["title"][:52], r["time"], r["wd"]))
            else:
                got = int(mine[:2]) * 60 + int(mine[3:5])
                d = want - got                              # >0 = calendar is EARLY (miss the drop)
                tag = "MATCH" if d == 0 else ("MISMATCH %+d min" % d)
                print("  %-16s %-52s cal %s  CR %s" % (tag, r["title"][:52], mine, r["time"]))
    else:
        cur = ""
        for r in rows:
            if r["day"] != cur: print("\n--- %s ---" % r["day"]); cur = r["day"]
            print("  %-8s %-58s%s" % (r["time"], r["title"][:58], "  PREMIERE" if r["premiere"] else ""))
    print("\nrows=%d  (source: %s)" % (len(rows), URL))

main()
