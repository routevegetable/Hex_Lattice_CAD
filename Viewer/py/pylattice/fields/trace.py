"""A particle picking its own way across the lattice."""
import math
from collections.abc import Iterator

from pylattice.examples.midi import MIDIFor
from pylattice.examples.tempo import Event, History
from pylattice.fields.types import ScalarField
from pylattice.graph import EndRef, Graph, TileRef


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

    What travels is the first half of a sine wave: the ends just behind the
    head ramp up to 1 and back down to 0 over WIDTH edges. Every end a path
    does not reach is 0, which is most of them most of the time.

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
    """

    PARTICLES = 8       # how many can be in flight at once
    LENGTH = 24         # edges traced before a particle runs out of path
    WIDTH = 5.0         # edges the sine hump spans

    SLOWEST = 500       # ms an edge takes at CC 0
    FASTEST = 15        # ms an edge takes at CC 127

    # % chance a step takes the turn that steers it wrong. A few keeps the
    # paths from being rigid rays; much more and they wander off the aim.
    KINK = 4

    def __init__(self, graph: Graph, midi: MIDIFor, *, note: int, speed: int, aim: int):
        self._vertexes = list(graph.vertexes())
        self._width = graph.width * TileRef.WIDTH
        self._height = graph.height * TileRef.HEIGHT

        self._note = midi.note(note)
        self._speed_cc = midi.cc(speed, "speed")
        self._aim_cc = midi.cc(aim, "aim")

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

    def _heading(self, ev: Event, aim: float) -> tuple[float, float]:
        """Which way a particle is trying to go.

        A random direction, pulled toward straight up or straight down by how
        far `aim` is off centre: at 1 they all go up, at 0 they all go down,
        and at 0.5 nothing pulls them and they spread evenly round the circle.
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

    def _start(self, ev: Event, heading: tuple[float, float]) -> EndRef:
        """Where a particle starts - a random vertex, leaving by whichever of
        its three ends points nearest the heading."""
        vertex = self._vertexes[ev.rand() % len(self._vertexes)]
        return max(vertex.ends_cw(), key=lambda e: self._along(heading, e))

    def _step(self, end: EndRef) -> tuple[float, float]:
        return wrapped_step(end, self._width, self._height)

    def _along(self, heading: tuple[float, float], end: EndRef) -> float:
        """How much of travelling out through an end is progress."""
        hx, hy = heading
        dx, dy = self._step(end)
        return hx * dx + hy * dy

    def _across(self, heading: tuple[float, float], end: EndRef) -> float:
        """How far out to one side travelling out through an end puts it."""
        hx, hy = heading
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
        heading = self._heading(ev, aim)

        current = self._start(ev, heading)
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
            drift += self._across(heading, current)

            left, right = current.other().lr()

            wrong = ev.rand(i + 2) % 100 < self.KINK
            straighter = min(left, right, key=lambda e: abs(drift + self._across(heading, e)))

            if wrong:
                current = right if straighter is left else left
            else:
                current = straighter

    def _level(self, at: float, head: float) -> float:
        """Half a sine wave trailing the head: 0 at the head itself, 0 again
        WIDTH edges behind it, 1 in the middle."""
        behind = head - at

        if behind <= 0 or behind >= self.WIDTH:
            return 0.0          # not reached yet, or long gone

        return math.sin(behind / self.WIDTH * math.pi)

    def _regen(self, now: Event):
        """Re-trace every particle in flight, if the time has moved on."""
        if now.when == self._generated:
            return

        self._generated = now.when
        self._consume_note()
        self._state = {}

        # ms the head takes to cross one edge. Geometric rather than linear -
        # over a range this wide a linear knob spends most of its travel in
        # the slow end and crams every fast speed into the last few steps.
        step = self.SLOWEST * (self.FASTEST / self.SLOWEST) ** (self._speed_cc().data / 127)

        # Read once a frame, so a knob turn steers the paths already in flight
        # as one - they are re-traced from scratch anyway.
        aim = self._aim_cc().data / 127

        for ev in self._queue.events():
            if ev is None:
                continue        # this latch has not been used yet

            head = (now.when - ev.when) / step
            if head <= 0 or head - self.WIDTH > self.LENGTH:
                continue        # not off yet, or run off the end of its path

            for i, end in enumerate(self._trace(ev, aim)):
                if i >= head:
                    break       # the rest of the path is ahead of the head

                # An edge is entered before it is left, so its far end lights
                # half a step after its near one.
                for at, lit in ((i, end), (i + 0.5, end.other())):
                    level = self._level(at, head)

                    if level > 0:
                        # Paths cross, and one can cross itself - the brightest
                        # pass over an end wins.
                        self._state[lit] = max(level, self._state.get(lit, 0.0))

    def get(self, now: Event, end: EndRef) -> float:
        self._regen(now)
        return self._state.get(end, 0.0)
