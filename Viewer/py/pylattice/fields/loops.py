"""Closed loops scattered about the lattice, each with a trail going round."""
import itertools

from pylattice.examples.midi import CustomChoice, FloatRange, MIDIFor
from pylattice.examples.tempo import Event, ZERO, trail
from pylattice.fields.mask import D1, D2, along
from pylattice.fields.trace import RandomTraceField, TraceLinesField, level
from pylattice.fields.types import ScalarField
from pylattice.graph import EdgeClass, EndRef, Graph, TileRef


MOST = 16       # copies at the top of the count knob
EDGES = list(EdgeClass)     # any of them can start a figure, each turned further round

# The lines a fired trace may hold: the two diagonals, never the horizontal.
# A horizontal line has no edge of the lattice to stop at, so it goes round the
# x wrap and comes back to where it set out - a trace on one runs the whole
# width and meets itself. A diagonal climbs and stops at the top or the bottom.
DIAGONALS = (D1, D2)


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

    # Figures only ever placed where the whole thing fits, rather than being
    # cut off at the top or the bottom. Only the hexagon: three quarters of the
    # lattice suits it, where the cloud has 20 placements out of 240 and would
    # be nailed to them.
    WHOLE = {"hexagon"}

    # How long the head takes to come up to full as it arrives. 0 is a hard
    # edge, which is how it was before there was a knob for it.
    ATTACK = FloatRange(0, 1000, "ms")
    SPREAD = 0.2        # how far a copy's own speed may stray from the knob

    # A count, not a sweep: half a copy is not a thing. Spelling out which
    # knob position means which number keeps the knob on whole copies and
    # gives the UI something to step between, rather than 128 positions of
    # which only sixteen differ.
    #
    # The position is the count, counting from zero, rather than the counts
    # being spread over 0-127. Spread, raising MOST would move every position
    # below the top one, and a recording of this knob would come back asking
    # for a different number of copies. MOST lives outside the class because a
    # comprehension in a class body cannot see the class's own names.
    COPIES = CustomChoice({i: str(i + 1) for i in range(MOST)})

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

        # Each copy: the end it starts from, where every end of that one figure
        # sits around it, and the line out of each of its firing corners. A
        # figure at a time rather than all of them merged, because each runs at
        # its own speed.
        self._loops: list[tuple[EndRef, dict[EndRef, list[float]],
                                list[list[EndRef]]]] = []
        self._laid_out: tuple[int, int, int] | None = None

        # The ends each figure may be placed at, worked out the first time it
        # is asked for and kept: it depends on the figure and the lattice, not
        # on any press.
        self._placements: dict[int, list[EndRef]] = {}


    @classmethod
    def _count(cls, value: int) -> int:
        """How many copies the knob is asking for.

        Read out of the same list the UI draws from, by the same nearest-one
        rule, so the number on screen is the number on the lattice.
        """
        return int(cls.COPIES.at(value))

    @classmethod
    def _spread(cls, start: EndRef) -> float:
        """How far off the knob this copy runs, from the end it starts at.
        The end is the copy, so its hash is as good a source as any - and it
        means the same figure in the same place always runs at the same
        speed."""
        return 1 + ((start.__hash__() % 1000) / 500 - 1) * cls.SPREAD

    def _where(self, shape: int) -> list[EndRef]:
        """The ends a copy of this figure may start from.

        Every end of every tile, and for a figure that is only drawn whole,
        only the ends that leave it whole. What counts as whole is the most of
        itself the figure manages anywhere on the lattice, so nothing here has
        to know how many ends a hexagon has.
        """
        if shape in self._placements:
            return self._placements[shape]

        name, path = self.SHAPES[shape]
        every = [end
                 for x in range(self._graph.width)
                 for y in range(self._graph.height)
                 for edge in EDGES
                 for end in (self._graph.TILE[x, y].top_end(edge),
                             self._graph.TILE[x, y].bottom_end(edge))]

        if name in self.WHOLE:
            covered = [len(self._instance(end, path)[0]) for end in every]
            whole = max(covered)
            every = [end for end, ends in zip(every, covered) if ends == whole]

        self._placements[shape] = every
        return every

    def _instance(self, start: EndRef, path: str):
        """One copy of a figure: every end it covers and where that end sits
        around it, 0 to 1, and the corners that fire a trace.

        An end can appear more than once if the figure comes back over itself,
        which is why each one holds a list.
        """
        ends: list[EndRef] = []

        # The first end of each edge, in the order the walk takes them, and
        # where each of those sits in `ends` - which is how a corner gets at
        # its own height further down.
        walk: list[EndRef] = []
        sat_at: list[int] = []
        last = None

        for end in start.path(itertools.cycle(path)):
            if ends and ends[0] == end:
                break               # back where it started: the figure closed

            walk.append(end)
            sat_at.append(len(ends))
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

        return phases, self._corners(ends, walk, sat_at, climbed)

    def _corners(self, ends: list[EndRef], walk: list[EndRef],
                 sat_at: list[int], climbed: list[float]) -> list[EndRef]:
        """The ends a trace is fired out of: one per corner of the figure
        whose spare end leads away from it.

        Two edges meet at every corner, which uses two of that vertex's three
        ends and leaves one over. Where that spare end leads straight back
        onto the figure the corner is pointing into itself and fires nothing;
        where it leads away, it is the way out.
        """
        on_figure = ({end.vertex() for end in ends}
                     | {end.other().vertex() for end in ends})
        corners = []

        for i, end in enumerate(walk):
            # Consecutive edges share a vertex, so the next edge's near end is
            # at the corner, and the spare is the other one there.
            onward = walk[(i + 1) % len(walk)]
            left, right = end.other().lr()
            spare = right if onward == left else left

            if not 0 <= climbed[sat_at[(i + 1) % len(walk)]] <= self._height:
                continue        # that corner is off the lattice

            if spare.other().vertex() in on_figure:
                continue        # it leads back onto the figure, not away

            corners.append(spare)

        return corners

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

        where = self._where(shape)

        for i in range(copies):
            # Everything about a copy is drawn from the press, so the same hit
            # always scatters them the same way - and only the end is chosen,
            # because the end is the copy. Which edge of which tile it is says
            # where the figure sits, and the top or bottom end of that edge
            # flips it over, so the one end covers place and facing both.
            start = where[hit.rand(i) % len(where)]

            phases, corners = self._instance(start, path)

            # The way out of each corner, worked out now rather than per frame:
            # it only changes when the copies do.
            self._loops.append((start, phases,
                                [list(along(corner, self._line_of(corner),
                                            self._height))
                                 for corner in corners]))

    @staticmethod
    def _line_of(corner: EndRef) -> frozenset[EdgeClass]:
        """Which diagonal a trace out of this corner holds.

        Every edge class is on at least one of the two, and the verticals are
        on both, so the end picks between them by its own hash - the same
        corner in the same place always fires the same way.
        """
        holding = [classes for classes in DIAGONALS
                   if corner.edge_class in classes]
        return holding[corner.__hash__() % len(holding)]

    def fired(self, now: Event) -> list[list[EndRef]]:
        """The line out of every firing corner of every copy, as the copies
        stand now. What loop_traces runs its heads along.

        Laying the copies out is part of answering, so the traces work whether
        the bodies are in a slot or not.
        """
        self._lay_out(now)

        return [path for _start, _phases, paths in self._loops for path in paths]

    def get(self, now: Event, end: EndRef) -> float:
        self._lay_out(now)

        # Read live, so the knob moves the trails without disturbing the
        # figures. Like scope, the phase comes off the clock rather than being
        # accumulated, so a turn of this knob does carry them along with it.
        base = self.SPEED.at(self._speed_cc().data)
        attack = self.ATTACK.at(self._attack_cc().data)
        result = 0.0

        for start, phases, _paths in self._loops:
            here = phases.get(end)

            if here is None:
                continue            # this copy does not cover this end

            period = base * self._spread(start)

            for phase in here:
                result = max(result, trail(now, period, phase, attack))

        return result


class LoopTracesField(ScalarField):
    """What the loops figures fire out of their corners.

    The figures are not this field's: the shape and how many there are belong
    to loops, and this one only asks it where its corners point. What is here
    is everything about the traces themselves - the pad that fires them and
    how they fly - so the bodies and what they throw off can be patched to
    different things and dialled apart.

    Nothing is kept between frames but the press. A fire lights every corner
    of every copy at once, and firing again starts them over.

    CC:
        * speed - how fast a head travels, 500ms an edge at 0 down to 15ms
          at 127
        * attack - how long the rise in front of the head takes, 0 for a hard
          edge
        * decay - how long the trail behind it takes to fade, 20ms for a bare
          head up to 2s
    """

    # Speed and attack are a trace's own knobs and the fall is the one
    # trace_lines dials, so these are the same declarations rather than copies
    # of them.
    SPEED = RandomTraceField.SPEED
    ATTACK = RandomTraceField.ATTACK
    DECAY = TraceLinesField.DECAY

    def __init__(self, loops: LoopsField, midi: MIDIFor, *, fire: int,
                 speed: int, attack: int, decay: int):
        self._loops = loops

        # A pad of its own, so traces can be fired at a standing shape without
        # scattering it.
        self._fire = midi.note(fire, "fire")
        self._speed_cc = midi.cc(speed, "speed", meta=self.SPEED)
        self._attack_cc = midi.cc(attack, "attack", meta=self.ATTACK)
        self._decay_cc = midi.cc(decay, "decay", meta=self.DECAY)

        # A float per end, the ends at 0 left out. Thrown away and re-traced
        # whenever the time moves on, the same way a trace field does it.
        self._state: dict[EndRef, float] = {}
        self._generated: int | None = None

    def _regen(self, now: Event):
        """Re-trace what the corners fired, if the time has moved on."""
        if now.when == self._generated:
            return

        self._generated = now.when
        self._state = {}

        pressed = self._fire()

        if pressed is None:
            return              # the pad has not been hit yet

        ev = pressed[0]

        # ms the head takes to cross one edge, and the trail in edges.
        step = self.SPEED.at(self._speed_cc().data)
        attack = self.ATTACK.at(self._attack_cc().data)
        decay = self.DECAY.at(self._decay_cc().data)

        head = (now.when - ev.when) / step
        ahead = attack / step
        behind = decay / step

        if head + ahead <= 0:
            return              # not off yet

        for path in self._loops.fired(now):
            if head - behind > len(path):
                continue        # this one is over and gone everywhere

            for i, end in enumerate(path):
                if i >= head + ahead:
                    break       # beyond even the rise that runs before the head

                # An edge is entered before it is left, so its far end lights
                # half a step after its near one.
                for at, lit in ((i, end), (i + 0.5, end.other())):
                    lit_at = level(at, head, step, attack, decay)

                    if lit_at > 0:
                        # Corners fire into each other's lines, and a line can
                        # come back over itself - the brightest pass over an
                        # end wins.
                        self._state[lit] = max(lit_at,
                                               self._state.get(lit, 0.0))

    def get(self, now: Event, end: EndRef) -> float:
        self._regen(now)
        return self._state.get(end, 0.0)
