from abc import ABC, abstractmethod
import abc
import asyncio
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
import math
import random
import time
from typing import Any, Coroutine, Generator, Optional, Protocol
from py.pylattice.examples.midi import MIDI
from pylattice.frame import RGB, EndFrame, ModuleFrame
from pylattice.graph import EdgeClass, EdgeRef, Graph, TileRef, VertexClass, EndRef, VertexRef
from pylattice.lattice_client import LatticeClient
from pylattice.lattice_writer import LatticeWriter

from pylattice.examples.tempo import Event, EventLatch, History, periodic, psweep, sweep
from pylattice.examples.colors import hsv, vary, YELLOW_ROSE

from pylattice.examples import artnet

ROWS = 2
COLS = 8

lattice = LatticeWriter(COLS, ROWS)

graph = Graph(COLS*2, ROWS)



midi = MIDI()


def run_artnet(fps: float = 60.0):
    """Drive the lattice from incoming Art-Net - see pylattice.examples.artnet."""
    artnet.run(lattice, graph, fps)


def blend_max(end: EndRef, idx: int, n: list[float]):
    o_r,o_g,o_b = lattice[end][idx]
    n_r,n_g, n_b = n 
    lattice[end][idx] = [max(o_r, n_r), max(o_g, n_g), max(o_b, n_b)]

def adsr(now: Event, trigger: Event, length: int, shape: float) -> float: ...


def get_vertex_down_ends(v: VertexRef):
    return [end for end in graph.VERTEX[0,0].ends_cw() if end.top]

def randown(v: EndRef):
    return random.choice(get_vertex_down_ends(graph.VERTEX[1,2]))

v = graph.VERTEX[0,0]

vec = v.ends_cw()[0].physical_to_next()


ZERO = Event.for_now()

def make_spark_fn(lattice: LatticeWriter, end: EndRef, end_idx: int, fiber_idx: int, colors=YELLOW_ROSE):
    latch = EventLatch()

    def spark_fn(now: Event):
        spark = latch.maybe(now, end.__hash__() + fiber_idx, 2000 + end_idx*13, 0.1)

        if spark is None:
            return
        
        color = colors[(spark.rand() % len(colors))]

        brightness = ...
    

beat_event = EventLatch()

C1 = 36
C4 = 72
midi.on_note(C1, lambda n, on: beat_event.put())
midi.on_note(C4, lambda n, on: beat_event.put())


def trace(now: Event, trigger: Event, base: EndRef, path: str, period: int, rate: float) -> Generator[tuple[float, EndRef]]:
    for i, end in enumerate(base.path(path)):
        d_frac = i / len(path)
        d = sweep(now, trigger.delay(rate * d_frac), period, 0, 1, 0)
        yield (d, end)

beat_event.put()

zap_event = {(end, i): EventLatch() for end in graph.ends() for i in range(4)}


KNOBS = [
    midi.cc(10),
    midi.cc(74)
]

def squeeze_hue(value, start_hue, end_hue):
    # if we want to go eg from purple (eg .8) to orange (eg .05) via red, 
    # we can add 1 to the end_hue and hsv with treat it with a %1 
    if end_hue < start_hue:
        end_hue += 1
    hue_range = end_hue - start_hue
    step = hue_range / 127
    dist = step * value
    return start_hue + dist




while True:
    
    midi.tick()
    lattice.clear()
    now = Event.for_now()

    beat_env = sweep(now, beat_event.read(), 350, 0.5, 0.01, 0.01)
    
    brightness = min(KNOBS[0](), 20) / 20
    hue = squeeze_hue(KNOBS[1]())

    for end in graph.ends():
        #break
        many_tubes = 2
        do_zap = beat_event.read().rand(end.__hash__()) % many_tubes == 0
        
        PERIOD = 100 + (end.__hash__() % 100)
        for i in range(4):
            
        #    hb = (beat_event.read().rand(end.__hash__()) % 10) / 10
        #    hue = vary(now, hb, hb+0.01, PERIOD, i/4)
           value = vary(now, 0.1, 0.3, PERIOD*7.1, i/4)
           saturation = vary(now, .955, 1, PERIOD*3, i/4)
        
           #hue = 0
           #value = 0
           #saturation = 1
           

           if end.top:
               # Only think about bottoms
               continue
           
           
           
           if not do_zap:
               lattice[end][i] = hsv(hue, saturation, value * brightness)
               lattice[end.other()][i] = hsv(hue, saturation, value * brightness)
               continue
            
           #if not do_zap:
               
           #    continue
            
           zap = zap_event[(end, i)].maybe(now, end.__hash__() + i, 40, beat_env)

           zap_env = sweep(now, zap, 50, 1, 0, 0)

           #r = periodic(now, 90).rand(i + end.__hash__()) % 1000
           #if r < 5:

           if zap_env > 0.1:
               hue = hue + 0.5
               value = 0.4 * brightness
               saturation = 1 - zap_env
               lattice[end][i] = hsv(hue, saturation, value)
               lattice[end.other()][i] = hsv(hue, saturation, value)
               
    
    
    # Every beat, there's a random selection of hexagons
    
    if brightness == 0:
        
        last: EndRef | None = None
        for d, end in trace(now, beat_event.read(), graph.TILE[0,0].bottom_end(EdgeClass.E), "LRLRLLL", 300, 200):
            v = math.sin(d * math.pi)
            #print(d)
            blend_max(end, 0, hsv(0.8, 1, v))
            blend_max(last.other(), 0, hsv(0.8, 1, v)) if last else ...
            #lattice[end][0] = hsv(0.8, 1, v)
            last = end
    
    else:
        
        for x in range(0, graph.width):
            for y in range(0, graph.height):
                break
                
                coord = (x,y)
                r = beat_event.read().rand((x,y).__hash__())
                
                if r % 3 != 0:
                    continue
                
                # Randomize for this thing
                max_sweep = 1 + r % 15
                
                for d, end in enumerate(graph.HEX[x, y].ends()):
                    
                    # Rotation
                    #v = psweep(now, beat_event.read(), 3000, 0.1, max_sweep, max_sweep)
                    v = psweep(now, 1500 + (coord.__hash__() % 2000), 0.1, 15)
                    pos = ((math.sin(v) / v) * 16) % 6 // 1
                    
                    #print(pos // 1)
                    #print(max_sweep, v)
                    
                    #s = sweep(now, beat_event.read().delay(100 * (pos - d)), 300, 0, 1, 0)
                    s = 1
                    v = 0.2
                    if pos == d:
                        v = 1
                        s = 0
                    h = r % 100 / 300
                    col = hsv((pos-d) / 6, s, v)
                    #for i in range(4):
                    i = coord.__hash__() % 4
                    lattice[end][i] = col
                    lattice[end.other()][i] = col
        
            

    time.sleep(0.01)
    lattice.show()


