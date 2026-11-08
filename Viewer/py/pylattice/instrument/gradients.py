"""The gradients declared in code: usable by every preset.

A knob picks a gradient by its index, and a declared gradient's index is its
place in `GLOBAL_GRADIENTS`. A preset can also carry gradients of its own, in its
file, and a knob reaches those at 64 and up; see `pylattice.fields.gradients`.
"""

from pylattice.fields.gradients import (
    GLOBAL_SLOTS,
    OWN_FIRST,
    GradientDef,
)
from pylattice.instrument.patch import PresetBank

COLOR_TEMP_BRIGHT_SEQ = [  # (frac, hue 0-1, sat 0-1)
    (0.0, 0.0000, 1.0000),
    (0.4, 0.0392, 1.0000),
    (0.6, 0.0741, 0.5294),
    (0.65, 0.0741, 0.0000),  # white, hue kept from the left side
    (0.75, 0.6599, 0.0000),  # white, hue kept from the right side
    (1.0, 0.6599, 0.9608),
]

# The six hues of ROYGBV as the rig's LEDs show them - red, orange, yellow, green,
# blue, violet - not the even steps of the colour wheel: orange and yellow sit close
# to red and violet stops short of the wheel's end. From the CircuitPython rig.
ROYGBV_HUES = [0.0, 0.03, 0.15, 0.32, 0.65, 0.82]

# APPEND ONLY - by a person or by a program. A gradient's index is its place in this
# list, and a preset's gradient knob holds that number, so removing one, or putting
# one anywhere but the end, makes every preset that points past it come back
# playing a different gradient. To retire one, leave it where it is. There is room
# for GLOBAL_SLOTS (64).
GLOBAL_GRADIENTS: list[GradientDef] = [
    GradientDef("color_temp_bright", list(COLOR_TEMP_BRIGHT_SEQ)),
    GradientDef(
        "roygbv_rainbow",
        [(i / (len(ROYGBV_HUES) - 1), hue, 1.0) for i, hue in enumerate(ROYGBV_HUES)],
    ),
]

if len(GLOBAL_GRADIENTS) > GLOBAL_SLOTS:
    raise ValueError(f"at most {GLOBAL_SLOTS} declared gradients, found {len(GLOBAL_GRADIENTS)}")


def gradient_at(bank: PresetBank, idx: int) -> GradientDef | None:
    """The gradient a knob at `idx` (0-127) is on, or None where nothing is.

    Below 64 it is a declared gradient, by its order in `GLOBAL_GRADIENTS`. From 64
    it is the playing preset's own, by its order in the preset's `gradients`.
    """
    if idx < 0:
        return None

    if idx < GLOBAL_SLOTS:
        return GLOBAL_GRADIENTS[idx] if idx < len(GLOBAL_GRADIENTS) else None

    patch = bank.playing()
    own = idx - OWN_FIRST

    if patch is None or own >= len(patch.gradients):
        return None

    return patch.gradients[own]
