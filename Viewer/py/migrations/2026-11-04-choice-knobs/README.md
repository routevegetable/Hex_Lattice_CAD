# Choice knobs stopped being spread, 2026-11-04

A `CustomChoice` names which knob position means which option. Four of them
spread their options over the whole 0-127 range - `rotary.parts` and
`v_rotary.parts` at 0, 32, 64, 95, 127, `loops.copies` every 8 or 9,
`random_lines.count` every 13, `trace_lines.mode` every 21. The other three,
`scope.pattern`, `loops.shape` and `tile_pattern.pattern`, used the CC value
as an index and always had.

Spreading cannot survive a new option. Adding a seventh mode moves all six of
the others, so every recording of that knob comes back meaning something else -
and `random_lines.count` was worse, since its length comes from the widest
family of lines on the lattice: the same preset on a different-sized lattice
lit a different number of lines. All four now index the CC directly, so an
option added later appends and leaves the rest where they are.

That left 37 presets holding positions from the old layout. `migrate.py`
moved each one to the position that reads the same, `presets-before.tar.gz`
holds all 57 preset files as they were, and `migrate.py --check` compares the
two - every knob reads what it read before, and nothing but their CC values
moved.

## The two that could not be moved cleanly

`72.json` and `73.json` map `trace_lines.mode` onto CC 93, where
`rotary.parts` and `v_rotary.parts` also land by default. The two old layouts
happened to agree at those values; indexed, they want different positions, and
one CC cannot hold both. `trace_lines.mode` was put there on purpose, so it
kept CC 93; the parts pair moved to CC 94, which nothing else uses. Both
presets play as they did, and parts is no longer on the desk in those two - it
was never independently adjustable there anyway, since one knob moved both.

## Cost on the desk

`rotary.parts` is on KA6, a knob sending absolute 0-127, and its positions are
now 0-4: from the hardware the control is bottom-of-travel only. `scope.pattern`
on KB8 was already like this. The others are off the desk. Fixing it properly
means scaling incoming CC per meta rather than spreading the lists.
