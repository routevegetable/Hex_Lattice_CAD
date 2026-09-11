"""Scratch example: paint specific edges of specific modules.

1. python3 serve.py                 # creates the socket + serves the viewer
2. python3 -m pylattice.examples.tinkering
"""

import time

from pylattice.format import STANDARD_MODULE
from pylattice import ModuleEdge, ModuleFrame, LatticeClient
from pylattice.examples.tempo import Event
from pylattice.examples.colors import vary, hsv

FPS = 60

CYAN = (0, 255, 255)
PINK = (255, 0, 128)
GREEN = (0, 255, 0)

UNDULATE_PERIOD = 3000  # ms - Event.when (and so vary/psweep) counts in ms


def _unit(col):
    return [c / 255 for c in col]


def paint(mf: ModuleFrame, edge: ModuleEdge, color) -> None:
    ends = mf[edge].ends
    for f in range(4):
        ends.top[f][:] = _unit(color)
        ends.bottom[f][:] = _unit(color)


def undulate(
    mf: ModuleFrame,
    edge: ModuleEdge,
    now: Event,
    period: int,
    hue: tuple[float, float] = (0.0, 0.0),
    hue_offset: float = 0,
    sat: tuple[float, float] = (1.0, 1.0),
    sat_offset: float = 0,
    val: tuple[float, float] = (1.0, 1.0),
    val_offset: float = 0,
    fibers: tuple[int, ...] = (0, 1, 2, 3),
) -> None:
    h = vary(now, hue[0], hue[1], period, hue_offset)
    s = vary(now, sat[0], sat[1], period, sat_offset)
    v = vary(now, val[0], val[1], period, val_offset)
    color = hsv(h, s, v)
    ends = mf[edge].ends
    for f in fibers:
        ends.top[f][:] = color
        ends.bottom[f][:] = color


client = LatticeClient()

mf_0_0 = ModuleFrame.blank()
mf_0_0_edges = [
    ModuleEdge.A1,
    ModuleEdge.B1,
    ModuleEdge.E1,
    ModuleEdge.A2,
    ModuleEdge.B2,
    ModuleEdge.D2,
    ModuleEdge.C2,
]

mf_1_0 = ModuleFrame.blank()

mf_1_0_edges = [
    ModuleEdge.F1,
    ModuleEdge.F2,
    ModuleEdge.E1,
    ModuleEdge.D2,
    ModuleEdge.D1,
    ModuleEdge.E2,
    ModuleEdge.C2,
]


def trees():
    while True:
        now = Event.for_now()
        for edge in mf_1_0_edges:
            for fiber in range(4):
                offset = fiber / 4
                undulate(
                    mf_1_0,
                    edge,
                    now,
                    UNDULATE_PERIOD,
                    hue=(0.01, 0.15),
                    hue_offset=UNDULATE_PERIOD * offset,
                    fibers=(fiber,),
                )
        for edge in mf_0_0_edges:
            for fiber in range(4):
                offset = fiber / 4
                undulate(
                    mf_0_0,
                    edge,
                    now,
                    UNDULATE_PERIOD,
                    hue=(0.01, 0.15),
                    hue_offset=UNDULATE_PERIOD * offset,
                    fibers=(fiber,),
                )
        data_1_0 = STANDARD_MODULE.serialize(mf_1_0)
        data_0_0 = STANDARD_MODULE.serialize(mf_0_0)
        client.send(1, 0, data_1_0)
        client.send(0, 0, data_0_0)
        time.sleep(1 / FPS)


trees()
