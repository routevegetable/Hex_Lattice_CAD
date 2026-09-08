from abc import ABC, abstractmethod
import abc
import asyncio
from collections import deque
from collections.abc import Callable, Iterable
import math
import random
import time
from typing import Any, Coroutine, Generator, Optional
from pylattice.frame import RGB, EndFrame, ModuleFrame
from pylattice.graph import EdgeClass, EdgeRef, Graph, TileRef, VertexClass, EndRef, VertexRef
from pylattice.lattice_client import LatticeClient
from pylattice.lattice_writer import LatticeWriter

from pylattice.examples.tempo import Event, EventLatch, History, periodic, psweep, sweep
from pylattice.examples.colors import vary, YELLOW_ROSE

ROWS = 2
COLS = 8

lattice = LatticeWriter(COLS, ROWS)

graph = Graph(COLS*2, ROWS)

def get_vertex_down_ends(v: VertexRef):
    return [end for end in graph.VERTEX[0,0].ends_cw() if end.top]

def randown(v: EndRef):
    return random.choice(get_vertex_down_ends(graph.VERTEX[1,2]))

v = graph.VERTEX[0,0]

vec = v.ends_cw()[0].physical_to_next()

def hsv(h: float, s: float, v: float) -> tuple[float,float,float]:
    h = (h % 1 + 1) % 1
    i = int(h * 6)
    f = h * 6 - i
    p, q, u = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    return [(v, u, p), (q, v, p), (p, v, u), (p, q, v), (u, p, v), (v, p, q)][i % 6]


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
           hue = vary(now, .67, .7, PERIOD, i/4)
           value = vary(now, 0, .1, PERIOD*7.1, i/4)
           saturation = vary(now, .7, 1, PERIOD*3, i/4)

           lattice[end][i] = hsv(hue, saturation, value)

    time.sleep(0.02)
    lattice.show()


