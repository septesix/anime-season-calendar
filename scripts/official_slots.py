#!/usr/bin/env python3
r"""official_slots.py — read the JP broadcast slate off a show's OWN official site.

  usage: official_slots.py <url> [<url> ...] [--expected "Sun 23:30"]

Why this exists: a Japanese official site publishes 放送・配信情報 weeks or months
before premiere, whereas AniList's schedule rows are routinely absent or wrong until
the show has actually aired (they have been observed 12h off, and corrected after the
fact). So for the JP anchor - weekday + JST clock - the official site is the EARLIEST
source, and AniList is the cross-check. Neither is the source for the US minute.

This script ENUMERATES, it does not DECIDE. It never prints a single "best" slot,
because picking is a judgment and every heuristic tried so far has been wrong:
  - "earliest broadcast"  -> picks up 再放送/リピート slots (Ramparts of Ice: Sun 07:30
    repeat beats the real Thu 23:56 anchor)
  - "the 地上波 slot"     -> wrong for Korean-origin simulcasts (Overgeared: JP AT-X
    Fri 23:30 vs the Sun 23:30 slot that actually governs the US drop)
  - "the stream slot"     -> JP-only 配信 (AnimeFesta/dアニメストア) is not the anchor
    unless the show has no TV broadcast at all
Read the tagged candidates and choose. If you disagree with all of them, the page is
telling you something AniList does not.

Observed parse rate: 13/18 sites on Fall 2026 (5 were client-rendered shells - see
BROWSER FALLBACK below). Of the 13, 8 agreed with AniList to <=1 minute; the other 5
disagreed on WHICH slot, not on parsing.

EXIT: 0 = at least one slot parsed, 3 = nothing parsed (page is JS-gated or unlisted).

BROWSER FALLBACK for exit-3 sites (they need JS, not a better regex):
  browser_use navigate <url>, then execute_js:
    return document.body.innerText.replace(/\s+/g,' ').slice(0,6000)
  and read the 放送 line by eye. Do not conclude "no schedule published" from a
  shell page - that is how a show ends up parked at a guessed round number.
"""
import urllib.request, urllib.parse, socket, re, html, sys

socket.setdefaulttimeout(22)
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")
WD = {"日":"Sun","月":"Mon","火":"Tue","水":"Wed","木":"Thu","金":"Fri","土":"Sat"}
ORD = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]

# Japanese promo sites write times in KANJI, not HH:MM. A colon-only regex scores 0/1
# on pages that are perfectly parseable - the single most expensive bug in v1.
#   よる11時45分 = 23:45   深夜1時03分 = 25:03 (next day)   あさ5時00分 = 05:00
RX_KANJI = re.compile(
    r"(毎週\s*)?([日月火水木金土])\s*曜(?:日)?\s*(よる|午後|深夜|あさ|午前|朝)?\s*(\d{1,2})\s*時\s*(\d{1,2})?\s*分")
RX_DIGIT = re.compile(r"(毎週\s*)?([日月火水木金土])\s*曜(?:日)?\s*(よる|午後|深夜|あさ|午前|朝)?[^0-9]{0,10}?(\d{1,2})\s*[:：]\s*(\d{2})")

def adj(pre, h):
    """Period prefix -> 24h. 深夜 N時 = 24+N (next day); よる/午後 N = 12+N."""
    if pre in ("よる", "午後") and h < 12: h += 12
    if pre == "深夜": h += 24
    return h
NETS = ["テレビ朝日","フジテレビ","日本テレビ","TBS","MBS","RKB","メ～テレ","チューリップ","ABEMA","アニメタイムズ",
        "TOKYO MX","tvk","テレビ神奈川","KBS京都","テレビ愛知","BS日テレ","BS-TBS","BS11","BS12","BS富士","BS朝日",
        "BSフジ","AT-X","アニマックス","J:COM","dアニメストア","AnimeFesta","FOD","U-NEXT","TELASA","Lemino","TVer"]
REPEAT = ("リピート","再放送","見逃し","一挙放送","一気")

def fetch(u):
    try:
        raw = urllib.request.urlopen(urllib.request.Request(
            u, headers={"User-Agent": UA, "Accept-Language": "ja"})).read()
    except Exception as e:
        return ""
    for enc in ("utf-8", "shift_jis", "euc-jp"):
        try: return raw.decode(enc)
        except Exception: pass
    return raw.decode("utf-8", "ignore")

def totext(b):
    b = re.sub(r"(?s)<(script|style|noscript)[^>]*>.*?</\1>|<!--.*?-->", " ", b)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", b))).replace("：", ":")

def slots(t):
    """-> list of (weekday_idx, hh, mm, kind, network, context) deduped."""
    out = []
    for m in RX_KANJI.finditer(t):
        wd, pre, h, mi = m.group(2), m.group(3), int(m.group(4)), int(m.group(5) or 0)
        out.append((ORD.index(WD[wd]), adj(pre, h), mi, m.start()))
    for m in RX_DIGIT.finditer(t):
        # group 3 is the period prefix: よる11:45 is 23:45, not 11:45. Missing it was a
        # silent 12-hour error on every colon-form site that prefixes with よる/午後.
        wd, pre, h, mi = m.group(2), m.group(3), int(m.group(4)), int(m.group(5))
        out.append((ORD.index(WD[wd]), adj(pre, h), mi, m.start()))
    seen, res = set(), []
    for d, h, mi, pos in sorted(out, key=lambda x: (x[3],)):
        roll = 0
        hh = h
        while hh >= 24: hh -= 24; roll = 1   # 25:05 -> 01:05 next day
        day = (d + roll) % 7
        if (day, hh, mi) in seen: continue
        seen.add((day, hh, mi))
        w = t[max(0, pos - 90):pos + 40]
        wp = t[max(0, pos - 45):pos]      # markers BEFORE the slot only: a ※リピート放送
        net = ""                          # note belongs to the PREVIOUS line's slots
        for n in NETS:
            j = w.rfind(n)
            if j >= 0 and (not net or j > w.rfind(net)): net = n
        kind = "repeat" if any(k in wp for k in REPEAT) else ("stream" if ("配信" in w and "放送" not in w) else "tv")
        res.append((day, hh, mi, kind, net, re.sub(r"\s+", " ", w)[-70:]))
    return sorted(res, key=lambda x: (x[3] != "tv", x[0], x[1]))

def report(url):
    origin = re.match(r"(https?://[^/]+)", url).group(1)
    # Root is often a shell and the slate lives one hop away. This list is the whole
    # difference between 0 and 13 hits in the first prototype run.
    paths = [url, url.rstrip("/") + "/onair/", origin + "/onair/", origin + "/onair",
             origin + "/broadcast/", origin + "/tv/", origin + "/information/",
             origin + "/news/", origin + "/staffcast/", origin + "/intro/"]
    for p in paths:
        t = totext(fetch(p))
        if len(t) < 400: continue
        s = slots(t)
        if s:
            return s, ("(root)" if p == url else p.replace(origin, "")), len(t)
    return [], "-", 0

def main():
    args = [a for a in sys.argv[1:]]
    exp = None
    if "--expected" in args:
        i = args.index("--expected"); exp = args[i + 1]; del args[i:i + 2]
    if not args:
        print(__doc__); sys.exit(2)
    found = 0
    for url in args:
        s, where, tl = report(url)
        print("=== %-46s page=%-12s slots=%d" % (url.replace("https://", "")[:46], where, len(s)))
        if not s:
            print("    NOTHING PARSED (textlen=%d) -> use the BROWSER FALLBACK in the docstring" % tl)
            continue
        found += 1
        for d, h, mi, kind, net, ctx in s:
            print("    %s %02d:%02d JST  %-6s %-12s | %s" % (ORD[d], h, mi, kind, net, ctx))
        if exp:
            ewd, eclk = exp.split(); eh, em = map(int, eclk.split(":"))
            ea = ORD.index(ewd) * 1440 + eh * 60 + em
            def cand(pool):
                # sort on ABSOLUTE distance; keep the signed value only for display,
                # otherwise a negative delta wins over an exact 0 match.
                out = []
                for d, h, mi, k, n, c in pool:
                    sd = ((((d * 1440 + h * 60 + mi) - ea) + 5040) % 10080) - 5040
                    out.append((abs(sd), sd, d, h, mi))
                return min(out, default=None)
            best = cand([x for x in s if x[3] == "tv"]) or cand(s)
            if best is None:
                print("    vs expected %s -> no slots at all" % exp)
            else:
                sd, d, h, mi = best[1], best[2], best[3], best[4]
                verdict = "MATCH" if sd == 0 else ("AGREES %+d min" % sd if abs(sd) <= 90 else "DIFFERS")
                print("    vs expected %s -> %s   (closest site slot %s %02d:%02d)"
                      % (exp, verdict, ORD[d], h, mi))
                # Paste-ready season.txt column 10. The "@host" is what makes the claim
                # checkable: _vp_check.py only honours JPSLOT=official when this line was
                # copied here, so a hand-typed slot cannot buy a downgrade.
                host = url.split("//")[-1].split("/")[0].replace("www.", "")
                print("    col10 -> %s %02d:%02d @ %s" % (ORD[d], h, mi, host))
    sys.exit(0 if found else 3)

main()
