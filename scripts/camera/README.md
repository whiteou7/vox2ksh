# scripts/camera/

**Empty — the camera element has not been started.**

Scope: lane tilt, spin, zoom and roll — the `.vox` tracks that move the playfield rather than the notes on it.

Read [`specs/camera.md`](../../specs/camera.md) first. Unlike the notes element, nothing here is known yet: the audio work never touched these tracks, and the community [`vox_format.md`](../../specs/vox_format.md) is unverified and has already been wrong about other sections.

This element is also different in kind from the other two. Audio and notes are transcription problems — the game does something exact and the job is to read it out of the binary. Camera is a **mapping** problem on top of that, because `.ksh` expresses only a subset of what `.vox` can describe. Document what gets dropped; a converter that silently discards camera data is worse than one that reports it.

Suggested order: survey with `../shared/voxsurvey.py` retargeted at the camera sections, then find the consumer in the DLL with `../shared/da.py` and `../shared/callargs.py` starting from the chart reader `FUN_180239810`, then decide the `.ksh` mapping last. The unexamined gameplay-event kinds in `FUN_180407200` are a plausible lead — see `specs/camera.md`.
