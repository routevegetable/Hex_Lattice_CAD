# Waves effect
from collections.abc import Iterable
import gc
import math
import time
from typing import Callable
from pylattice.effects.pluck import Pluck, WobbleNet
from pylattice.effects.boom_zaps import ProbZaps, init_boom_zaps, prob_zaps, run_boom_zaps
from pylattice.effects.waves import BgWaves, bg_waves
from pylattice.examples.colors import hsv, vary
from pylattice.fields.types import ConstantField, ScalarField, Slot, UnconnectedSlot
from pylattice.instrument.maps import ColorMap
from pylattice.examples.tempo import Event, EventLatch, sweep
from pylattice.graph import EdgeClass, EndRef, Graph
from pylattice.lattice_writer import LatticeWriter
from pathlib import Path
from pylattice.instrument.api import serve
from pylattice.instrument.fields import FIELDS
from pylattice.instrument.hardware import STEPS, graph, lattice, midi
from pylattice.instrument.console import Console
from pylattice.instrument.patch import Patch, PresetBank, named
from pylattice.instrument.types import Effect






from pylattice.examples.sunrise import color_transitions, sunrise

class Sunrise(Effect):
    value: Slot

    def draw_sunrise(self):
        sunrise(color_transitions)

    def render(self, now: Event, lattice: LatticeWriter, graph: Graph):
        return




class BisexualSpin(Effect):
    value: Slot
    speed: Slot


    def draw_hex(self, base: EndRef, lattice: LatticeWriter):
        val = self.value.get(now, base)
        if val < 0.1:
            return
        hue = 0.8

        period = self.speed.get(now, base) * 10000 + 1

        if period > 500:
            period = 10000
        else:
            period = 500

        for dist, end in enumerate(base.path("RRRRR")):

            f = dist / 6

            #hue = vary(now, 0.66, 1, 5000, f)

            for i in range(4):

                hue = vary(now, 0.66, 1.02, period, f + i*0.05)
                #print(hue)
                col = list(hsv(hue, 1, val))
                lattice[end][i] = col
                lattice[end.lr()[0]][i] = col




    def render(self, now: Event, lattice: LatticeWriter, graph: Graph):


        for base in [
            graph.TILE[0,0].bottom_end(EdgeClass.D),
            graph.TILE[1,0].bottom_end(EdgeClass.B),
            graph.TILE[3,1].bottom_end(EdgeClass.D),
            graph.TILE[4,0].bottom_end(EdgeClass.B),
        ]:
            self.draw_hex(base, lattice)

        return

class DumbEffect(Effect):
    value: Slot
    def render(self, now: Event, lattice: LatticeWriter, graph: Graph):

        for end in graph.ends():

            val = self.value.get(now, end)

            lattice[end][0] = [val, val, 1]

        return


class MapFiber(Effect):
    value: Slot
    hue: Slot
    saturation: Slot
    def render(self, now: Event, lattice: LatticeWriter, graph: Graph):

        for end in graph.ends():

            val = self.value.get(now, end)
            hue = self.hue.get(now, end)
            saturation = self.saturation.get(now, end)


            if val > 0.1:
                lattice[end][0] = list(hsv(hue, saturation, val))
            if val > 0.3:
                lattice[end][1] = list(hsv(hue, saturation, val/2))
            if val > 0.6:
                lattice[end][2] = list(hsv(hue, saturation, val/3))
            if val > 0.8:
                lattice[end][3] = list(hsv(hue, saturation, val/4))

        return


# This is the living field-slot data structure
class EFFECTS:

    bg_waves = BgWaves(
        hue=FIELDS.param_a,
        value=FIELDS.fader_a,
        flow=0
    )
    bg_waves2 = BgWaves(
        hue=FIELDS.param_a,
        value=FIELDS.fader_a,
        flow=0
    )
    net = WobbleNet(
        amp=FIELDS.ripple2,
        hue=FIELDS.param_b,
        value=FIELDS.fader_b
    )
    sunrise = Sunrise( 
        value=FIELDS.param_a,
    )
    bisexual = BisexualSpin(
        value = FIELDS.param_a,
        speed = FIELDS.param_b
    )
    prob_zaps = ProbZaps(
        prob=FIELDS.ripple2
    )
    map_fiber = MapFiber(
        value=0,
        hue=0,
        saturation=0
    )
    map_fiber2 = MapFiber(
        value=0,
        hue=0,
        saturation=0
    )
    map_fiber3 = MapFiber(
        value=0,
        hue=0,
        saturation=0
    )


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
        CONSOLE.load_current_from(number)
        print(f"preset {number} loaded")
    except (FileNotFoundError, ValueError) as e:
        print(f"preset {number}: {e}")


# Start from preset 0 - the knobs and wiring are only remembered by presets.
load_preset(0)

# A step button loads the preset of the same number, and so does a program
# change - the BSP sends one per project, and a sequencer upstream can send
# them wherever it likes.
step_ccs = [midi.cc(cc, f"preset {n}", hidden=True)
            for n, cc in enumerate(STEPS[:BANK.size])]
step_seen = [0] * len(step_ccs)

program = midi.program()
program_seen = 0


def check_steps():
    """Load a preset when its step button is newly pressed - a CC of 127."""
    for number, watch in enumerate(step_ccs):
        moved = watch()

        if moved.when == step_seen[number] or moved.data != 127:
            continue        # not new, or the button coming back up

        step_seen[number] = moved.when
        load_preset(number)


def check_program():
    """Load a preset when a program change picks it."""
    global program_seen

    chosen = program()

    if chosen.when == program_seen:
        return              # nothing new - the seed included

    program_seen = chosen.when

    if chosen.data >= BANK.size:
        print(f"program {chosen.data}: only {BANK.size} presets")
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
        check_steps()
        check_program()

        for effect in effects:
            try:
                effect.render(now, lattice, graph)
            except UnconnectedSlot:
                pass        # nothing plugged into it - it just does not draw
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
