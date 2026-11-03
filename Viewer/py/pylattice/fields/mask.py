"""Which edges count: fields that are 1 on some of the edges and 0 on the rest."""
from collections.abc import Iterator

from pylattice.examples.midi import CustomChoice, MIDIFor
from pylattice.examples.tempo import Event, ZERO
from pylattice.fields.types import ScalarField
from pylattice.graph import EdgeClass, EdgeRef, EndRef, Graph, TileRef


# The edge classes that make up each named family, declared here rather than
# at the masks in instrument/fields.py so that the one set serves both them
# and whatever else picks edges by direction.
#
# H, D1 and D2 are each four classes, and they are families of continuous
# zigzag lines running one way across the lattice: every vertex has exactly
# two of its three ends in each of them, so the lines pass through every
# vertex and never stop. V is the odd one out - two classes, one end per
# vertex, so it is single edges standing apart rather than lines.
V = frozenset({EdgeClass.C, EdgeClass.F})
H = frozenset({EdgeClass.A, EdgeClass.B, EdgeClass.D, EdgeClass.E})
D1 = frozenset({EdgeClass.A, EdgeClass.C, EdgeClass.E, EdgeClass.F})
D2 = frozenset({EdgeClass.B, EdgeClass.C, EdgeClass.D, EdgeClass.F})

# The three a direction can be picked from. V is not among them: a single
# class, or a pair of them standing apart, is not a direction to run in.
FAMILIES = [("d1", D1), ("d2", D2), ("h", H)]


class EdgeMaskField(ScalarField):
    def __init__(self, edges: frozenset[EdgeClass]):
        self._edges = edges

    def get(self, now: Event, end: EndRef) -> float:

        return 1 if end.edge_class in self._edges else 0


def _crosses(end: EndRef, height: float) -> bool:
    """Does this edge join the top of the lattice to the bottom?

    The graph wraps both ways, but only sideways is real: an edge whose two
    vertices are a whole lattice apart in y is one the walk is not allowed to
    take. On this lattice that is the F edges, one to a column.
    """
    return abs(end.other().vertex().physical()[1]
               - end.vertex().physical()[1]) > height / 2


def onward(end: EndRef, classes: frozenset[EdgeClass]) -> EndRef:
    """The one way on from an end, staying in the family.

    A family leaves exactly two of a vertex's three ends in it, so there is
    never a choice: arrive along one and the other is the way on.
    """
    on = [o for o in end.other().lr() if o.edge_class in classes]
    assert len(on) == 1, f"{classes} is not a family of lines"
    return on[0]


def along(end: EndRef, classes: frozenset[EdgeClass],
          height: float) -> Iterator[EndRef]:
    """The ends a straight line visits, setting out through `end`.

    Stops where the line would run off the top or the bottom, and stops when
    it comes back round to where it set out - which is what a horizontal line
    does and a diagonal one never gets the chance to.
    """
    start = end

    while not _crosses(end, height):
        yield end
        end = onward(end, classes)

        if end == start:
            return


def _walks(graph: Graph, classes: frozenset[EdgeClass]) -> list[list[EndRef]]:
    """Every edge of a family, gathered into the closed walks it forms.

    Following `onward` until it comes back round gathers the family into walks
    with nothing left over.
    """
    seen: set[EndRef] = set()
    out: list[list[EndRef]] = []

    for edge_class in sorted(classes):
        for x in range(graph.width):
            for y in range(graph.height):
                end = EdgeRef(graph, x, y, edge_class).ends()[0]

                if end in seen:
                    continue

                walk = []

                while end not in seen:
                    seen.add(end)
                    seen.add(end.other())
                    walk.append(end)

                    end = onward(end, classes)

                out.append(walk)

    return out


def lines(graph: Graph, classes: frozenset[EdgeClass]) -> list[list[EndRef]]:
    """A family's lines: each walk cut where it would run off the top.

    A diagonal walk climbs, so it reaches the top and would carry on from the
    bottom. Cutting it there leaves a line that runs from one end of the
    lattice to the other, and the edge it was cut at belongs to no line. A
    horizontal walk never climbs far enough to be cut, so it stays whole and
    goes round the lattice to meet itself.
    """
    height = graph.height * TileRef.HEIGHT
    out = []

    for walk in _walks(graph, classes):
        cuts = [i for i, end in enumerate(walk) if _crosses(end, height)]

        if not cuts:
            out.append(walk)        # meets itself
            continue

        # From just after each cut to the next one round, so every edge
        # between two cuts is one line and the cut edges are in none.
        for start, stop in zip(cuts, cuts[1:] + [cuts[0] + len(walk)]):
            line = [walk[i % len(walk)] for i in range(start + 1, stop)]

            if line:
                out.append(line)

    return out


class RandomLinesField(ScalarField):
    """Some number of whole lines lit, re-picked on a note.

    A press picks one of the three families - d1, d2 or h, the same sets the
    edge masks name - and shuffles its lines. The knob then says how many of
    them are lit, taking them off the front of that shuffle, so turning it up
    lights more lines without disturbing the ones already lit and turning it
    back down puts out the last ones it lit. The order only changes when the
    note is pressed.

    A diagonal line runs from the bottom of the lattice to the top and stops
    there, since only sideways is really joined up. A horizontal one has
    nothing to stop it, so it goes round the lattice and meets itself.

    Families do not hold the same number of lines - ten each for the diagonals
    here against four for the horizontal, which are five times as long - so the
    knob is read as a count and anything above what the family has lights all
    of them.

    Both ends of a lit edge read 1, since they are two ends of the one thing.

    CC:
        * count - how many lines are lit
    """

    def __init__(self, graph: Graph, midi: MIDIFor, *, note: int, count: int):
        self._note = midi.note(note, "randomize")

        # The lines themselves never change: they are a fact about the lattice,
        # not about any press. Worked out once here, so a press only has to
        # shuffle them.
        self._families = [(name, lines(graph, classes)) for name, classes in FAMILIES]

        # A count, not a sweep: half a line is not a thing. Spelled out as far
        # as the largest family goes, so the knob steps over whole lines and
        # the UI has something to step between.
        most = max(len(family) for _, family in self._families)
        self._count = CustomChoice({round(i * 127 / most): str(i)
                                    for i in range(most + 1)})
        self._count_cc = midi.cc(count, "count", meta=self._count)

        # Every end on a lit line, and how far down the shuffle its line came.
        # Both ends of an edge, so an end that is handed to get() can be looked
        # up as it is, with nothing built per frame. Ends rather than edges
        # because an EndRef is not equal to the EdgeRef it is part of - it
        # carries which end it is.
        self._rank: dict[EndRef, int] = {}
        self._picked: int | None = None

    def _count_at(self, value: int) -> int:
        """How many lines the knob is asking for - read off the same list the
        UI draws from, so the number on screen is the number on the lattice."""
        return int(self._count.at(value))

    def _pick(self, now: Event):
        """Shuffle one family's lines. Only on a press: the count knob reads a
        prefix of whatever this left behind."""
        pressed = self._note()
        hit = pressed[0] if pressed else ZERO

        if hit.when == self._picked:
            return

        self._picked = hit.when
        _, family = self._families[hit.rand(0) % len(self._families)]

        # Ordered by a number drawn from the press, so the same press always
        # gives the same shuffle and nothing has to be stored between frames.
        order = sorted(range(len(family)), key=lambda i: hit.rand(i + 1))

        self._rank = {}

        for rank, i in enumerate(order):
            for end in family[i]:
                self._rank[end] = rank
                self._rank[end.other()] = rank

    def get(self, now: Event, end: EndRef) -> float:
        self._pick(now)

        rank = self._rank.get(end)

        if rank is None:
            return 0        # not on a line of the family that was picked
        return 1 if rank < self._count_at(self._count_cc().data) else 0
