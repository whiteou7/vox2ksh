#!/usr/bin/env python3
"""
Survey the "pretilt cancellation" idiom in the hand-charted references.

Per direction (see specs/camera.md): KSM's own auto-tilt anticipates an
upcoming laser and starts tilting before the arcade would, so charters
insert an explicit `tilt=0` shortly before a laser run starts to cancel
that anticipation, then `tilt=normal` once the run actually begins to hand
control back to KSM's own auto-tilt. This script measures the tick gaps
around every literal `tilt=0` line in the 30 matched reference charts
against the nearest laser-run start, to find the triggering pattern.

    python pretilt.py [--only substring] [--dump N]
"""
import argparse
import bisect
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import correlate


def laser_run_starts(chart):
    """-> sorted list of (tick, side) for every node_type==1 (run start) row
    on either laser lane.
    """
    out = []
    for side, lst in (("L", chart.laser[0]), ("R", chart.laser[1])):
        for p in lst:
            if p.node_type == 1:
                out.append((p.tick, side))
    out.sort()
    return out


def section_start_runs(chart, silence_min=48):
    """-> sorted list of run-start ticks that begin a fresh laser *section*:
    no laser point (either lane) active in the `silence_min` cells right
    before this run starts. Excludes runs that are just the next segment of
    an ongoing back-to-back laser passage - the pretilt idiom is plausibly
    only inserted once per silence -> laser transition, not per run.
    """
    all_points = []
    for lst in chart.laser:
        for p in lst:
            all_points.append(p.tick)
    all_points.sort()

    starts = laser_run_starts(chart)
    out = []
    for (t, side) in starts:
        i = bisect.bisect_left(all_points, t)
        prev_tick = all_points[i - 1] if i > 0 else None
        if prev_tick is None or t - prev_tick >= silence_min:
            out.append(t)
    return sorted(set(out))


def next_at_or_after(sorted_ticks, tick):
    i = bisect.bisect_left(sorted_ticks, tick)
    return sorted_ticks[i] if i < len(sorted_ticks) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    ap.add_argument("--dump", type=int, default=25)
    ap.add_argument("--silence", type=int, default=48,
                     help="min cells of no-laser-anywhere before a run counts as a fresh section (default 48 = 1 beat)")
    ap.add_argument("--all-runs", action="store_true",
                     help="don't filter to section starts - check every run start (the noisier, original pass)")
    args = ap.parse_args()

    pairs = correlate.find_pairs()
    if args.only:
        pairs = [p for p in pairs if args.only in p[2]]
    print("matched %d chart(s)" % len(pairs))

    pre_gaps = []          # tick gap: laser-run-start - tilt=0 tick  (>=0 expected)
    post_gaps = []         # tick gap: next-tilt-event - laser-run-start, only when next value is "normal"
    next_val_counts = collections.Counter()
    unexplained = []       # tilt=0 events with no laser run within a generous window
    samples = []

    UNEXPLAINED_WINDOW = 400   # cells; ~2 measures at 48/quarter, generous

    for (vox_path, ksh_path, label) in pairs:
        try:
            chart = correlate.vox.load(vox_path)
            ev = correlate.parse_ksh_events(ksh_path, chart.tl)
        except Exception as e:
            print("  failed: %s: %r" % (label, e))
            continue

        if args.all_runs:
            run_ticks = [t for (t, _s) in laser_run_starts(chart)]
        else:
            run_ticks = section_start_runs(chart, args.silence)

        tilt_events = sorted(ev.opt["tilt"], key=lambda x: x[0])
        tilt_ticks = [t for (t, _v) in tilt_events]

        for i, (t0, raw) in enumerate(tilt_events):
            if raw.strip() != "0":
                continue
            nxt_run = next_at_or_after(run_ticks, t0)
            gap_pre = (nxt_run - t0) if nxt_run is not None else None
            if gap_pre is None or gap_pre > UNEXPLAINED_WINDOW:
                unexplained.append((label, t0, gap_pre))
                continue
            pre_gaps.append(gap_pre)

            # next tilt event after this one, and its gap from the run start
            if i + 1 < len(tilt_events):
                t1, v1 = tilt_events[i + 1]
                next_val_counts[v1] += 1
                if v1 == "normal":
                    post_gaps.append(t1 - nxt_run)
            if len(samples) < args.dump:
                samples.append((label, t0, gap_pre, nxt_run,
                                 tilt_events[i + 1] if i + 1 < len(tilt_events) else None))

    print("\ntilt=0 events preceding a laser run within %d cells: %d" % (UNEXPLAINED_WINDOW, len(pre_gaps)))
    print("tilt=0 events with no laser run nearby (unexplained): %d" % len(unexplained))
    if unexplained:
        print("  sample unexplained (label, tick, gap_to_next_run_or_None):")
        for u in unexplained[:15]:
            print("   ", u)

    def stats(name, xs):
        if not xs:
            print("%s: no data" % name)
            return
        xs = sorted(xs)
        n = len(xs)
        print("%s: n=%d min=%d max=%d median=%d mean=%.1f" % (
            name, n, xs[0], xs[-1], xs[n // 2], sum(xs) / n))
        print("  distribution:", collections.Counter(xs).most_common(15))

    print()
    stats("gap: laser-run-start - tilt=0-tick (pretilt lead time)", pre_gaps)
    print()
    print("value of the tilt= event immediately following tilt=0:", dict(next_val_counts.most_common(10)))
    print()
    stats("gap: (next tilt=normal event) - laser-run-start", post_gaps)

    print("\nsample (label, tilt0_tick, gap_to_run, run_tick, next_tilt_event):")
    for s in samples:
        print("  ", s)


if __name__ == "__main__":
    main()
