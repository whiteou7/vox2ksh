# scripts/notes/

**Empty — the notes element has not been started.**

Scope: BT/FX/laser note data, timing, BPM and time-signature changes, laser slams and curve types, chip vs hold — everything that becomes the `.ksh` chart body. This is the element the converter needs first.

Read [`specs/notes.md`](../../specs/notes.md) before writing anything here. A useful amount is already established as a side effect of the audio work — track layout, column meanings, the C4-vs-C7 trap, and what a laser slam actually is — and re-deriving it would be wasted effort.

Two things to do before the first script:

1. Lift the `.vox` parser out of `../audio/apply_chart.py` into `../shared/vox.py` (`HANDOFF.md` §3.1). It already handles tick→time with BPM and time-signature changes. Doing this second means maintaining two parsers.
2. Retarget `../shared/voxsurvey.py` at the note tracks to see what column values actually occur across all 8103 charts before assuming what they mean. That method is what settled the effect parameter layouts.

Verification should be a real chart round-tripping into a playable `.ksh` — not eyeballing the output.
