"""The scalar fields themselves - a value per vertex, driven by MIDI."""
import math

from pylattice.examples.colors import vary
from pylattice.examples.midi import MIDI
from pylattice.examples.tempo import Event, EventLatch, sweep
from pylattice.fields.types import ScalarField
from pylattice.graph import EndRef, Graph, TileRef, VertexRef


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
        self._period = midi.cc(period) # How long to do one rotation (0 is 0.5 sec, 1 is 1sec, 2 is 2sec)
        self._parts = midi.cc(parts) # How many parts
        self._shape = midi.cc(shape) # What wave shape
    
    def get(self, now: Event, end: EndRef) -> float:
        v = end.vertex()
        offset = v.physical()[0] / (TileRef.WIDTH * self._width) # we are here between 0 -> 1
        #print(v.physical(), offset)
        period = math.pow(2, self._period().data) * 500
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
            
            period = ccv
            if period < 0:
                period = -period
                
            period = period * 5 # period goes from 0 to 5
            
            period = 2000 / (period + 1) # middle CC (0 ccv here) means 2000 ms, max CC is 400ms
            
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

        # How long the front takes to cross the whole lattice
        crossing = self.SLOWEST - (self.SLOWEST - self.FASTEST) * (self._speed_cc().data / 127)

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
