# Sparks `prob` became a share of 100, 2026-11-05

`sparks.prob` used to be the number of LEDs lit at once - 15 for about 15, 50 for
about 50 - and the effect divided it by the 960 LEDs on the rig to get each
one's chance. A formula is now held to 0-1 where it is evaluated, so a slot
driven by a fader could never ask for more than about one spark: `100 x fader_a`
came out as 1.

`prob` is now that count as a share of `Sparks.MAX_SPARKS`, which is 100. 0.15
asks for about 15 lit, 0.5 for about 50, 1 for 100. A fader on `prob` runs the
whole range with no multiplier.

## What was rewritten

Every preset that set `sparks.prob` to something other than 0 was changed so it
still asks for the same number of LEDs:

| was | now |
|---|---|
| a constant `n` | `n / 100` |
| `mul(100, fader_a)` | `fader_a` |
| `mul(c, X)` or `mul(X, c)` | the same with `c / 100` |

That was 10 presets: 19, 20, 21, 22, 24, 28, 31, 37, 39 and 40. Nothing else in any
of them moved. `presets-before.tar.gz` holds all 63 preset files as they were, and
`migrate.py --check` compares the two: each `sparks.prob` asks for the same count at
a spread of field values, and nothing but `sparks.prob` differs.

## Things to know

- **A preset saved by an instrument still on the old code is back to the old
  numbers.** The instrument keeps every preset in memory and writes it whole, so
  saving preset 31 from a session started before this change puts `mul(100,
  fader_a)` back - which the new code reads as 10000 LEDs, i.e. every one of them,
  all the time. Restart the instrument on the new code before saving, or migrate
  the file again with `migrate.py --write presets/31.json`. It cannot tell a value
  that has already been migrated from one that has not, so look at what it lists.
- **The top of the range is 100.** A factor over 100 (`mul(150, fader_a)`) cannot
  be written any more: it is held to 1, which is 100 LEDs. None of the presets had
  one. `MAX_SPARKS` is one constant in `effects/sparks.py` if a bigger ceiling is
  wanted, and changing it means redoing this.
- **The low end is coarser.** A 7-bit knob steps by 1/127, so the smallest
  non-zero setting asks for about 0.8 LEDs. The old "0.25 for a one in four chance"
  reading is not reachable from a fader.
