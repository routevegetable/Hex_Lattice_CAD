"""The live patch, reachable from another thread.

The render loop runs in the main thread; the REST server runs in its own. Both
go through a Console, which holds one lock. The loop takes it for the whole
frame, so nothing ever renders half a patch.
"""
import threading
from dataclasses import dataclass, field

from pylattice.examples.midi import MIDI
from pylattice.fields.types import ScalarField
from pylattice.instrument.patch import Patch, PresetBank, named
from pylattice.instrument.types import Effect


@dataclass
class Stats:
    """How the render loop is doing."""
    fps: float = 0.0
    render_ms: float = 0.0
    gc_ms: float = 0.0


@dataclass
class Rig:
    """What can be patched - the names a Patch refers to, and the bank.

    Everything about what is *set* lives in the Patch itself; this is only the
    vocabulary, so a UI knows which fields it may choose and which slots exist
    at all, including the ones nothing is plugged into.
    """
    fields: list[str] = field(default_factory=list)
    slots: list[str] = field(default_factory=list)      # "effect.slot"
    presets: list[int] = field(default_factory=list)
    selected: int | None = None
    size: int = 16


class Console:
    """Thread-safe access to the patch. Every method takes the lock."""

    def __init__(self, midi: MIDI, fields: type, effects: type, bank: PresetBank):
        self.lock = threading.RLock()
        self._midi = midi
        self._fields = fields
        self._effects = effects
        self._bank = bank
        self._stats = Stats()
        self._selected: int | None = None

    # -- settings ---------------------------------------------------------

    def read_settings(self) -> Patch:
        """The patch as it stands."""
        with self.lock:
            return Patch.capture(self._midi, self._fields, self._effects)

    def write_settings(self, patch: Patch):
        """Apply a patch. Knobs it does not mention are left alone."""
        with self.lock:
            patch.apply(self._midi, self._fields, self._effects)

    # -- presets ----------------------------------------------------------

    def read_preset(self, number: int) -> Patch:
        with self.lock:
            return self._bank.read(number)

    def store_current_to(self, number: int):
        with self.lock:
            self._bank.write(number, self.read_settings())
            self._selected = number

    def load_current_from(self, number: int):
        with self.lock:
            self.write_settings(self._bank.read(number))
            self._selected = number

    def selected(self) -> int | None:
        with self.lock:
            return self._selected

    # -- stats ------------------------------------------------------------

    def get_stats(self) -> Stats:
        with self.lock:
            return Stats(self._stats.fps, self._stats.render_ms, self._stats.gc_ms)

    def set_stats(self, fps: float, render_ms: float, gc_ms: float):
        with self.lock:
            self._stats = Stats(fps, render_ms, gc_ms)

    # -- what there is to patch -------------------------------------------

    def describe(self) -> Rig:
        with self.lock:
            slots = [f"{name}.{slot}"
                     for name, effect in named(self._effects, Effect).items()
                     for slot in effect.get_slots()]

            return Rig(
                fields=list(named(self._fields, ScalarField)),
                slots=slots,
                presets=self._bank.saved(),
                selected=self._selected,
                size=self._bank.size,
            )
