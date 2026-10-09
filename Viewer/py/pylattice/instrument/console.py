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
class Rig:
    """What can be patched - the names a Patch refers to, and the bank.

    Everything about what is *set* lives in the Patch itself; this is only the
    vocabulary, so a UI knows which fields it may choose and which slots exist
    at all, including the ones nothing is plugged into.
    """
    fields: list[FieldInfo] = field(default_factory=list)
    slots: list[str] = field(default_factory=list)      # "effect.slot"
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
        self._stats = Stats()
        self._selected: int | None = None
        # When a patch was last applied. Controls it moved are not news - the
        # display is for knobs someone turned, not knobs a preset put back.
        self._applied = 0

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

    def read_settings(self) -> Patch:
        """The patch as it stands.

        Also hands it to the bank as the selected preset's current state - a
        knob moving is what makes that preset dirty, and this is where the
        bank finds out about it.
        """
        with self.lock:
            patch = Patch.capture(self._midi, self._fields, self._effects)

            if self._selected is not None:
                self._bank.put(self._selected, patch)

            return patch

    def write_settings(self, patch: Patch, whole: bool = True):
        """Apply a patch. Knobs it does not mention are left alone.

        `whole` says the patch is the rig - slots it leaves out are emptied,
        which is what loading or reverting a preset means. An edit of one slot
        from the UI passes it off, or it would unplug everything else.
        """
        with self.lock:
            patch.apply(self._midi, self._fields, self._effects, whole)
            self._applied = Event.for_now().when

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

    def save_preset(self, number: int):
        """Write a preset's edits out to its file."""
        with self.lock:
            self.read_settings()        # catch up on anything just moved
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
            patch = self.read_settings()
            self._bank.put(number, patch)
            self._selected = number

    def all_presets(self) -> dict[int, Patch]:
        """Every preset the bank holds, each saying whether it is dirty."""
        with self.lock:
            self.read_settings()        # so the selected one is up to date
            return self._bank.get_all()

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
            self.read_settings()        # so `dirty` reflects the knobs now

            slots = [f"{name}.{slot}"
                     for name, effect in named(self._effects, Effect).items()
                     for slot in effect.get_slots()]

            return Rig(
                fields=[FieldInfo(name, type(f).__name__)
                        for name, f in named(self._fields, ScalarField).items()],
                slots=slots,
                presets=self._bank.saved(),
                dirty=self._bank.dirty_presets(),
                selected=self._selected,
                size=self._bank.size,
            )
