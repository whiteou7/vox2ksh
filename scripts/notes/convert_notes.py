#!/usr/bin/env python3
"""Converts buttons and lasers from .vox to the .ksh chart body (specs/notes.md). `--preview` fills po= and plength= from the song audio.

    python convert_notes.py <chart.vox> [-o out.ksh] [--ksh-version 1|2] [--preview]
"""

import argparse
import bisect
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for _sibling in ("notes", "shared", "camera", "audio"):
    sys.path.insert(0, os.path.join(HERE, os.pardir, _sibling))

import camera_events  # noqa: E402
import laser_curves as laser  # noqa: E402
import vox_parser as vox  # noqa: E402

BT_CHIP, BT_HOLD = "1", "2"
FX_CHIP, FX_HOLD = "2", "1"

# USC steps each ksh row by a whole number of its 240-per-beat ticks, so a finer row spacing (a 480-resolution vox can need 1920 rows a measure) truncates to zero and collapses the measure.
USC_TICKS_PER_BEAT = 240

DIFF_MAP = {"1n": "light", "2a": "challenge", "3e": "extended",
            "4i": "infinite", "5m": "infinite"}


class HoldLane:
    def __init__(self, notes):
        holds = sorted((n.tick, n.end_tick) for n in notes if n.is_hold)
        self.hold_starts = [h[0] for h in holds]
        self.hold_ends = [h[1] for h in holds]
        self.hold_start_set = set(self.hold_starts)
        self.chip_ticks = {n.tick for n in notes if not n.is_hold}
        self.se_chip_ticks = {n.tick for n in notes if not n.is_hold and n.c2 > 0}

    def ksh_char_at(self, tick, chip_char, hold_char):
        if tick in self.chip_ticks:
            return chip_char
        i = bisect.bisect_right(self.hold_starts, tick) - 1
        if i >= 0 and tick < self.hold_ends[i]:
            return hold_char
        return "0"

    def grid_anchor_ticks(self):
        return self.chip_ticks | self.hold_start_set | set(self.hold_ends)


class LaserLane:
    def __init__(self, runs):
        self.runs = sorted(runs, key=lambda r: r.start_tick)
        self.run_starts = [r.start_tick for r in self.runs]
        self.curve_ticks = {}
        for r in self.runs:
            for i, curve in enumerate(r.curves):
                if curve is None:
                    continue
                tick = r.points[i - 1][0] if i > 0 and r.slam_after[i - 1] else r.points[i][0]
                self.curve_ticks.setdefault(tick, curve)
        # The first point at a tick wins, so build each run's map back to front.
        self.run_chars = [{t: laser.pos_to_char(v) for (t, v) in reversed(r.points)}
                          for r in self.runs]

    def ksh_char_at(self, tick):
        i = bisect.bisect_right(self.run_starts, tick) - 1
        if i < 0 or tick > self.runs[i].end_tick:
            return "-"
        return self.run_chars[i].get(tick, ":")

    def run_starting_at(self, tick):
        i = bisect.bisect_left(self.run_starts, tick)
        return self.runs[i] if i < len(self.runs) and self.runs[i].start_tick == tick else None

    def grid_anchor_ticks(self):
        out = {t for r in self.runs for (t, _v) in r.points}
        for a, b in zip(self.runs, self.runs[1:]):
            if b.start_tick - a.end_tick >= 2:
                out.add(a.end_tick + 1)
        return out


def slots_per_measure(length, anchor_offsets):
    divisor = length
    for offset in anchor_offsets:
        if 0 < offset < length:
            divisor = math.gcd(divisor, offset)
    if divisor <= 0:
        divisor = length
    return max(1, length // divisor)


def _format_bpm(bpm):
    s = ("%.4f" % bpm).rstrip("0").rstrip(".")
    return s or "0"


def _format_curve(curve):
    return "%.2f;%.2f" % curve


def _camera_events_by_tick(chart, pretilt_fix, simulate_tilt):
    """Per-tick option lines (tilt, zoom) and per-tick spin tokens."""
    options, spins = {}, {}
    for (tick, value) in camera_events.compute_tilt_events(chart, pretilt_fix=pretilt_fix, simulate=simulate_tilt):
        options.setdefault(tick, []).append("tilt=" + value)
    for (tick, line) in camera_events.compute_zoom_events(chart):
        options.setdefault(tick, []).append(line)
    for tick, (_side, token) in camera_events.compute_spin_tokens(chart).items():
        spins[tick] = token
    return options, spins


def _tempo_changes(tl):
    """(tick, bpm) at every tempo change that alters the BPM."""
    changes, previous_bpm = [], None
    for (measure, beat, cell, bpm) in tl.bpms:
        if bpm != previous_bpm:
            changes.append((tl.tick_at(measure, beat, cell), bpm))
            previous_bpm = bpm
    return changes


def _chart_last_tick(button_lanes, laser_lanes, extra_ticks):
    last = 0
    for lane in button_lanes:
        last = max([last, *lane.hold_ends, *lane.chip_ticks])
    for lane in laser_lanes:
        last = max([last, *(run.end_tick for run in lane.runs)])
    return max([last, *extra_ticks])


def convert(vox_path, out_path, camera=False, meta=None, slam_gap_frac=laser.SLAM_GAP_FRAC,
            pretilt_fix=False, ksh_version=1, simulate_tilt=False):
    chart = vox.load(vox_path, res_unit=USC_TICKS_PER_BEAT)
    tl = chart.tl

    use_curves = ksh_version >= 2
    button_lanes = [HoldLane(notes) for notes in chart.bt + chart.fx]
    bt_lanes, fx_lanes = button_lanes[:len(chart.bt)], button_lanes[len(chart.bt):]
    laser_lanes = [LaserLane(laser.build_runs(pts, tl, slam_gap_frac=slam_gap_frac, curves=use_curves))
                   for pts in chart.laser]
    camera_options, spin_tokens = _camera_events_by_tick(chart, pretilt_fix, simulate_tilt) if camera else ({}, {})

    tight_runs = sum(1 for lane in laser_lanes for r in lane.runs if r.tight)
    if tight_runs:
        print("note: %d laser run(s) needed a sub-24th-note gap to keep their true "
              "shape (see laser_curves.py's docstring, point 3) - real, unavoidable "
              "given .ksh's grid" % tight_runs, file=sys.stderr)

    bpm_changes = _tempo_changes(tl)
    # A chart with one constant BPM states it in the header only.
    multi_bpm = len({bpm for _tick, bpm in bpm_changes}) > 1
    bpm_change_at_tick = dict(bpm_changes if multi_bpm else bpm_changes[1:])
    beat_by_measure = {measure: (numerator, denominator) for (measure, numerator, denominator) in tl.beats}

    last_tick = _chart_last_tick(button_lanes, laser_lanes, [*camera_options, *spin_tokens])
    last_measure, _ = tl.measure_and_offset(last_tick)

    anchor_ticks = set(bpm_change_at_tick) | set(camera_options) | set(spin_tokens)
    for lane in button_lanes + laser_lanes:
        anchor_ticks |= lane.grid_anchor_ticks()
    sorted_anchors = sorted(anchor_ticks)

    lines = _ksh_header(chart, bpm_changes, tl.beats, meta=meta)
    current_time_signature = None

    for measure in range(last_measure + 1):
        measure_length_ticks = tl.measure_length(measure)
        measure_start = tl.measure_start_tick(measure)

        first = bisect.bisect_left(sorted_anchors, measure_start)
        end = bisect.bisect_left(sorted_anchors, measure_start + measure_length_ticks)
        offsets = (tick - measure_start for tick in sorted_anchors[first:end])
        subdivisions = slots_per_measure(measure_length_ticks, offsets)
        ticks_per_slot = measure_length_ticks // subdivisions
        assert ticks_per_slot * USC_TICKS_PER_BEAT % tl.res == 0, "row spacing off USC's tick grid"

        time_signature = beat_by_measure.get(measure)
        if time_signature is not None:
            if measure == 0 or time_signature != current_time_signature:
                lines.append("beat=%d/%d" % time_signature)
            current_time_signature = time_signature

        for slot in range(subdivisions):
            tick = measure_start + slot * ticks_per_slot
            if tick in bpm_change_at_tick:
                lines.append("t=%s" % _format_bpm(bpm_change_at_tick[tick]))
            lines.extend(camera_options.get(tick, ()))

            for side, lane in zip("lr", fx_lanes):
                if tick in lane.hold_start_set:
                    lines.append("fx-%s=" % side)
                if tick in lane.se_chip_ticks:
                    lines.append("fx-%s_se=clap;0" % side)

            for side, lane in zip("lr", laser_lanes):
                run = lane.run_starting_at(tick)
                if run is not None and run.width == 2:
                    lines.append("laserrange_%s=2x" % side)
                if use_curves and tick in lane.curve_ticks:
                    lines.append("laser_%s_curve=%s" % (side, _format_curve(lane.curve_ticks[tick])))

            bt_chars = "".join(lane.ksh_char_at(tick, BT_CHIP, BT_HOLD) for lane in bt_lanes)
            fx_chars = "".join(lane.ksh_char_at(tick, FX_CHIP, FX_HOLD) for lane in fx_lanes)
            laser_chars = "".join(lane.ksh_char_at(tick) for lane in laser_lanes)
            lines.append("%s|%s|%s%s" % (bt_chars, fx_chars, laser_chars, spin_tokens.get(tick, "")))

        lines.append("--")

    with open(out_path, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    return out_path


def _ksh_header(chart, bpm_changes, beat_changes, meta=None):
    meta = meta or {}
    base = os.path.splitext(os.path.basename(chart.path))[0]
    diff_suffix = base.rsplit("_", 1)[-1] if "_" in base else ""
    difficulty = meta.get("difficulty") or DIFF_MAP.get(diff_suffix, "infinite")

    bpms = sorted({b for _t, b in bpm_changes}) or [120.0]
    if len(bpms) == 1:
        tempo = _format_bpm(bpms[0])
    else:
        tempo = "%s-%s" % (_format_bpm(min(bpms)), _format_bpm(max(bpms)))
    num0, den0 = beat_changes[0][1:] if beat_changes else (4, 4)

    return [
        "title=%s" % meta.get("title", base),
        "artist=%s" % meta.get("artist", ""),
        "effect=%s" % meta.get("effect", ""),
        "jacket=%s" % meta.get("jacket", ""),
        "illustrator=%s" % meta.get("illustrator", ""),
        "difficulty=%s" % difficulty,
        "level=%s" % meta.get("level", "1"),
        "t=%s" % tempo,
        "to=0",
        "beat=%d/%d" % (num0, den0),
        "m=%s" % meta.get("m", "dummy.ogg"),
        "mvol=100",
        "o=0",
        "bg=desert",
        "layer=arrow",
        "po=%s" % meta.get("po", 0),
        "plength=%s" % meta.get("plength", 0),
        "total=0",
        "information=%s" % meta.get("information", ""),
        "icon=%s" % meta.get("icon", "../sdvx07.png"),
        "chokkakuvol=0",
        "chokkakuautovol=1",
        "filtertype=peak",
        "pfiltergain=0",
        "pfilterdelay=40",
        "ver=171",
        "--",
    ]


def build_arg_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("vox", help="path to a .vox chart")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--ksh-version", type=int, choices=(1, 2), default=1,
                    help="1 (default) writes every laser curve as interpolated points, which is "
                         "all KSM v1.xx can read. 2 re-fits each curve and writes it as a "
                         "laser_l_curve/laser_r_curve bezier over far fewer points - smoother and "
                         "closer to the vox shape, but KSM v1.xx ignores the option lines and "
                         "draws the remaining points straight. See specs/notes.md")
    ap.add_argument("--no-slam-gap", action="store_true",
                    help="place a genuine same-tick vox slam's landing point on the "
                         "very next free tick instead of ksh's standard 1/64-of-a-measure "
                         "gap (laser_curves.py's SLAM_GAP_FRAC). On by default, since the bare "
                         "next-free-tick placement renders as a near-invisible hairline "
                         "and can force a measure's grid down to near-native resolution "
                         "to fit just one point - see laser_curves.py's module docstring")
    ap.add_argument("--preview", action="store_true",
                    help="fill in po=/plength= by locating the song's _pre.s3v inside its "
                         ".s3v, both taken from the chart's own folder. Off by default: it "
                         "needs ffmpeg and the audio files, which a notes-only conversion "
                         "otherwise never touches. See ../audio/preview_offset.py")
    return ap


def _preview_header_fields(vox_path):
    import preview_offset

    folder = os.path.dirname(os.path.abspath(vox_path))
    got = preview_offset.measure_preview_window(os.path.join(folder, os.path.basename(folder) + ".s3v"))
    if got is None:
        print("preview: no offset found for %s - leaving po=0 plength=0" % os.path.basename(folder))
        return {}
    print("preview: po=%d plength=%d" % got)
    return {"po": got[0], "plength": got[1]}


def main():
    args = build_arg_parser().parse_args()
    out = args.output or os.path.splitext(os.path.basename(args.vox))[0] + ".ksh"
    slam_gap_frac = 0 if args.no_slam_gap else laser.SLAM_GAP_FRAC
    meta = _preview_header_fields(args.vox) if args.preview else None
    path = convert(args.vox, out, meta=meta, slam_gap_frac=slam_gap_frac,
                   ksh_version=args.ksh_version)
    print("wrote %s" % path)


if __name__ == "__main__":
    main()
