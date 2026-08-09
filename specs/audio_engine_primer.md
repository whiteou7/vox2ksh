# How SOUND VOLTEX makes the music "warp" — explained from scratch

This is the plain-language version of `audio_engine.md`. No audio-engineering or assembly-language background assumed. If you already know what a biquad filter is, read the other file instead.

---

## 1. What we're actually talking about

When you hold an FX button on a long note, or sweep a knob, the song changes: it stutters, goes muffled, goes tinny, wobbles, or grinds. That is not a separate pre-recorded sound. The game takes the **one single music file** for the song and modifies the audio *live*, on the fly, while it plays.

So the question "how do I replicate this?" really means: *what exact recipe does the game apply to the audio samples?* That recipe is what we dug out of the game's code.

---

## 2. Some vocabulary you need (and only this much)

**Sample.** Digital audio is just a very long list of numbers. Each number is the position of the speaker cone at one instant. SOUND VOLTEX uses **44,100 numbers per second, per channel** (left and right), so a 2.5-minute song is about 6.6 million numbers per channel.

**16-bit.** Each of those numbers is a whole number between −32,768 and +32,767. Zero = silence. Big numbers = loud.

> Worth knowing: most audio software converts these to a −1.0…+1.0 range before doing
> maths. SOUND VOLTEX does **not**. It works directly with the −32768…+32767 numbers.
> If you copy the game's formulas but use −1…+1, a few effects will come out wrong
> because some of them add a fixed amount rather than multiplying.

**Block.** The game doesn't process the song all at once. The sound card asks for a small chunk at a time — maybe 64 or 256 samples — and the game fills it in. This is called a *block* or *buffer*. It matters because the game only recalculates an effect's settings **once per block**, not for every single sample. So the exact block size slightly changes the result.

**Dry and wet.** "Dry" = the original untouched audio. "Wet" = the audio after the effect. Almost every effect in SOUND VOLTEX blends the two:

```
result = (1 − mix) × dry  +  mix × wet
```

`mix` comes from the chart as a percentage (e.g. `95.00` means 95 %). At mix = 100 % you hear only the processed sound; at 0 % nothing happens. This is why almost every effect in the chart file starts with a number like `90.00` or `98.00`.

---

## 3. How we found the recipe

The game's logic lives in `modules/soundvoltex.dll`, which is compiled machine code — not readable text. Three things made it tractable:

1. **The programmers left class names in the file.** C++ compilers embed the names of certain classes so the program can identify object types at runtime. Searching the file for those names turned up `BMSoundLibSvo::CSvoEffectedAudioGeneratorImpl` — literally "the SVO effected-audio generator". That told us exactly which part of the 12 MB file to look at.

2. **A decompiler.** Ghidra (free, made by the NSA) turns machine code back into C-like pseudo-code. It's not the original source — variable names are gone and it's often ugly — but the arithmetic is faithful, and arithmetic is all we needed.

3. **Cross-checking against the charts.** Every song folder has `.vox` chart files that are plain text and list the effect settings. Reading all 8,103 of them and comparing the value ranges against the limits hard-coded in the DLL confirmed which chart column feeds which knob in the code.

The giveaway constant, which appears in every filter in the file, is `0.00014247585`. That is 2π ÷ 44100 — the standard way to convert a frequency in Hz into the angle a digital filter needs. Spotting it immediately told us "this function is a filter, and the sample rate is fixed at 44100."

---

## 4. The signal path, start to finish

```
  the song file (.s3v)                one long list of 16-bit numbers
            │
            ▼
  copy one block into scratch space   left channel and right channel kept separate,
                                      converted to decimals but still −32768…32767
            │
            ▼
  run the effect                      (see section 5)
            │
            ▼
  blend dry + wet, then clip          anything above +32767 becomes +32767,
                                      anything below −32768 becomes −32768
            │
            ▼
  write back as 16-bit, interleaved   L,R,L,R,L,R... ready for the speakers
```

**One genuine oddity.** In the step that copies audio into scratch space, the code checks whether the *left* channel sample is exactly zero — and if it is, it forces **both** channels to zero for that instant. That's almost certainly an old bug nobody ever noticed (a true zero sample is rare and one silenced sample is inaudible). We documented it but deliberately did *not* copy it into our version.

---

## 5. The effects, one at a time

There are 13 FX-button effects and 3 laser effects. Here's what each actually does.

### Retrigger  (and "Echo", which is the same machinery)

Chops out a short slice of the music and plays it over and over.

Imagine the last half-second of music is written on a loop of tape. Retrigger plays that loop `count` times, and each repeat is quieter than the last by a fixed factor (`feedback`). Each repeat is also cut short — `gate` says what fraction of the slice actually sounds before it goes silent, and `release` fades out the end of each burst so it doesn't click.

The chart gives the slice length **in beats**, and the game converts it using the song's BPM: `seconds = beats × 60 ÷ BPM`. At 210 BPM, "2 beats split into 4 repeats" comes out as four 1/8-note stutters.

### Gate

A very fast on/off switch — a stutter or "chopper".

The game keeps a little 16-slot table of volume levels and steps through it. The factory-default table is `[32, 4, 32, 4, …]`, and each entry is multiplied by `0.0322`, giving alternating volumes of about **1.03** and **0.13**. So: loud, quiet, loud, quiet. The chart says how many steps fit in the cycle and how long the cycle is (again in beats).

### Bit Crusher

Despite the name, it does **not** reduce bit depth. It's a "sample and hold": it freezes one sample and repeats it `rate` times before grabbing a new one. With `rate = 12` you're effectively listening at 1/12 of the sample rate, which adds the harsh, gritty, robotic aliasing everybody associates with lo-fi.

Quirk: the counter restarts at every block boundary, so this effect genuinely sounds slightly different at different buffer sizes.

### Tape Stop

Exactly what it sounds like: the record player being switched off.

The game records the incoming audio into a buffer, then plays it back progressively slower — the pitch drops as the playback rate decays — while simultaneously fading the volume to zero over the given duration. Unlike most other effects, its duration is given in **plain seconds**, not beats.

### Side Chain

The rhythmic "pumping" you hear in dance music, where everything ducks on each kick drum.

Real sidechain compression listens to a kick drum track. SOUND VOLTEX doesn't bother — it just runs a repeating volume envelope: drop to silence over `attack`, stay silent for `hold`, climb back over `release`, repeat every cycle. Simple and effective.

### Flanger

The classic "jet plane whoosh".

It mixes the music with a copy of itself delayed by a tiny amount (0.1–3 milliseconds). Because the delay is constantly swaying back and forth, certain frequencies cancel out and the cancellation point sweeps up and down. The right channel's sweep is offset by a quarter cycle from the left, which makes it sound wide and stereo. It can run several passes stacked on top of each other for a stronger effect.

### Low Pass / High Pass Filter

The two "muffle" and "thin out" effects.

- **Low pass** lets low frequencies through and removes highs → sounds like the music is behind a wall.
- **High pass** does the opposite → sounds like a tiny phone speaker.

Both use the same textbook filter design ("RBJ cookbook" biquad — the same one in essentially every synth and DAW). Two settings matter: the **cutoff frequency** (where the cut begins) and **Q / resonance** (how much the frequencies right at the cutoff get boosted, which produces the squelchy "wah" character).

One detail that turned out to matter: after mixing dry and wet, the game multiplies the whole thing by `1 − Q × 0.04`. So at high resonance the entire signal gets a little quieter. That's why SDVX laser sweeps duck slightly as you crank them.

### Wobble

Not its own filter — it's a **low pass, high pass, or band pass filter whose cutoff is being swung back and forth automatically**. The chart picks which filter, which sweep shape, the two frequencies to sweep between, and how long one sweep takes.

Five sweep shapes are supported: ramp up, ramp down, sine, triangle, and square (which just jumps between the two frequencies). The sine and triangle shapes sweep *logarithmically*, which is why they sound musically even rather than lopsided.

### Pitch Shift

Changes the pitch without changing the speed, by chopping the audio into small grains, resampling them, and cross-fading them back together. We identified the routine (it computes `2^(semitones ÷ 12)`, the standard pitch ratio) but did **not** finish transcribing it — it's the one effect our script doesn't implement.

---

## 6. The laser (knob) effects

Lasers use the *same* filters as above, but the cutoff frequency follows your knob position instead of an automatic sweep.

Each chart defines its laser effects in a block called `#TAB EFFECT INFO`. Every single one of the 8,103 charts in this game uses the exact same five:

```
1, 90.00, 400.00, 18000.00, 0.70     low pass,  400 Hz .. 18000 Hz, gentle
1, 90.00, 600.00, 15000.00, 5.00     low pass,  600 Hz .. 15000 Hz, very resonant
2, 90.00,  40.00,  5000.00, 0.70     high pass,  40 Hz ..  5000 Hz, gentle
2, 90.00,  40.00,  2000.00, 3.00     high pass,  40 Hz ..  2000 Hz, resonant
3, 100.00, 30                        bit crusher
```

The knob position is a number from 0 to 127, and the cutoff is worked out like this:

```
low pass :   cutoff = lowFreq × (highFreq ÷ lowFreq) ^ (1 − knob/127)
high pass:   cutoff = lowFreq × (highFreq ÷ lowFreq) ^ (    knob/127)
```

Reading that in words: at knob 0 the filter is wide open and you barely hear it; as you turn it the cutoff slides *exponentially* (i.e. evenly in musical terms) toward the closed end. Bit crusher works the same way, with the hold length going from 1 to 30.

Interesting finding: the "peaking filter" that fan-made SDVX clones use as the default laser sound **does exist** in the real game's code — but it is only reachable through Wobble. The arcade game's lasers only ever use low pass, high pass, or bit crusher.

### Laser slams — where that "whoosh" comes from

A **slam** is when the laser jumps sideways instantly. In the chart file it looks like two points written at the *same* time with different positions:

```
004,01,39	0.000000	1	...      <- laser is at the far left
004,01,39	0.750000	0	...      <- and instantly at 75% right
```

There is no separate "slam effect" in the game's code. What you hear is simply the filter cutoff **jumping the entire distance in one step**. If the laser is carrying, say, the resonant high-pass, the cutoff can leap from 2000 Hz down to 40 Hz between one audio block and the next — the bass slams back in and you get that sharp whoosh.

Two things this means if you're writing your own version:

- **Don't smooth the knob curve.** A slam has to stay a hard step. Interpolating it into a short ramp turns the whoosh into a wash.
- **Don't assume one filter per laser section.** Charts change the filter *mid-section*, and they often do it right at a slam. (Our first attempt used a single filter for each section, which both applied the wrong filter and put the slam in the wrong place — it affected about 18 seconds of the test song. Fixed.)

If a slam sits on its own, with no laser stretch attached to it, the engine really does produce nothing: every effect wrapper refuses to run on anything shorter than one audio block.

**But that is not the whole story.** A laser slam *also* plays a short sound sample on top of the music — a separate thing from the filter jump, and the more obvious of the two. See the next section.

---

## 6b. The other half: sounds layered on top of the music

Everything up to here has been the game *modifying* the song. Some of what you hear is instead the game *adding* samples over it. Those live in `data/sound/ver5/general_sampler.s3p` — a container holding 15 short sounds:

| # | name | what it is |
|---|---|---|
| 0 | `fs00_virtical_se01` | the **laser slam** sound |
| 1–14 | `fs01_virtical_se02` … `fs14_shot13` | **FX chip note** samples — clap, snare, crash, "hey", … |

An FX chip note picks which one via the *same* column that a long FX note uses to pick its effect. On a hold that number means "effect definition"; on a chip it means "which sample". One column, two meanings, decided by whether the note has a length.

**Crucially, `0` means no sample at all** — and almost every FX chip is `0`. On the test song, 3 chips out of 228 make a sound. Charters use these deliberately, for accents. (An earlier version of this write-up got that backwards and put a clap on every single FX chip, which sounded nothing like the game.)

`apply_chart.py` mixes both in. Turn them off with `--no-se`, or nudge their overall level with `--se-trim`.

### How loud?

The slam ends up quieter than the chip samples, for three reasons:

1. It is simply a **quieter recording** — it peaks at 17446 out of a possible 32767, while the chip samples reach 28765–32767. That's about 5.5 dB down before anything else happens.
2. Its slow 228 ms swell means your ear registers it as quieter still than that number suggests.
3. The game turns the two down by **different amounts** on top of that. See below.

For a long time I could not find *where* the game sets those volumes, so the number was picked by trial and error against a recording of the real cabinet. It turned out I was looking in the wrong place entirely — see the next section.

A related thing I got wrong at first: I picked an over-quiet level to avoid *clipping* — the digital equivalent of a signal being too loud for the format. Then I found the game's own output stage in the code (`CGainWithHardLimiter`), and it turns out to be nothing more than "multiply by a volume, then chop anything over the maximum". The real game clips too. So being timid about it was costing audibility for no reason.

### Where the volumes actually live: inside the sound files

I spent a long time hunting through the program for something like `setVolume(slam, 0.55)`. There is nothing of the kind, and that turned out to be the answer: **the volume isn't in the program, it's written into each sound file's own header.**

Every sound the game loads starts with a 32-byte label before the audio data — file type, size, a checksum, and, 20 bytes in, a **volume written in decibels**.

Two bits of vocabulary:

**Decibels (dB).** A way of writing "how much louder or quieter", where equal steps mean equal *ratios* rather than equal amounts. 0 dB = leave it alone. −6 dB = about half as loud. −13 dB = about a fifth. Sound people work in dB because that's closer to how hearing works.

**Fixed-point.** The file can't store a decimal like `−5.17`, because the field is a whole number. So the value is stored multiplied by 256: `−5.17` is written as `−1324`, and whoever reads it divides by 256 to get the real value back. This is an old, cheap trick for storing fractions without floating-point maths.

Put together, the game does this when it loads a bank of sounds:

```
read the whole number from the header        e.g. -1324
divide by 256   -> decibels                       -5.172 dB
convert decibels to a plain multiplier       ->   0.5513
attach that multiplier to the sound
```

Reading the actual files:

| sound | in the file | decibels | multiplier |
|---|---|---|---|
| laser slam | −1324 | −5.17 dB | **0.55** |
| FX chip samples | −3328 | −13.00 dB | **0.22** |
| the song itself | 0 | 0.00 dB | **1.00** |

So the game plays the song untouched, the slam at a bit over half volume, and the chip sounds at about a fifth. The chips are **7.8 dB below the slam** — I had previously assumed they were equal, because nothing in the program distinguished them. Nothing in the program *does*; the distinction is in the data.

Why this was so hard to find: the volume is applied *once*, when the sound bank is loaded at startup, to a small "mixer connection" object attached to each sound. It never appears near the code that actually plays a note. Every search that started from "find the code that plays a slam and work outwards" was doomed, because the answer isn't on that path at all.

### The part that still doesn't add up

Here is the honest bit. The file says the slam should play at **0.55**. Comparing my render against the cabinet recording says it sounds right at about **0.69**. That's a gap of roughly 2 dB — small, but far too consistent to be noise, and I don't know where it comes from.

The awkward part is *what the measurement can and cannot see*. Comparing two recordings, I have no absolute volume reference — the recording could have been made with the cabinet's dial anywhere. So the only thing that can be measured is the **balance** between the slam and the music, not either one's absolute level. Which means these two explanations produce an identical result and cannot be told apart by listening or measuring:

* the slam is 2 dB louder than the file says, or
* the music is 2 dB **quieter** than I think, which makes the slam *seem* 2 dB louder.

The second one is the more suspicious. The music file's header says 0 dB — play it as-is — so if something is quietening the music, it's happening somewhere I haven't looked yet.

Things I checked and eliminated:

* **A volume attached to a whole bank of sounds rather than each one.** The function that registers each bank takes only an id number and a filename. No volume.
* **The music duck.** During knob sections the game deliberately lowers the music (see §6c) so the filter sweep stands out. I wondered whether it stays lowered between sections instead of returning to full. It doesn't — the code explicitly loads "1.0" when no knob is active.
* **Making it stay lowered anyway**, as an experiment. That *does* pull the fitted slam volume down to 0.52–0.55, tantalisingly close to the file's number, but it makes the whole render measurably worse. Right answer for the wrong reason — it's a coincidence, not a fix.
* **Overlapping slams stacking up** and supplying the extra loudness. Measurably worse.
* **Another program file being responsible.** The game ships a dozen `.dll` files and I'd assumed one of the audio-looking ones might own the mixer. It doesn't: the code that reads these sound files exists in `soundvoltex.dll` and nowhere else.

What's left to check is a loose thread in the loading code itself. When it reads the volume out of the header, it does the decibel conversion **twice** and does two different things with the answers — one goes to the sound's mixer connection (the part I traced), and the other gets filed away in a list whose readers I never followed. If a second volume is being applied to the music somewhere, that list is where I'd look first.

### What the script does about it

`apply_chart.py` reads each sample's volume straight out of its file, so the *relationship* between the sounds is the game's own and you never have to guess at it. The single leftover mystery is parked in one flag:

```
--se-trim 1.25    (the default)
```

That 1.25 is the unexplained 2 dB and nothing else. Set `--se-trim 1.0` and you hear exactly what the files say; leave it at 1.25 and you get the closest match to the recording. If someone eventually finds the missing piece, this flag should become 1.0 and stay there.

`--slam-gain` and `--se-gain` still exist, but they're now blunt overrides — give one a number and it ignores both the file's volume and the trim.

---

## 6c. The default laser sound, which lives somewhere else entirely

Every laser node carries a number saying which effect it uses. `1`–`5` pick one of the five laser effects defined in the chart; `6` means none. But **`0` means "peak filter"**, and that is the *default* — on the test song, 870 of 894 left-laser nodes are `0`.

The peak filter is the classic SDVX laser "wah". It is not produced by the effect engine documented above — the game routes it through a **DirectSound parametric EQ** instead, a Windows built-in effect with three settings: centre frequency, bandwidth and gain.

For a long time I could not find the code that steers it, because I was looking in the wrong place: I kept searching around the *effect* classes. It is actually driven from the code that handles gameplay events — the same function that decides when to play a hit sound. Every frame it looks at both knobs, works out how far along its sweep each one is (the right knob is mirrored, so pushing it right and pushing the left knob left do the same thing), takes whichever is further, and remembers that number. **Eighty milliseconds later** it feeds that number, scaled to 0–127, into a lookup:

* a **128-entry table of frequencies** sitting in the binary as plain data — hand-drawn, not a formula: `0, 6, 12 … 100, 106 … 202, 232 … 3672, 3852 … 8400 … 10800` Hz;
* anything under 80 Hz or over 16000 Hz is clamped away (those are DirectSound's own limits);
* bandwidth and gain come from simple straight-line rules off that frequency, topping out at +15 dB of boost;
* below knob value 4 the gain is forced to zero, so a barely-moved knob does nothing.

The same function also turns the *music* down slightly while the knob is away from rest — to about 0.57 at the extreme — which is makeup for that +15 dB boost. It slides there slowly, about a third of the way per second.

That table of frequencies was the thing that cracked it. Searching for the *data* the effect would need, rather than for the class that applies it, found the code in one step.

Everything above is now read straight out of the binary. Three details of it were then checked against the recording, and all three held: sweeping the 80 ms delay puts the best match at exactly 80 ms; forcing the EQ on during lasers that already have their own effect makes those sections much worse (so the field I read as "which effect" really is that); and removing the music duck costs measurable accuracy.

An earlier version of this write-up gave up here and measured the filter from the recording instead. That fit got the general shape right and the loudness badly wrong — it guessed +4 dB where the real answer is +15 dB — and it missed the delay, the dead zone and the duck entirely.

---

## 7. Measuring what I couldn't read

At this point a recording of the actual cabinet playing this chart became available, which turns guesswork into measurement. It isn't a clean file — it's polarity-flipped, lossily compressed, and its clock runs 8 parts-per-million fast, drifting 45 samples over the track. So you can't just subtract it from the original and see what changed.

What you *can* do is compare **spectra**: chop both into 46 ms slices, measure how much energy sits in each of 46 frequency bands, and compare. That ignores timing and phase, which is roughly what "sounds the same" means anyway.

Doing that on slices where the chart says a default laser is active, sorted by knob position, draws the filter for you:

```
knob position    far left  ....................................  far right
boost centred at   115 Hz   474   1285   1796   2634   3373   4935 Hz
```

A boost that slides upward as you turn the knob — that's the "wah". It also confirmed the boost slides in *opposite* directions for the two knobs, which matches a mirroring branch in the game's code.

That measurement was what I rendered with until I found the real table (§6c). Comparing the two afterwards is a good lesson in what curve-fitting does and doesn't get you: the shape was right, the loudness was off by 11 dB, and three separate behaviours — the 80 ms delay, the dead zone near rest, and the music duck — were invisible to the fit because each of them is small on its own.

The same method fixed the slam volume. Testing a range of levels and picking the closest match:

```
slam volume   0.4    0.55   0.6    0.65   0.7    0.8    1.0
mismatch     1.94   1.83   1.81   1.80   1.80   1.83   1.94     (lower = closer)
```

0.65 wins, and 1.6 — what I'd shipped at one point — is dramatically wrong. My reasoning for 1.6 had been "the game hard-clips anyway, so louder is safe". The recording says that was about 10 dB too hot. This one is still a fit — the sound file's own header says 0.55 (§6b), and the recording says 0.69, and that 2 dB disagreement is unexplained.

One more thing about that number: it is not just "how loud is a slam". Earlier the same test said 0.5, because I was letting overlapping copies of the sample add together. The slam sound is 1.78 seconds long and slams come about every 0.4 seconds, so up to ten copies were piling up — and that pile was quietly supplying level the single volume setting was missing. The game cannot do that: it keeps **one voice per sound**, so playing a sound again cuts off the previous one. Fixing that made each slam shorter, and the fitted volume had to rise to 0.65 to compensate. A fitted number absorbs whatever the model gets wrong, which is exactly why it is worth replacing with a real one when you can.

Overall the render went from 3.17 (untouched track) to **1.80** on that mismatch score, with about 1.14 being the floor set by the recording's own compression noise.

---

## 7. Where the numbers come from in a chart file

Open any `.vox` file in Notepad — they're plain text. The two blocks that matter:

```
#TAB EFFECT INFO            <- the 5 laser effects (see above)
#FXBUTTON EFFECT INFO       <- up to 12 FX-button effects for this chart
```

An FX definition looks like `3, 75.00, 2.00, 0.50, 90, 2.00`. The first number is the effect type (3 = flanger); the rest are its settings, and the meaning of each column depends on the type. The full table is in `audio_engine.md` §3.

Then, further down, the note tracks:

| block | what it is |
|---|---|
| `#TRACK1` | left knob (VOL-L) |
| `#TRACK2` | **FX-L button** |
| `#TRACK3`–`#TRACK6` | BT-A, BT-B, BT-C, BT-D |
| `#TRACK7` | **FX-R button** |
| `#TRACK8` | right knob (VOL-R) |

Laser lines have nine columns, and it matters which is which: column 4 (counting from 0) is the **laser effect**, column 7 is the **curve shape**. Both happen to hold small numbers in the same 0–5 range, so mixing them up produces something that looks right and sounds wrong — I did exactly that, and it put filters all over the chart at the wrong moments.

An FX-button line is `position, length, effect`, e.g. `007,01,00  72  5`: hold starting at measure 7 beat 1, lasting 72 ticks (48 ticks = 1 beat, so 1.5 beats), using effect number 5. **The effect number is offset by 2** — a `5` means "the 4th definition in the list" (index 3). That's not a typo on our part; the game literally subtracts 2 before looking it up.

Laser lines carry the knob position (0.0–1.0) plus a column saying which of the five laser effects is active — **offset by 1** this time, where `0` means "no effect".

---

## 8. Using the scripts

Two files:

- **`scripts/audio/sdvx_fx.py`** — the effects themselves. Apply one effect to a WAV file.
- **`scripts/audio/apply_chart.py`** — reads a real chart + its audio and applies every effect at the right moment, automatically.

Requirements: Python with `numpy` (and `scipy`, optional but much faster), plus `ffmpeg` for reading the game's `.s3v` audio files.

```bash
# see what's available
python scripts/audio/sdvx_fx.py --list

# one effect on a WAV of your own
python scripts/audio/sdvx_fx.py song.wav out.wav --effect gate --params 98,8,0.286

# a knob sweep: knob goes 0 -> 127 -> 0 over 6 seconds
python scripts/audio/sdvx_fx.py song.wav out.wav --effect laser_lpf --params 90,400,18000,0.7 --knob 0:0,3:127,6:0

# a whole real chart, effects and all
python scripts/audio/apply_chart.py data/music/2229_kamui_tjhangneil -d 5m -o kamui_fx.ogg
```

`-d` picks the difficulty (`1n` novice, `2a` advanced, `3e` exhaust, `4i` infinite, `5m` maximum). Add `--no-laser` or `--no-fx` to hear just one half.

---

## 9. What's *not* in here

Being honest about the edges:

- **Pitch Shift is not implemented.** Charts that use it will report it as skipped.
- **Tape Stop Ex** (a variant with a pre-roll) falls back to nothing; it's identified but its envelope constants aren't fully transcribed.
- **This is not sample-exact.** Getting bit-identical output would need the same block size the arcade cabinet's sound card uses, and the game's grid-snapping (it nudges each effect's start backwards to land on a musical beat). Ours starts effects exactly where the chart says. It sounds right; it won't diff to zero.
- **We assume perfect play.** The real game only applies an effect while you're actually holding the button.
