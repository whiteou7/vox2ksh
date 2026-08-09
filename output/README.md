# output/

Everything the scripts write. **Git-ignored** — only this file and `.gitkeep` are tracked.

Nothing in here is precious. If it takes up too much space, delete all of it; every file is regenerable from the game data plus `scripts/`. That is the point of the directory: no script writes next to itself, so cleaning up is always safe.

The one input that is *not* regenerable lives elsewhere on purpose — `scripts/audio/reference/kamui_goal.ogg`, the cabinet capture. Do not move it here.

## What tends to end up here

| path | what it is | regenerate with |
|---|---|---|
| `work/kamui_dry.wav` | The song's own audio, decoded from `.s3v`. | ffmpeg — see `HANDOFF.md` §5 |
| `work/goal.wav` | The cabinet capture, decoded from `reference/kamui_goal.ogg`. | ffmpeg — see `HANDOFF.md` §5 |
| `work/best.wav` | Whatever render is currently being scored. Copy a render here. | `apply_chart.py -o` |
| `work/gs/` | The `general_sampler` bank decoded to individual WAVs. | `python scripts/audio/s3p_decode.py ../data/sound/ver5/general_sampler.s3p output/work/gs` |
| `*_fx.ogg` | Chart renders (Vorbis by default; pass a `.wav` name for lossless). | `python scripts/audio/apply_chart.py <song folder> -o output/<name>.ogg` |

`work/` is created on demand by `_paths.ensure_work()`.

The three `.mp3` files currently here are carried over from the predecessor project as audible examples of the finished audio element: a full chart render and a before/after pair for the laser-slam SE layer. They are not needed by anything.
