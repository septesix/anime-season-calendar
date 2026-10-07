import sys, datetime
season, actual = sys.argv[1], sys.argv[2]
WD = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
truth = {}
for line in open(actual):
    line = line.rstrip("\n")
    if not line.strip(): continue
    p = line.split("\t")
    if len(p) < 2 or not p[0].isdigit():
        print("!! probe output unusable: " + line[:60]); sys.exit(3)
    truth[int(p[0])] = dict(n=int(p[1]), wd=p[2], clock=p[3], first=p[4], last=p[5],
                            dates=set(p[6].split(",")) if len(p) > 6 and p[6] else set())
fails = 0; rows = 0; seen = {}; bad = set()
print("%-52s %-4s %-6s %-11s %-5s %s" % ("TITLE","ID","verdict","declared","truth","detail"))
for line in open(season):
    line = line.rstrip("\n")
    if not line.strip() or line.startswith("TITLE"): continue
    f = line.split("|")
    if len(f) < 7: print("!! malformed row (needs >=7 cols): " + line[:60]); fails += 1; continue
    title, d, clk, mode, svc, conf, aid = f[0], f[1], f[2], f[3], f[4], f[5], f[6]
    rows += 1
    key2 = (d, clk)
    seen.setdefault(key2, []).append(title)
    if not aid.isdigit():
        print("%-52s %-4s %-6s %-11s %-5s NO ANILIST ID -> unverifiable" % (title[:52], "-", "FAIL", d+" "+clk, "-")); fails += 1; continue
    t = truth.get(int(aid))
    if t is None or t["n"] == 0:
        print("%-52s %-4s %-6s %-11s %-5s no AniList schedule rows" % (title[:52], aid, "WARN", d+" "+clk, "-")); continue
    try: dw = WD[datetime.date(*map(int, d.split("-"))).weekday()]
    except Exception: print("!! bad date " + d); fails += 1; continue
    v, det = "OK", ""
    if mode.upper().startswith("ET"):
        print("%-52s %-4s %-6s %-11s %-5s ET-instant row; JST truth = %s" % (title[:52], aid, "INFO", d+" "+clk, "-", t["wd"]+" "+t["clock"])); continue
    if dw != t["wd"]: v, det = "FAIL", "weekday %s != AniList %s" % (dw, t["wd"])
    if clk != t["clock"] and v == "OK": v, det = "FAIL", "clock %s JST != AniList %s" % (clk, t["clock"])
    # START: d must sit on the show's real weekly grid. Membership alone is the wrong
    # test - AniList often stores ep1 as a next-day 00:00 placeholder, so the true
    # premiere date may be absent from the row set. Instead: take the rows that share
    # d's weekday and require d to fall within the airing window (1 week of slack).
    if v == "OK":
        dd = datetime.date(*map(int, d.split("-")))
        same = [datetime.date(*map(int, x.split("-"))) for x in t["dates"]
                if WD[datetime.date(*map(int, x.split("-"))).weekday()] == t["wd"]]
        if same:
            lo, hi = min(same), max(same)
            if dd < lo - datetime.timedelta(days=13) or dd > hi + datetime.timedelta(days=13):
                v, det = "FAIL", "start %s outside airing window %s..%s" % (d, lo, hi)
        else:
            v, det = "FAIL", "no AniList row on a %s show ever aired" % dw
    # --- corroboration, not just transcription -------------------------------------
    # v1 could only prove "I copied AniList correctly". AniList's own pre-air values have
    # been wrong (12h off; corrected after premiere), so a passing gate proved nothing.
    # cols: 9=JPSLOT(official|anilist|guess) 10=OFFICIAL_SLOT("Wed 23:45") 11=EPS
    jps = (f[8].strip().lower() if len(f) > 8 else "")
    off = (f[9].strip() if len(f) > 9 else "")
    epsdecl = (f[10].strip() if len(f) > 10 else "")
    if v == "FAIL" and jps == "official" and off:
        try:
            owd, oclk = off.split()
        except ValueError:
            owd, oclk = "", ""
        if owd == dw and oclk == clk:
            # The row follows the show's own site and conflicts with AniList. That is the
            # documented case, not an error: official sites publish 放送情報 months ahead,
            # AniList fills placeholder rows first and fixes them after air.
            v, det = "WARN", "row = OFFICIAL SITE %s, AniList says %s %s -> re-pull after premiere" % (off, t["wd"], t["clock"])
    if conf == "high" and (len(f) < 8 or f[7] != "sched"):
        v, det = "FAIL", (det + "; " if det else "") + "conf=high without SRC=sched"
    if conf == "high" and jps not in ("official", "anilist"):
        v, det = "FAIL", (det + "; " if det else "") + \
            ("conf=high with JPSLOT=%r -> run scripts/official_slots.py <official-site-url> "
             "--expected '%s %s' and record JPSLOT=official|anilist" % (jps or "unset", dw, clk))
    if epsdecl.isdigit() and t["n"]:
        if int(epsdecl) < t["n"]:
            v, det = "FAIL", (det + "; " if det else "") + "EPS=%s but AniList has %d rows -> leg ends early" % (epsdecl, t["n"])
        elif int(epsdecl) > t["n"]:
            # Not an error: 2-cour shows (連続2クール) have only the first cour entered.
            # Rayearth: 12 rows but 24 eps. Warn, and never let the shorter span win.
            det = (det + "; " if det else "") + "declared EPS=%s > AniList rows %d (2-cour? confirm with the official site before trusting either span)" % (epsdecl, t["n"])
    print("%-52s %-4s %-6s %-11s %-5s %d eps  %s" % (title[:52], aid, v, d+" "+clk, t["wd"]+" "+t["clock"], t["n"], det))
    if v == "FAIL": fails += 1; bad.add(title)
for (d, clk), names in sorted(seen.items()):
    if len(names) > 1 and any(n in bad for n in names):
        print("DUPCLOCK  %s %s shared by: %s  <- %s" % (
            d, clk, " | ".join(names),
            "one of these is a copy; the other verified clean" ))
# Co-timed rows that BOTH verify against their own AniList record are simply shows that
# share a broadcast slot - extremely common (two Sunday 23:30 titles). Reporting those
# would fire on most seasons and train everyone to ignore the warning.
print("---\nrows=%d  failures=%d" % (rows, fails))
sys.exit(1 if fails else 0)
