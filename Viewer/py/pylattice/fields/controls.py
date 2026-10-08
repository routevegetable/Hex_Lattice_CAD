"""Control-surface inputs read straight out as fields - the same
value at every end, whatever the lattice is doing."""

from pylattice.examples.midi import MIDIFor
from pylattice.examples.tempo import Event
from pylattice.fields.types import ScalarField
from pylattice.graph import EndRef


class CCField(ScalarField):
    """
    A CC as a field
    """


    def __init__(self, midi: MIDIFor, *, value: int):
        self._cc = midi.cc(value, "value")
        
    def get(self, now: Event, end: EndRef) -> float:
        return self._cc().data / 127


class PolyTouchField(ScalarField):
    """
    A polytouch as a field
    """


    def __init__(self, midi: MIDIFor, *, note: int):
        self._poly = midi.polytouch(note)
        
    def get(self, now: Event, end: EndRef) -> float:
        return self._poly() / 127


class FaderField(ScalarField):
    def __init__(self, midi: MIDIFor, fader: int):
        self._fader_cc = midi.cc(fader, "fader")
        self._flipped = False

    def set_flipped(self, flipped: bool):
        self._flipped = flipped

    def get(self, now: Event, end: EndRef) -> float:

        if self._flipped:
            return 1 - self._fader_cc()
        else:
            return self._fader_cc()


class StrobeField(ScalarField):
    def __init__(self, midi: MIDIFor, strobe: int):
        self._note = midi.note(strobe, "strobe")

    def get(self, now: Event, end: EndRef) -> float:
        n = self._note()
        if n is None:
            return 0
        
        _, release = n
        return 1 if release is None else 0
