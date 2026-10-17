"""Slow blooms: a press lights a random handful of edges, which swell and fade."""

from pylattice.examples.midi import MIDIFor
from pylattice.examples.tempo import Event
from pylattice.fields.types import ScalarField
from pylattice.graph import EndRef


class BloomField(ScalarField):
    """
    Each note press picks a random set of edges and sends them through an
    envelope. The note can come from a pad or from the sequencer - it is the
    same note either way - so a run of them gives a run of blooms, which overlap.

    `envelope` is anything with get(now, trigger) -> 0..1 (see ShapedEnvelope).
    `density` is the share of edges each press lights, 0..1.
    """

    OVERLAP = 6  # presses that can be blooming at once
    DEFAULTS = {"attack": 1500.0, "hold": 500.0, "decay": 3000.0, "density": 0.06}

    def __init__(self, midi: MIDIFor, *, note: int, envelope):
        self._note = midi.note(note, "trigger")
        self.envelope = envelope
        self.density = self.DEFAULTS["density"]
        self._presses: list[Event | None] = [None] * self.OVERLAP
        self._next = 0
        self._seen: Event | None = None

    @property
    def params(self) -> dict[str, float]:
        return {
            "attack": self.envelope.attack,
            "hold": self.envelope.hold,
            "decay": self.envelope.decay,
            "density": self.density,
        }

    def set_params(self, params: dict[str, float]):
        """Change any of the above; what is left out stays as it is."""
        for key, value in params.items():
            if key == "density":
                self.density = min(max(float(value), 0.0), 1.0)
            elif key in ("attack", "hold", "decay"):
                setattr(self.envelope, key, max(float(value), 1.0))

    def _consume_note(self):
        """Take a new press, once - get() runs per end, so this must not repeat."""
        pressed = self._note()
        if pressed is None:
            return
        on, _release = pressed
        if self._seen is not None and not on.after(self._seen):
            return
        self._seen = on
        self._presses[self._next] = on
        self._next = (self._next + 1) % self.OVERLAP

    def get(self, now: Event, end: EndRef) -> float:
        self._consume_note()

        # Both ends of an edge share a salt, so the edge blooms as one.
        salt = hash((end.edge_class, end.tile.x, end.tile.y)) & 0xFFFF
        level = 0.0
        for press in self._presses:
            if press is None:
                continue
            if (press.rand(salt) % 1000) / 1000 >= self.density:
                continue
            level = max(level, self.envelope.get(now, press))
        return level
