"""Python port of ts/lib/frame.ts — one module's LED frame + (de)serialisation.

A module has 12 edges (A1..F2); each edge has a top and bottom end; each end
carries 4 filament RGBs (floats 0..1, may exceed 1 to drive bloom). serialize()
packs them into the 4-channel NeoPixel byte stream the hardware expects;
deserialize() is the exact inverse.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum
from typing import Dict, List, Tuple

from .graph import EdgeClass, EndRef

RGB = List[float]          # [r, g, b]
EndFrame = List[RGB]       # 4 filaments

class ModuleEdge(IntEnum):
    A1 = 0
    B1 = 1
    C1 = 2
    D1 = 3
    E1 = 4
    F1 = 5
    A2 = 6
    B2 = 7
    C2 = 8
    D2 = 9
    E2 = 10
    F2 = 11

EDGE_CLASS_TO_MODULE_EDGES: dict[EdgeClass, tuple[ModuleEdge, ModuleEdge]] = {
    EdgeClass.A: (ModuleEdge.A1, ModuleEdge.A2),
    EdgeClass.B: (ModuleEdge.B1, ModuleEdge.B2),
    EdgeClass.C: (ModuleEdge.C1, ModuleEdge.C2),
    EdgeClass.D: (ModuleEdge.D1, ModuleEdge.D2),
    EdgeClass.E: (ModuleEdge.E1, ModuleEdge.E2),
    EdgeClass.F: (ModuleEdge.F1, ModuleEdge.F2),
}


@dataclass
class Ends:
    top: EndFrame
    bottom: EndFrame


@dataclass
class EdgeFrame:
    ends: Ends


CHANNELS = 4
PIXELS_PER_EDGE = 8


class ModuleFrame:
    """12 edges (A1..F2), each with a top and bottom end of 4 filament RGBs."""

    CHANNELS = 4
    PIXELS_PER_EDGE = 8

    def __init__(self, edges: List[EdgeFrame]):
        self.edges = edges

    def __getitem__(self, edge: ModuleEdge) -> EdgeFrame:
        return self.edges[int(edge)]

    @staticmethod
    def blank() -> "ModuleFrame":
        return ModuleFrame([
            EdgeFrame(Ends(
                top=[[0.0, 0.0, 0.0] for _ in range(4)],
                bottom=[[0.0, 0.0, 0.0] for _ in range(4)],
            )) for _ in range(12)
        ])

    def get_end_frame(self, er: EndRef) -> EndFrame:
        # Get the edges for this edge class
        edges = EDGE_CLASS_TO_MODULE_EDGES[er.edge_class]
        # Get the frame for the edge we are interested in
        edge_frame = self[edges[er.tile.x % 2]]

        # Get the appropriate end of the frame
        return edge_frame.ends.top if er.top else edge_frame.ends.bottom