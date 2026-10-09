#!/usr/bin/env python3
"""Converts buttons and lasers from .vox to the .ksh chart body (specs/notes.md). `--preview` fills po= and plength= from the song audio.

    python convert_notes.py <chart.vox> [-o out.ksh] [--ksh-version 1|2] [--preview]
"""

import argparse
import bisect
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared"))
import vox_parser as vox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import laser_curves as laser


BT_CHIP, BT_HOLD = "1", "2"
FX_CHIP, FX_HOLD = "2", "1"


class HoldLane:
    def __init__(self, notes):
        holds = sorted((n.tick, n.end_tick) for n in notes if n.is_hold)
        self.starts = [h[0] for h in holds]
        self.ends = [h[1] for h in holds]
        self.chips = set(n.tick for n in notes if not n.is_hold)
        self.sfx_chips = set(n.tick for n in notes if not n.is_hold and n.c2 > 0)

    def char_at(self, tick, chip_char, hold_char):
        if tick in self.chips:
            return chip_char
        i = bisect.bisect_right(self.starts, tick) - 1
        if i >= 0 and tick < self.ends[i]:
            return hold_char
        return "0"

    def hold_starting_at(self, tick):
        return tick in self.starts

    def anchors(self):
        out = set(self.chips)
        for s, e in zip(self.starts, self.ends):
            out.add(s)
            out.add(e)
        return out


class LaserLane:
    def __init__(self, runs):
        self.runs = sorted(runs, key=lambda r: r.start_tick)
        self.run_starts = [r.start_tick for r in self.runs]
        self.curve_ticks = self._build_curve_ticks()

    def _build_curve_ticks(self):
        out = {}
        for r in self.runs:
            for i, curve in enumerate(r.curves):
                if curve is None:
                    continue
                tick = r.points[i][0]
                if i > 0 and r.slam_after[i - 1]:
                    tick = r.points[i - 1][0]
                out.setdefault(tick, curve)
        return out

    def curve_at(self, tick):
        return self.curve_ticks.get(tick)

    def run_at(self, tick):
        i = bisect.bisect_right(self.run_starts, tick) - 1
        if i >= 0 and self.runs[i].start_tick <= tick <= self.runs[i].end_tick:
            return self.runs[i]
        return None

    def char_at(self, tick):
        r = self.run_at(tick)
        if r is None:
            return "-"
        ticks = [p[0] for p in r.points]
        j = bisect.bisect_left(ticks, tick)
        if j < len(ticks) and ticks[j] == tick:
            return laser.pos_to_char(r.points[j][1])
        return ":"

    def run_starting_at(self, tick):
        i = bisect.bisect_left(self.run_starts, tick)
        return self.runs[i] if i < len(self.runs) and self.runs[i].start_tick == tick else None

    def anchors(self):
        out = set()
        for r in self.runs:
            for (t, _v) in r.points:
                out.add(t)
        for a, b in zip(self.runs, self.runs[1:]):
            if b.start_tick - a.end_tick >= 2:
                out.add(a.end_tick + 1)
        return out


def measure_resolution(length, anchor_offsets):
    g = length
    for o in anchor_offsets:
        if 0 < o < length:
            g = math.gcd(g, o)
    if g <= 0:
        g = length
    return max(1, length // g)


DIFF_MAP = {"1n": "light", "2a": "challenge", "3e": "extended",
            "4i": "infinite", "5m": "infinite"}


def convert(vox_path, out_path, camera=False, meta=None, slam_gap_frac=laser.SLAM_GAP_FRAC,
            pretilt_fix=False, ksh_version=1):
    chart = vox.load(vox_path)
    tl = chart.tl

    curves = ksh_version >= 2
    bt_lanes = [HoldLane(notes) for notes in chart.bt]
    fx_lanes = [HoldLane(notes) for notes in chart.fx]
    laser_lanes = [LaserLane(laser.build_runs(pts, tl, slam_gap_frac=slam_gap_frac, curves=curves))
                   for pts in chart.laser]

    cam_opts = {}
    cam_spin = {}
    if camera:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "camera"))
        import camera_events as camera_mod
        for (t, value) in camera_mod.compute_tilt_events(chart, pretilt_fix=pretilt_fix):
            cam_opts.setdefault(t, []).append("tilt=" + value)
        for (t, line) in camera_mod.compute_zoom_events(chart):
            cam_opts.setdefault(t, []).append(line)
        for t, (_side, token) in camera_mod.compute_spin_tokens(chart).items():
            cam_spin[t] = token

    tight_runs = sum(1 for lane in laser_lanes for r in lane.runs if r.tight)
    if tight_runs:
        print("note: %d laser run(s) needed a sub-24th-note gap to keep their true "
              "shape (see laser_curves.py's docstring, point 3) - real, unavoidable "
              "given .ksh's grid" % tight_runs, file=sys.stderr)

    bpm_changes = []
    seen_bpm = None
    for (mm, bb, tt, bpm) in tl.bpms:
        tick = tl.abs_tick(mm, bb, tt)
        if bpm != seen_bpm:
            bpm_changes.append((tick, bpm))
            seen_bpm = bpm
    beat_changes = []
    for (mm, num, den) in tl.beats:
        beat_changes.append((mm, num, den))

    last_tick = 0
    for lane in bt_lanes + fx_lanes:
        if lane.ends:
            last_tick = max(last_tick, lane.ends[-1])
        if lane.chips:
            last_tick = max(last_tick, max(lane.chips))
    for lane in laser_lanes:
        for r in lane.runs:
            last_tick = max(last_tick, r.end_tick)
    if camera:
        if cam_opts:
            last_tick = max(last_tick, max(cam_opts))
        if cam_spin:
            last_tick = max(last_tick, max(cam_spin))
    last_measure, _ = tl.measure_of_tick(last_tick)

    bpm_by_measure = {}
    multi_bpm = len(set(b for _t, b in bpm_changes)) > 1
    for (tick, bpm) in bpm_changes if multi_bpm else bpm_changes[1:]:
        m, off = tl.measure_of_tick(tick)
        bpm_by_measure.setdefault(m, []).append((off, bpm))
    beat_by_measure = {mm: (num, den) for (mm, num, den) in beat_changes}

    lines = []
    lines.extend(_header(chart, bpm_changes, beat_changes, meta=meta))

    cur_num, cur_den = None, None

    for m in range(0, last_measure + 1):
        mlen = tl.measure_length(m)
        m_start = tl.measure_start_tick(m)

        anchors = set()
        for lane in bt_lanes + fx_lanes:
            anchors |= {t - m_start for t in lane.anchors()
                        if m_start <= t < m_start + mlen}
        for lane in laser_lanes:
            anchors |= {t - m_start for t in lane.anchors()
                        if m_start <= t < m_start + mlen}
        for (off, _bpm) in bpm_by_measure.get(m, []):
            anchors.add(off)
        if camera:
            anchors |= {t - m_start for t in cam_opts if m_start <= t < m_start + mlen}
            anchors |= {t - m_start for t in cam_spin if m_start <= t < m_start + mlen}

        res = measure_resolution(mlen, anchors)
        step = mlen // res

        if m in beat_by_measure:
            num, den = beat_by_measure[m]
            if m == 0 or (num, den) != (cur_num, cur_den):
                lines.append("beat=%d/%d" % (num, den))
            cur_num, cur_den = num, den

        bpm_here = {m_start + off: bpm for (off, bpm) in bpm_by_measure.get(m, [])}

        for k in range(res):
            tick = m_start + k * step
            if tick in bpm_here:
                lines.append("t=%s" % _fmt_bpm(bpm_here[tick]))
            if camera:
                for opt_line in cam_opts.get(tick, ()):
                    lines.append(opt_line)

            for li, lane in enumerate(fx_lanes):
                side = "l" if li == 0 else "r"

                if lane.hold_starting_at(tick):
                    lines.append("fx-%s=" % side)

                if tick in lane.sfx_chips:
                    lines.append("fx-%s_se=clap;0" % side)

            for li, lane in enumerate(laser_lanes):
                side = "l" if li == 0 else "r"
                run = lane.run_starting_at(tick)
                if run is not None and run.width == 2:
                    lines.append("laserrange_%s=2x" % side)
                if curves:
                    curve = lane.curve_at(tick)
                    if curve is not None:
                        lines.append("laser_%s_curve=%s" % (side, _fmt_curve(curve)))

            bt_chars = "".join(lane.char_at(tick, BT_CHIP, BT_HOLD) for lane in bt_lanes)
            fx_chars = "".join(lane.char_at(tick, FX_CHIP, FX_HOLD) for lane in fx_lanes)
            laser_chars = "".join(lane.char_at(tick) for lane in laser_lanes)
            spin_suffix = cam_spin.get(tick, "") if camera else ""
            lines.append("%s|%s|%s%s" % (bt_chars, fx_chars, laser_chars, spin_suffix))

        lines.append("--")

    with open(out_path, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    return out_path


def _fmt_bpm(bpm):
    s = "%.4f" % bpm
    s = s.rstrip("0").rstrip(".")
    return s if s else "0"


def _fmt_curve(curve):
    return "%.2f;%.2f" % curve


def _header(chart, bpm_changes, beat_changes, meta=None):
    meta = meta or {}
    base = os.path.splitext(os.path.basename(chart.path))[0]
    diff_suffix = base.rsplit("_", 1)[-1] if "_" in base else ""
    difficulty = meta.get("difficulty") or DIFF_MAP.get(diff_suffix, "infinite")

    bpms = sorted(set(b for _t, b in bpm_changes)) or [120.0]
    if len(bpms) == 1:
        t_val = _fmt_bpm(bpms[0])
    else:
        t_val = "%s-%s" % (_fmt_bpm(min(bpms)), _fmt_bpm(max(bpms)))
    num0, den0 = (beat_changes[0][1], beat_changes[0][2]) if beat_changes else (4, 4)

    h = [
        "title=%s" % meta.get("title", base),
        "artist=%s" % meta.get("artist", ""),
        "effect=%s" % meta.get("effect", ""),
        "jacket=%s" % meta.get("jacket", ""),
        "illustrator=%s" % meta.get("illustrator", ""),
        "difficulty=%s" % difficulty,
        "level=%s" % meta.get("level", "1"),
        "t=%s" % t_val,
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
    return h


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


def _preview_meta(vox_path):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "audio"))
    import preview_offset as preview

    folder = os.path.dirname(os.path.abspath(vox_path))
    s3v = os.path.join(folder, os.path.basename(folder) + ".s3v")
    got = preview.measure(s3v)
    if got is None:
        print("preview: no offset found for %s - leaving po=0 plength=0"
              % os.path.basename(folder))
        return {}
    print("preview: po=%d plength=%d" % got)
    return {"po": got[0], "plength": got[1]}


def main():
    args = build_arg_parser().parse_args()
    out = args.output or os.path.splitext(os.path.basename(args.vox))[0] + ".ksh"
    slam_gap_frac = 0 if args.no_slam_gap else laser.SLAM_GAP_FRAC
    meta = _preview_meta(args.vox) if args.preview else None
    path = convert(args.vox, out, meta=meta, slam_gap_frac=slam_gap_frac,
                    ksh_version=args.ksh_version)
    print("wrote %s" % path)


if __name__ == "__main__":
    main()
