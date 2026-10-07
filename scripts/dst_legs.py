#!/usr/bin/env python3
"""Split a JST-weekly anime run into DST-correct US Eastern calendar legs.

A single weekly recurrence cannot cross a US DST change: the ET wall-clock time
shifts by an hour. This emits one leg per contiguous run that shares an ET clock
time, ready to feed to apple-calendar as separate --recur weekly events.

usage: dst_legs.py <first_ep_jst_date:YYYY-MM-DD> <jst_clock:HH:MM> <n_eps>
       dst_legs.py --tsv <schedule.tsv>     (cols: date  clock  n_eps)
"""
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
ET  = ZoneInfo("America/New_York")
WD  = ["sun","mon","tue","wed","thu","fri","sat"]

def legs(d, clock, n):
    H, M = (int(x) for x in clock.split(":"))
    try:
        start = datetime(d.year, d.month, d.day, H, M, tzinfo=JST)
    except ValueError:
        # 24:00-style JST slot means "just after midnight, next day"
        start = datetime(d.year, d.month, d.day, 0, M, tzinfo=JST) + timedelta(days=1)
    out = []
    for i in range(n):
        et = (start + timedelta(days=7*i)).astimezone(ET)
        key = (et.hour, et.minute)
        if out and out[-1]["key"] == key:
            out[-1]["eps"].append(et)
        else:
            out.append({"key": key, "eps": [et]})
    return out

def emit(d, clock, n, label=""):
    L = legs(d, clock, n)
    rows = []
    for g in L:
        first, last = g["eps"][0], g["eps"][-1]
        until = (last + timedelta(days=1)).date()   # until compares at 00:00 -> +1 day
        off = first.utcoffset() - timedelta(hours=-5) if False else first.utcoffset()
        # isoweekday(): Mon=1..Sun=7 -> %7 gives Sun=0, matching WD below.
        # (Python's weekday() is Monday=0 and would shift every leg one day wrong.)
        rows.append((first.strftime("%Y-%m-%d"), first.strftime("%H:%M"),
                     WD[first.isoweekday() % 7], str(until), len(g["eps"]),
                     "UTC%+d" % (off.days*24 + off.seconds//3600)))
    print("%-42s %d leg(s)" % (label, len(rows)))
    for r in rows:
        print("   start=%s %s %s tz=%s | occurrences=%d | --recur-until %s"
              % (r[0], r[1], r[2], r[5], r[4], r[3]))
        print("     apple-calendar create --start \"%sT%s:00%s\" --end \"%sT%s:00%s\" "
              "--recur weekly --recur-days %s --recur-until %s"
              % (r[0], r[1], _z(r[0], r[1]), r[0], _e(r[1]), _z(r[0], r[1]), r[2], r[3]))
    return rows

def _z(dstr, hms):
    dt = datetime.strptime(dstr+" "+hms, "%Y-%m-%d %H:%M").replace(tzinfo=ET)
    return dt.strftime("%z")[:3] + ":" + dt.strftime("%z")[3:]

def _e(hms):
    h, m = (int(x) for x in hms.split(":"))
    m += 30
    if m >= 60: h, m = h+1, m-60
    h %= 24
    return "%02d:%02d" % (h, m)

if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__); sys.exit(2)
    if a[0] == "--tsv":
        for line in open(a[1]):
            if not line.strip(): continue
            p = line.rstrip("\n").split("\t")
            y, mo, da = (int(x) for x in p[0].split("-"))
            n = int(p[2]) if len(p) > 2 else 12
            emit(datetime(y, mo, da), p[1], n, label=p[0]+" "+p[1])
    else:
        y, mo, da = (int(x) for x in a[0].split("-"))
        emit(datetime(y, mo, da), a[1], int(a[2]), label="run")
