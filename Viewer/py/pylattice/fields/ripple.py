"""A front spreading outwards from wherever a note landed."""
import math

from pylattice.examples.midi import MIDIFor
from pylattice.examples.tempo import Event, EventLatch, sweep
from pylattice.fields.types import ScalarField
from pylattice.graph import EndRef, Graph, TileRef


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

    def __init__(self, graph: Graph, midi: MIDIFor, *, note: int, speed: int):
        self._vertexes = list(graph.vertexes())
        self._width = graph.width * TileRef.WIDTH
        self._height = graph.height * TileRef.HEIGHT
        # The lattice wraps, so nothing is ever further than half of it away.
        self._furthest = math.hypot(self._width / 2, self._height / 2)

        self._note = midi.note(note)
        self._poly = midi.polytouch(note)
        self._speed_cc = midi.cc(speed, "speed")
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
