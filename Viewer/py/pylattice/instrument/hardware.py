"""What the instrument is plugged into: the lattice, and the box on the desk.

These are module-level singletons because there is one of each per process -
importing this opens the MIDI port.
"""

import os
import sys

import mido

from pylattice.examples.midi import MIDI
from pylattice.graph import Graph
from pylattice.lattice_writer import LatticeWriter

COLS = 6
ROWS = 2

graph = Graph(COLS, ROWS)

lattice = LatticeWriter(COLS / 2, ROWS)

# One entry per controller this instrument knows how to talk to. `ports` is
# what MIDI() opens; the CC/note layout is BSP's, and akai's is only partly
# mapped - see its entry.
CONTROLLERS = {
    "beatstep": {
        "ports": ["Arturia BeatStep Pro Arturia BeatStepPro"],
        "KA": (10, 74, 71, 76, 77, 93, 73, 75),
        "KB": (114, 18, 19, 16, 17, 91, 79, 72),
        "PA": (44, 45, 46, 47, 48, 49, 50, 51),
        "PB": (36, 37, 38, 39, 40, 41, 42, 43),
        "STEPS": list(range(20, 56)),
    },
    "akai": {
        "ports": ["MPD232 Port A", "MPD232 Port B", "MPD232 MIDI", "MPD232 Remote"],
        # Controller mode, Q-Link bank 1, pad bank A - see docs/akai_mpd232.svg.
        # Only what has been mapped against the hardware is real; the rest keep
        # the BeatStep's numbers, which the MPD232 never sends, so they do nothing.
        #   KA1-KA4 are faders F1-F4 (cc 12-15); the knobs send cc 22 up, not yet used.
        "KA": (12, 13, 14, 15, 77, 93, 73, 75),
        "KB": (114, 18, 19, 16, 17, 91, 79, 72),
        #   PA1-PA3 are pads 13-15; PB1-PB7 are pads 9-12 and 5-7.
        "PA": (81, 83, 84, 47, 48, 49, 50, 51),
        "PB": (74, 76, 77, 79, 67, 69, 71, 43),
        "STEPS": list(range(20, 56)),
    },
}


def _pick_controller() -> str:
    """LATTICE_CONTROLLER wins outright; otherwise whichever profile's ports
    are actually present, else the original default."""
    override = os.environ.get("LATTICE_CONTROLLER")
    if override:
        if override not in CONTROLLERS:
            raise ValueError(
                f"LATTICE_CONTROLLER={override!r}: pick one of {list(CONTROLLERS)}"
            )
        return override

    if sys.implementation.name == "pypy" and not os.environ.get("MIDO_BACKEND"):
        mido.set_backend("mido.backends.portmidi")
    available = set(mido.get_input_names())

    for name, profile in CONTROLLERS.items():
        if set(profile["ports"]) & available:
            return name

    return "beatstep"


CONTROLLER = _pick_controller()
_profile = CONTROLLERS[CONTROLLER]

# The hardware for live playing, the IAC bus for whatever Ableton plays back.
midi = MIDI([*_profile["ports"], "IAC Driver Bus 1"])

# Knobs KA1-KB8 are CCs, pads PA1-PB8 are notes; row A is the top/upper one.
KA1, KA2, KA3, KA4, KA5, KA6, KA7, KA8 = _profile["KA"]
KB1, KB2, KB3, KB4, KB5, KB6, KB7, KB8 = _profile["KB"]

PA1, PA2, PA3, PA4, PA5, PA6, PA7, PA8 = _profile["PA"]
PB1, PB2, PB3, PB4, PB5, PB6, PB7, PB8 = _profile["PB"]

# The step buttons, one preset each. They send CCs, and a press arrives as 127.
STEPS = _profile["STEPS"]
