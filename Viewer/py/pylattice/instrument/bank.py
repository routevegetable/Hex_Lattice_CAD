"""The preset bank, made once and shared.

It is here, and not in `__main__`, because the fields need to ask it which
preset is playing (a gradient knob reads the playing preset's own gradients)
and they are built before `__main__` gets to the console.
"""

from pathlib import Path

from pylattice.instrument.patch import PresetBank

BANK = PresetBank(Path("presets"))
