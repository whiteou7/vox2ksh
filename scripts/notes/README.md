# scripts/notes/

Buttons and lasers: `.vox` -> `.ksh` chart body. Writeup: [`specs/notes.md`](../../specs/notes.md).

| file | what it does |
|---|---|
| `convert.py` | The converter. `python convert.py <chart.vox> [-o out.ksh]`. |
| `laser.py` | Vox's pre-interpolated laser curve -> the discrete points a `.ksh` grid can hold. |
| `xcheck.py` | Structural crosscheck against `scripts/shared/reference/ksh`. `python xcheck.py [-n N] [--only substr] [--worst N] [--csv out.csv]`. |
