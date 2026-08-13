#!/usr/bin/env python3
"""Diff two notes/xcheck.py --csv runs, per category.

    python compare.py before.csv after.csv [--worst 6]

xcheck writes `chart,category,ours,theirs`, one row per (chart, category).
`theirs` is the hand-made reference conversion and does not change between
runs; what moves is `ours`. The error compared here is |ours - theirs|, so a
category improves when that absolute error shrinks.

Only charts present in BOTH runs are compared. A chart that appears in one run
and not the other converted in one tree and raised in the other - that is
listed separately, because a new conversion failure is a blocking regression
however good the aggregate looks.
"""
import argparse
import collections
import csv
import sys


def load(path):
    """-> {(chart, category): (ours, theirs)}"""
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                out[(row["chart"], row["category"])] = (int(row["ours"]),
                                                        int(row["theirs"]))
            except (KeyError, ValueError):
                continue
    if not out:
        sys.exit("no usable rows in %s (expected notes xcheck --csv output)" % path)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--worst", type=int, default=6,
                    help="per-chart swings to list for each moved category")
    args = ap.parse_args()

    a, b = load(args.before), load(args.after)
    shared = sorted(set(a) & set(b))
    if not shared:
        sys.exit("the two runs share no (chart, category) pairs")

    lost = sorted({c for c, _ in set(a) - set(b)})
    gained = sorted({c for c, _ in set(b) - set(a)})

    print("paired on %d (chart, category) rows\n" % len(shared))
    if lost:
        print("  BLOCKING: %d chart(s) scored before and not after - they now fail\n"
              "  to convert, or stopped matching:" % len(lost))
        for c in lost[:20]:
            print("    %s" % c)
        print()
    if gained:
        print("  %d chart(s) newly scored (converted after but not before):" % len(gained))
        for c in gained[:20]:
            print("    %s" % c)
        print()

    per = collections.defaultdict(list)   # category -> [(chart, err_before, err_after)]
    for key in shared:
        chart, cat = key
        per[cat].append((chart, abs(a[key][0] - a[key][1]), abs(b[key][0] - b[key][1])))

    print("  %-14s %9s %9s %9s %9s %9s %s"
          % ("category", "mean|d| b", "mean|d| a", "delta", "exact% b", "exact% a", "better/worse"))
    moved = []
    for cat in sorted(per):
        rows = per[cat]
        n = len(rows)
        mb = sum(r[1] for r in rows) / n
        ma = sum(r[2] for r in rows) / n
        eb = sum(1 for r in rows if r[1] == 0) / n * 100
        ea = sum(1 for r in rows if r[2] == 0) / n * 100
        better = sum(1 for r in rows if r[2] < r[1])
        worse = sum(1 for r in rows if r[2] > r[1])
        flag = "" if better == worse == 0 else "  <--"
        print("  %-14s %9.2f %9.2f %+9.2f %8.1f%% %8.1f%%   %d/%d%s"
              % (cat, mb, ma, ma - mb, eb, ea, better, worse, flag))
        if better or worse:
            moved.append(cat)

    for cat in moved:
        rows = [r for r in per[cat] if r[2] != r[1]]
        rows = sorted(rows, key=lambda r: -abs(r[2] - r[1]))[:args.worst]
        print("\n  largest per-chart swings, %s:" % cat)
        for chart, eb, ea in rows:
            arrow = "better" if ea < eb else "worse"
            print("    |d| %4d -> %4d  (%s)  %s" % (eb, ea, arrow, chart))

    print("\n  Lower mean|d| is better. Button categories (bars, BT/FX chip and hold)")
    print("  are exact by construction - any non-zero mean there is a bug, not an")
    print("  approximation. Laser points are approximate by design.")


if __name__ == "__main__":
    main()
