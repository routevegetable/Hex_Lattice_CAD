# Waves effect
from collections.abc import Iterable
import gc
import math
import time
import traceback
from typing import Callable
from pylattice.effects.bisexual_spin import BisexualSpin
from pylattice.effects.map_fiber import MapFiber
from pylattice.effects.map_tiles import MapTiles
from pylattice.effects.sunrise import Sunrise
from pylattice.effects.pluck import Pluck, WobbleNet
from pylattice.effects.boom_zaps import ProbZaps, init_boom_zaps, prob_zaps, run_boom_zaps
from pylattice.effects.waves import BgWaves, bg_waves
from pylattice.examples.colors import hsv, vary
from pylattice.fields.types import Slot
from pylattice.instrument.maps import ColorMap
from pylattice.examples.tempo import Event, EventLatch, sweep
from pylattice.graph import EdgeClass, EndRef, Graph
from pylattice.lattice_writer import LatticeWriter
from pathlib import Path
from pylattice.instrument.api import serve
from pylattice.instrument.fields import FIELDS
from pylattice.instrument.hardware import graph, lattice, midi
from pylattice.instrument.console import Console
from pylattice.instrument.patch import Patch, PresetBank, named
from pylattice.instrument.types import Effect






class DumbEffect(Effect):
    value: Slot
    def render(self, now: Event, lattice: LatticeWriter, graph: Graph):

        for end in graph.ends():

            val = self.value.get(now, end)

            lattice[end][0] = [val, val, 1]

        return


# This is the living field-slot data structure
class EFFECTS:
    """The effects that draw, in the order they draw in.

    Nothing is wired here - every slot starts on a constant 0 and the preset
    loaded at startup says what actually drives what.
    """

    bg_waves = BgWaves()
    bg_waves2 = BgWaves()
    net = WobbleNet()
    prob_zaps = ProbZaps(midi.for_("prob_zaps"))
    map_fiber = MapFiber()
    map_fiber2 = MapFiber()
    map_fiber3 = MapFiber()
    #map_tiles = MapTiles()

    # Parked: no longer offered. Presets that name them skip those slots.
    #sunrise = Sunrise()
    #bisexual = BisexualSpin()


# Everything declared in EFFECTS, in the order written - so a preset patches
# the same objects that render.
effects: list[Effect] = list(named(EFFECTS, Effect).values())




init_boom_zaps(graph, lattice)


BANK = PresetBank(Path("presets"))
CONSOLE = Console(midi, FIELDS, EFFECTS, BANK)
serve(CONSOLE)

def load_preset(number: int):
    """Switch the bank to a preset, saying so either way."""
    try:
        CONSOLE.select_preset(number)
        print(f"preset {number} loaded")
    except (FileNotFoundError, ValueError) as e:
        print(f"preset {number}: {e}")


# Start from preset 0 - the knobs and wiring are only remembered by presets.
load_preset(0)

# A program change loads the preset of the same number - the BSP sends one per
# project, and a sequencer upstream can send them wherever it likes.
program = midi.program()
program_seen = 0


def check_program():
    """Load a preset when a program change picks it."""
    global program_seen

    chosen = program()

    if chosen.when == program_seen:
        return              # nothing new - the seed included

    program_seen = chosen.when

    if chosen.data not in BANK.numbers():
        print(f"program {chosen.data}: no such preset")
        return

    load_preset(chosen.data)



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

    # The API thread takes this same lock, so a preset can never land halfway
    # through a frame.
    with CONSOLE.lock:
        lattice.clear()

        now = Event.for_now()
        midi.tick()
        check_program()

        for effect in effects:
            if effect.active and not effect.muted:
                effect.render(now, lattice, graph)
        lattice.show()

    frames += 1
    elapsed = now.when - counted_from.when
    if elapsed >= 1000:
        fps = frames * 1000 / elapsed
        print(f"{fps:.1f} fps (Render: {dt_render/1000000}ms GC: {dt_gc/1000000}ms)")
        CONSOLE.set_stats(fps, dt_render / 1000000, dt_gc / 1000000)
        frames = 0
        counted_from = now

    # Do GC every frame
    t1 = time.time_ns()
    gc_step()
    dt_gc = time.time_ns() - t1
    dt_render = t1 - t0
    
    
    time.sleep(0.02)
    
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
