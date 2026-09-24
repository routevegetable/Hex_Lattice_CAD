# Waves effect
from collections.abc import Iterable
import gc
import math
import time
from typing import Callable
from pylattice.effects.pluck import Pluck
from pylattice.effects.boom_zaps import ProbZaps, init_boom_zaps, prob_zaps, run_boom_zaps
from pylattice.effects.waves import BgWaves, bg_waves
from pylattice.examples.colors import hsv, vary
from pylattice.fields.types import ConstantField, ScalarField
from pylattice.fields.scalar import CCField, NoteRippleField, PolyTouchField, RotaryField
from pylattice.examples.instrument import ColorMap
from pylattice.examples.midi import MIDI
from pylattice.examples.tempo import Event, EventLatch, sweep
from pylattice.graph import EndRef, Graph
from pylattice.lattice_writer import LatticeWriter
from pylattice.runner.types import Effect


COLS = 16
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


param = CCField(
    midi,
    value=KA1
)

polytouch = PolyTouchField(
    midi,
    note=PA1
)

ripple = NoteRippleField(
    graph, midi,
    note=PA1,
    speed=KA8
)

ripple2 = NoteRippleField(
    graph, midi,
    note=PA2,
    speed=KA8
)

rotary = RotaryField(
    graph, midi,
    period=KA2,
    parts=KA3,
    shape=KA4
)

# Built from the fields above
zap_prob = ripple * polytouch

effects: list[Effect] = [
    BgWaves(
        hue=param,
        value=param
    ),
    #Pluck(
    #    a_amp=rotary,
    #    b_amp=ripple,
    #    c_amp=ripple2,
    #    period=param
    #),
    ProbZaps(
        prob=ripple2
    ),
]



C1 = 36
C4 = 72


init_boom_zaps(graph, lattice)



# PyPy collects incrementally, so a bounded step per frame is what its GC
# wants. CPython has no such thing - the youngest generation is the cheap
# equivalent.
gc_step = getattr(gc, "collect_step", None) or (lambda: gc.collect(0))

frames = 0
counted_from = Event.for_now()

render_len = 0
gc_len = 0

while True:
    t0 = time.time_ns()
    lattice.clear()

    now = Event.for_now()
    midi.tick()

    for effect in effects:
        effect.render(now, lattice, graph)
    lattice.show()

    frames += 1
    elapsed = now.when - counted_from.when
    if elapsed >= 1000:
        print(f"{frames * 1000 / elapsed:.1f} fps (Render: {dt_render/1000000}ms GC: {dt_gc/1000000}ms)")
        frames = 0
        counted_from = now

    # Do GC every frame
    t1 = time.time_ns()
    gc_step()
    dt_gc = time.time_ns() - t1
    dt_render = t1 - t0
    
    
    time.sleep(0.002)
    
    # To sec
    dt = (t1 - t0) / 1000000000
    
    PERIOD = 0.001
    if dt < PERIOD:
        time.sleep(PERIOD - dt)
        
    
    
    continue


    # Background effects
    
    # Note effects
    
    # Impulse effects
    
    
    bg_waves(graph, lattice, now, param_field, note_wipe)
    
    #run_boom_zaps(now)
    prob_zaps(now, polytouch_field * note_wipe)
    
    lattice.show()
    time.sleep(0.05)
