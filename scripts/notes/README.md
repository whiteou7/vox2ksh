# scripts/notes/

Buttons and lasers: `.vox` -> `.ksh` chart body. Timing/metadata are just
enough to make that possible - see HANDOFF.md 3.1 for what's explicitly out
of scope (song/track metadata, every sound-fx parameter). Roll/swing (spin)
is out of scope here too - it's camera-domain, not notes.

| file | what it does |
|---|---|
| `convert.py` | The converter. `python convert.py <chart.vox> [-o out.ksh]`. BT/FX are a direct grid mapping (ticks are already integers on both sides); lasers go through `laser.py` first. Picks each measure's line resolution independently, via gcd over that measure's real events - always exact, never a resample. |
| `laser.py` | Vox's pre-interpolated laser curve -> the discrete points a `.ksh` grid can hold. Douglas-Peucker simplification + a minimum-spacing pass, documented in its own docstring - this is where all three of HANDOFF.md 3.1's named problems (width, continuity, the unrepresentable-32nd-slam limit) actually live. |
| `xcheck.py` | Structural crosscheck against `scripts/shared/reference/ksh` - note/hold/laser-point *counts* on both sides, not a text diff (these are hand conversions, not an oracle - see that folder's README). Matches every difficulty in every reference folder that has a corresponding `.vox`, the same name-matching `../audio/masscheck.py` uses - not one hand-picked chart per song. `python xcheck.py [-n N] [--only substr] [--worst N] [--csv out.csv]`. |

## Status

30 chart/difficulty pairs currently matched (every reference folder
`xcheck.py` can pair to a `data/music` chart, times every difficulty
present in that folder):

* BT chip: exact on 83% of charts, off by 1 on the rest. BT hold, FX chip,
  FX hold: exact on 97-100%. This is the ceiling for hand conversions -
  HANDOFF.md's "error might exist but pretty minor" shows up here as the
  occasional single note, on either side.
* Laser runs: exact on 97% of charts.
* Laser points (after decimation): mean absolute difference 24 points, on
  typical per-chart totals of 500-700 (~4%). No exact matches, and none
  expected - decimation approximates a curve's shape, it doesn't reproduce
  one specific charter's point choices. `laser.py`'s `RDP_TOL` is fit to all
  30 of these charts (swept and took the total point-count error's minimum -
  see its comment); re-sweep if `xcheck.py` picks up more references and the
  error drifts. `min_gap_frac=24` (the "1/24 of a measure" from
  HANDOFF.md 3.1) sits in a wide, stable optimum on the same sweep - moving
  off it in either direction gets worse, occasionally sharply for specific
  charts with very regular/periodic curves (a hard spacing threshold
  crossing a repeating gap admits or drops many of that one chart's points
  at once - not a bug, just how a threshold filter behaves on periodic
  input).
* **Fixed a real bug found against a chart outside the reference set**
  (`2393_alive_dadadaizu_5m.vox`, user-reported): a fast-but-continuous
  curve tail (a sine ease-in's sharp finish) could leave decimation's
  forward pass one point away from the run's true end with less than 1/24
  of a measure of room - landing exactly on ksh's 1/32 slam cutoff and
  rendering as an unintended slam. `_enforce_min_gap` now backs off the
  previous kept point first when that alone clears the violation, which it
  does for an ordinary curve tail. Across all 30 reference charts, every
  `Run.tight` case turned out to be this - zero remain after the fix (was
  several dozen instances before).
* Bars: exact on 77% of charts, short by 1-3 measures on the rest.
  Deliberately NOT padded to vox's `#END POSITION` - see the comment above
  `last_tick` in convert.py, that field is the arcade chart's official end
  and routinely runs measures past the last real event with nothing but
  silence between. `crystalia/mxm.ksh` is the one 3-measure outlier: its vox
  has `#SPCONTROLER` camera movement (`CAM_Radi`, `Tilt`) continuing to
  measure 179, well past the last note, and the reference conversion kept
  the chart open for it. Worth remembering once the camera element starts -
  chart length may need to grow again once camera data is in play.

`shared/vox.py`'s `read_sections` had a real bug caught by this: it closed
the current section on any line *starting with* "#END", which also matches
the opening tag "#END POSITION" and silently dropped its one data line.
Fixed - now closes only on an exact "#END" token. `apply_chart.py` has its
own copy of the same parser with the same bug, unfixed - it doesn't appear
to read `#END POSITION` for anything, so it's likely benign there, but
worth knowing if that file is ever touched again.

## Known, accepted limitations (not bugs)

* **Sub-1/24 real movements.** A vox curve can have a genuine (non-slam)
  bend closer together than the minimum spacing this converter enforces,
  with no earlier point to back off to either (see `_enforce_min_gap`'s
  docstring). `laser.py`'s `Run.tight` flags a run when this happens;
  `convert.py` prints a count. There is no `.ksh` construct that does
  better - see `laser.py`'s docstring, point 3. Not observed in any of the
  30 reference charts as of the backing-off fix above; kept as a fallback
  for whatever chart eventually has one.
* **1-tick gaps between two laser runs.** Needed to fit an explicit '-' row
  between two runs that end/start one vox tick apart; there's no room for a
  third distinct row at that spacing. Not observed in the 30 reference
  charts, only reasoned about - see `LaserLane.anchors()` in convert.py.

## Not done, and deliberately out of scope here

* **Roll/swing** (vox `#TRACK1`/`#TRACK8` C3 -> `.ksh`'s spin markers) -
  belongs to the camera element, not here.
* **`#TRACK AUTO TAB`** (FX-hold effects applied to lasers) - not read at
  all. Out of scope per the "sound-fx doesn't matter yet" direction, but
  flagging in case it ever needs the note-length/timing side of that track
  independent of the effect it names.
* Metadata is all placeholder (title = the vox filename, everything else
  blank/default) and `m=dummy.ogg` - as directed.
