"""A front crossing the lattice top to bottom, or the other way."""
import math

from pylattice.examples.midi import MIDIFor
from pylattice.examples.tempo import Event, EventLatch, sweep
from pylattice.fields.types import ScalarField
from pylattice.graph import EndRef, Graph, TileRef


class WipeField(ScalarField):
    def __init__(self, graph: Graph, midi: MIDIFor, *, period: int):
        self._width = graph.width
        self._height = graph.height
        self._period = midi.cc(period, "period") # How long to do one wipe
    
    def get(self, now: Event, end: EndRef) -> float:
        return 0


class NoteWipeField(ScalarField):
    """
    A note that makes a wipe field
    
    CC:
        * 0-63 means down, 64-127 is up
        * diff from center is velocity. 63 is 0.1 sec. 0 is 1 sec
    
    """


    def __init__(self, midi: MIDIFor, *, note: int, speed: int):
        self._note = midi.note(note)
        self._speed_cc = midi.cc(speed, "speed")
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
