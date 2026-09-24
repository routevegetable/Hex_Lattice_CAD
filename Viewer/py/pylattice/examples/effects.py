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
from pylattice.fields.scalar import CCField, NoteRippleField, NoteWipeField, PolyTouchField, RotaryField
from pylattice.examples.instrument import ColorMap
from pylattice.examples.midi import MIDI
from pylattice.examples.tempo import Event, EventLatch, sweep
from pylattice.graph import EndRef, Graph
from pylattice.lattice_writer import LatticeWriter
from pylattice.runner.preset import Preset, named
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


# A class body, not a SimpleNamespace: the editor infers each attribute's
# type from what it is assigned, so FIELDS.ripple is a NoteRippleField and
# a typo is an error. SimpleNamespace attributes are all Any.
class FIELDS:
    
    # CC fields
    fader_a = CCField(
        midi,
        value=KA1
    )
    fader_b = CCField(
        midi,
        value=KA2
    )
    param_a = CCField(
        midi,
        value=KA3
    )
    param_b = CCField(
        midi,
        value=KA4
    )
    
    # Ripples
    ripple = NoteRippleField(
        graph, midi,
        note=PB1,
        speed=KB1
    )
    ripple2 = NoteRippleField(
        graph, midi,
        note=PB2,
        speed=KB2
    )
    
    # Wipes
    wipe1 = NoteWipeField(
        midi,
        note=PB3,
        speed=KB3
    )
    wipe2 = NoteWipeField(
        midi,
        note=PB4,
        speed=KB4
    )
    
    # Rotary
    rotary = RotaryField(
        graph, midi,
        period=KA5,
        parts=KA6,
        shape=KA7
    )


# This is the living field-slot data structure
class EFFECTS:
    bg_waves = BgWaves(
        hue=FIELDS.param_a,
        value=FIELDS.fader_a
    )
    pluck = Pluck(
        a_amp=FIELDS.wipe2,
        b_amp=FIELDS.wipe1,
        c_amp=FIELDS.wipe1,
        period=FIELDS.param_b,
        value=FIELDS.fader_b
    )
    prob_zaps = ProbZaps( # We're always zappin
        prob=FIELDS.ripple2
    )


p = Preset.capture(midi, FIELDS, EFFECTS)
p.save("preset.json")



# Everything declared in EFFECTS, in the order written - so a preset patches
# the same objects that render.
effects: list[Effect] = list(named(EFFECTS, Effect).values())




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
