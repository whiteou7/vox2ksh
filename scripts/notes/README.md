# scripts/notes/

Buttons and lasers: `.vox` -> `.ksh` chart body. Writeup: [`specs/notes.md`](../../specs/notes.md).

| file | what it does |
|---|---|
| `convert.py` | The converter. `python convert.py <chart.vox> [-o out.ksh] [--ksh-version 1\|2] [--preview]`. `--preview` fills the header's `po=`/`plength=` in from the song's own audio, via [`../audio/preview.py`](../audio/preview.py). |
| `laser.py` | Vox's pre-interpolated laser curve -> the discrete points a `.ksh` grid can hold, or (`--ksh-version 2`) the `laser_l_curve`/`laser_r_curve` beziers a KSM v2 grid can hold. |
| `xcheck.py` | Structural crosscheck against `scripts/shared/reference/ksh`. `python xcheck.py [-n N] [--only substr] [--worst N] [--csv out.csv]`. |
