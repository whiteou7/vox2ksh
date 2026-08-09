# The camera element

**Status: not started.** Nothing here is established yet — this file records the scope and the approach so the work does not start from zero.

Scope: lane tilt, spin, zoom and roll — the `.vox` tracks that move the playfield rather than the notes on it.

---

## What makes this element different

Audio and notes were both *transcription* problems: the game does something exact, and the job was to read it out of the binary. Camera is a **mapping** problem on top of that. `.ksh` expresses only a subset of what `.vox` can describe, so once the `.vox` side is understood there is a design decision to make about what to drop, what to approximate, and what to warn about.

Document the lossy parts explicitly. A converter that silently discards camera data is worse than one that says what it discarded.

---

## What is known

Essentially nothing, beyond the `.vox` container conventions in [`vox_format.md`](vox_format.md) — which is community-sourced and unverified, and has already been wrong about other sections (see [`README.md`](README.md) in this directory).

The audio element never touched these tracks.

## Suggested starting point

1. **Survey before assuming.** Retarget `scripts/shared/voxsurvey.py` at the camera/tilt sections and tabulate what values actually occur across all 8103 charts in `data/music/`. That is what settled the effect-parameter layouts for audio, and it is cheap.
2. **Then find the consumer in the DLL.** The chart reader is `FUN_180239810` and the writer is `FUN_1800d40c0` — the effect sections' column order was recovered from their format strings, and the camera sections' should come out the same way. `scripts/shared/da.py` and `scripts/shared/callargs.py` are the tools for this.
3. **Check the gameplay event dispatcher.** `FUN_180407200` (`Game::GameAudio::Update`) walks a vector of 28-byte gameplay events with a `kind` field of 2..7, of which audio accounted for kinds 3, 4 and 6. The remaining kinds are unexamined and camera events are a plausible occupant. Note that the *producer* of that event vector was never found — see `HANDOFF.md` §2.2, which is an open item for exactly this reason.
4. **Decide the `.ksh` mapping last**, once you know what the source data can express.
