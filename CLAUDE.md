# CLAUDE.md

- Never manually word-wrap prose (inserting line breaks at ~72-80 columns). Write each paragraph as one long line and let the editor/viewer soft-wrap it. This applies to Markdown docs, comments, and commit messages alike.
- `specs/` states conclusions only. The measurements, counts and per-chart examples behind them live in `specs/evidence/` (one file per spec). Read the matching evidence file whenever you need to check a claim in a spec, judge a change against past results, or add a new finding. Put new measurements there, and keep the spec to the takeaway.
