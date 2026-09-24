"""Colour maps and envelopes - the non-field half of the instrument.

The fields themselves live in pylattice.fields.
"""
from typing import Protocol

from pylattice.examples.colors import hsv
from pylattice.examples.midi import MIDI
from pylattice.examples.tempo import Event
from pylattice.frame import RGB



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

class CCEnvelope(Envelope):
    def __init__(self, midi: MIDI, *, period_cc: int, up: bool):
        self._period = midi.cc(period_cc)  # How long to do a sweep
        self._up = up  # True if going 0 to 1 else 1 to 0

    def get(self, now: Event, trigger: Event) -> float:

        return 0


class CCHueMap(ColorMap):
    """
    Just a hue that goes from
    0 brightness to max brightness of a CC-specified hue
    """

    def __init__(self, midi: MIDI, *, hue_cc: int):
        self._hue = midi.cc(hue_cc)  # Hue control

    def get(self, v: float, y: float) -> RGB:
        h = self._hue().data / 127
        return list(hsv(h, 1, v))


class CCHueSatMap(ColorMap):
    """
    A hue that goes from 0 saturation to max saturation
    of a CC-specified hue, at CC-specified brightness
    """

    def __init__(self, midi: MIDI, *, hue_cc: int, value_cc: int):
        self._hue = midi.cc(hue_cc)  # Hue control
        self._value = midi.cc(value_cc)  # Value control

    def get(self, s: float, y: float) -> RGB:
        h = self._hue().data / 127
        v = self._value().data / 127
        return list(hsv(h, s, v))


class CCRgbMap(ColorMap):
    """
    Fixed color that goes from 0 brightness to max brightness
    of a CC-specified RGB
    """

    def __init__(self, midi: MIDI, *, r_cc: int, g_cc: int, b_cc):
        self._r = midi.cc(r_cc)  # Red component
        self._g = midi.cc(g_cc)  # Green component
        self._b = midi.cc(b_cc)  # Blue component

    def get(self, v: float, y: float) -> RGB:
        return [
            self._r().data * v / 127,
            self._g().data * v / 127,
            self._b().data * v / 127
        ]
