# How the audio effects work, in plain terms

A short version of [`audio_engine.md`](audio_engine.md) for readers with no DSP or assembly background.

## Basics

When you hold an FX button or turn a knob, the game changes the song's audio live. There is one music file per song and no pre-recorded effect sounds. The goal here is to copy the exact math.

* Audio is a list of numbers, 44,100 per second per channel. The game keeps them as 16-bit integers (-32768 to 32767), not -1 to 1. A few effects add a fixed amount rather than multiplying, so scaling to -1..1 breaks them.
* The game works in blocks (64 to 256 samples) and recalculates effect settings once per block, so block size slightly changes the output.
* Almost every effect blends dry and wet: `result = (1 - mix) * dry + mix * wet`. `mix` is the first number in the chart's effect definition (e.g. `90.00`).

## How the recipe was found

1. The DLL contains the class name `BMSoundLibSvo::CSvoEffectedAudioGeneratorImpl`, which points at the effect code.
2. Ghidra decompiles it into readable arithmetic.
3. All 8,103 charts' effect values were compared against limits in the code to confirm which chart column feeds which parameter.

The constant `0.00014247585` is 2pi / 44100, which marks a filter and confirms the fixed 44.1 kHz rate.

## Signal path

Song `.s3v` to a block copied into float scratch (left and right separate), then the effect, then dry/wet blend and clip to 16-bit, then interleaved output. The game's copy step zeros both channels when the left sample is exactly 0. That's probably a bug, and we don't copy it.

## The effects

13 FX-button effects and 3 laser effects.

* Retrigger / Echo: repeats a short slice `count` times, each repeat quieter by `feedback`. `gate` is the fraction of each slice that sounds, `release` fades its end. Slice length is in beats: `seconds = beats * 60 / BPM`.
* Gate: steps through a 16-slot volume table. The default `[32, 4, 32, 4, ...]` times `0.0322` gives alternating 1.03 and 0.13.
* Bit Crusher: sample-and-hold. It freezes one sample and repeats it `rate` times, with no bit-depth reduction. The counter restarts each block, so output depends on block size.
* Tape Stop: plays buffered audio back progressively slower while fading to zero. Duration is in seconds.
* Tape Stop Ex: the opposite. After a preroll it starts slow and quiet and speeds up to full volume. Times are in beats. Read as seconds, the preroll outlasts the note and the effect silently does nothing. How quiet it starts is still fitted, not read from the game.
* Side Chain: a repeating volume envelope (drop over `attack`, hold, climb over `release`), not a real sidechain.
* Flanger: mixes in a copy delayed by 0.1 to 3 ms with a swaying delay. The right channel's sweep is a quarter cycle behind. Can stack passes.
* Low pass / High pass: standard RBJ cookbook biquads with cutoff and Q. After the blend the output is multiplied by `1 - Q * 0.04`, which is why high-resonance sweeps get slightly quieter.
* Wobble: a low, high or band pass whose cutoff swings between two frequencies. Shapes: ramp up, ramp down, sine, triangle, square. Sine and triangle sweep logarithmically.
* Pitch Shift: grain-based; see `audio_engine.md` for current status.

## Laser effects

Lasers use the same filters, with the cutoff following the knob (0 to 127) instead of an automatic sweep. Every chart's `#TAB EFFECT INFO` defines the same five:

```
1, 90.00, 400.00, 18000.00, 0.70     low pass, gentle
1, 90.00, 600.00, 15000.00, 5.00     low pass, resonant
2, 90.00,  40.00,  5000.00, 0.70     high pass, gentle
2, 90.00,  40.00,  2000.00, 3.00     high pass, resonant
3, 100.00, 30                        bit crusher
```

```
low pass:   cutoff = low * (high / low) ^ (1 - knob/127)
high pass:  cutoff = low * (high / low) ^ (knob/127)
```

Bit crusher hold length goes from 1 to 30. A peaking filter exists in the code, but only Wobble reaches it.

### Slams

A slam is two laser points at the same tick with different positions. There's no slam effect: the filter cutoff just jumps the whole distance in one step. So:

* Don't smooth the knob curve. A ramp turns the whoosh into a wash.
* Don't assume one filter per laser section; charts change filter mid-section, often at a slam.

A slam with no laser stretch attached makes no filter sound, because effect wrappers refuse anything shorter than one block. The slam sample (below) plays regardless.

## Samples layered on the music

`data/sound/ver5/general_sampler.s3p` holds 15 samples: #0 is the laser slam, #1 to #14 are FX chip sounds (clap, snare, crash, ...).

On a chip note, the same column that picks an effect on a hold picks the sample. `0` means no sample, and most chips are 0 (3 of 228 on the test song). `render_chart.py` mixes these in; `--no-se` disables them and `--se-trim` scales them.

### Volume lives in the file header

There is no `setVolume(slam, 0.55)` in the code. Each sound file has a 32-byte header, and at offset 20 is a volume in dB times 256 (so -5.17 dB is stored as -1324). The loader divides by 256 and converts dB to a multiplier once, at bank load.

| sound | stored | dB | multiplier |
|---|---|---|---|
| laser slam | -1324 | -5.17 | 0.55 |
| FX chips | -3328 | -13.00 | 0.22 |
| song | 0 | 0 | 1.00 |

Chips are 7.8 dB below the slam. The game's output stage (`CGainWithHardLimiter`) just multiplies and clips, so the game clips too.

### Unexplained 2 dB

Measured against the cabinet recording, the slam fits best at about 0.69, not 0.55. Only the slam-to-music balance can be measured, so either the slam is 2 dB louder or the music is 2 dB quieter than assumed. Ruled out: a per-bank volume, the music duck failing to reset, overlapping slams stacking, and another DLL owning the mixer. Keeping the music ducked fits 0.52 to 0.55 but makes the render worse overall. The loader converts dB twice and files the second result in a list whose readers were never followed; that's the lead.

`--se-trim 1.2` (default) covers this gap. `1.0` gives exactly what the files say. If the cause is found, it should become 1.0. `--slam-gain` and `--se-gain` override file volume and trim outright.

## Default laser sound: the DirectSound ParamEq

Laser nodes carry an effect number: `1` to `5` pick a defined effect, `6` means none, and `0` means peak filter, the default (870 of 894 left-laser nodes on the test song). The peak filter doesn't go through the effect engine; it uses a DirectSound parametric EQ (centre frequency, bandwidth, gain).

It's driven from the gameplay-event code. Each frame it takes the farther-along of the two knobs (the right one mirrored) and remembers it. 80 ms later it maps that value, scaled to 0..127, through:

* a 128-entry hand-drawn frequency table (0, 6, 12, ... up to 10800 Hz), clamped to 80..16000 Hz;
* bandwidth and gain from straight-line rules on the frequency, up to +15 dB;
* zero gain below knob value 4.

The same code lowers the music to about 0.57 at the extreme, sliding about a third of the way per second, to offset the boost. Finding the frequency table's data was what located all this.

Checked against the recording: the best delay is exactly 80 ms, forcing the EQ onto lasers that have their own effect makes it worse, and removing the music duck costs accuracy. An earlier fit from the recording alone got +4 dB where the real value is +15 dB, and missed the delay, dead zone and duck.

## Measurement

The cabinet recording is polarity-flipped, lossy, and 8 ppm fast (45 samples of drift), so it can't be subtracted. Instead, compare spectra: 46 ms slices, 46 frequency bands, mean dB difference. Lower is closer. The default laser's boost centre, fitted per knob position, rises from 115 Hz at far left to 4935 Hz at far right.

Slam volume sweep: 0.4 gives 1.94, 0.55 gives 1.83, 0.65 gives 1.80, 0.7 gives 1.80, 1.0 gives 1.94. Earlier fits gave 0.5 because overlapping copies of the 1.78 s sample stacked up. The game keeps one voice per sound, so a retrigger cuts the previous one; fixing that raised the fit to 0.65.

Overall: untouched 3.17, render 1.80, floor 1.14 (the recording's own codec noise).

## Chart columns

```
#TAB EFFECT INFO         5 laser effects
#FXBUTTON EFFECT INFO    up to 12 FX-button effects
```

An FX definition like `3, 75.00, 2.00, 0.50, 90, 2.00` is effect type (3 = flanger) then its settings. The type-by-type table is in `audio_engine.md` §3.

| block | what it is |
|---|---|
| `#TRACK1` | left knob |
| `#TRACK2` | FX-L |
| `#TRACK3` to `#TRACK6` | BT-A to BT-D |
| `#TRACK7` | FX-R |
| `#TRACK8` | right knob |

Laser lines have nine columns: column 4 (from 0) is the laser effect, column 7 is the curve shape. Both hold values in 0 to 5, so mixing them up looks right and sounds wrong.

An FX line is `position, length, effect`: `007,01,00  72  5` is measure 7 beat 1, 72 ticks (48 per beat), effect 5. The effect number is offset by 2 (5 is the 4th definition, index 3). A laser's effect column is offset by 1, with 0 meaning none.

## Scripts

```bash
python scripts/audio/fx_dsp.py --list
python scripts/audio/fx_dsp.py song.wav out.wav --effect gate --params 98,8,0.286
python scripts/audio/fx_dsp.py song.wav out.wav --effect laser_lpf --params 90,400,18000,0.7 --knob 0:0,3:127,6:0
python scripts/audio/render_chart.py data/music/2229_kamui_tjhangneil -d 5m -o kamui_fx.ogg
```

Needs `numpy` (`scipy` optional, faster) and ffmpeg. `-d` is `1n`, `2a`, `3e`, `4i` or `5m`. `--no-laser` and `--no-fx` isolate one half.

## Limits

* Not sample-exact. That would need the cabinet's block size.
* Perfect play is assumed. The real game only applies an effect while the button is held.
* A lasers-borrowing-button-effects mode is implemented but off by default; it helps on some songs and hurts on others.
* The keyframed composite effect isn't implemented: it stores time/value checkpoints, but what the value controls is unknown.
