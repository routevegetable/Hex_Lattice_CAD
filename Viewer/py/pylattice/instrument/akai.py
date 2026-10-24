"""The Akai MPD232, as the BSP.

The instrument only knows the BSP's numbers - presets record them - so what the
Akai sends is turned into them as it comes in (see `Controller` in
examples/midi.py). Kept apart from hardware.py, which opens the MIDI port on
import, so the tables can be read and tested without one.
"""

# The BSP's numbers, as hardware.py names them: knobs KA1-KB8 are CCs, pads
# PA1-PB8 are notes.
KA1, KA2, KA3, KA4, KA5, KA6, KA7, KA8 = 10, 74, 71, 76, 77, 93, 73, 75
KB1, KB2, KB3, KB4, KB5, KB6, KB7, KB8 = 114, 18, 19, 16, 17, 91, 79, 72

PA1, PA2, PA3, PA4, PA5, PA6, PA7, PA8 = 44, 45, 46, 47, 48, 49, 50, 51
PB1, PB2, PB3, PB4, PB5, PB6, PB7, PB8 = 36, 37, 38, 39, 40, 41, 42, 43

# The Akai MPD232's pads, as the notes it sends (Controller mode, pad bank A),
# in the order of the BSP pads above. PA1-PA4 are the unit's pads 13-16, and
# PB1-PB8 are its pads 9-12 and 5-8; the unit's own pad numbers for PA5-PA8 are
# not recorded. Heard: every pad the rig uses (PA1-PA3 and PB1-PB8). PA4 (86) is
# INFERRED from the C-major run the other pads follow, and PA5-PA8 (48-51) are
# placeholders, not what the unit sends; no field uses PA4-PA8.
AKAI_PA = (81, 83, 84, 86, 48, 49, 50, 51)
AKAI_PB = (74, 76, 77, 79, 67, 69, 71, 72)

# What the Akai plays -> the BSP pad it counts as. One lookup, applied once on
# the way in: the numbers overlap (the Akai's 48-51 are the BSP's PA5-PA8), so
# it must never be chained.
AKAI_PADS = dict(zip(AKAI_PA + AKAI_PB,
                     (PA1, PA2, PA3, PA4, PA5, PA6, PA7, PA8,
                      PB1, PB2, PB3, PB4, PB5, PB6, PB7, PB8)))

# The Akai's knobs and faders, as the CCs it sends, for the BSP control each
# stands for. Faders F1-F8 are CC 12-19 and knobs K1-K8 are CC 22-29 (Controller
# mode, Q-Link bank 1); the order is by what the control does, not by position:
# the speeds and periods sit together on the knobs.
#   heard: every one of them, CC 12-19 (F1-F8) and 22-29 (K1-K8)
# rotary.parts and rotary.shape (KA6 and KA7 as the rotary field names them) do
# nothing, so no control is given for them.
AKAI_CCS = {
    12: KA1,    # F1  fader_a
    13: KA2,    # F2  fader_b
    14: KA3,    # F3  param_a
    15: KA4,    # F4  param_b
    17: KA6,    # F6  v_gradient.origin
    16: KA7,    # F5  burst.decay
    18: KB6,    # F7  trace.aim
    19: KB8,    # F8  scope.pattern
    22: KA5,    # K1  rotary.period
    23: KA8,    # K2  random.period
    24: KB1,    # K3  ripple.speed
    25: KB2,    # K4  ripple2.speed
    26: KB3,    # K5  wipe1.speed
    27: KB4,    # K6  wipe2.speed
    28: KB5,    # K7  trace.speed
    29: KB7,    # K8  scope.speed
}

# How many scope patterns there are (ScopeFieldBetter.PATTERNS). The field reads
# its knob as the pattern's number, 0 to 4, and presets record it that way - so
# a fader's 0-127 is cut into that many even steps on the way in, and nothing
# else has to change.
SCOPE_PATTERNS = 5


def _scope_pattern(value: int) -> int:
    return min(value * SCOPE_PATTERNS // 128, SCOPE_PATTERNS - 1)


# For the BSP controls that do not read 0-127 as it is: where the Akai's value
# is turned into what the field wants.
AKAI_CC_VALUES = {KB8: _scope_pattern}
