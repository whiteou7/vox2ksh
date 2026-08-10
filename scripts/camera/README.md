# scripts/camera/

Scope: lane tilt, spin/swing, and top/bottom zoom - the `.vox` tracks that move the playfield rather than the notes on it (`zoom_side`/`center_split`/`rotation_deg`/etc. are out of scope - see [`specs/camera.md`](../../specs/camera.md)).

**Status: converter exists, several constants are documented approximations.** Read [`specs/camera.md`](../../specs/camera.md) first - it explains which pieces are solid (zoom sign/direction, spin kind/direction, the pretilt-cancellation pattern) and which are honest guesses (zoom scale factor, spin length for most `roll_type`s, the auto-tilt formula itself).

| file | what it does |
|---|---|
| `camera.py` | The conversion logic: `compute_tilt_events`, `compute_zoom_events`, `compute_spin_tokens`. Pure functions over a loaded `VoxChart`, no file I/O - every constant is commented with where it came from. |
| `convert.py` | CLI: `python convert.py <chart.vox> [-o out.ksh]`. Calls `../notes/convert.py`'s `convert(..., camera=True)`, which places `camera.py`'s events into the same grid it builds for notes/lasers. |
| `survey.py` | Walks all 8103 `.vox` charts, tabulates `#SPCONTROLER` control types and laser roll/swing distributions. `--locate <roll_types>` pinpoints exact chart/measure occurrences. |
| `correlate.py` | Matches every `scripts/shared/reference/ksh` pair to its `.vox` source and correlates vox camera data against the hand-charted ksh lines by tick. |
| `pretilt.py` | Measures the tick gaps around the pretilt-cancellation idiom (`tilt=0` before a laser run, `tilt=normal` once it starts) against laser-run boundaries. |

`../shared/vox.py`'s `VoxChart.camera` (`{"tilt": [...], "cam_rotx": [...], "cam_radi": [...]}`) is the parsed form everything here builds on.

Headline results, all in `specs/camera.md`: the reference `.ksh` conversions are hand-made, not derived from `.vox`, which is why the zoom scale factor is a per-song-varying approximation rather than an exact constant, and why tilt-intervention style varies so much chart to chart. Despite that, three things came out clean and are implemented with high confidence: zoom sign/direction, the roll-vs-swing -> full-vs-half-spin symbol mapping (100% match, 66/66), and the slam-direction -> clockwise/counterclockwise rule (also 100%, 66/66).
