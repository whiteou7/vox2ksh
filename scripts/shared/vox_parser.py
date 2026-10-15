#!/usr/bin/env python3
"""Parser for .vox charts (formats 10, 12 and 13). Camera control tracks end up in VoxChart.camera, and laser points expose roll_type, roll_length, cells_per_chain and unknown_c8, resolved per format version.
"""

import bisect
from dataclasses import dataclass
from functools import cached_property

DEFAULT_BEAT_RESOLUTION = 48
# Measures past this are extrapolated from the last time signature.
TABLE_MEASURES = 4000


def read_sections(path):
    with open(path, "r", encoding="cp932", errors="replace") as f:
        lines = f.read().splitlines()
    sections, current_tag = {}, None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if stripped.split("//", 1)[0].strip() == "#END":
            current_tag = None
        elif stripped.startswith("#"):
            current_tag = stripped
            sections.setdefault(current_tag, [])
        elif current_tag is not None and stripped:
            sections[current_tag].append(stripped)
    return sections


def parse_position(position):
    measure, beat, cell = (int(x) for x in position.split(","))
    return (measure - 1, beat - 1, cell)


class Timeline:
    """Maps measure,beat,cell positions to absolute ticks and ticks to seconds. Measures are 0-based."""

    def __init__(self, sections, res=DEFAULT_BEAT_RESOLUTION):
        self.res = res

        self.beats = sorted(
            (parse_position(fields[0])[0], int(fields[1]), int(fields[2]))
            for fields in (line.split() for line in sections.get("#BEAT INFO", [])))
        if not self.beats:
            self.beats = [(0, 4, 4)]

        self.bpms = sorted(
            parse_position(fields[0]) + (float(fields[1]),)
            for fields in (line.split() for line in sections.get("#BPM INFO", [])))
        if not self.bpms:
            self.bpms = [(0, 0, 0, 120.0)]

        self._measure_tick = []
        self._measure_cpb = []
        self._measure_len = []
        tick, beat_index = 0, 0
        for measure in range(TABLE_MEASURES):
            while beat_index + 1 < len(self.beats) and self.beats[beat_index + 1][0] <= measure:
                beat_index += 1
            numerator, denominator = self.beats[beat_index][1], self.beats[beat_index][2]
            cells_per_beat = self._cells_for_denominator(denominator)
            self._measure_tick.append(tick)
            self._measure_cpb.append(cells_per_beat)
            self._measure_len.append(numerator * cells_per_beat)
            tick += numerator * cells_per_beat

        # (tick, bpm) for every tempo change, with the elapsed seconds at each.
        self.bpm_pts = sorted((self.tick_at(measure, beat, cell), bpm)
                              for (measure, beat, cell, bpm) in self.bpms)
        self._bpm_ticks = [change_tick for change_tick, _ in self.bpm_pts]
        self._bpm_sec = [0.0]
        for (previous_tick, bpm), (next_tick, _) in zip(self.bpm_pts, self.bpm_pts[1:]):
            self._bpm_sec.append(self._bpm_sec[-1] + (next_tick - previous_tick) / self.res * (60.0 / bpm))

    def _cells_for_denominator(self, denominator):
        return int(round((4.0 / denominator) * self.res))

    @staticmethod
    def _in_measure_table(measure0):
        return 0 <= measure0 < TABLE_MEASURES

    def tick_at(self, measure0, beat0, cell):
        return self.measure_start_tick(measure0) + beat0 * self.cells_per_beat(measure0) + cell

    def tick_of_position(self, position):
        return self.tick_at(*parse_position(position))

    def measure_start_tick(self, measure0):
        if self._in_measure_table(measure0):
            return self._measure_tick[measure0]
        last = TABLE_MEASURES - 1
        return self._measure_tick[last] + (measure0 - last) * self.measure_length(measure0)

    def measure_length(self, measure0):
        if self._in_measure_table(measure0):
            return self._measure_len[measure0]
        numerator, denominator = self.beats[-1][1], self.beats[-1][2]
        return numerator * self._cells_for_denominator(denominator)

    def cells_per_beat(self, measure0):
        if self._in_measure_table(measure0):
            return self._measure_cpb[measure0]
        return self._cells_for_denominator(self.beats[-1][2])

    def measure_and_offset(self, tick):
        meas = max(0, bisect.bisect_right(self._measure_tick, tick) - 1)
        return meas, tick - self._measure_tick[meas]

    def timesig_at_measure(self, measure0):
        signature = self.beats[0][1:]
        for (measure, numerator, denominator) in self.beats:
            if measure > measure0:
                break
            signature = (numerator, denominator)
        return signature

    def bpm_at(self, tick):
        return self.bpm_pts[self._tempo_index(tick)][1]

    def beats_per_measure_at(self, tick):
        numerator, denominator = self.timesig_at_measure(self.measure_and_offset(tick)[0])
        return numerator * (4.0 / denominator)

    def seconds_at(self, tick):
        i = self._tempo_index(tick)
        change_tick, bpm = self.bpm_pts[i]
        return self._bpm_sec[i] + (tick - change_tick) / self.res * (60.0 / bpm)

    def _tempo_index(self, tick):
        return max(0, bisect.bisect_right(self._bpm_ticks, tick) - 1)


@dataclass(slots=True, eq=False)
class ChipHold:
    tick: int
    length: int
    c2: int = 0
    c3: int = None

    @property
    def is_hold(self):
        return self.length > 0

    @property
    def end_tick(self):
        return self.tick + self.length


@dataclass(slots=True, eq=False)
class LaserPoint:
    tick: int
    pos: float
    node_type: int
    roll_type: int
    effect: int
    width: int
    curve_type: int
    roll_length: int
    cells_per_chain: int
    unknown_c8: int = 0


@dataclass(slots=True, eq=False)
class CameraSeg:
    tick: int
    length: int
    start: float
    end: float
    node_type: int
    c2: int = 2

    @property
    def end_tick(self):
        return self.tick + self.length


def parse_button_track(sections, tl, tag):
    out = []
    for line in sections.get(tag, []):
        fields = line.split()
        if len(fields) < 2:
            continue
        c2 = int(fields[2]) if len(fields) > 2 else 0
        c3 = int(fields[3]) if len(fields) > 3 else None
        out.append(ChipHold(tl.tick_of_position(fields[0]), int(fields[1]), c2, c3))
    out.sort(key=lambda n: n.tick)
    return out


def parse_laser_track(sections, tl, tag, version):
    out = []
    for line in sections.get(tag, []):
        fields = line.split()
        if len(fields) < 7:
            continue
        pos = float(fields[1])
        if version < 12 or pos > 1.0:
            pos = pos / 127.0

        def column(index):
            return int(fields[index]) if len(fields) > index else None

        # v13 inserts one unknown column before the roll length.
        shift = 1 if version >= 13 else 0
        out.append(LaserPoint(
            tick=tl.tick_of_position(fields[0]), pos=pos, node_type=int(fields[2]), roll_type=int(fields[3]),
            effect=int(fields[4]), width=int(fields[5]), curve_type=column(7) or 0,
            roll_length=column(8 + shift) or 0, cells_per_chain=column(9 + shift),
            unknown_c8=(column(8) or 0) if shift else 0))
    out.sort(key=lambda p: p.tick)
    return out


def parse_camera_segments(sections, tl, control_type):
    """Rows of one control type from #SPCONTROLER and #LOCKED_SPCONTROLER, which the game reads alike. Fields split on any whitespace, as the game's sscanf does, so an empty field (two tabs) is skipped. BIL_RotZ values carry a `d` prefix (degrees)."""
    out = []
    for line in sections.get("#SPCONTROLER", []) + sections.get("#LOCKED_SPCONTROLER", []):
        fields = line.split()
        if len(fields) < 6 or fields[1] != control_type:
            continue
        node_type = int(float(fields[6].lstrip("d"))) if len(fields) > 6 else 0
        out.append(CameraSeg(tl.tick_of_position(fields[0]), int(float(fields[3])),
                             float(fields[4].lstrip("d")), float(fields[5].lstrip("d")), node_type, int(float(fields[2]))))
    out.sort(key=lambda s: s.tick)
    return out


def parse_tilt_modes(sections, tl):
    """(tick, mode) rows of #TILT MODE INFO, in time order."""
    rows = [(tl.tick_of_position(fields[0]), int(fields[1]))
            for fields in (line.split() for line in sections.get("#TILT MODE INFO", [])) if len(fields) >= 2]
    rows.sort(key=lambda row: row[0])
    return rows


BT_TAGS = ["#TRACK3", "#TRACK4", "#TRACK5", "#TRACK6"]
FX_TAGS = ["#TRACK2", "#TRACK7"]
LASER_TAGS = ["#TRACK1", "#TRACK8"]


class VoxChart:
    """One parsed chart. `sec` keeps the raw sections for the tags this parser does not interpret."""

    def __init__(self, path):
        self.path = path
        self.sec = read_sections(path)
        self.version = int((self.sec.get("#FORMAT VERSION") or ["10"])[0].strip())
        res_lines = self.sec.get("#BEAT RESOLUTION")
        self.res = int(res_lines[0].strip()) if res_lines else DEFAULT_BEAT_RESOLUTION
        self.tl = Timeline(self.sec, self.res)

        self.bt = [parse_button_track(self.sec, self.tl, t) for t in BT_TAGS]
        self.fx = [parse_button_track(self.sec, self.tl, t) for t in FX_TAGS]
        self.laser = [parse_laser_track(self.sec, self.tl, t, self.version) for t in LASER_TAGS]

        end_position = self.sec.get("#END POSITION")
        self.end_tick = self.tl.tick_of_position(end_position[0]) if end_position else self._infer_end_tick()

    @cached_property
    def camera(self):
        """Tilt, zoom-top, zoom-bottom and BIL_RotZ segments, and the (tick, mode) rows of #TILT MODE INFO. Parsed on first use, since only the camera converter reads them."""
        return {
            "tilt": parse_camera_segments(self.sec, self.tl, "Tilt"),
            "cam_rotx": parse_camera_segments(self.sec, self.tl, "CAM_RotX"),
            "cam_radi": parse_camera_segments(self.sec, self.tl, "CAM_Radi"),
            "bil_rotz": parse_camera_segments(self.sec, self.tl, "BIL_RotZ"),
            "tilt_mode": parse_tilt_modes(self.sec, self.tl),
        }

    def _infer_end_tick(self):
        holds = [n.end_tick for track in self.bt + self.fx for n in track]
        points = [p.tick for track in self.laser for p in track]
        return max(holds + points, default=0)


def load(path):
    return VoxChart(path)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        raise SystemExit("usage: vox_parser.py <chart.vox>")
    c = load(sys.argv[1])
    print("version", c.version, "resolution", c.res, "end_tick", c.end_tick)
    for i, lst in enumerate(c.bt):
        print("BT-%s: %d notes" % ("ABCD"[i], len(lst)))
    for i, lst in enumerate(c.fx):
        print("FX-%s: %d notes" % ("LR"[i], len(lst)))
    for i, lst in enumerate(c.laser):
        print("laser-%s: %d points" % ("LR"[i], len(lst)))
    for name, lst in c.camera.items():
        print("%s: %d rows" % (name, len(lst)))
