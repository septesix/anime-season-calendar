#!/usr/bin/env python3
"""dst_audit.py — the invariant that catches the hour-drift class of bug.

  usage: dst_audit.py [--boundary 2026-11-01] [--calendar "Anime Calendar"]

Root cause it tests for: apple-calendar has NO per-event timezone and EventKit stores a
weekly RRULE as a wall-clock time in the DEVICE zone. When the device zone's UTC offset
changes (first Sunday in Nov / Mar) a JST-anchored simulcast keeps the same clock and
therefore moves by an hour in absolute time. The fix is to split each series into two
same-title weekly legs across the boundary; anything not split is wrong after it.

The test itself is trivial and does not care how the legs were built: take the last week
before the boundary and the first week after, and compare each title's clock. A JST-
anchored show MUST shift by exactly 60 minutes. A PT/UTC-anchored one (Netflix originals)
must NOT shift.

This is a post-build check. Run it after any bulk create/rename, and once per season
before each DST boundary - it is the only guard here that cannot be skipped by reading
a file and forgetting to act on it.
"""
import subprocess, json, datetime, re, sys, unicodedata

def arg(name, dflt=None):
    a = sys.argv[1:]
    return a[a.index(name) + 1] if name in a else dflt

CAL = arg("--calendar", "Anime Calendar")
B = arg("--boundary")
if not B:
    t = datetime.date.today()
    y = t.year if t <= datetime.date(t.year, 11, 1) else t.year + 1
    d = datetime.date(y, 11, 1)
    while d.weekday() != 6: d += datetime.timedelta(days=1)
    B = d.isoformat()
BOUND = datetime.date.fromisoformat(B)

JST_SVC = r"\((Crunchyroll|HIDIVE|OceanVeil)\)$"
def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip()

def week(start):
    end = (start + datetime.timedelta(days=7)).isoformat()
    r = subprocess.run(["apple-calendar", "list", "--calendar", CAL, "--start", start.isoformat(),
                        "--end", end, "--compact"], capture_output=True, text=True)
    try: ev = json.loads(r.stdout)["data"]["events"]
    except Exception: sys.exit("!! unreadable calendar window %s: %s" % (start, r.stdout[:150]))
    out = {}
    for e in ev: out.setdefault(norm(e.get("title") or ""), []).append((e.get("start") or "")[11:16])
    return {k: v[0] for k, v in out.items() if len(set(v)) == 1}

pre = week(BOUND - datetime.timedelta(days=7))
post = week(BOUND)
both = sorted(set(pre) & set(post))
lost = sorted(set(pre) - set(post) - set(week(BOUND - datetime.timedelta(days=14))))
fails, exempt, good = [], [], []
for t in both:
    if pre[t] == post[t]:
        (fails if re.search(JST_SVC, t) else exempt).append(t)
    else:
        h1 = int(pre[t][:2]) * 60 + int(pre[t][3:5]); h2 = int(post[t][:2]) * 60 + int(post[t][3:5])
        d = h2 - h1
        (good if abs(d) == 60 else fails).append(t if abs(d) == 60 else "%s  (shifted %+d min, expected -60)" % (t, d))

print("DST boundary %s | calendar %r" % (B, CAL))
print("  titles present both weeks: %d" % len(both))
print("  split correctly (-60 min): %d" % len(good))
print("  NOT split, JST-anchored  : %d  <-- these air an hour early after the boundary" % len(fails))
for t in fails: print("     ! %s" % t[:78])
print("  NOT split, exempt (PT/UTC-anchored or undecorated): %d" % len(exempt))
for t in exempt[:12]: print("     . %s" % t[:78])
if lost:
    print("  vanished after boundary (check the leg 2 end date): %d" % len(lost))
    for t in lost[:10]: print("     ? %s" % t[:78])
print("\nverdict: %s" % ("PASS" if not fails and not lost else
                          "FAIL - rebuild the listed titles as two legs (see dst_legs.py)"))
sys.exit(0 if not fails and not lost else 1)
