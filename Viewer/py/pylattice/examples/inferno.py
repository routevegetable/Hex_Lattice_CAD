from abc import ABC, abstractmethod
import abc
import asyncio
from collections import deque
from collections.abc import Callable, Iterable
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

from stupidArtnet import StupidArtnetServer

ROWS = 2
COLS = 8

lattice = LatticeWriter(COLS, ROWS)

graph = Graph(COLS*2, ROWS)



midi = MIDI()


# Art-Net channel map.
#
# Universe == fiber index: universe 0 drives filament 0 of every end, universe 1
# filament 1, and so on. Inside a universe the tiles follow graph.tiles() order,
# 36 channels each: edge classes A..F, and for each edge the top end's RGB then
# the bottom end's RGB.
#
#   tile block: [A top RGB][A bottom RGB][B top RGB]...[F bottom RGB]
#
# 36 channels per tile means only the first 14 tiles fit in a 512-channel
# universe; tiles past that are not addressable over Art-Net.
ARTNET_EDGE_ORDER = tuple(EdgeClass)
FIBERS = 4
CHANNELS_PER_EDGE = 6                                            # top RGB + bottom RGB
CHANNELS_PER_TILE = len(ARTNET_EDGE_ORDER) * CHANNELS_PER_EDGE   # 36
UNIVERSE_SIZE = 512
TILES_PER_UNIVERSE = UNIVERSE_SIZE // CHANNELS_PER_TILE          # 14


def _artnet_rgb(data, o: int) -> RGB:
    return [data[o] / 255, data[o + 1] / 255, data[o + 2] / 255]


def _paint_universe(tiles: list[TileRef], fiber: int, data) -> None:
    """Paint one universe's DMX frame onto `fiber` of every addressable end."""
    for t, tile in enumerate(tiles):
        base = t * CHANNELS_PER_TILE
        for e, edge_class in enumerate(ARTNET_EDGE_ORDER):
            o = base + e * CHANNELS_PER_EDGE
            if o + CHANNELS_PER_EDGE > len(data):
                return              # short frame: nothing left to read
            lattice[tile.top_end(edge_class)][fiber] = _artnet_rgb(data, o)
            lattice[tile.bottom_end(edge_class)][fiber] = _artnet_rgb(data, o + 3)


def run_artnet(fps: float = 60.0):
    """Receive Art-Net and paint it straight onto the lattice.

    Listens on one universe per fiber (see the channel map above) and redraws at
    `fps`. Blocks until interrupted.
    """
    tiles = list(graph.tiles())[:TILES_PER_UNIVERSE]

    # The server receives on its own thread and keeps the last frame per
    # listener; we sample whatever is in each buffer when we come to draw
    # rather than redrawing from a callback.
    server = StupidArtnetServer()
    listeners = [server.register_listener(fiber) for fiber in range(FIBERS)]

    try:
        while True:
            lattice.clear()
            for fiber, listener in enumerate(listeners):
                _paint_universe(tiles, fiber, server.get_buffer(listener))
            lattice.show()
            time.sleep(1 / fps)
    finally:
        server.delete_all_listener()
        server.close()


class Field(Protocol):
    """
    Something that has a value for each vertex.
    Rotating.
    Wiping.
    Particle distance.
    """
    def get(v: VertexRef) -> float: ...


class ColorMap(Protocol):
    def get(v: float) -> RGB: ...

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

def squeeze_hue(value, min_hue, max_hue):
    hue_range = max_hue - min_hue
    step = hue_range / 127
    dist = step * value
    return min_hue + dist




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


