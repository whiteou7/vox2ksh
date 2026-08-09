# scripts/

| directory | contents |
|---|---|
| [`shared/`](shared/) | Binary-analysis toolkit and path resolution. Element-agnostic. |
| [`audio/`](audio/) | DSP reimplementation, chart renderer, calibration harness. | 
| [`notes/`](notes/) | BT/FX/laser → `.ksh` chart body. |
| [`camera/`](camera/) | Lane tilt/spin/zoom/roll. |

## Rules 

**No hard-coded machine paths.** Everything resolves through [`shared/_paths.py`](shared/_paths.py), which derives the game install from this project's location and honours `SDVX_GAME`, `SDVX_DLL`, `SDVX_SYMS` and `FFMPEG` overrides. The predecessor project had the same path pasted into 20 files and a `_paths.py` that nothing imported; do not recreate that.

**All output goes to `output/`**, which is git-ignored. Nothing in `scripts/` should write next to itself. The one exception is `audio/reference/`, which holds an input that cannot be regenerated.

**Findings go in `specs/`, not in comments.** A script is allowed to reference a spec section (`see audio_engine.md §6.1.4`); it should not be the only place a fact is written down.


## Running anything

Scripts insert their own directory and `shared/` on `sys.path`, so run them from wherever:

```bash
python scripts/audio/sdvx_fx.py --list
```

