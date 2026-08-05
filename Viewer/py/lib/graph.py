"""Python port of ts/lib/graph.ts — the module/edge/vertex connectivity graph.

Everything outside the app addresses LEDs in module/edge terms. This graph maps
between tiles, edges, ends and vertices so higher-level (hex) authoring can be
translated down to module edges.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import ClassVar, Dict, Iterator, Tuple


class EdgeClass(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"


class VertexClass(str, Enum):
    ABF = "ABF"
    ABC = "ABC"
    CDE = "CDE"
    DEF = "DEF"


@dataclass(frozen=True)
class TileRef:
    x: int
    y: int

    # ClassVar so they aren't __init__ fields; the singletons are attached below.
    THIS: ClassVar["TileRef"]
    LEFT: ClassVar["TileRef"]
    RIGHT: ClassVar["TileRef"]
    UP: ClassVar["TileRef"]
    DOWN: ClassVar["TileRef"]

    @staticmethod
    def from_xy(x: int, y: int) -> "TileRef":
        return TileRef(x, y)

    def offset(self, a):
        """Translate any {tile: TileRef} ref by this tile's offset."""
        return replace(a, tile=a.tile.add(self))

    def negate(self) -> "TileRef":
        return TileRef(-self.x, -self.y)

    def add(self, tr: "TileRef") -> "TileRef":
        return TileRef(self.x + tr.x, self.y + tr.y)

    def edge(self, c: EdgeClass) -> "EdgeRef":
        return EdgeRef(c, self)

    def vertex(self, v: VertexClass) -> "VertexRef":
        return VertexRef(v, self)

    def top_end(self, c: EdgeClass) -> "EndRef":
        return EndRef(c, self, True)

    def bottom_end(self, c: EdgeClass) -> "EndRef":
        return EndRef(c, self, False)


# dataclass turns the annotations above into fields; strip the constant markers
# and attach the real singletons.
for _name in ("THIS", "LEFT", "RIGHT", "UP", "DOWN"):
    TileRef.__dataclass_fields__.pop(_name, None)
TileRef.THIS = TileRef(0, 0)
TileRef.LEFT = TileRef(-1, 0)
TileRef.RIGHT = TileRef(1, 0)
TileRef.UP = TileRef(0, 1)
TileRef.DOWN = TileRef(0, -1)


@dataclass(frozen=True)
class VertexRef:
    vertex_class: VertexClass
    tile: TileRef

    @staticmethod
    def ends_cw(v: "VertexRef") -> Tuple["EndRef", "EndRef", "EndRef"]:
        """Clockwise ends around the vertex; index 0 is always the vertical."""
        s = VERTEX_END_SETS[v.vertex_class]
        points_up = not s.v.top
        order = (s.v, s.r, s.l) if points_up else (s.v, s.l, s.r)
        return tuple(v.tile.offset(x) for x in order)  # type: ignore[return-value]


@dataclass(frozen=True)
class EdgeRef:
    edge_class: EdgeClass
    tile: TileRef

    @staticmethod
    def ends(e: "EdgeRef") -> Tuple["EndRef", "EndRef"]:
        return (EndRef(e.edge_class, e.tile, True),
                EndRef(e.edge_class, e.tile, False))

    @staticmethod
    def vertex_pair(e: "EdgeRef") -> "EdgeVertexPair":
        p = EDGE_VERTEX_PAIRS[e.edge_class]
        return EdgeVertexPair(e.tile.offset(p.top), e.tile.offset(p.bottom))


@dataclass(frozen=True)
class EndRef(EdgeRef):
    top: bool

    @staticmethod
    def other(er: "EndRef") -> "EndRef":
        return replace(er, top=not er.top)

    @staticmethod
    def vertex(e: "EndRef") -> VertexRef:
        vp = EdgeRef.vertex_pair(e)
        return vp.top if e.top else vp.bottom

    @staticmethod
    def lr(er: "EndRef") -> Tuple["EndRef", "EndRef"]:
        cw = VertexRef.ends_cw(EndRef.vertex(er))
        if cw[0].edge_class == er.edge_class:
            return (cw[1], cw[2])
        elif cw[1].edge_class == er.edge_class:
            return (cw[2], cw[0])
        else:
            return (cw[0], cw[1])


@dataclass(frozen=True)
class EndSet:
    v: EndRef
    l: EndRef
    r: EndRef


@dataclass(frozen=True)
class EdgeVertexPair:
    top: VertexRef
    bottom: VertexRef


VERTEX_END_SETS: Dict[VertexClass, EndSet] = {
    VertexClass.ABC: EndSet(
        v=TileRef.THIS.top_end(EdgeClass.C),
        l=TileRef.LEFT.bottom_end(EdgeClass.B),
        r=TileRef.THIS.bottom_end(EdgeClass.A),
    ),
    VertexClass.ABF: EndSet(
        v=TileRef.UP.bottom_end(EdgeClass.F),
        l=TileRef.THIS.top_end(EdgeClass.A),
        r=TileRef.THIS.top_end(EdgeClass.B),
    ),
    VertexClass.CDE: EndSet(
        v=TileRef.THIS.bottom_end(EdgeClass.C),
        l=TileRef.LEFT.top_end(EdgeClass.E),
        r=TileRef.THIS.top_end(EdgeClass.D),
    ),
    VertexClass.DEF: EndSet(
        v=TileRef.THIS.top_end(EdgeClass.F),
        l=TileRef.THIS.bottom_end(EdgeClass.D),
        r=TileRef.THIS.bottom_end(EdgeClass.E),
    ),
}

EDGE_VERTEX_PAIRS: Dict[EdgeClass, EdgeVertexPair] = {
    EdgeClass.A: EdgeVertexPair(VertexRef(VertexClass.ABF, TileRef.THIS),
                                VertexRef(VertexClass.ABC, TileRef.THIS)),
    EdgeClass.B: EdgeVertexPair(VertexRef(VertexClass.ABF, TileRef.THIS),
                                VertexRef(VertexClass.ABC, TileRef.RIGHT)),
    EdgeClass.C: EdgeVertexPair(VertexRef(VertexClass.ABC, TileRef.THIS),
                                VertexRef(VertexClass.CDE, TileRef.THIS)),
    EdgeClass.D: EdgeVertexPair(VertexRef(VertexClass.CDE, TileRef.THIS),
                                VertexRef(VertexClass.DEF, TileRef.THIS)),
    EdgeClass.E: EdgeVertexPair(VertexRef(VertexClass.CDE, TileRef.RIGHT),
                                VertexRef(VertexClass.DEF, TileRef.THIS)),
    EdgeClass.F: EdgeVertexPair(VertexRef(VertexClass.DEF, TileRef.THIS),
                                VertexRef(VertexClass.ABF, TileRef.DOWN)),
}


@dataclass(frozen=True)
class HexGridCoord:
    x: int
    y: int

    @staticmethod
    def ends(gc: "HexGridCoord") -> Iterator[EndRef]:
        """The 12 ends (top/bottom of each of 6 edges) around a hexagon."""
        if gc.y % 2 == 0:
            vertex = TileRef(gc.x, gc.y // 2).vertex(VertexClass.DEF)
        else:
            vertex = TileRef(gc.x + 1, gc.y // 2).vertex(VertexClass.ABC)

        below = VertexRef.ends_cw(vertex)[0]     # top of the vertical below the vertex
        current = EndRef.lr(below)[1]

        for _ in range(6):
            yield current
            current = EndRef.other(current)
            yield current
            current = EndRef.lr(current)[0]
