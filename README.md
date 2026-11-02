# vox2ksh

vox to ksh converter

## Features

* note, laser & camera events convert
* arcade tilt simulation to deal with pretilt
* embedded audio fx engine

## Credits

* **zacharied**: original `.vox` format specs
* **m0seng**: rewrite and extension
* **Rosemoe**: [`sdvx-sfx-renderer`](https://github.com/Rosemoe/sdvx-sfx-renderer)

Manual converts by the community used for regression and refchecking.

## Requirements & Development

* Python 3.12
* `ffmpeg` on `PATH`

Clone this repo inside the game's `contents/` directory; scripts will find the game data relative to it.

## Usage

```bash
pip install -r requirements-gui.txt
python gui/main.py
```
