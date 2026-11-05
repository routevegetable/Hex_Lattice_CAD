"""The gradients declared in code: usable by every preset.

A preset can also carry gradients of its own, in its file, laid over these
while it plays; see `pylattice.fields.gradients` for how, and why a gradient has
a written-down position rather than a place in a list.

To add one: pick a free position and write it as `(frac, hue, sat)` stops. The
UI keeps 0-63 for these and 64-127 for a preset's own, so stay in 0-63. Never
reuse or renumber a position - a preset's knob holds the number, and would come
back meaning a different gradient. Two stops at the same frac make a hard step.
"""

from pylattice.fields.gradients import Gradient, GradientLibrary

COLOR_TEMP_BRIGHT_SEQ = [  # (frac, hue 0-1, sat 0-1)
    (0.0, 0.0000, 1.0000),
    (0.4, 0.0392, 1.0000),
    (0.6, 0.0741, 0.5294),
    (0.65, 0.0741, 0.0000),  # white, hue kept from the left side
    (0.75, 0.6599, 0.0000),  # white, hue kept from the right side
    (1.0, 0.6599, 0.9608),
]

GLOBAL_GRADIENTS = [
    Gradient("color_temp_bright", 0, tuple(COLOR_TEMP_BRIGHT_SEQ)),
]

# One object, shared by every operator that reads a gradient and by the patch
# that lays its own over these.
GRADIENTS = GradientLibrary(GLOBAL_GRADIENTS)
