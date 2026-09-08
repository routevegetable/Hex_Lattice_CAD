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

ROWS = 2
COLS = 8

lattice = LatticeWriter(COLS, ROWS)

graph = Graph(COLS*2, ROWS)

midi = MIDI()

CC_THING = midi.cc(3)

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
    

while True:
    lattice.clear()
    now = Event.for_now()

    for end in graph.ends():
        PERIOD = 200 + (end.__hash__() % 200)
        for i in range(4):
           
           
           hb = 0# i / 4
           hue = vary(now, hb, hb+0.03, PERIOD, i/4)
           value = vary(now, 0.3, 0.5, PERIOD*7.1, i/4)
           saturation = vary(now, .955, 1, PERIOD*3, i/4)
        
           #hue = 0
           value = 0.7
           saturation = 1
           r = periodic(now, 70).rand(i + end.__hash__()) % 1000
           if r < 40:
               #hue = 0.03
               value = 1
               saturation = 0
               lattice[end][i] = hsv(hue, saturation, value)
               lattice[end.other()][i] = hsv(hue, saturation, value)
           else:
               lattice[end][i] = hsv(hue, saturation, value)
           #break

    time.sleep(0.01)
    lattice.show()


