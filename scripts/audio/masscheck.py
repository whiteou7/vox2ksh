#!/usr/bin/env python3
"""Run xcheck.py across every reference recording and aggregate by effect.

    python masscheck.py [-n 10] [--extra=--no-persist] [--csv out.csv]

`scripts/shared/reference/ksh/<song>/` holds gameplay recordings with the audio
effects already applied. This matches each of those to the game's own chart in
data/music, renders it, and scores per effect - then aggregates.

One chart can only ever be suggestive: an effect might appear twice, or overlap
something else the whole time. Aggregating the *exclusive* per-effect gain over
many charts is what turns "this render sounds off" into "this DSP is wrong".

Positive gain = the render is closer to the recording than doing nothing.
Negative = that effect is actively making its region worse.
"""
import argparse
import os
import re
import subprocess
import sys
import collections

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, os.pardir, "shared"))
from _paths import GAME, MUSIC, SCRIPTS

REF = os.path.join(SCRIPTS, "shared", "reference", "ksh")
# highest first - the recordings are of the hardest chart in each folder
DIFF_ORDER = ["mxm", "inf", "grv", "hvn", "vvd", "xcd", "exh", "adv", "nov"]


def match_songs():
    """reference folder -> (data/music folder, recording path)."""
    music = {}
    for d in sorted(os.listdir(MUSIC)):
        m = re.match(r"^(\d+)_(.*)$", d)
        if m:
            music.setdefault(m.group(2).replace("_", ""), d)
    out = []
    for r in sorted(os.listdir(REF)):
        rd = os.path.join(REF, r)
        if not os.path.isdir(rd):
            continue
        key = r.replace("_", "")
        cand = [v for k, v in music.items() if k.startswith(key) or key.startswith(k)]
        if not cand:
            continue
        oggs = [f for f in os.listdir(rd) if f.endswith(".ogg")]
        if not oggs:
            continue
        pick = None
        for d in DIFF_ORDER:
            for o in oggs:
                if os.path.splitext(o)[0].lower() == d:
                    pick = o
                    break
            if pick:
                break
        pick = pick or sorted(oggs)[0]
        out.append((r, cand[0], os.path.join(rd, pick)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--limit", type=int, default=0, help="only the first N songs")
    ap.add_argument("--only", default=None, help="substring filter on the song name")
    ap.add_argument("--extra", default="", help="flags passed through to apply_chart.py")
    ap.add_argument("-b", "--block", type=int, default=512)
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()

    songs = match_songs()
    if args.only:
        songs = [s for s in songs if args.only in s[0]]
    if args.limit:
        songs = songs[:args.limit]
    print("matched %d songs with recordings\n" % len(songs))

    agg = collections.defaultdict(list)      # effect -> [exclusive gain, ...]
    overall = []
    rows_csv = []
    for i, (name, folder, ref) in enumerate(songs, 1):
        print("[%d/%d] %-34s %s" % (i, len(songs), name, os.path.basename(ref)))
        cmd = [sys.executable, os.path.join(_HERE, "xcheck.py"),
               os.path.join(MUSIC, folder), ref, "-b", str(args.block), "--quiet"]
        if args.extra:
            cmd += ["--extra=" + args.extra]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        except subprocess.TimeoutExpired:
            print("      timeout"); continue
        if r.returncode != 0:
            print("      failed: %s" % (r.stderr.strip().splitlines() or [""])[-1][:110])
            continue
        here = {}
        for line in r.stdout.splitlines():
            f = line.split()
            if len(f) == 8 and f[0] not in ("region",):
                eff, gain, excl, ecnt = f[0], f[3], f[5], f[6]
                if eff == "ALL":
                    try:
                        overall.append(float(gain))
                    except ValueError:
                        pass
                    continue
                if excl == "-" or eff in ("idle", "laser"):
                    continue
                try:
                    g, c = float(excl), int(ecnt)
                except ValueError:
                    continue
                if c >= 20:                    # ignore tiny samples
                    agg[eff].append(g)
                    here[eff] = g
                    rows_csv.append((name, eff, g, c))
        # only what THIS chart contained - printing the running dict would
        # repeat the last value of effects this chart never used
        print("      %s" % (", ".join("%s %+.2f" % kv for kv in sorted(here.items()))
                            or "(no scorable effect regions)"))

    print("\n=== aggregate: exclusive per-effect gain (dry - render) ===")
    print("  %-22s %8s %8s %8s %7s" % ("effect", "mean", "median", "worst", "charts"))
    for eff in sorted(agg, key=lambda k: sum(agg[k]) / len(agg[k])):
        v = sorted(agg[eff])
        mean = sum(v) / len(v)
        med = v[len(v) // 2]
        print("  %-22s %+8.3f %+8.3f %+8.3f %7d" % (eff, mean, med, v[0], len(v)))
    if overall:
        print("\n  ALL (whole track), mean gain over %d charts: %+.3f"
              % (len(overall), sum(overall) / len(overall)))
    print("\n  Negative mean = that DSP is reproducing the game badly.")

    if args.csv:
        with open(args.csv, "w", encoding="utf-8") as fh:
            fh.write("song,effect,excl_gain,frames\n")
            for row in rows_csv:
                fh.write("%s,%s,%.4f,%d\n" % row)
        print("  wrote %s" % args.csv)


if __name__ == "__main__":
    main()
