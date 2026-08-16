from collections.abc import Callable
import math
import random
import time
from typing import Any, Optional
from pylattice.frame import EndFrame, ModuleFrame
from pylattice.graph import HEX, VERTEX, TileRef, VertexClass, EndRef, VertexRef
from pylattice.lattice_client import LatticeClient
from pylattice.lattice_writer import LatticeWriter

from pylattice.examples.tempo import Event, EventLatch, psweep, sweep

ROWS = 2
COLS = 8

lattice = LatticeWriter(COLS, ROWS)



def get_vertex_down_ends(v: VertexRef):
    return [end for end in VERTEX[0,0].ends_cw() if end.top]

def randown(v: EndRef):
    return random.choice(get_vertex_down_ends(VERTEX[1,2]))


def hsv(h: float, s: float, v: float) -> tuple[float,float,float]:
    h = (h % 1 + 1) % 1
    i = int(h * 6)
    f = h * 6 - i
    p, q, u = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    return [(v, u, p), (q, v, p), (p, v, u), (p, q, v), (u, p, v), (v, p, q)][i % 6]


# Want a latch per filament
# Actually want a function to take a latch and write it to the appropriate frame

ZERO = Event.for_now()



def make_filament_fn(end: EndRef, idx: int) -> Callable[[Event[Any]],None]:
    latch: EventLatch[Any] = EventLatch()

    def filament_fn(now: Event[Any]):

        gate_prob = psweep(now, 6000, 0, 0.7)
        gate_prob = gate_prob * gate_prob

        # Random trigger
        trg = latch.maybe(now, idx + end.__hash__(), 100, gate_prob)

        # Saturation envelope
        s = sweep(now, trg, 100, 0.7, 1)

        # Value envelope
        v = sweep(now, trg, 200, 1, 0, 0)

        # Color
        color = hsv(0.7, s, v)

        # This end
        lattice[end][idx] = [*color]

        # Other end
        lattice[end.other()][idx] = [*color]

    return filament_fn

filament_fns: list[Callable[[Event[Any]], None]] = []

# For each end, make a filament render function
for x in range(0, 10):
    for end in HEX[x,1].ends():
        for i in range(0,4):
            filament_fns.append(make_filament_fn(end, i))
    

while True:
    lattice.clear()

    # Render filaments
    for fn in filament_fns:
        fn(Event.for_now())

    time.sleep(0.04)
    lattice.show()
    continue

    # Clockwise
    for v_end in VERTEX[1,3].ends_cw():

        # Draw a 'line'
        for dist, end in enumerate(v_end.path("RRRLR")):

            # Light up both ends of each filament
            for j in range(0,4):
                lattice[end][j] = [255,0,0]
                
                other = end.other()
                lattice[other][j] = [0,0,255]

    if False:
            i = int(time.monotonic()*10) % 6
            for j, end in enumerate(HEX[2,0].rotate(i).ends()):
                if j % 3 == 0:
                    continue
                lattice[end][0][j % 3] = 1

                other = end.other()
                lattice[other][2][j % 3] = 1

    #down = randown(current)
    # Down is a down-pointing end
    lattice.show()
    time.sleep(0.001)
    

# Send frames