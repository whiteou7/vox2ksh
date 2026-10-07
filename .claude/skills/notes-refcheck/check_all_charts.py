#!/usr/bin/env python3

import argparse
import os

from ksh_stats import CATEGORIES, convert_and_count, ensure_work, find_pairs


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
    agg = {name: [] for name, _ in CATEGORIES}
    csv_rows = []
    failures = []

    for i, (vox_path, ksh_path, label) in enumerate(pairs, 1):
        out_path = os.path.join(work, "check_all_%d.ksh" % i)
        try:
            ours, theirs = convert_and_count(vox_path, ksh_path, out_path)
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
