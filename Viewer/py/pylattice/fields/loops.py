"""Closed loops scattered about the lattice, each with a trail going round."""
import itertools

from pylattice.examples.midi import CustomChoice, FloatRange, MIDIFor
from pylattice.examples.tempo import Event, ZERO, trail
from pylattice.fields.types import ScalarField
from pylattice.graph import EdgeClass, EndRef, Graph, TileRef


MOST = 16       # copies at the top of the count knob
EDGES = list(EdgeClass)     # any of them can start a figure, each turned further round


class LoopsField(ScalarField):
    """Closed figures dotted about, each with a trail running round it.

    A shape is a string of turns that comes back to where it started, so the
    walk closes on itself: six lefts is one hexagon, and `LLLLRLLLLR` is two
    of them fused.

    A copy is nothing more than the end it starts from. That one end decides
    everything about it: where it sits, which way round it faces - the edge
    class turns the figure and the top or bottom end flips it - and how fast
    it runs, which comes off the end's own hash. So scattering the copies is
    picking ends, and picking ends is all it is.

    Nothing wanders on its own. Ends are picked afresh when the note is hit
    and when the count changes, and sit still otherwise - the speed knob moves
    how fast the trails run, not where the figures are. Each copy runs a fifth
    either side of the knob, so they drift apart rather than pulsing as one.

    Sideways the lattice wraps and so do the figures - one running off the
    right comes back on the left, whole. Up and down it does not: a figure
    that would run off the top is cut off there rather than reappearing
    underneath. Its trail still runs round the whole figure, so what is left
    goes dark for as long as the head is out of sight.

    CC:
        * shape  - which closed figure to trace
        * copies - how many of them
        * speed  - how long a trail takes to go round
    """

    # Every one of these closes from any A end on a lattice this size, which
    # is what lets a copy start anywhere. The bowtie crosses itself, so two of
    # its ends are on the figure twice over at different points round it -
    # which is why an end's phases are a list and get() takes the max.
    SHAPES = [
        ("hexagon", "LLLLLL"),              # 6 edges, one cell
        ("sausage", "LLLLRLLLLR"),          # 10, two cells, standing up
        ("bowtie", "LLLLLRRRRRRL"),         # 12 over 10 ends, a figure eight
        ("clover", "LLLRLLLRLLLR"),         # 12, three cells round a point
        ("clump", "LLLLRRLLLRLLLRLR"),      # 16, lopsided, no two sides alike
        ("cloud", "LRLLLRLRLRLLLRLRLLRLLR"),  # 22, six cells, lopsided
    ]

    SPEED = FloatRange(4000, 30, "ms", geometric=True)

    # How long the head takes to come up to full as it arrives. 0 is a hard
    # edge, which is how it was before there was a knob for it.
    ATTACK = FloatRange(0, 1000, "ms")
    SPREAD = 0.2        # how far a copy's own speed may stray from the knob

    # A count, not a sweep: half a copy is not a thing. Spelling out which
    # knob position means which number keeps the knob on whole copies and
    # gives the UI something to step between, rather than 128 positions of
    # which only sixteen differ. MOST lives outside the class because a
    # comprehension in a class body cannot see the class's own names.
    COPIES = CustomChoice({round(i * 127 / (MOST - 1)): str(i + 1)
                           for i in range(MOST)})

    def __init__(self, graph: Graph, midi: MIDIFor, *,
                 note: int, shape: int, copies: int, speed: int, attack: int):
        self._graph = graph
        self._height = graph.height * TileRef.HEIGHT
        self._note = midi.note(note, "trigger")

        # Not a sweep: the value picks a figure, so the UI is better off
        # naming them than offering 0-127 of which only a couple mean anything.
        self._shape_cc = midi.cc(shape, "shape", meta=CustomChoice(
            {index: name for index, (name, _) in enumerate(self.SHAPES)}))
        self._copies_cc = midi.cc(copies, "copies", meta=self.COPIES)
        self._speed_cc = midi.cc(speed, "speed", meta=self.SPEED)
        self._attack_cc = midi.cc(attack, "attack", meta=self.ATTACK)

        # Each copy: the end it starts from, and where every end of that one
        # figure sits around it. A figure at a time rather than all of them
        # merged, because each runs at its own speed.
        self._loops: list[tuple[EndRef, dict[EndRef, list[float]]]] = []
        self._laid_out: tuple[int, int, int] | None = None

    @classmethod
    def _count(cls, value: int) -> int:
        """How many copies the knob is asking for.

        Read out of the same list the UI draws from, by the same nearest-one
        rule, so the number on screen is the number on the lattice.
        """
        nearest = min(cls.COPIES.items, key=lambda key: abs(key - value))
        return int(cls.COPIES.items[nearest])

    @classmethod
    def _spread(cls, start: EndRef) -> float:
        """How far off the knob this copy runs, from the end it starts at.
        The end is the copy, so its hash is as good a source as any - and it
        means the same figure in the same place always runs at the same
        speed."""
        return 1 + ((start.__hash__() % 1000) / 500 - 1) * cls.SPREAD

    def _instance(self, start: EndRef, path: str) -> dict[EndRef, list[float]]:
        """One copy of a figure: every end it covers, and where that end sits
        around it, 0 to 1. An end can appear more than once if the figure
        comes back over itself, which is why each one holds a list."""
        ends: list[EndRef] = []
        last = None

        for end in start.path(itertools.cycle(path)):
            if ends and ends[0] == end:
                break               # back where it started: the figure closed

            ends.append(end)

            # An edge is entered before it is left, so its far end is on the
            # figure too, half a step further round.
            if last is not None:
                ends.append(end.other())

            last = end

        # How far up each end is, counted as the walk goes rather than read
        # off the lattice: stepping off the top lands at the bottom, so the
        # raw height jumps a whole lattice and that jump is what gives the
        # crossing away. Anything that ends up outside is off the lattice as
        # far as this figure is concerned.
        climbed: list[float] = []
        shift = 0.0
        previous = None

        for end in ends:
            y = end.vertex().physical()[1]

            if previous is not None:
                step = y - previous

                if step > self._height / 2:
                    shift -= self._height       # stepped down off the bottom
                elif step < -self._height / 2:
                    shift += self._height       # stepped up off the top

            previous = y
            climbed.append(y + shift)

        phases: dict[EndRef, list[float]] = {}

        for i, (end, y) in enumerate(zip(ends, climbed)):
            if not 0 <= y <= self._height:
                continue        # past the top or the bottom: cut off

            # Out of however far round the whole figure, not just the part
            # that fits - the trail keeps its timing through the gap.
            phases.setdefault(end, []).append(i / len(ends))

        return phases

    def _lay_out(self, now: Event):
        """Pick the ends the copies start from. Only when the note is hit, the
        count moves, or the figure changes - turning the speed knob leaves
        them where they are."""
        pressed = self._note()
        hit = pressed[0] if pressed else ZERO

        copies = self._count(self._copies_cc().data)
        shape = min(self._shape_cc().data, len(self.SHAPES) - 1)

        if (hit.when, copies, shape) == self._laid_out:
            return

        self._laid_out = (hit.when, copies, shape)
        _, path = self.SHAPES[shape]
        self._loops = []

        for i in range(copies):
            # Everything about a copy is drawn from the press, so the same hit
            # always scatters them the same way - and only the end is chosen,
            # because the end is the copy.
            tile = self._graph.TILE[hit.rand(i * 4) % self._graph.width,
                                    hit.rand(i * 4 + 1) % self._graph.height]

            # Which edge of the tile it starts on turns the figure, and the
            # top or bottom end of it flips the figure over, so the one random
            # end covers where it is and which way it faces both.
            edge = EDGES[hit.rand(i * 4 + 2) % len(EDGES)]
            start = (tile.top_end(edge) if hit.rand(i * 4 + 3) % 2
                     else tile.bottom_end(edge))

            self._loops.append((start, self._instance(start, path)))

    def get(self, now: Event, end: EndRef) -> float:
        self._lay_out(now)

        # Read live, so the knob moves the trails without disturbing the
        # figures. Like scope, the phase comes off the clock rather than being
        # accumulated, so a turn of this knob does carry them along with it.
        base = self.SPEED.at(self._speed_cc().data)
        attack = self.ATTACK.at(self._attack_cc().data)
        result = 0.0

        for start, phases in self._loops:
            here = phases.get(end)

            if here is None:
                continue            # this copy does not cover this end

            period = base * self._spread(start)

            for phase in here:
                result = max(result, trail(now, period, phase, attack))

        return result
