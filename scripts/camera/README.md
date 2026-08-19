# scripts/camera/

Scope: lane tilt, spin/swing, and top/bottom zoom - the `.vox` tracks that move the playfield rather than the notes on it (`zoom_side`/`center_split`/`rotation_deg`/etc. are out of scope - see [`specs/camera.md`](../../specs/camera.md)).

**Status: converter exists. Zoom sign/direction and spin kind/direction are solid; spin length and the zoom scale factor are approximations.** Read [`specs/camera.md`](../../specs/camera.md) first - it explains which pieces are solid and which are honest guesses. **Pretilt (KSM tilting in anticipation of an upcoming laser) is out of scope by direction**: it's triggered by any laser at all, not something the chart data can selectively detect, so it's a game-engine problem rather than a `.vox` -> `.ksh` mapping problem - this converter doesn't attempt to cancel or reproduce it. See specs/camera.md's "Tilt" section.

**Next task, by direction (see [`specs/camera.md`](../../specs/camera.md), "Spin/swing: length")**: re-derive spin length for all seven `roll_type` values from scratch, by regression against `scripts/shared/reference/ksh`'s hand charts - not by trusting `vox_format.md`'s inherited per-type default-duration names, which are already known wrong for at least two types. Treat the vox spec as a hypothesis to verify, the same way the kind mapping and direction rule were independently confirmed at 100% each, rather than assumed.

| file | what it does |
|---|---|
| `camera.py` | The conversion logic: `compute_tilt_events`, `compute_zoom_events`, `compute_spin_tokens`. Pure functions over a loaded `VoxChart`, no file I/O - every constant is commented with where it came from. |
| `convert.py` | CLI: `python convert.py <chart.vox> [-o out.ksh]`. Calls `../notes/convert.py`'s `convert(..., camera=True)`, which places `camera.py`'s events into the same grid it builds for notes/lasers. |
| `survey.py` | Walks all 8103 `.vox` charts, tabulates `#SPCONTROLER` control types and laser roll/swing distributions. `--locate <roll_types>` pinpoints exact chart/measure occurrences. |
| `correlate.py` | Matches every `scripts/shared/reference/ksh` pair to its `.vox` source and correlates vox camera data against the hand-charted ksh lines by tick - the tool the next spin-length task should build on. |

`../shared/vox.py`'s `VoxChart.camera` (`{"tilt": [...], "cam_rotx": [...], "cam_radi": [...]}`) is the parsed form everything here builds on; laser points additionally expose `.roll_type`, `.roll_length`, `.cells_per_chain` and `.unknown_c8`. The last three are version-resolved: the length is `C8` up to format 12 and `C9` from 13, cells-per-chain sits one column to its right, and `.unknown_c8` is the v13-only column that shift introduced. Read the column *quantity*, never a fixed index.

Headline results, all in `specs/camera.md`: the reference `.ksh` conversions are hand-made, not derived from `.vox`, which is why the zoom scale factor is a per-song-varying approximation rather than an exact constant, and why tilt-intervention style varies so much chart to chart. Despite that, two things came out clean and are implemented with high confidence: zoom sign/direction, and both the roll-vs-swing -> full-vs-half-spin symbol mapping and the slam-direction -> clockwise/counterclockwise rule (100% match, 66/66, against the reference set).

`vox_format.md`'s format-13 material is this project's own survey of a newer vox chart format (postdates the inherited community notes) - relevant here because it's where the roll-length column shift was found: format 13 inserted a column after the curve type and pushed the length from `C8` to `C9`. That was first read as a `roll_type=6`/`7`-only quirk and is now settled, from the game's own row parser, as applying to every roll type - see `camera.md`'s "Which column holds the length". Format-13 charts only ship in update folders, so surveying for them needs `survey.py --root`.

Earlier work here tried to find a pretilt triggering condition (`pretilt.py`, since removed, plus a hand-built `.ksh` test chart that's currently `git stash`ed) before concluding it's not a chart-side problem at all - see specs/camera.md for the full history if picking that back up.
