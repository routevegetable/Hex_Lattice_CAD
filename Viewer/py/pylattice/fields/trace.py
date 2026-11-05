"""Particles picking their way across the lattice, loose or on its lines."""
import itertools
import math
from collections.abc import Iterator

from pylattice.examples.midi import CustomChoice, FloatRange, MIDIFor
from pylattice.examples.tempo import Event, History
from pylattice.fields.mask import D1, D2, FAMILIES, H, along, lines
from pylattice.fields.types import ScalarField
from pylattice.graph import EdgeClass, EdgeRef, EndRef, Graph, TileRef


# Which families each mode of a line trace is allowed to hold, in the order
# they sit on the knob. The narrowed bidirectionals are the point of it: a knob
# position for a line of each sort, rather than taking whatever comes up. Out
# here rather than on the field because a comprehension in a class body cannot
# see the class's own names.
MODE_FAMILIES = {
    "straight": (D1, D2, H),
    "bidirectional": (D1, D2, H),
    "bidirectional-d": (D1, D2),
    "bidirectional-d1": (D1,),
    "bidirectional-d2": (D2,),
    "bidirectional-h": (H,),
    "star": (D1, D2, H),
}


def level(at: float, head: float, step: float, attack: float,
          decay: float) -> float:
    """How bright a point on a path is, by how long ago the head was there -
    the same shape scope and loops draw.

    Negative is ahead of the head, which is where the rise lives: it reaches
    full just as the head arrives, then falls away behind over `decay`.
    """
    age = (head - at) * step        # ms since the head passed this point

    if age > decay:
        return 0.0                  # long gone

    if age >= 0:
        return 1 - age / decay      # the fall, behind the head

    if -age >= attack:
        return 0.0                  # too far ahead to have started rising

    return 1 + age / attack         # the rise: 0 an attack ahead, 1 at the head


def heading(ev: Event, aim: float) -> tuple[float, float]:
    """Which way a particle is trying to go.

    A random direction, pulled toward straight up or straight down by how far
    `aim` is off centre: at 1 they all go up, at 0 they all go down, and at 0.5
    nothing pulls them and they spread evenly round the circle.
    """
    angle = ev.rand(1) % 3600 / 3600 * 2 * math.pi
    bias = aim * 2 - 1              # -1 down, 0 no preference, +1 up
    pull = abs(bias)

    x = math.cos(angle) * (1 - pull)
    y = math.sin(angle) * (1 - pull) + math.copysign(pull, bias)

    if abs(x) + abs(y) < 1e-6:
        # The random direction happened to cancel the pull exactly.
        return 0.0, math.copysign(1.0, bias)

    return x, y


def progress(head: tuple[float, float], end: EndRef,
             width: float, height: float) -> float:
    """How much of travelling out through an end is progress on a heading."""
    hx, hy = head
    dx, dy = wrapped_step(end, width, height)
    return hx * dx + hy * dy


def wrapped_step(end: EndRef, width: float, height: float) -> tuple[float, float]:
    """Which way travelling out through an end goes, the short way round.

    The lattice wraps, so the two vertices of an edge across the seam are
    stored a whole lattice apart - this folds that back to the real step.
    """
    dx, dy = end.physical_to_next()

    if dx > width / 2:
        dx -= width
    elif dx < -width / 2:
        dx += width

    if dy > height / 2:
        dy -= height
    elif dy < -height / 2:
        dy += height

    return dx, dy


class RandomTraceField(ScalarField):
    """
    A note that sends a particle off along a path of its own.

    Like NoteRippleField, everything about a particle is decided by the press
    that spawned it - the vertex it starts from and the heading it tries to
    hold come out of that event's `rand`, so a particle is never stored, only
    re-derived, and never moves once it is on its way.

    What travels is a head at full brightness with a trail behind it, the
    same shape scope and loops draw: up over `attack` ms as the head comes on,
    full as it passes, then straight down over DECAY ms. Both are times
    rather than distances, so the trail reads the same however fast the head
    is moving.
    Every end a path does not reach is 0, which is most of them most of the
    time.

    A path wraps round the sides of the lattice but not the top or the bottom
    - one that gets that far is cut off there.

    The paths are traced once a frame rather than once an end - the first
    `get` at a new `now` regenerates the state and the rest of the frame reads
    it - so what this costs follows the particles in flight, not the lattice.

    CC:
        * speed - how fast a head travels, 500ms an edge at 0 down to 15ms
          at 127
        * aim - which way they go: 0 is mostly downward, 1 is mostly upward,
          and 0.5 is evenly spread round the circle
        * attack - how long the rise in front of the head takes, 0 for a hard
          edge
    """

    PARTICLES = 8       # how many can be in flight at once
    LENGTH = 24         # edges traced before a particle runs out of path

    # The trail in time rather than in edges, so it reads the same however
    # fast the head is going: full as the head passes, up over `attack` ms
    # before it gets there and straight back down over DECAY after. The fall
    # is a fixed length and a straight line, the way scope's is.
    ATTACK = FloatRange(0, 1000, "ms")
    DECAY = 400         # ms the trail takes to fade out behind the head

    AIM = FloatRange(0, 1)      # 0 fires down, 1 up, 0.5 every way at once

    SLOWEST = 500       # ms an edge takes at CC 0
    FASTEST = 15        # ms an edge takes at CC 127
    # Geometric rather than linear - over a range this wide a linear knob
    # spends most of its travel in the slow end and crams every fast speed
    # into the last few steps.
    SPEED = FloatRange(SLOWEST, FASTEST, "ms", geometric=True)

    # % chance a step takes the turn that steers it wrong. A few keeps the
    # paths from being rigid rays; much more and they wander off the aim.
    KINK = 4

    def __init__(self, graph: Graph, midi: MIDIFor, *, note: int, speed: int,
                 aim: int, attack: int):
        self._vertexes = list(graph.vertexes())
        self._width = graph.width * TileRef.WIDTH
        self._height = graph.height * TileRef.HEIGHT

        self._note = midi.note(note)
        self._speed_cc = midi.cc(speed, "speed", meta=self.SPEED)
        self._aim_cc = midi.cc(aim, "aim", meta=self.AIM)
        self._attack_cc = midi.cc(attack, "attack", meta=self.ATTACK)

        # The queue of particles - one latch each, a press rotates onto the
        # next, so the oldest is the one that gets overwritten.
        self._queue: History[int] = History(self.PARTICLES)

        # A float per end, the ends at 0 left out. Thrown away and re-traced
        # whenever the time moves on.
        self._state: dict[EndRef, float] = {}
        self._generated: int | None = None
        self._seen: Event | None = None

    def _consume_note(self):
        """Put a new press on the queue. A release ends nothing - a particle
        runs until it reaches the end of its path."""
        pressed = self._note()
        if pressed is None:
            return

        on, _release = pressed
        if not on.after(self._seen):
            return              # already queued this press

        self._seen = on
        self._queue.update().latch(on)

    def _start(self, ev: Event, head: tuple[float, float]) -> EndRef:
        """Where a particle starts - a random vertex, leaving by whichever of
        its three ends points nearest the heading."""
        vertex = self._vertexes[ev.rand() % len(self._vertexes)]
        return max(vertex.ends_cw(), key=lambda e: self._along(head, e))

    def _step(self, end: EndRef) -> tuple[float, float]:
        return wrapped_step(end, self._width, self._height)

    def _along(self, head: tuple[float, float], end: EndRef) -> float:
        return progress(head, end, self._width, self._height)

    def _across(self, head: tuple[float, float], end: EndRef) -> float:
        """How far out to one side travelling out through an end puts it."""
        hx, hy = head
        dx, dy = self._step(end)
        return hx * dy - hy * dx

    def _trace(self, ev: Event, aim: float) -> Iterator[EndRef]:
        """The ends a particle visits, in order.

        A vertex has three ends - the one the path came in by, and a left and
        a right - so there is no carrying straight on, only zig-zagging. Which
        way it zigs is whichever keeps it on its heading: `drift` is how far
        off to one side the path has wandered so far, and each step is the turn
        that brings that back toward nothing. Now and then a step takes the
        wrong turn instead and kinks off course, and the drift pulls it back
        over the steps after.

        The lattice wraps top to bottom, but a trace does not: one that
        reaches the top or the bottom ends there rather than coming back round
        on the other side. Sideways it still wraps.
        """
        head = heading(ev, aim)

        current = self._start(ev, head)
        drift = 0.0

        # Where the path has got to vertically, carried along by hand - the
        # vertices themselves only know their wrapped position.
        y = current.vertex().physical()[1]

        for i in range(self.LENGTH + 1):
            _dx, dy = self._step(current)

            # `_step` gives an edge's real displacement, while the vertex it
            # lands on is stored wrapped. The two only disagree across the
            # seam, which is where this path stops.
            if abs(current.other().vertex().physical()[1] - (y + dy)) > self._height / 2:
                return

            yield current

            y += dy
            drift += self._across(head, current)

            left, right = current.other().lr()

            wrong = ev.rand(i + 2) % 100 < self.KINK
            straighter = min(left, right,
                             key=lambda e: abs(drift + self._across(head, e)))

            if wrong:
                current = right if straighter is left else left
            else:
                current = straighter

    def _regen(self, now: Event):
        """Re-trace every particle in flight, if the time has moved on."""
        if now.when == self._generated:
            return

        self._generated = now.when
        self._consume_note()
        self._state = {}

        # ms the head takes to cross one edge.
        step = self.SPEED.at(self._speed_cc().data)

        # Read once a frame, so a knob turn steers the paths already in flight
        # as one - they are re-traced from scratch anyway.
        aim = self.AIM.at(self._aim_cc().data)
        attack = self.ATTACK.at(self._attack_cc().data)

        # The trail in edges, which is what the path is counted in.
        behind = self.DECAY / step
        ahead = attack / step

        for ev in self._queue.events():
            if ev is None:
                continue        # this latch has not been used yet

            head = (now.when - ev.when) / step
            if head + ahead <= 0 or head - behind > self.LENGTH:
                continue        # not off yet, or run off the end of its path

            for i, end in enumerate(self._trace(ev, aim)):
                if i >= head + ahead:
                    break       # beyond even the rise that runs before the head

                # An edge is entered before it is left, so its far end lights
                # half a step after its near one.
                for at, lit in ((i, end), (i + 0.5, end.other())):
                    lit_at = level(at, head, step, attack, self.DECAY)

                    if lit_at > 0:
                        # Paths cross, and one can cross itself - the brightest
                        # pass over an end wins.
                        self._state[lit] = max(lit_at, self._state.get(lit, 0.0))

    def get(self, now: Event, end: EndRef) -> float:
        self._regen(now)
        return self._state.get(end, 0.0)


class TraceLinesField(ScalarField):
    """A note that shoots traces off along the straight lines of the lattice.

    Trace, kept to the rails. The head and its trail are the same shape trace
    draws, but a path here is one of the lattice's lines rather than a heading
    held by zig-zagging: it sets out from an end and holds that line until it
    runs off the top or comes back to where it started.

    There are six ways out of a vertex, not three: three families of lines pass
    through it, and each can be taken either way. Mode says how many are taken.

        * straight        - one of the six
        * bidirectional   - two opposite ones: the whole line through the
                            vertex, on whichever family comes up
        * bidirectional-d - the same, held to a diagonal, either of them
        * bidirectional-d1, -d2 - held to that one diagonal
        * bidirectional-h - the same, held to the horizontal
        * star            - three of the six, one out of each of the vertex's
                            three ends and each on a different family

    Where a trace sets out is drawn evenly from the ends - all of them, the
    rows capping the lattice included. An arm that sets out through one of
    those has nowhere to go and draws nothing, so a press at the boundary can
    come out short an arm, or show nothing at all.

    The narrowed modes draw from fewer ends, since a trace can only set out on
    a line it is actually on: every end is on a diagonal, but only the four
    horizontal classes are on a horizontal line, so bidirectional-h never
    starts on a C or an F.

    A press fires from one vertex at the bottom of the nodes knob and from one
    more for every step up it, each of them a whole mode's worth of arms.

    Ten presses can be in flight together, each with its own vertices and its
    own arms; the eleventh overwrites the oldest. The knobs are read live rather
    than kept with the press, so turning one moves everything still running.

    CC:
        * speed - how fast a head travels, 500ms an edge at 0 down to 15ms
          at 127
        * attack - how long the rise in front of the head takes, 0 for a hard
          edge
        * decay - how long the trail behind it takes to fade, 20ms for a bare
          head up to 2s
        * mode - straight, bidirectional or star
        * nodes - how many vertices a press fires from, one more than the knob
    """

    TRACES = 10         # how many presses can be in flight at once

    # Speed and attack mean what they mean for a loose trace, so they are the
    # same declarations rather than copies of them.
    SPEED = RandomTraceField.SPEED
    ATTACK = RandomTraceField.ATTACK

    # How long the trail takes to fade out behind the head. Geometric over a
    # hundredfold range, so the short end is not crammed into the first few
    # steps. It never reaches 0: at 20ms the fall is over inside an edge, which
    # is a bare head, and a fall over no time at all is not a trail.
    DECAY = FloatRange(20, 2000, "ms", geometric=True)

    # How many vertices a press fires from. The knob is the count less one, so
    # 0 is one vertex and every step up adds another - a range rather than a
    # list of 128 names, which reads the same and says so in the UI.
    NODES = FloatRange(1, 128, "nodes")

    # The position is an index into MODE_FAMILIES, not a sweep over 0-127: a
    # mode added later then appends, rather than moving every position below
    # the top one and leaving a recording of this knob on some other mode.
    MODE = CustomChoice({i: name for i, name in enumerate(MODE_FAMILIES)})

    def __init__(self, graph: Graph, midi: MIDIFor, *, note: int, speed: int,
                 attack: int, decay: int, mode: int, nodes: int):
        self._height = graph.height * TileRef.HEIGHT

        every = [
            end
            for x in range(graph.width)
            for y in range(graph.height)
            for edge_class in EdgeClass
            for end in EdgeRef(graph, x, y, edge_class).ends()
        ]

        # The ends a trace may set out from, per mode: a mode held to one sort
        # of line can only set out from an end that is on one. Drawn between
        # evenly within that.
        self._starts = {
            mode: [end for end in every
                   if any(end.edge_class in classes for classes in holds)]
            for mode, holds in MODE_FAMILIES.items()
        }

        # The longest line there is, which is as far as a head can get. Only to
        # know when a trace is long over and can be left out altogether.
        self._longest = max(len(line) for _, classes in FAMILIES
                            for line in lines(graph, classes))

        self._note = midi.note(note)
        self._speed_cc = midi.cc(speed, "speed", meta=self.SPEED)
        self._attack_cc = midi.cc(attack, "attack", meta=self.ATTACK)
        self._decay_cc = midi.cc(decay, "decay", meta=self.DECAY)
        self._mode_cc = midi.cc(mode, "mode", meta=self.MODE)
        self._nodes_cc = midi.cc(nodes, "nodes", meta=self.NODES)

        # The queue of presses - one latch each, a press rotates onto the next,
        # so the oldest is the one that gets overwritten. Nothing else is kept:
        # where a press's arms go is worked out from the press itself every
        # frame.
        self._queue: History[int] = History(self.TRACES)
        self._seen: Event | None = None

        # A float per end, the ends at 0 left out. Thrown away and re-traced
        # whenever the time moves on.
        self._state: dict[EndRef, float] = {}
        self._generated: int | None = None

    def _consume_note(self):
        """Put a new press on the queue. A release ends nothing - arms run
        until they reach the end of their lines."""
        pressed = self._note()

        if pressed is None:
            return

        on, _release = pressed

        if not on.after(self._seen):
            return              # already queued this press

        self._seen = on
        self._queue.update().latch(on)

    def _family_of(self, ev: Event, end: EndRef, salt: int,
                   holds: tuple[frozenset[EdgeClass], ...]) -> frozenset[EdgeClass]:
        """Which line to hold, of the ones the mode allows that can be set out
        on through this end. An edge class sits in two of the three families,
        so there is at least one whatever the mode allows, and the press picks
        between them when there are two."""
        holding = [classes for classes in holds if end.edge_class in classes]
        return holding[ev.rand(salt) % len(holding)]

    def _star(self, ev: Event, ends: tuple[EndRef, ...], salt: int = 0):
        """Three arms, one out of each end and each on a different family.

        Of the six ways out of a vertex there are only two ways to pick three
        that use every end and every family once, since each family holds two
        of the three ends. The press picks which of the two.
        """
        ways = [order for order in itertools.permutations(ends)
                if all(end.edge_class in classes
                       for end, (_, classes) in zip(order, FAMILIES))]
        assert len(ways) == 2, "a vertex should offer two stars"

        order = ways[ev.rand(salt + 4) % len(ways)]
        return [(end, classes) for end, (_, classes) in zip(order, FAMILIES)]

    def _node(self, ev: Event, mode: str, which: int):
        """One vertex's worth: where it shoots from, and the line each arm
        holds. Mode says how many arms that is."""
        starts = self._starts[mode]

        # A salt per vertex, so the vertices of one press are drawn
        # independently rather than all landing in the same place.
        salt = which * 8
        out = starts[ev.rand(salt) % len(starts)]

        if mode == "star":
            return self._star(ev, out.vertex().ends_cw(), salt)

        classes = self._family_of(ev, out, salt + 3, MODE_FAMILIES[mode])

        if mode.startswith("bidirectional"):
            # The family's two ends at this vertex, which is the one line
            # through it taken both ways.
            return [(end, classes) for end in out.vertex().ends_cw()
                    if end.edge_class in classes]

        return [(out, classes)]

    def _arms(self, ev: Event, mode: str, nodes: int):
        """Where this press shoots from. A press fires from `nodes` vertices at
        once, each of them a whole mode's worth of arms."""
        return [arm
                for which in range(nodes)
                for arm in self._node(ev, mode, which)]

    def _regen(self, now: Event):
        """Re-trace every press in flight, if the time has moved on."""
        if now.when == self._generated:
            return

        self._generated = now.when
        self._consume_note()
        self._state = {}

        # ms the head takes to cross one edge.
        step = self.SPEED.at(self._speed_cc().data)

        # Read once a frame, so a knob turn moves what is in flight as one - it
        # is all re-traced from scratch anyway.
        attack = self.ATTACK.at(self._attack_cc().data)
        decay = self.DECAY.at(self._decay_cc().data)
        mode = self.MODE.at(self._mode_cc().data)
        nodes = round(self.NODES.at(self._nodes_cc().data))

        # The trail in edges, which is what a path is counted in.
        behind = decay / step
        ahead = attack / step

        for ev in self._queue.events():
            if ev is None:
                continue        # this latch has not been used yet

            head = (now.when - ev.when) / step

            if head + ahead <= 0 or head - behind > self._longest:
                continue        # not off yet, or over and gone everywhere

            for out, classes in self._arms(ev, mode, nodes):
                for i, end in enumerate(along(out, classes, self._height)):
                    if i >= head + ahead:
                        break   # beyond even the rise that runs before the head

                    # An edge is entered before it is left, so its far end
                    # lights half a step after its near one.
                    for at, lit in ((i, end), (i + 0.5, end.other())):
                        lit_at = level(at, head, step, attack, decay)

                        if lit_at > 0:
                            # Arms of a star meet at the vertex they left, a
                            # line can come back over itself, and presses
                            # cross - the brightest pass over an end wins.
                            self._state[lit] = max(lit_at,
                                                   self._state.get(lit, 0.0))

    def get(self, now: Event, end: EndRef) -> float:
        self._regen(now)
        return self._state.get(end, 0.0)
