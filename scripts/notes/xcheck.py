#!/usr/bin/env python3
"""
Structural crosscheck against every matched reference conversion.

    python xcheck.py [-n 10] [--only substring] [--worst 10] [--csv out.csv]

These are HAND conversions (scripts/shared/README.md), not a byte-for-byte
oracle - HANDOFF.md flags "error might exist but pretty minor". This counts
notes/holds/laser features on both sides and reports the deltas, which is
the right grain for "does this look like the same chart", not a diff.

Matching follows scripts/audio/masscheck.py's approach (by folder-name
substring, since reference folders are named after the song, not the game's
internal id), but crosschecks *every* difficulty present in each reference
folder rather than only the hardest - more charts is more signal for tuning
laser.py's decimation constants, which is the point of this script.
"""

import argparse
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared"))
from _paths import MUSIC, SCRIPTS, ensure_work

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "audio"))
from masscheck import match_songs, DIFF_SUFFIX  # noqa: F401 - re-exported below

REF = os.path.join(SCRIPTS, "shared", "reference", "ksh")

# match_songs / DIFF_SUFFIX now come from scripts/audio/masscheck.py (imported
# above) rather than being duplicated here. The duplicate had the same
# ambiguous-title bug masscheck.py's own match_songs used to have - e.g.
# "akasha" resolving to the wrong same-named song - fixed once, in one place.


def find_pairs():
    """-> [(vox_path, ksh_path, label), ...] for every difficulty present in
    every matched reference folder that also has a matching .vox chart.
    """
    pairs = []
    for ref_name, folder in sorted(match_songs().items()):
        rd = os.path.join(REF, ref_name)
        for fn in sorted(os.listdir(rd)):
            base, ext = os.path.splitext(fn)
            if ext.lower() != ".ksh":
                continue
            suffix = DIFF_SUFFIX.get(base.lower())
            if suffix is None:
                continue
            vox_path = os.path.join(MUSIC, folder, "%s_%s.vox" % (folder, suffix))
            if os.path.exists(vox_path):
                pairs.append((vox_path, os.path.join(rd, fn), "%s/%s" % (ref_name, fn)))
    return pairs


class KshStats:
    """Feature counts from a .ksh file's body - independent of convert.py,
    so this doesn't just check the writer against itself.
    """

    def __init__(self, path):
        self.bt_chip = [0] * 4
        self.bt_hold = [0] * 4
        self.fx_chip = [0] * 2
        self.fx_hold = [0] * 2
        self.laser_points = [0] * 2     # explicit chars, any value
        self.laser_runs = [0] * 2
        self.bars = 0

        prev_bt = ["0"] * 4
        prev_fx = ["0"] * 2
        prev_laser = ["-"] * 2
        seen_body = False
        for raw in open(path, "r", encoding="utf-8-sig", errors="replace"):
            line = raw.strip()
            if not line or line.startswith("//") or line.startswith("#"):
                continue
            if line == "--":
                self.bars += 1
                seen_body = True
                continue
            m = re.match(r"^([012]{4})\|([012]{2})\|(.{2})", line)
            if not m:
                continue
            seen_body = True
            bt, fx, ls = m.group(1), m.group(2), m.group(3)
            for i, c in enumerate(bt):
                if c == "1":
                    self.bt_chip[i] += 1
                elif c == "2" and prev_bt[i] != "2":
                    self.bt_hold[i] += 1
                prev_bt[i] = c
            for i, c in enumerate(fx):
                if c == "2":
                    self.fx_chip[i] += 1
                elif c == "1" and prev_fx[i] != "1":
                    self.fx_hold[i] += 1
                prev_fx[i] = c
            for i, c in enumerate(ls):
                if c not in "-:":
                    self.laser_points[i] += 1
                    if prev_laser[i] == "-":
                        self.laser_runs[i] += 1
                prev_laser[i] = c
        if not seen_body:
            raise ValueError("no chart body found in %s" % path)


CATEGORIES = [
    ("bars", lambda s: [s.bars]),
    ("BT chip", lambda s: s.bt_chip),
    ("BT hold", lambda s: s.bt_hold),
    ("FX chip", lambda s: s.fx_chip),
    ("FX hold", lambda s: s.fx_hold),
    ("laser runs", lambda s: s.laser_runs),
    ("laser points", lambda s: s.laser_points),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--limit", type=int, default=0, help="only the first N charts")
    ap.add_argument("--only", default=None, help="substring filter on the reference path")
    ap.add_argument("--worst", type=int, default=8,
                    help="how many worst-mismatched charts to list per category")
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()

    pairs = find_pairs()
    if args.only:
        pairs = [p for p in pairs if args.only in p[2]]
    if args.limit:
        pairs = pairs[:args.limit]
    print("matched %d chart(s)\n" % len(pairs))

    work = ensure_work()
    agg = {name: [] for name, _ in CATEGORIES}     # name -> [(ref_label, abs_err, ours_total, theirs_total), ...]
    csv_rows = []
    failures = []

    for i, (vox_path, ksh_path, label) in enumerate(pairs, 1):
        out_path = os.path.join(work, "xcheck_%d.ksh" % i)
        try:
            convert.convert(vox_path, out_path)
            ours = KshStats(out_path)
            theirs = KshStats(ksh_path)
        except Exception as e:
            failures.append((label, repr(e)))
            continue
        for name, getter in CATEGORIES:
            a, b = sum(getter(ours)), sum(getter(theirs))
            agg[name].append((label, a - b, a, b))
            csv_rows.append((label, name, a, b))

    print("=== aggregate over %d charts (%d failed) ===" % (len(pairs) - len(failures), len(failures)))
    print("  %-14s %8s %8s %8s %8s" % ("category", "mean|d|", "median|d|", "exact%", "worst"))
    for name, _ in CATEGORIES:
        rows = agg[name]
        if not rows:
            continue
        diffs = [abs(d) for (_l, d, _a, _b) in rows]
        exact = sum(1 for d in diffs if d == 0) / len(diffs) * 100
        diffs_sorted = sorted(diffs)
        worst = max(rows, key=lambda r: abs(r[1]))
        print("  %-14s %8.2f %8.1f %7.1f%% %8d  (%s: %d vs %d)" % (
            name, sum(diffs) / len(diffs), diffs_sorted[len(diffs_sorted) // 2], exact,
            abs(worst[1]), worst[0], worst[2], worst[3]))

    for name, _ in CATEGORIES:
        rows = sorted(agg[name], key=lambda r: -abs(r[1]))[:args.worst]
        rows = [r for r in rows if r[1] != 0]
        if not rows:
            continue
        print("\n  worst '%s' mismatches:" % name)
        for (label, d, a, b) in rows:
            print("    %+4d  (%4d vs %4d)  %s" % (d, a, b, label))

    if failures:
        print("\n  failed to convert (%d):" % len(failures))
        for label, err in failures[:20]:
            print("    %-40s %s" % (label, err))

    if args.csv:
        with open(args.csv, "w", encoding="utf-8") as f:
            f.write("chart,category,ours,theirs\n")
            for (label, name, a, b) in csv_rows:
                f.write("%s,%s,%d,%d\n" % (label, name, a, b))
        print("\n  wrote %s" % args.csv)


if __name__ == "__main__":
    main()
