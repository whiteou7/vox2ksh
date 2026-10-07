#!/usr/bin/env python3
import argparse
import collections
import csv
import sys


def load(path):
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                out[(row["song"], row["effect"])] = (float(row["excl_gain"]),
                                                     int(row["frames"]))
            except (KeyError, ValueError):
                continue
    if not out:
        sys.exit("no usable rows in %s (expected check_all_charts.py --csv output)" % path)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--worst", type=int, default=6,
                    help="per-chart swings to list for each moved effect")
    ap.add_argument("--flat", type=float, default=0.02,
                    help="|mean delta| under this counts as unchanged")
    args = ap.parse_args()

    a, b = load(args.before), load(args.after)
    shared = sorted(set(a) & set(b))
    if not shared:
        sys.exit("the two runs share no (chart, effect) pairs")

    only_a, only_b = len(set(a) - set(b)), len(set(b) - set(a))
    print("paired on %d (chart, effect) rows"
          "  [before-only %d, after-only %d]\n" % (len(shared), only_a, only_b))
    if only_a or only_b:
        print("  note: the runs do not cover the same set. Unpaired rows are\n"
              "  excluded, but a large imbalance means the corpus or the match\n"
              "  changed too, and the comparison is weaker than it looks.\n")

    per = collections.defaultdict(list)
    for key in shared:
        song, eff = key
        per[eff].append((song, a[key][0], b[key][0], b[key][1]))

    print("  %-20s %8s %8s %8s %9s %7s %s"
          % ("effect", "before", "after", "delta", "frame-wtd", "charts", "up/down"))
    moved = []
    for eff in sorted(per, key=lambda e: sum(r[2] - r[1] for r in per[e]) / len(per[e])):
        rows = per[eff]
        mb = sum(r[1] for r in rows) / len(rows)
        ma = sum(r[2] for r in rows) / len(rows)
        nf = sum(r[3] for r in rows) or 1
        fw = sum((r[2] - r[1]) * r[3] for r in rows) / nf
        up = sum(1 for r in rows if r[2] - r[1] > 1e-9)
        dn = sum(1 for r in rows if r[2] - r[1] < -1e-9)
        flag = "" if abs(ma - mb) < args.flat else "  <--"
        print("  %-20s %+8.3f %+8.3f %+8.3f %+9.3f %7d   %d/%d%s"
              % (eff, mb, ma, ma - mb, fw, len(rows), up, dn, flag))
        if abs(ma - mb) >= args.flat:
            moved.append(eff)

    for eff in moved:
        rows = sorted(per[eff], key=lambda r: -abs(r[2] - r[1]))[:args.worst]
        print("\n  largest per-chart swings, %s:" % eff)
        for song, bv, av, frames in rows:
            print("    %+7.3f  (%+.3f -> %+.3f, %5d frames)  %s"
                  % (av - bv, bv, av, frames, song))

    print("\n  Positive gain = closer to the cabinet recording than doing nothing.")
    print("  Rows without '<--' moved less than %.3f dB and count as unchanged."
          % args.flat)


if __name__ == "__main__":
    main()
