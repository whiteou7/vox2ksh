#!/usr/bin/env python3
"""Run check_one_chart.py across every reference recording and aggregate by effect.

    python check_all_charts.py [-n 10] [-j 8] [--extra=--wobble-persist] [--csv out.csv]

Pairs run concurrently across -j worker threads (default: cpu count). Each
check_one_chart.py call is its own subprocess doing numpy/ffmpeg work, so subprocess.run
blocks on a released GIL and threads here get real parallelism rather than
fighting each other for it.

`scripts/shared/reference/ksh/<song>/` holds gameplay recordings with the audio
effects already applied. This matches each of those to the game's own chart in
data/music, renders it, and scores per effect - then aggregates.

Scores EVERY difficulty capture present in a matched folder, not just the
hardest - most folders carry 2-4 (nov/adv/exh/inf.../mxm), and each is an
independent (chart, real cabinet recording) pair. Each is rendered with the
matching chart difficulty explicitly (`-d`), not apply_chart's own "hardest
present" default, which would silently pick the wrong chart on a folder whose
data/music entry has a harder difficulty than what got captured.

One chart can only ever be suggestive: an effect might appear twice, or overlap
something else the whole time. Aggregating the *exclusive* per-effect gain over
many charts is what turns "this render sounds off" into "this DSP is wrong".

Positive gain = the render is closer to the recording than doing nothing.
Negative = that effect is actively making its region worse.
"""
import argparse
import collections
import concurrent.futures
import os
import subprocess
import sys
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, os.pardir, os.pardir, os.pardir, "scripts", "shared"))
from _paths import MUSIC, WORK
from refmatch import REF, DIFF_SUFFIX, match_songs, music_index


def find_pairs():
    """-> [(ref_name, music_folder, ogg_path, vox_suffix), ...] for every
    difficulty actually captured (has both a .ksh and a .ogg) in every
    matched reference folder, provided that chart exists in data/music too.
    """
    pairs = []
    for ref_name, folder in sorted(match_songs().items()):
        rd = os.path.join(REF, ref_name)
        for fn in sorted(os.listdir(rd)):
            base, ext = os.path.splitext(fn)
            if ext.lower() != ".ogg":
                continue
            suffix = DIFF_SUFFIX.get(base.lower())
            if suffix is None:
                continue
            vox_path = os.path.join(MUSIC, folder, "%s_%s.vox" % (folder, suffix))
            if os.path.exists(vox_path):
                pairs.append((ref_name, folder, os.path.join(rd, fn), suffix))
    return pairs


def run_pair(i, ref_name, folder, ref, suffix, args):
    """Run check_one_chart.py for one (chart, capture) pair and return its raw result.

    Runs in a worker thread - subprocess.run releases the GIL while the child
    (a separate Python process, mostly numpy/ffmpeg) is running, so several of
    these overlap real CPU work despite the GIL.

    check_one_chart.py's render filename always embeds the song folder name, which
    differs per pair almost every time (nothing to overwrite, unlike the
    same-song-different-difficulty case) - so the pile of temp WAVs in WORK
    only ever grows over a run, concurrent or not. A sequential run just grew
    it slowly enough (~1 render in flight at a time) that nobody noticed
    output/work eating disk over many sessions; 16x concurrency across the
    full 645-pair corpus filled the drive in ~10 minutes and cascaded into
    497 failures. So: give each job its own --work-tag (worker thread id, so
    concurrent jobs against the *same* song folder don't race on the same
    path) and then delete that render as soon as we're done scoring it - we
    only ever wanted the score, not a persistent copy.
    """
    label = "%s/%s(%s)" % (ref_name, folder, suffix)
    render = os.path.join(WORK, "%s_w%d_check_one.wav" % (folder, threading.get_ident()))
    cmd = [sys.executable, os.path.join(_HERE, "check_one_chart.py"),
           os.path.join(MUSIC, folder), ref, "-d", suffix,
           "-b", str(args.block), "--quiet",
           "--work-tag", "w%d" % threading.get_ident()]
    if args.extra:
        cmd += ["--extra=" + args.extra]
    try:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        except subprocess.TimeoutExpired:
            return (i, label, ref, None, "timeout")
        if r.returncode != 0:
            err = (r.stderr.strip().splitlines() or [""])[-1][:110]
            return (i, label, ref, None, "failed: %s" % err)
        return (i, label, ref, r.stdout, None)
    finally:
        try:
            os.remove(render)
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--limit", type=int, default=0, help="only the first N (chart, capture) pairs")
    ap.add_argument("--only", default=None,
                    help="substring filter on the song name; comma-separated for "
                         "several (a pair is kept if it matches any of them)")
    ap.add_argument("--extra", default="", help="flags passed through to apply_chart.py")
    ap.add_argument("-b", "--block", type=int, default=512)
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 4,
                    help="parallel check_one_chart.py workers (default: cpu count, %d here)" % (os.cpu_count() or 4))
    ap.add_argument("--csv", default=None)
    ap.add_argument("--verbose-match", action="store_true",
                    help="list reference folders that failed to match (ambiguous or absent)")
    args = ap.parse_args()

    if args.verbose_match:
        music = music_index()
        matched = set(match_songs())
        unmatched, ambiguous = [], []
        for r in sorted(os.listdir(REF)):
            if not os.path.isdir(os.path.join(REF, r)) or r in matched:
                continue
            key = r.replace("_", "")
            cands = music.get(key) or [v for k, vs in music.items()
                                       if (k.startswith(key) or key.startswith(k)) for v in vs]
            (ambiguous if len(cands) > 1 else unmatched).append((r, cands))
        print("unmatched (no candidate found): %d" % len(unmatched))
        print("ambiguous (2+ candidates, skipped rather than guessed): %d" % len(ambiguous))
        for r, cands in ambiguous:
            print("  %-40s %s" % (r, cands))
        print()

    pairs = find_pairs()
    if args.only:
        keys = [k for k in args.only.split(",") if k]
        pairs = [p for p in pairs if any(k in p[0] for k in keys)]
    if args.limit:
        pairs = pairs[:args.limit]
    n_folders = len(set(p[0] for p in pairs))
    print("matched %d (chart, capture) pairs across %d song folders, %d workers\n"
          % (len(pairs), n_folders, args.jobs))

    agg = collections.defaultdict(list)      # effect -> [exclusive gain, ...]
    overall = []
    rows_csv = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(run_pair, i, ref_name, folder, ref, suffix, args)
                   for i, (ref_name, folder, ref, suffix) in enumerate(pairs, 1)]
        done = 0
        for fut in concurrent.futures.as_completed(futures):
            _, label, ref, stdout, err = fut.result()
            done += 1
            print("[%d/%d] %-44s %s" % (done, len(pairs), label, os.path.basename(ref)))
            if err:
                print("      %s" % err)
                continue
            here = {}
            for line in stdout.splitlines():
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
                        rows_csv.append((label, eff, g, c))
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
