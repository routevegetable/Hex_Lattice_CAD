# Waves effect
from collections.abc import Iterable
import math
import time
from typing import Callable
from py.pylattice.effects.boom_zaps import init_boom_zaps, prob_zaps, run_boom_zaps
from py.pylattice.effects.waves import bg_waves
from py.pylattice.examples.colors import hsv, vary
from py.pylattice.examples.instrument import CCField, ColorMap, NoteWipeField, RotaryField, ScalarField
from py.pylattice.examples.midi import MIDI
from py.pylattice.examples.tempo import Event, EventLatch, sweep
from py.pylattice.graph import EndRef, Graph
from py.pylattice.lattice_writer import LatticeWriter


COLS = 16
ROWS = 2

graph = Graph(COLS, ROWS)

lattice = LatticeWriter(COLS / 2, ROWS)

midi = MIDI()




C1 = 36
C4 = 72

param_field = CCField(midi, value_cc=10)

rotary = RotaryField(graph, midi,
                        period_cc=74,
                        parts_cc=71,
                        shape_cc=76)

note_wipe = NoteWipeField(midi,
                          note=44,
                          speed_cc=75)


#midi.on_note(C1, lambda n, on: beat_event.put())
#midi.on_note(C4, lambda n, on: beat_event.put())

init_boom_zaps(graph, lattice)

while True:
    lattice.clear()

    now = Event.for_now()
    midi.tick()

    bg_waves(graph, lattice, now, param_field, note_wipe)
    
    #run_boom_zaps(now)
    prob_zaps(now, rotary + note_wipe)
    
    lattice.show()
    time.sleep(0.05)
