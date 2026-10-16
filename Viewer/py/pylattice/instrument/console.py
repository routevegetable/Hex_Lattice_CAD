"""The live patch, reachable from another thread.

The render loop runs in the main thread; the REST server runs in its own. Both
go through a Console, which holds one lock. The loop takes it for the whole
frame, so nothing ever renders half a patch.
"""
import threading
from dataclasses import dataclass, field

from pylattice.examples.midi import MIDI
from pylattice.examples.tempo import Event
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
class FieldInfo:
    """A field a slot can be pointed at, and what kind it is."""
    name: str
    kind: str


@dataclass
class ControlInfo:
    """A control on the box, and what the instrument uses it for.

    `comments` is what asked for it, as `field.role` - the same thing the
    knob readout shows. One control can have several.
    """
    kind: str                                           # "cc" or "note"
    number: int
    value: int                                          # or pressure, for a note
    comments: list[str] = field(default_factory=list)
    hidden: bool = False


@dataclass
class PresetView:
    """A preset twice over: as it stands, and as its file has it.

    Both copies rather than a flag, so a UI can work out exactly what has been
    changed rather than only that something has.
    """
    live: Patch
    stored: Patch
    dirty: bool = False


@dataclass
class Knob:
    """The control that moved most recently, for a UI to show as it happens.

    `age_ms` is how long ago, worked out here because the clock is monotonic
    and means nothing on the other side of the wire.
    """
    cc: int
    value: int
    comments: list[str] = field(default_factory=list)
    age_ms: int = 0


@dataclass
class EffectInfo:
    """An effect, and the slots it has to plug fields into."""
    slots: list[str] = field(default_factory=list)


@dataclass
class Rig:
    """What can be patched - the names a Patch refers to, and the bank.

    Everything about what is *set* lives in the Patch itself; this is only the
    vocabulary, so a UI knows which fields it may choose and which slots exist
    at all, including the ones nothing is plugged into. A slot is named
    `effect.slot` wherever a Patch refers to one; here the two halves are kept
    apart, since the effect is what a UI groups by.
    """
    fields: list[FieldInfo] = field(default_factory=list)
    effects: dict[str, EffectInfo] = field(default_factory=dict)
    presets: list[int] = field(default_factory=list)
    dirty: list[int] = field(default_factory=list)      # edited since saving
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
        bank.live_ccs = self._live_ccs      # so the bank can keep up with the knobs
        self._stats = Stats()
        self._selected: int | None = None
        # When a patch was last applied. Controls it moved are not news - the
        # display is for knobs someone turned, not knobs a preset put back.
        self._applied = 0

    def controls(self) -> list[ControlInfo]:
        """Every control the instrument watches, and what for.

        Strays that merely turned up on the wire are left out - the same test
        a preset uses to decide what is a setting of ours.
        """
        with self.lock:
            out = [ControlInfo("cc", number, state.value,
                               list(state.comments), state.hidden)
                   for number, state in self._midi.get_ccs().items() if state.watched]

            out += [ControlInfo("note", number, state.pressure, list(state.comments))
                    for number, state in self._midi.get_notes().items()]

            return sorted(out, key=lambda c: (c.kind, c.number))

    def last_cc(self) -> Knob | None:
        """Whichever control moved last, or None if none ever has.

        Controls are seeded at `when` 0, which is not a move - a knob nobody
        has touched since the app started is not news, nor is a knob that a
        preset moved. Controls marked hidden are skipped outright.
        """
        with self.lock:
            now = Event.for_now().when

            latest, moved = None, 0
            for number, state in self._midi.get_ccs().items():
                if state.hidden:
                    continue                # plumbing, not a knob anyone turned

                when = state.event.read().when

                if when <= self._applied:
                    continue                # a preset put it there, not a hand

                if when > moved:
                    latest, moved = (number, state), when

            if latest is None:
                return None

            number, state = latest
            return Knob(cc=number, value=state.value,
                        comments=list(state.comments), age_ms=now - moved)

    # -- settings ---------------------------------------------------------

    def _live_ccs(self) -> dict[int, int]:
        """Where every watched knob is sitting now."""
        return {number: state.value
                for number, state in self._midi.get_ccs().items() if state.watched}

    def _select(self, number: int | None):
        """Say which preset is playing. The bank needs to know too, so it can
        fold the knobs into the right one."""
        self._selected = number
        self._bank.current = number

    def read_settings(self) -> Patch:
        """The patch as it stands.

        A plain read of the rig - nothing is banked. What a preset is holding
        is the bank's business: slots get there through write_settings, and
        knob positions through the bank's own fold.
        """
        with self.lock:
            return Patch.capture(self._midi, self._fields, self._effects)

    def write_settings(self, patch: Patch):
        """Apply a patch. Knobs it does not mention are left alone, but slots
        it does not mention are emptied - a patch is the whole picture."""
        with self.lock:
            patch.apply(self._midi, self._fields, self._effects)
            self._applied = Event.for_now().when

            # What is playing is what this preset now holds. The knobs come
            # back round through the fold, so a patch with no ccs in it - what
            # the UI posts - does not lose them.
            if self._selected is not None:
                self._bank.put(self._selected, patch)

    # -- presets ----------------------------------------------------------

    def read_preset(self, number: int) -> PresetView:
        with self.lock:
            return self._view(number)

    def _view(self, number: int) -> PresetView:
        """A preset against its file. The lock is already held."""
        return PresetView(live=self._bank.read(number),
                          stored=self._bank.stored(number),
                          dirty=self._bank.dirty(number))

    def store_current_to(self, number: int):
        with self.lock:
            self._bank.write(number, self.read_settings())
            self._select(number)

    def load_current_from(self, number: int):
        with self.lock:
            patch = self._bank.read(number)
            self._select(number)            # before applying, so it banks here
            self.write_settings(patch)

    def save_preset(self, number: int):
        """Write a preset's edits out to its file."""
        with self.lock:
            self._bank.save(number)

    def revert_preset(self, number: int) -> Patch:
        """Drop a preset's edits. If it is the one playing, put it back live."""
        with self.lock:
            patch = self._bank.revert(number)

            if number == self._selected:
                self.write_settings(patch)

            return patch

    def duplicate_current_to(self, number: int):
        """Put what is playing into another preset, and move there.

        Nothing is written - the slot is left dirty, so the save button is
        what commits it. The rig carries on untouched; it is the same patch,
        it just answers to a different preset now. The one being left keeps
        its own edits, since reading the settings banks them first.
        """
        with self.lock:
            patch = self._bank.read(self._selected) if self._selected is not None \
                else self.read_settings()
            self._bank.put(number, patch)
            self._select(number)

    def all_presets(self) -> dict[int, PresetView]:
        """Every preset the bank holds, each against its file."""
        with self.lock:
            return {number: self._view(number) for number in range(self._bank.size)}

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
            effects = {name: EffectInfo(list(effect.get_slots()))
                       for name, effect in named(self._effects, Effect).items()}

            return Rig(
                fields=[FieldInfo(name, type(f).__name__)
                        for name, f in named(self._fields, ScalarField).items()],
                effects=effects,
                presets=self._bank.saved(),
                dirty=self._bank.dirty_presets(),
                selected=self._selected,
                size=self._bank.size,
            )
