"""The live patch, reachable from another thread.

The render loop runs in the main thread; the REST server runs in its own. Both
go through a Console, which holds one lock. The loop takes it for the whole
frame, so nothing ever renders half a preset.
"""
import threading
from dataclasses import dataclass, field

from pylattice.examples.midi import MIDI
from pylattice.fields.types import ScalarField
from pylattice.runner.preset import FieldRef, Preset, PresetBank, encode_field, named
from pylattice.runner.types import Effect


@dataclass
class Stats:
    """How the render loop is doing."""
    fps: float = 0.0
    render_ms: float = 0.0
    gc_ms: float = 0.0


@dataclass
class ControlState:
    """Where a knob is."""
    cc: int
    value: int


@dataclass
class SlotState:
    """One of an effect's inputs, and what is plugged into it."""
    name: str
    driver: FieldRef | None
    connected: bool


@dataclass
class EffectState:
    name: str
    effect: str
    slots: list[SlotState] = field(default_factory=list)


@dataclass
class PatchState:
    """Everything a UI needs to draw the wiring page."""
    fields: list[str] = field(default_factory=list)
    effects: list[EffectState] = field(default_factory=list)
    controls: list[ControlState] = field(default_factory=list)
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

    def read_settings(self) -> Preset:
        """The patch as it stands."""
        with self.lock:
            return Preset.capture(self._midi, self._fields, self._effects)

    def write_settings(self, preset: Preset):
        """Apply a patch. Knobs it does not mention are left alone."""
        with self.lock:
            preset.apply(self._midi, self._fields, self._effects)

    # -- presets ----------------------------------------------------------

    def read_preset(self, number: int) -> Preset:
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

    def read_controls(self) -> list[ControlState]:
        """Every control's value, lowest CC first."""
        with self.lock:
            return [ControlState(cc, value) for cc, value in sorted(self._midi.get_ccs().items())]

    # -- describing the patch ---------------------------------------------

    def describe(self) -> PatchState:
        """Field names, effects and their slots - what a UI draws from."""
        with self.lock:
            fields = named(self._fields, ScalarField)
            names = {id(f): n for n, f in fields.items()}

            effects = []
            for effect_name, effect in named(self._effects, Effect).items():
                slots = []
                for slot_name, slot in effect.get_slots().items():
                    driver = None
                    if slot.field is not None:
                        try:
                            driver = encode_field(slot.field, names)
                        except ValueError:
                            driver = None       # unnameable, shown as unset
                    slots.append(SlotState(slot_name, driver, slot.connected))
                effects.append(EffectState(effect_name, type(effect).__name__, slots))

            return PatchState(
                fields=list(fields),
                effects=effects,
                controls=self.read_controls(),
                presets=self._bank.saved(),
                selected=self._selected,
                size=self._bank.size,
            )
