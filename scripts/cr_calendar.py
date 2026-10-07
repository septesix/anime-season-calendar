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
HOUR but the published minute varies per show, measured 0 to +45 min above the JST
instant across 5 shows on 2026-10-06. Deriving gives you a time that is defensibly
wrong by up to three-quarters of an hour; this gives you the real one.

--diff DATE joins the parsed rows against that day's Apple Calendar events by
normalized title and reports MATCH / MISMATCH / NOT-IN-CAL.
"""
import urllib.request, socket, re, html, sys, json, subprocess, unicodedata, datetime

socket.setdefaulttimeout(30)
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")
URL = "https://www.crunchyroll.com/simulcastcalendar?filter=premium"
ROW = re.compile(r"(\d{1,2}:\d{2}\s*(?:am|pm))\s+(Premiere\s+)?(?:In Queue|Available|Premiere)?\s*(.{6,90}?)\s+Season\s+\d", re.I)
DAY = re.compile(r"(?:(Last Week|Today)\s+)?(\d{1,2}/\d{1,2})\s+(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b")

def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"\((Crunchyroll|Netflix|HIDIVE|Prime Video|OceanVeil|streamer TBC)\)\s*$", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return " ".join(s.split())

def parse():
    raw = urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": UA})).read()
    body = raw.decode("utf-8", "ignore")
    if len(body) < 20000:
        sys.exit("!! got a %d-byte JS shell, not the SSR page. The ?filter=premium param "
                 "is mandatory - do not conclude CR publishes nothing from this." % len(body))
    t = re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>|<[^>]+>", " ", body)
    t = re.sub(r"\s+", " ", html.unescape(t))
    marks = [(m.start(), m.group(2), m.group(3), m.group(1) or "") for m in DAY.finditer(t)]
    rows = []
    for m in ROW.finditer(t):
        tm, prem, title = m.group(1), (m.group(2) or "").strip(), m.group(3).strip()
        day = wknd = lbl = ""
        for pos, d, w, tag in marks:
            if pos < m.start(): day, wknd, lbl = d, w, tag
        title = re.sub(r"^(In Queue|Premiere|Available)\s+", "", title).strip(" -–")
        rows.append(dict(time=re.sub(r"\s+", "", tm.lower().replace("am", "am").replace("pm", "pm")),
                         day=day, wd=wknd, premiere=bool(prem), title=title))
    return rows

def cal_on(date, calendar):
    nx = (datetime.date.fromisoformat(date) + datetime.timedelta(days=1)).isoformat()
    r = subprocess.run(["apple-calendar", "list", "--calendar", calendar, "--start", date,
                        "--end", nx, "--compact"], capture_output=True, text=True)
    try: ev = json.loads(r.stdout)["data"]["events"]
    except Exception: sys.exit("!! could not read the calendar for %s: %s" % (date, r.stdout[:120]))
    return {norm(e.get("title") or ""): (e.get("start") or "")[11:16] for e in ev}

def main():
    a = sys.argv[1:]
    grep = a[a.index("--grep") + 1] if "--grep" in a else None
    diff = a[a.index("--diff") + 1] if "--diff" in a else None
    cal = a[a.index("--calendar") + 1] if "--calendar" in a else "Anime Calendar"
    rows = [r for r in parse() if (not grep or re.search(grep, r["title"], re.I))]
    # CR's own clock -> minutes, for comparison with a 24h calendar time
    def mins(s):
        h, rest = int(s[:-2]), s[-2:]
        if rest == "pm" and h != 12: h += 12
        if rest == "am" and h == 12: h = 0
        return h * 60
    if diff:
        c = cal_on(diff, cal)
        print("== CR published vs calendar on %s ==" % diff)
        seen = set()
        for r in rows:
            k = norm(r["title"])
            if k in seen: continue
            seen.add(k)
            mine = next((v for kk, v in c.items() if kk[:12] == k[:12] and k[:12]), None)
            want = mins(r["time"])
            if mine is None:
                print("  NOT-IN-CAL  %-52s CR %s" % (r["title"][:52], r["time"]))
            else:
                got = int(mine[:2]) * 60 + int(mine[3:5])
                d = got - want
                tag = "MATCH" if abs(d) <= 5 else ("MISMATCH %+d min" % d)
                print("  %-16s %-52s cal %s  CR %s" % (tag, r["title"][:52], mine, r["time"]))
    else:
        cur = ""
        for r in rows:
            if r["day"] != cur: print("\n--- %s ---" % r["day"]); cur = r["day"]
            print("  %-8s %-58s%s" % (r["time"], r["title"][:58], "  PREMIERE" if r["premiere"] else ""))
    print("\nrows=%d  (source: %s)" % (len(rows), URL))

main()
