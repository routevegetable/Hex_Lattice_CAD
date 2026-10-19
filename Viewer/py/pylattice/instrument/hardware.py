"""What the instrument is plugged into: the lattice, and the box on the desk.

These are module-level singletons because there is one of each per process -
importing this opens the MIDI port.
"""
from pylattice.examples.midi import MIDI
from pylattice.graph import Graph
from pylattice.lattice_writer import LatticeWriter


COLS = 6
ROWS = 2

graph = Graph(COLS, ROWS)

lattice = LatticeWriter(COLS / 2, ROWS)
#midi = MIDI('Arturia BeatStep Pro Arturia BeatStepPro')
midi = MIDI()

# BSP control mode. Knobs KA1-KB8 are CCs, pads PA1-PB8 are notes; row A is
# the top/upper one.
KA1, KA2, KA3, KA4, KA5, KA6, KA7, KA8 = 10, 74, 71, 76, 77, 93, 73, 75
KB1, KB2, KB3, KB4, KB5, KB6, KB7, KB8 = 114, 18, 19, 16, 17, 91, 79, 72

PA1, PA2, PA3, PA4, PA5, PA6, PA7, PA8 = 44, 45, 46, 47, 48, 49, 50, 51
PB1, PB2, PB3, PB4, PB5, PB6, PB7, PB8 = 36, 37, 38, 39, 40, 41, 42, 43

# The step buttons. They send CCs 20-55, a press arriving as 127. Nothing
# watches them - presets are selected by program change - so they are here as
# a note of what the box sends rather than as something wired up.
STEPS = list(range(20, 56))
