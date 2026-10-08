"""The scalar fields themselves - a value per vertex, driven by MIDI."""
import itertools
import math
from collections.abc import Iterator

from pylattice.examples.colors import vary
from pylattice.examples.midi import MIDI
from pylattice.examples.tempo import ZERO, Event, EventLatch, History, psweep, sweep
from pylattice.fields.types import ScalarField
from pylattice.graph import EdgeClass, EndRef, Graph, TileRef, VertexRef


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


class CCField(ScalarField):
    """
    A CC as a field
    """


    def __init__(self, midi: MIDI, *, value: int):
        self._cc = midi.cc(value)
        
    def get(self, now: Event, end: EndRef) -> float:
        return self._cc().data / 127


class PolyTouchField(ScalarField):
    """
    A polytouch as a field
    """


    def __init__(self, midi: MIDI, *, note: int):
        self._poly = midi.polytouch(note)
        
    def get(self, now: Event, end: EndRef) -> float:
        return self._poly() / 127


class RotaryField(ScalarField):

    def __init__(self, graph: Graph, midi: MIDI, *, period: int, parts: int, shape: int):
        self._width = graph.width
        self._height = graph.height
        self._period = midi.cc(period) # How long to do one rotation (0.5 sec at 0, 16 sec at 127)
        self._parts = midi.cc(parts) # How many parts
        self._shape = midi.cc(shape) # What wave shape
    
    def get(self, now: Event, end: EndRef) -> float:
        v = end.vertex()
        offset = v.physical()[0] / (TileRef.WIDTH * self._width) # we are here between 0 -> 1
        #print(v.physical(), offset)
        # 0.5s a rotation at 0 up to 16s at 127, a constant ratio per step.
        # Doubling per CC step ran off the end of the knob by about step 5.
        period = 500 * (16000 / 500) ** (self._period().data / 127)
        return vary(now, 0, 1, period, offset)


class WipeField(ScalarField):
    def __init__(self, graph: Graph, midi: MIDI, *, period: int):
        self._width = graph.width
        self._height = graph.height
        self._period = midi.cc(period) # How long to do one wipe
    
    def get(self, now: Event, end: EndRef) -> float:
        return 0


class NoteWipeField(ScalarField):
    """
    A note that makes a wipe field
    
    CC:
        * 0-63 means down, 64-127 is up
        * diff from center is velocity. 63 is 0.1 sec. 0 is 1 sec
    
    """


    def __init__(self, midi: MIDI, *, note: int, speed: int):
        self._note = midi.note(note)
        self._speed_cc = midi.cc(speed)
        self._latches = [EventLatch() for _ in range(4)]
        self._last_latch = 0
        self._seen: Event | None = None
        
    def _consume_note(self):
        """Rotate a new press into the next latch, so wipes can overlap.
        
        Called from get(), which runs per vertex - so it only acts on an event
        it has not already seen.
        """
        pressed = self._note()
        if pressed is None:
            return
        
        on, _release = pressed          # a release ends nothing - the wipe runs on
        if self._seen is not None and not on.after(self._seen):
            return
        
        self._seen = on
        self._latches[self._last_latch].put()
        self._last_latch = (self._last_latch + 1) % 4
        
    def get(self, now: Event, end: EndRef) -> float:
        v = end.vertex()
        self._consume_note()
        
        output = 0
        for latch in self._latches:
            ev = latch.read()
            
            if ev is None:
                continue        # this latch has not been used yet
            
            
            ccv = self._speed_cc().data / 64 - 1 # CCV goes from -1 to 1
            
            # Sign is the direction, size is the speed: 2000ms at the middle of
            # the knob down to 333ms at either end, a constant ratio per step.
            period = 2000 * (333 / 2000) ** abs(ccv)
            
            y = v.physical()[1] # My y position
            
            total_height = TileRef.HEIGHT * v.tile.graph.height
            
            dy = y / total_height
            if ccv < 0:
                dy = 1 - dy
            #dy = dy - 1
            #print(dy)
            
            this_output = min(1, math.sin(sweep(now, ev.delay(dy * period), period, math.pi/2, math.pi, 0)))
            
            output = max(output, this_output)
        
        #print(output)
        return output
            
        #if ccv > 0:
        #    # Up
        #    return sweep(now, ev, period, 0, v.tile.graph.height, 0)
        #else:
        #    # Down
        #    return sweep(now, ev, period, v.tile.graph.height, 0, v.tile.graph.height)
       # 
       # return


class NoteRandomField(ScalarField):
    """
    A note that re-rolls every edge to a new random number.

    One value per edge, so both of its ends read the same - they are two ends
    of the same thing. A press glides every edge from where it was to a fresh
    number, all of them together, over however long the knob says.

    What an edge lands on comes out of the press event itself, so nothing is
    stored but the two presses being crossfaded between. Both start seeded at
    time zero, which gives a still pattern to begin with rather than nothing.

    CC:
        * period - how long the glide takes, 4s at 0 down to 30ms at 127
    """

    def __init__(self, midi: MIDI, *, note: int, period: int):
        self._note = midi.note(note)
        self._period_cc = midi.cc(period)

        # The press being faded from and the one being faded to.
        self._from: Event = ZERO
        self._to: Event = ZERO
        self._seen: Event | None = None

    def _consume_note(self):
        """Start a fresh glide on a new press. A release ends nothing."""
        pressed = self._note()
        if pressed is None:
            return

        on, _release = pressed
        if not on.after(self._seen):
            return              # already rolling on this press

        self._seen = on
        self._from = self._to
        self._to = on

    def _value(self, ev: Event, edge: EndRef) -> float:
        """What an edge settles on for a given press."""
        return ev.rand(hash(edge)) % 1000 / 1000

    def get(self, now: Event, end: EndRef) -> float:
        self._consume_note()

        # Both ends of an edge answer with the edge's own number.
        edge = end if end.top else end.other()

        # 4s at 0 down to 30ms at 127, a constant ratio per step - a
        # reciprocal spends all its useful travel in the first sixth.
        period = 4000 * (30 / 4000) ** (self._period_cc().data / 127)
        return sweep(now, self._to, period,
                     self._value(self._from, edge), self._value(self._to, edge))


class NoteRippleField(ScalarField):
    """
    A note that spawns a ripple at a random vertex, ramping outwards from it.

    Four latches deep like NoteWipeField, so four ripples can be in flight at
    once - the field is the strongest of them.

    Where a ripple starts comes from the note event itself (`Event.rand`), so
    it needs no stored state: the same event always picks the same vertex.

    A vertex ramps up to 1, then holds at whatever aftertouch the pad is
    reporting - so the front stays full brightness and what is behind it
    follows how hard you are leaning.

    CC:
        * speed - how long the front takes to cross the lattice,
          2000ms at 0 down to 250ms at 127
    """

    RAMP = 300          # ms a vertex takes to go 0 -> 1 once the front reaches it
    DECAY = 500         # ms to fall back to 0 once the note is let go

    SLOWEST = 2000      # ms to cross the lattice at CC 0
    FASTEST = 250       # ms to cross the lattice at CC 127

    def __init__(self, graph: Graph, midi: MIDI, *, note: int, speed: int):
        self._vertexes = list(graph.vertexes())
        self._width = graph.width * TileRef.WIDTH
        self._height = graph.height * TileRef.HEIGHT
        # The lattice wraps, so nothing is ever further than half of it away.
        self._furthest = math.hypot(self._width / 2, self._height / 2)

        self._note = midi.note(note)
        self._poly = midi.polytouch(note)
        self._speed_cc = midi.cc(speed)
        self._latches = [EventLatch() for _ in range(4)]
        self._releases = [EventLatch() for _ in range(4)]
        self._last_latch = 0
        self._current: int | None = None
        self._seen: Event | None = None

    def _consume_note(self):
        """Rotate a new press into the next latch, so ripples can overlap, and
        hang the release off whichever ripple is still going.

        Called from get(), which runs per vertex - so it only acts on an event
        it has not already seen.
        """
        pressed = self._note()
        if pressed is None:
            return

        on, release = pressed

        if self._seen is None or on.after(self._seen):
            self._seen = on
            self._current = self._last_latch
            self._latches[self._current].latch(on)
            self._releases[self._current].clear()    # a fresh press is not over
            self._last_latch = (self._last_latch + 1) % 4

        if release is not None and self._current is not None:
            self._releases[self._current].latch(release)

    def _spawn(self, ev: Event) -> "VertexRef":
        """Where this ripple started - decided by the event, so it never moves."""
        return self._vertexes[ev.rand() % len(self._vertexes)]

    def _distance(self, a, b) -> float:
        """Physical distance, the short way round - the lattice is a torus."""
        ax, ay = a.physical()
        bx, by = b.physical()

        dx = abs(ax - bx)
        dx = min(dx, self._width - dx)

        dy = abs(ay - by)
        dy = min(dy, self._height - dy)

        return math.hypot(dx, dy)

    def get(self, now: Event, end: EndRef) -> float:
        self._consume_note()

        v = end.vertex()

        # How long the front takes to cross the whole lattice, a constant
        # ratio per knob step.
        crossing = self.SLOWEST * (self.FASTEST / self.SLOWEST) ** (self._speed_cc().data / 127)

        # What a vertex holds at once it has finished ramping up.
        pressure = self._poly() / 127

        output = 0
        for i, latch in enumerate(self._latches):
            ev = latch.read()

            if ev is None:
                continue        # this latch has not been used yet

            # The front reaches a vertex later the further out it is, and the
            # vertex ramps up once it arrives.
            arrival = self._distance(self._spawn(ev), v) / self._furthest * crossing
            attack = sweep(now, ev.delay(int(arrival)), self.RAMP, 0, 1, 0)

            released = self._releases[i].read()

            if released is None:
                # The ramp runs its own course; aftertouch only takes over once
                # a vertex has got all the way up.
                level = pressure if attack >= 1 else attack
            else:
                # Letting the note go always falls from 1, however far up the
                # ramp got, and whatever the pad is reporting - but somewhere
                # the front never reached has nothing to fall from.
                decay = sweep(now, released, self.DECAY, 1, 0, 1)
                level = decay if attack > 0 else 0

            output = max(output, level)
            #print

        return output


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

    def __init__(self, graph: Graph, midi: MIDI, *, note: int, speed: int, aim: int):
        self._vertexes = list(graph.vertexes())
        self._width = graph.width * TileRef.WIDTH
        self._height = graph.height * TileRef.HEIGHT

        self._note = midi.note(note)
        self._speed_cc = midi.cc(speed)
        self._aim_cc = midi.cc(aim)

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




class EdgeMaskField(ScalarField):
    def __init__(self, edges: set[EdgeClass]):
        self._edges = edges

    def get(self, now: Event, end: EndRef) -> float:

        return 1 if end.edge_class in self._edges else 0


class FaderField(ScalarField):
    def __init__(self, midi: MIDI, fader: int):
        self._fader_cc = midi.cc(fader)
        self._flipped = False

    def set_flipped(self, flipped: bool):
        self._flipped = flipped

    def get(self, now: Event, end: EndRef) -> float:

        if self._flipped:
            return 1 - self._fader_cc()
        else:
            return self._fader_cc()


class StrobeField(ScalarField):
    def __init__(self, midi: MIDI, strobe: int):
        self._note = midi.note(strobe)

    def get(self, now: Event, end: EndRef) -> float:
        n = self._note()
        if n is None:
            return 0
        
        _, release = n
        return 1 if release is None else 0

        

class ScopeFieldBetter(ScalarField):


    PATTERNS = [
        (0, EdgeClass.A, "RL"),   # Tile Y coord, edge class, path
        (0, EdgeClass.A, "LRRRLL"),
        (0, EdgeClass.A, "LRLRRRLRLL"),
        (0, EdgeClass.A, "LRLRRLRRLRLRLLLR"),
        (0, EdgeClass.E, "LRRLRLRLRLRL"),
    ]
    def __init__(self, graph: Graph, midi: MIDI, *, speed: int, pattern: int):
        self._width = graph.width * TileRef.WIDTH
        self._height = graph.height * TileRef.HEIGHT
        self._graph = graph

        self._speed_cc = midi.cc(speed)
        self._pattern_cc = midi.cc(pattern)

        self._phases: dict[EndRef, list[float]] = {} # 0 to 1
        self._built_time = ZERO

    
    def _rebuild_phases(self, now: Event):

        if self._built_time == now:
            return
        self._phases = {}

        pattern_idx = min(self._pattern_cc().data, len(self.PATTERNS)-1)

        start_tile_y, edge_class, path = self.PATTERNS[pattern_idx]

        start = self._graph.TILE[0, start_tile_y].bottom_end(edge_class)

        # Construct the list of vertexes in this path, overall going left to right
        path_ends: list[EndRef] = []
        last_end = None
        for end in start.path(itertools.cycle(path)):

            if len(path_ends) > 0 and path_ends[0] == end:
                break

            # Add to the vertex list
            path_ends.append(end)

            if last_end is not None:
                path_ends.append(end.other())

            last_end = end
            
        
        # Generate the phases
        for i, v in enumerate(path_ends):

            phase = i / len(path_ends)
            if v not in self._phases:
                self._phases[v] = []
            self._phases[v].append(phase)
            #if v not in self._phases or self._phases[v] < phase:
            #    self._phases[v] = phase 

            #print(f"phases{v} = {phase}")
        #print(self._phases)

        self._built_time = now

    def get(self, now: Event, end: EndRef) -> float:

        # 4 sec at 0 down to 30ms at 127, a constant ratio per step
        period = 4000 * (30 / 4000) ** (self._speed_cc().data / 127)

        self._rebuild_phases(now)

        if end in self._phases:
            #return 1 # TODO Thing

            phases = self._phases[end]
            result = 0
            for phase in phases:
                result = max(result,psweep(now.delay(period * -phase), period, 1, 0))
            return result
            
        else:
            return 0
