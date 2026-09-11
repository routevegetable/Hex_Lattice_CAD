import math
from typing import Protocol
from py.pylattice.examples.colors import hsv, vary
from py.pylattice.examples.midi import MIDI
from py.pylattice.examples.tempo import ZERO, Event, EventLatch, psweep, sweep
from py.pylattice.frame import RGB
from py.pylattice.graph import Graph, TileRef, VertexRef

class ScalarField(Protocol):
    """
    Something that has a value for each vertex.
    Rotating.
    Wiping.
    Particle distance.
    """
    def get(self, now: Event, v: VertexRef) -> float: ...
    
    def __add__(self, other: ScalarField) -> ScalarField:
        orig = self
        class Sum(ScalarField):
            def get(self, now: Event, v: VertexRef) -> float:
                return orig.get(now, v) + other.get(now, v)
        return Sum()
    
class ColorField(Protocol):
    """
    Something that has a color for each vertex.
    """
    def get(self, now: Event, v: VertexRef) -> RGB: ...

class ColorMap(Protocol):
    """
    A color mapping
    """
    def get(self, x: float, y: float) -> RGB: ...
    
class Envelope(Protocol):
    """
    Produce a scalar that changes over time.
    """
    def get(self, now: Event, trigger: Event) -> float: ...



class CCField(ScalarField):
    """
    A CC as a field
    """
    def __init__(self, midi: MIDI, *, value_cc: int):
        self._cc = midi.cc(value_cc)
        
    def get(self, now: Event, v: VertexRef) -> float:
        return self._cc() / 127

class RotaryField(ScalarField):
    
    def __init__(self, graph: Graph, midi: MIDI, *, period_cc: int, parts_cc: int, shape_cc: int):
        self._width = graph.width
        self._height = graph.height
        self._period = midi.cc(period_cc) # How long to do one rotation (0 is 0.5 sec, 1 is 1sec, 2 is 2sec)
        self._parts = midi.cc(parts_cc) # How many parts
        self._shape = midi.cc(shape_cc) # What wave shape
    
    def get(self, now: Event, v: VertexRef) -> float:
        offset = v.physical()[0] / (TileRef.WIDTH * self._width) # we are here between 0 -> 1
        #print(v.physical(), offset)
        period = math.pow(2, self._period()) * 500
        return vary(now, 0, 1, period, offset)

class WipeField(ScalarField):
    def __init__(self, graph: Graph, midi: MIDI, *, period_cc: int):
        self._width = graph.width
        self._height = graph.height
        self._period = midi.cc(period_cc) # How long to do one wipe
    
    def get(self, now: Event, v: VertexRef) -> float:
        return 0
    
class CCEnvelope(Envelope):
    def __init__(self, midi: MIDI, *, period_cc: int, up: bool):
        self._period = midi.cc(period_cc) # How long to do a sweep
        self._up = up # True if going 0 to 1 else 1 to 0
    
    def get(self, now: Event, trigger: Event) -> float:
        
        
        return 0

class CCHueMap(ColorMap):
    """
    Just a hue that goes from
    0 brightness to max brightness of a CC-specified hue
    """
    def __init__(self, midi: MIDI, *, hue_cc: int):
        self._hue = midi.cc(hue_cc) # Hue control
    
    def get(self, v: float, y: float) -> RGB:
        h = self._hue() / 127
        return list(hsv(h, 1, v))
    
class CCHueSatMap(ColorMap):
    """
    A hue that goes from 0 saturation to max saturation
    of a CC-specified hue, at CC-specified brightness
    """
    def __init__(self, midi: MIDI, *, hue_cc: int, value_cc: int):
        self._hue = midi.cc(hue_cc) # Hue control
        self._value = midi.cc(value_cc) # Value control
    
    def get(self, s: float, y: float) -> RGB:
        h = self._hue() / 127
        v = self._value() / 127
        return list(hsv(h, s, v))
    
class CCRgbMap(ColorMap):
    """
    Fixed color that goes from 0 brightness to max brightness
    of a CC-specified RGB
    """
    def __init__(self, midi: MIDI, *, r_cc: int, g_cc: int, b_cc):
        self._r = midi.cc(r_cc) # Red component
        self._g = midi.cc(g_cc) # Green component
        self._b = midi.cc(b_cc) # Blue component
    
    def get(self, v: float, y: float) -> RGB:
        return [
            self._r() * v / 127,
            self._g() * v / 127,
            self._b() * v / 127
        ]
        

class WipeField(ScalarField):
    def __init__(self, graph: Graph, midi: MIDI, *, period_cc: int):
        self._width = graph.width
        self._height = graph.height
        self._period = midi.cc(period_cc) # How long to do one wipe
    
    def get(self, now: Event, v: VertexRef) -> float:
        return 0

class NoteWipeField(ScalarField):
    """
    A note that makes a wipe field
    
    CC:
        * 0-63 means down, 64-127 is up
        * diff from center is velocity. 63 is 0.1 sec. 0 is 1 sec
    
    """
    def __init__(self, midi: MIDI, *, note: int, speed_cc: int):
        midi.on_note(note, self.on_note)
        self._speed_cc = midi.cc(speed_cc)
        self._latches = [EventLatch() for _ in range(4)]
        self._last_latch = 0
        
    def on_note(self, vel: int, on: bool):
        self._latches[self._last_latch].put()
        self._last_latch = (self._last_latch + 1) % 4
        
    def get(self, now: Event, v: VertexRef) -> float:
        
        output = 0
        for latch in self._latches:
            ev = latch.read()
            if ev is None:
                return 0
            
            ccv = self._speed_cc() / 64 - 1 # CCV goes from -1 to 1
            
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
            
            output = max(output, min(1, math.sin(sweep(now, ev.delay(dy * period), period, 0, math.pi, 0))))
        
        return output
            
        #if ccv > 0:
        #    # Up
        #    return sweep(now, ev, period, 0, v.tile.graph.height, 0)
        #else:
        #    # Down
        #    return sweep(now, ev, period, v.tile.graph.height, 0, v.tile.graph.height)
       # 
       # return