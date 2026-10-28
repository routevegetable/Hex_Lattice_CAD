"""The live patch, reachable from another thread.

The render loop runs in the main thread; the REST server runs in its own. Both
go through a Console, which holds one lock. The loop takes it for the whole
frame, so nothing ever renders half a patch.
"""
import threading
from dataclasses import dataclass, field

from pylattice.examples.midi import CCMeta, MIDI
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
    default: int | None = None                          # where a cc was declared


@dataclass
class PresetView:
    """A preset twice over: as it stands, and as its file has it.

    Both copies and no flag: whether a preset has drifted is a question about
    two patches, and the side that has to show what changed is better placed
    to answer it than the side that would only say yes or no.
    """
    live: Patch
    stored: Patch


@dataclass
class Knob:
    """One CC number as it stands, for a UI to draw.

    `age_ms` is how long since it last moved, worked out here because the
    clock is monotonic and means nothing on the other side of the wire. It is
    also how a UI picks out which knob was turned most recently, and whether
    that happened since it started watching.
    """
    cc: int
    value: int
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

    # Presentation metadata for controls
    control_meta: dict[str, CCMeta] = field(default_factory=dict)

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

        # name -> the effect object, built once. The same objects a patch is
        # applied to, indexed so the render loop can name them per frame.
        self._by_effect: dict[str, Effect] = named(effects, Effect)
        self._stats = Stats()
        self._selected: int | None = None

    def controls(self) -> list[ControlInfo]:
        """Every control the instrument watches, and what for.

        Strays that merely turned up on the wire are left out - the same test
        a preset uses to decide what is a setting of ours.
        """
        with self.lock:
            knobs = self._midi.get_ccs_by_number()

            out = [ControlInfo("cc", m.midi_cc, knobs[m.midi_cc].value, [name],
                               m.hidden, m.default_cc)
                   for name, m in self._midi.get_mappings().items()
                   if m.midi_cc in knobs]

            out += [ControlInfo("note", number, state.pressure, list(state.comments))
                    for number, state in self._midi.get_notes().items()]

            return sorted(out, key=lambda c: (c.kind, c.number))

    def set_cc(self, number: int, value: int):
        """Move a knob from outside - a drag in the UI.

        It lands exactly as a knob on the desk would, so the preset that is
        playing picks it up through the bank's fold and goes dirty.
        """
        with self.lock:
            self._midi.set_cc(number, max(0, min(127, value)))

    def knobs(self) -> dict[int, Knob]:
        """Every CC number that has said anything, named or not.

        Nothing is filtered: which of these are worth showing is for whoever
        has the mapping in front of them to decide, and mapping a knob means
        watching the ones that are not yet anybody's.
        """
        with self.lock:
            now = Event.for_now().when

            return {number: Knob(cc=number, value=state.value,
                                 age_ms=now - state.event.read().when)
                    for number, state in self._midi.get_ccs_by_number().items()}

    # -- settings ---------------------------------------------------------

    def _live_ccs(self) -> dict[int, int]:
        """Where every watched knob is sitting now - the ones a control is
        pointed at, not every stray that has turned up on the wire."""
        watched = self._midi.watched_ccs()

        return {number: state.value
                for number, state in self._midi.get_ccs_by_number().items()
                if number in watched}

    def _select(self, number: int | None):
        """Say which preset is playing. The bank needs to know too, so it can
        fold the knobs into the right one."""
        self._selected = number
        self._bank.current = number

    def chain(self) -> list[Effect]:
        """The effects that draw, in the order the patch that is playing names
        them.

        Read off the patch every frame rather than kept anywhere: the list is
        the record, and an effect chain is applied in sequence, so where a
        thing sits in it changes what comes out. A patch with no list at all
        was written before effects could be switched off, and means all of
        them. A name the code no longer has is skipped - apply() has already
        said so.
        """
        with self.lock:
            patch = self._bank.playing()

            if patch is None:
                return []               # nothing selected, nothing to draw

            names = list(self._by_effect) if patch.active is None else patch.active
            return [self._by_effect[name] for name in names if name in self._by_effect]

    def _apply(self, patch: Patch):
        """Put a patch into the rig. Knobs it does not mention are left alone,
        but slots it does not mention are emptied - a patch is the whole
        picture. The lock is already held."""
        patch.apply(self._midi, self._fields, self._effects)

    # -- the four things you can do to a preset ---------------------------

    def write_preset(self, number: int, patch: Patch):
        """Put a patch into a preset's live side.

        If that preset is the one playing, the rig hears it. Writing to any
        other preset is silent - it just sits there until something selects it.
        """
        with self.lock:
            self._bank.put(number, patch)

            if number == self._selected:
                self._apply(patch)

    def select_preset(self, number: int):
        """Play what is in a preset's live side."""
        with self.lock:
            patch = self._bank.read(number)
            self._select(number)            # before applying, so it banks here
            self._apply(patch)

    def commit_preset(self, number: int):
        """Write a preset's live side out to its file."""
        with self.lock:
            self._bank.save(number)

    def revert_preset(self, number: int):
        """Drop a preset's edits and read its file back. If it is the one
        playing, the rig goes back with it."""
        with self.lock:
            patch = self._bank.revert(number)

            if number == self._selected:
                self._apply(patch)

    # -- presets ----------------------------------------------------------

    def read_preset(self, number: int) -> PresetView:
        with self.lock:
            return self._view(number)

    def _view(self, number: int) -> PresetView:
        """A preset against its file. The lock is already held."""
        return PresetView(live=self._bank.read(number),
                          stored=self._bank.stored(number))

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
                control_meta={name: mapping.meta for name, mapping
                              in self._midi.get_mappings().items()},
                selected=self._selected,
                size=self._bank.size,
            )
