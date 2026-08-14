# The notes element — `.vox` buttons/lasers → `.ksh` chart body

Implementation: [`../scripts/notes/`](../scripts/notes/). Formats: [`vox_format.md`](vox_format.md), [`ksh_format.md`](ksh_format.md).

## Scope

BT/FX/laser notes, plus just enough BPM/time-signature to build the grid. Out of scope: all metadata (placeholders), every sound-fx parameter (already in the audio track), roll/swing (camera element - see `camera.md`), `#TRACK AUTO TAB`.

## Buttons

Direct grid mapping - vox ticks are always a whole multiple of whatever line count ksh uses, so this is exact. Each measure's line count is picked independently via gcd over that measure's real events. BT: `1` chip / `2` hold. FX: `2` chip / `1` hold (swapped vs BT per `ksh_format.md`). Chart length is the last real event, not vox's `#END POSITION` (which is the arcade chart's official end and often runs measures past the last note into silence).

## Lasers

Vox's laser tracks are pre-sampled curves (as fine as 1/64 of a measure), and ksh only has discrete points joined by `:` or a slam - so every curve gets decimated (Douglas-Peucker + a minimum-spacing pass at 1/24 of a measure) before it's written. Three problems, all in `laser.py`:

* **Width** - vox's normal/wide flag maps straight onto `laserrange_l`/`laserrange_r=2x`.
* **Continuity** - decimation must never leave two non-slam points closer than 1/24 of a measure, or ksh's engine reads the movement as an unintended slam (its own cutoff is 1/32).
* **Genuine same-tick slams** - kept exactly, including when the slam sits on a run *boundary* rather than inside one run's points. By default the end lands `SLAM_GAP_FRAC` (1/64 of the local measure) after the start, matching hand-charted slam width, instead of the bare next free tick (`slam_gap_frac=0`, CLI `--no-slam-gap`, GUI "Standard slam gap" checkbox); a dense enough chain (8 slams to a beat is the densest seen) can leave less than that much room, in which case the end just backs off to one tick before the collision.
* **The unrepresentable 32nd slam** - accepted as a real format limit when unavoidable, flagged via `Run.tight` rather than silently eaten.

## Crosscheck

`xcheck.py` matches every reference chart it can (30 pairs currently, same name-matching as `audio/masscheck.py`) and compares note/hold/laser-point counts, not text. BT/FX/laser-run counts match almost exactly; laser points land within ~4% mean (curve decimation approximates a shape, it isn't meant to reproduce one charter's exact point choices). See `RDP_TOL`/`min_gap_frac` in `laser.py` for the tuned constants.

## Bugs found and fixed

1. `shared/vox.py` dropped `#END POSITION`'s data (an `#END`-prefix check also matched that opening tag).
2. A fast curve tail could land its last kept point exactly on ksh's slam cutoff, rendering an unintended slam.
3. A same-tick slam landing on a run *boundary* (rather than inside one run) lost its true endpoint entirely, drawing a diagonal instead of a vertical drop.
4. The min-gap pass could keep a near-extremum instead of the true peak/trough, shifting turning points a few ticks early. Took three attempts to get right without regressing the 30-chart aggregate - see git history / `laser.py` comments for the two broken interim versions if this needs revisiting.
5. A genuine same-tick slam's end used to land on the bare next free tick - technically valid but a near-invisible hairline next to a hand-charted slam, and it forced that measure's grid down to near-native resolution just to place one point. Switched the default to a fixed 1/64-of-a-measure gap (`SLAM_GAP_FRAC`); the first version of this only looked ahead within the same run for a collision, so a run whose *own last point* was a slam could land its end on or past the *next run's* start tick, silently swallowing the one-tick gap `LaserLane.anchors()` needs to keep two runs visually distinct - found via the 649-chart aggregate (`gryphone/mxm.ksh`'s laser-run count went 204→155). Fixed by also checking the next run's true start tick, not just the next point in the current run.

All five found against charts outside the matched reference set; all verified against the full aggregate (649 charts as of this writing, up from the original 30 - see `reverse-engineering-corpus-scoring` in project memory) before being called fixed.
