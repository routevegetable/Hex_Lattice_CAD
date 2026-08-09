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

try:                                    # as a package (py.lib.frame)
    from .graph import EdgeClass, EndRef
except ImportError:                     # as loose modules on sys.path
    from graph import EdgeClass, EndRef


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


RGB = List[float]          # [r, g, b]
EndFrame = List[RGB]       # 4 filaments


@dataclass
class Ends:
    top: EndFrame
    bottom: EndFrame


@dataclass
class EdgeFrame:
    ends: Ends


# channel -> ordered [(edge, points_up)]
CHANNEL_EDGES: Dict[int, List[Tuple[ModuleEdge, bool]]] = {
    0: [(ModuleEdge.D1, True), (ModuleEdge.C1, True), (ModuleEdge.A1, True),
        (ModuleEdge.B1, False), (ModuleEdge.E2, True)],
    1: [(ModuleEdge.E1, True), (ModuleEdge.C2, True), (ModuleEdge.A2, True),
        (ModuleEdge.B2, False)],
    2: [(ModuleEdge.D2, False), (ModuleEdge.F2, False)],
    3: [(ModuleEdge.F1, False)],
}

EDGE_CLASS_TO_MODULE_EDGES: Dict[EdgeClass, Tuple[ModuleEdge, ModuleEdge]] = {
    EdgeClass.A: (ModuleEdge.A1, ModuleEdge.A2),
    EdgeClass.B: (ModuleEdge.B1, ModuleEdge.B2),
    EdgeClass.C: (ModuleEdge.C1, ModuleEdge.C2),
    EdgeClass.D: (ModuleEdge.D1, ModuleEdge.D2),
    EdgeClass.E: (ModuleEdge.E1, ModuleEdge.E2),
    EdgeClass.F: (ModuleEdge.F1, ModuleEdge.F2),
}

CHANNELS = 4
PIXELS_PER_EDGE = 8


def _byte(c: float) -> int:
    # Match JS Math.round (round half up) so bytes are identical across ports.
    return max(0, min(255, math.floor(c * 255 + 0.5)))


class ModuleFrame:
    """12 edges (A1..F2), each with a top and bottom end of 4 filament RGBs."""

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
        a, b = EDGE_CLASS_TO_MODULE_EDGES[er.edge_class]
        e = self[a if er.tile.x % 2 == 0 else b]
        return e.ends.top if er.top else e.ends.bottom

    @staticmethod
    def _ser_end(e: EndFrame, out: bytearray, flip: bool) -> None:
        # `flip` reverses the 4-LED order — the strip runs down one end and back
        # up the other, so the latter end of each edge is wired in reverse.
        for px in (reversed(e) if flip else e):
            out.append(_byte(px[0]))
            out.append(_byte(px[1]))
            out.append(_byte(px[2]))

    def serialize(self) -> bytes:
        out = bytearray()
        for ch in range(CHANNELS):
            edges = CHANNEL_EDGES[ch]
            out.append(len(edges) * PIXELS_PER_EDGE)      # channel pixel count
            for edge, points_up in edges:
                e = self[edge]
                if points_up:
                    ModuleFrame._ser_end(e.ends.bottom, out, False)
                    ModuleFrame._ser_end(e.ends.top, out, True)
                else:
                    ModuleFrame._ser_end(e.ends.top, out, False)
                    ModuleFrame._ser_end(e.ends.bottom, out, True)
        return bytes(out)

    @staticmethod
    def _deser_end(e: EndFrame, data: bytes, o: int, flip: bool) -> int:
        # `flip` reverses the LED order to match _ser_end.
        for j in range(4):
            i = 3 - j if flip else j
            e[i][0] = data[o] / 255
            e[i][1] = data[o + 1] / 255
            e[i][2] = data[o + 2] / 255
            o += 3
        return o

    def deserialize(self, data: bytes) -> None:
        """Inverse of serialize: parse `data` back into this frame, in place."""
        o = 0
        for ch in range(CHANNELS):
            o += 1                                          # skip the pixel-count byte
            for edge, points_up in CHANNEL_EDGES[ch]:
                e = self[edge]
                if points_up:
                    o = ModuleFrame._deser_end(e.ends.bottom, data, o, False)
                    o = ModuleFrame._deser_end(e.ends.top, data, o, True)
                else:
                    o = ModuleFrame._deser_end(e.ends.top, data, o, False)
                    o = ModuleFrame._deser_end(e.ends.bottom, data, o, True)
