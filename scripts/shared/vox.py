#!/usr/bin/env python3
"""
.vox parsing, shared by every element.

Lifted out of ../audio/apply_chart.py (HANDOFF.md 3.1) and generalised: that
file only needed BPM/time-signature -> seconds for the audio render, this
also exposes the note tracks (BT/FX/laser) as structured data for the notes
element, plus tick <-> measure/beat helpers neither caller needed before.

Terminology matches specs/vox_format.md throughout - "tick" here always
means an absolute 0-indexed cell count from the start of the chart, at
BEAT_RESOLUTION cells per 1/4 note (48 unless #BEAT RESOLUTION says otherwise).
"""

import os

DEFAULT_BEAT_RESOLUTION = 48   # cells per 1/4 note; max cell seen in any chart is res-1


# --------------------------------------------------------------------------
# raw section parsing
# --------------------------------------------------------------------------

def read_sections(path):
    """.vox file -> {tag: [line, ...]}. Tags keep their leading '#'."""
    txt = open(path, "r", encoding="cp932", errors="replace").read()
    out, cur = {}, None
    for line in txt.splitlines():
        ls = line.strip()
        if ls.startswith("//"):
            continue
        # The closing tag is exactly "#END" - startswith() alone also
        # matches the *opening* tag "#END POSITION" and silently swallows
        # it (and its one data line) as a bogus close. Comments can trail
        # a tag on the same line, so compare the token before any "//".
        token = ls.split("//", 1)[0].strip()
        if token == "#END":
            cur = None
            continue
        if ls.startswith("#"):
            cur = ls
            out.setdefault(cur, [])
            continue
        if cur is not None and ls:
            out[cur].append(ls)
    return out


def parse_pos(s):
    """'004,02,27' -> (measure0, beat0, cell), all 0-indexed."""
    m, b, t = (int(x) for x in s.split(","))
    return (m - 1, b - 1, t)


def parse_commasep(line):
    """'1,\t90.00,\t400.00' -> [1.0, 90.0, 400.0]. Trailing commas ignored."""
    parts = [p.strip() for p in line.split(",") if p.strip() != ""]
    return [float(p) for p in parts]


# --------------------------------------------------------------------------
# Timeline: measure/beat/cell <-> tick <-> seconds
# --------------------------------------------------------------------------

class Timeline:
    """Tick <-> seconds and tick <-> measure/beat/cell, honouring BPM and
    time-signature changes. `res` is the chart's #BEAT RESOLUTION (cells
    per 1/4 note); ticks throughout this module are in that unit.
    """

    def __init__(self, sec, res=DEFAULT_BEAT_RESOLUTION):
        self.res = res

        self.beats = []          # (measure0, num, den), sorted by measure0
        for line in sec.get("#BEAT INFO", []):
            f = line.split()
            mm = parse_pos(f[0])[0]
            self.beats.append((mm, int(f[1]), int(f[2])))
        if not self.beats:
            self.beats = [(0, 4, 4)]
        self.beats.sort()

        self.bpms = []           # (measure0, beat0, cell, bpm)
        for line in sec.get("#BPM INFO", []):
            f = line.split()
            mm, bb, tt = parse_pos(f[0])
            self.bpms.append((mm, bb, tt, float(f[1])))
        if not self.bpms:
            self.bpms = [(0, 0, 0, 120.0)]
        self.bpms.sort()

        # cumulative ticks at the start of each measure, and each measure's
        # own tick length - computed far enough to cover any real chart.
        self._measure_tick = {}
        self._measure_len = {}
        acc, mi = 0, 0
        for meas in range(0, 4000):
            while mi + 1 < len(self.beats) and self.beats[mi + 1][0] <= meas:
                mi += 1
            self._measure_tick[meas] = acc
            num, den = self.beats[mi][1], self.beats[mi][2]
            length = int(round(num * (4.0 / den) * self.res))
            self._measure_len[meas] = length
            acc += length
        self._last_measure_tick = acc

        # BPM changes as absolute ticks, plus elapsed seconds at each
        self._bpm_pts = []
        for (mm, bb, tt, bpm) in self.bpms:
            self._bpm_pts.append((self.abs_tick(mm, bb, tt), bpm))
        self._bpm_pts.sort()
        self._bpm_sec = [0.0]
        for i in range(1, len(self._bpm_pts)):
            dt = self._bpm_pts[i][0] - self._bpm_pts[i - 1][0]
            spb = 60.0 / self._bpm_pts[i - 1][1]
            self._bpm_sec.append(self._bpm_sec[-1] + dt / self.res * spb)

    # ---- measure/beat/cell <-> tick ----

    def abs_tick(self, m0, b0, t):
        return self._measure_tick[m0] + b0 * self.res + t

    def tick_of(self, poss):
        return self.abs_tick(*parse_pos(poss))

    def measure_start_tick(self, measure0):
        if measure0 in self._measure_tick:
            return self._measure_tick[measure0]
        # fall back to extrapolating with the last known time signature
        num, den = self.beats[-1][1], self.beats[-1][2]
        length = int(round(num * (4.0 / den) * self.res))
        base_m = max(self._measure_tick)
        return self._measure_tick[base_m] + (measure0 - base_m) * length

    def measure_length(self, measure0):
        if measure0 in self._measure_len:
            return self._measure_len[measure0]
        num, den = self.beats[-1][1], self.beats[-1][2]
        return int(round(num * (4.0 / den) * self.res))

    def measure_of_tick(self, tick):
        """tick -> (measure0, offset_within_measure)."""
        meas = 0
        for m, tk in sorted(self._measure_tick.items()):
            if tk <= tick:
                meas = m
            else:
                break
        return meas, tick - self._measure_tick[meas]

    def timesig_at_measure(self, measure0):
        num, den = self.beats[0][1], self.beats[0][2]
        for (mm, n, d) in self.beats:
            if mm <= measure0:
                num, den = n, d
            else:
                break
        return num, den

    def bpm_at(self, tick):
        bpm = self._bpm_pts[0][1]
        for (tk, v) in self._bpm_pts:
            if tk <= tick:
                bpm = v
            else:
                break
        return bpm

    def beats_per_measure(self, tick):
        meas, _ = self.measure_of_tick(tick)
        num, den = self.timesig_at_measure(meas)
        return num * (4.0 / den)

    def seconds(self, tick):
        i = 0
        for k, (tk, _) in enumerate(self._bpm_pts):
            if tk <= tick:
                i = k
            else:
                break
        tk, bpm = self._bpm_pts[i]
        return self._bpm_sec[i] + (tick - tk) / self.res * (60.0 / bpm)


# --------------------------------------------------------------------------
# note tracks
# --------------------------------------------------------------------------

class ChipHold:
    """One BT or FX note. `length` is in ticks; 0 = chip."""
    __slots__ = ("tick", "length", "c2", "c3")

    def __init__(self, tick, length, c2=0, c3=None):
        self.tick = tick
        self.length = length
        self.c2 = c2      # BT: unused(?). FX chip: sample id. FX hold: fx-def index (2-indexed)
        self.c3 = c3      # optional cells-per-chain

    @property
    def is_hold(self):
        return self.length > 0

    @property
    def end_tick(self):
        return self.tick + self.length


class LaserPoint:
    """One #TRACK1/#TRACK8 row, already resolved to an absolute tick and a
    0..1 position (v10's 0..127 integer range is rescaled here so callers
    never have to check the format version).
    """
    __slots__ = ("tick", "pos", "node_type", "roll_type", "effect",
                 "width", "curve_type", "roll_length", "cells_per_chain")

    def __init__(self, tick, pos, node_type, roll_type, effect, width,
                 curve_type, roll_length, cells_per_chain):
        self.tick = tick
        self.pos = pos
        self.node_type = node_type      # 0 continue, 1 start, 2 end
        self.roll_type = roll_type
        self.effect = effect
        self.width = width              # 1 normal, 2 wide
        self.curve_type = curve_type
        self.roll_length = roll_length
        self.cells_per_chain = cells_per_chain


def parse_bt_fx_track(sec, tag):
    """#TRACK2..7 -> sorted list of ChipHold."""
    out = []
    for line in sec.get(tag, []):
        f = line.split()
        if len(f) < 2:
            continue
        tick = _tick_from(f[0], sec)
        length = int(f[1])
        c2 = int(f[2]) if len(f) > 2 else 0
        c3 = int(f[3]) if len(f) > 3 else None
        out.append(ChipHold(tick, length, c2, c3))
    out.sort(key=lambda n: n.tick)
    return out


def parse_laser_track(sec, tag, version):
    """#TRACK1/#TRACK8 -> sorted list of LaserPoint."""
    out = []
    for line in sec.get(tag, []):
        f = line.split()
        if len(f) < 7:
            continue
        tick = _tick_from(f[0], sec)
        pos = float(f[1])
        if version < 12 or pos > 1.0:
            pos = pos / 127.0
        node_type = int(f[2])
        roll_type = int(f[3])
        effect = int(f[4])
        width = int(f[5])
        # C6 unused
        curve_type = int(f[7]) if len(f) > 7 else 0
        roll_length = int(f[8]) if len(f) > 8 else 0
        cells_per_chain = int(f[9]) if len(f) > 9 else None
        out.append(LaserPoint(tick, pos, node_type, roll_type, effect, width,
                               curve_type, roll_length, cells_per_chain))
    out.sort(key=lambda p: p.tick)
    return out


# tiny cache so _tick_from doesn't rebuild a Timeline per call; callers that
# already have one should prefer VoxChart, which does this once.
def _tick_from(poss, sec):
    tl = sec.get("__timeline__")
    if tl is None:
        tl = Timeline(sec, sec.get("__res__", DEFAULT_BEAT_RESOLUTION))
        sec["__timeline__"] = tl
    return tl.tick_of(poss)


# --------------------------------------------------------------------------
# whole-chart convenience wrapper
# --------------------------------------------------------------------------

BT_TAGS = ["#TRACK3", "#TRACK4", "#TRACK5", "#TRACK6"]   # BT-A..D
FX_TAGS = ["#TRACK2", "#TRACK7"]                          # FX-L, FX-R
LASER_TAGS = ["#TRACK1", "#TRACK8"]                       # laser-L, laser-R


class VoxChart:
    def __init__(self, path):
        self.path = path
        self.sec = read_sections(path)
        self.version = int((self.sec.get("#FORMAT VERSION") or ["10"])[0].strip())
        res_lines = self.sec.get("#BEAT RESOLUTION")
        self.res = int(res_lines[0].strip()) if res_lines else DEFAULT_BEAT_RESOLUTION
        self.sec["__res__"] = self.res
        self.tl = Timeline(self.sec, self.res)
        self.sec["__timeline__"] = self.tl

        self.bt = [parse_bt_fx_track(self.sec, t) for t in BT_TAGS]
        self.fx = [parse_bt_fx_track(self.sec, t) for t in FX_TAGS]
        self.laser = [parse_laser_track(self.sec, t, self.version) for t in LASER_TAGS]

        end = self.sec.get("#END POSITION")
        self.end_tick = self.tl.tick_of(end[0]) if end else self._infer_end_tick()

    def _infer_end_tick(self):
        last = 0
        for lst in self.bt + self.fx:
            for n in lst:
                last = max(last, n.end_tick)
        for lst in self.laser:
            for p in lst:
                last = max(last, p.tick)
        return last


def load(path):
    return VoxChart(path)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        raise SystemExit("usage: vox.py <chart.vox>")
    c = load(sys.argv[1])
    print("version", c.version, "resolution", c.res, "end_tick", c.end_tick)
    for i, lst in enumerate(c.bt):
        print("BT-%s: %d notes" % ("ABCD"[i], len(lst)))
    for i, lst in enumerate(c.fx):
        print("FX-%s: %d notes" % ("LR"[i], len(lst)))
    for i, lst in enumerate(c.laser):
        print("laser-%s: %d points" % ("LR"[i], len(lst)))
