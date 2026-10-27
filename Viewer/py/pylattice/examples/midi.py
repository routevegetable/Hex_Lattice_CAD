from enum import StrEnum, auto
import os
import sys
from dataclasses import dataclass, field
from typing import Callable, Literal
import mido

from pylattice.examples.tempo import Event, EventLatch


# What a control is, for whoever draws it. A tagged union.
# Just for UI presentation - doesn't affect behavior.

@dataclass(frozen=True)
class FloatRange:
    # Range start and end
    start: float
    end: float
    kind: Literal["float_range"] = "float_range"

@dataclass(frozen=True)
class GradientChoice:
    kind: Literal["gradient"] = "gradient"

@dataclass(frozen=True)
class CustomChoice:
    # value on the wire -> what to call it
    items: dict[int, str]
    kind: Literal["custom"] = "custom"

CCMeta = FloatRange | GradientChoice | CustomChoice

@dataclass
class CCMapping:
    """A named control: where it is plugged in, and where it was declared.

    The name is the identity - `rotary.period` is that control wherever it
    lives. A patch carries only the mappings that differ from their default,
    so a preset written before a control existed still brings it up where it
    was meant to be.
    """

    midi_cc: int | None = None
    default_cc: int | None = None
    # Plumbing rather than a knob - a preset selector, say. Still watched and
    # still latched, just not something to put in front of anyone.
    hidden: bool = False

    meta: CCMeta = FloatRange(0, 127)


@dataclass
class CCState:
    """One CC number: what it last read, and what is listening to it.

    The state belongs to the knob, not to whatever is plugged into it, so a
    value is a knob position rather than a control's memory of one. Several
    names can sit on the same number and all of them read it.
    """

    event: EventLatch[int] = field(default_factory=EventLatch)
    comments: set[str] = field(default_factory=set)

    def __post_init__(self):
        # Seeded, so a knob nobody has touched reads 0 rather than None. Its
        # `when` is 0, which nothing watching for movement counts as a move.
        self.event.latch(Event(when=0, data=0))

    @property
    def value(self) -> int:
        """Where the knob is now."""
        return self.event.read().data


@dataclass
class NoteState:
    """A note: when it went down, when it came up, how hard it is being leaned
    on, and what it is there for.

    Aftertouch lives here rather than in a map of its own - it is the same key
    being talked about, and anything watching one usually wants the other.
    """

    on: EventLatch[int] = field(default_factory=EventLatch)
    off: EventLatch[int] = field(default_factory=EventLatch)
    # Set to the velocity when the key goes down, then moved by aftertouch.
    # It is not cleared on release - the last press stands as a level.
    pressure: int = 0
    comments: list[str] = field(default_factory=list)


# Notes from elsewhere that count as one of the BSP's pads. The instrument
# only knows 36-51, so anything another box plays has to arrive as one of
# those or nothing is watching it.
#
# 60 is 36 two octaves up, so 60-75 lines up with the pads one for one and the
# rest of the range wraps back round. Hardcoded for now: when there is a second
# box worth naming, this becomes something it owns rather than a constant here.
PAD_ALIASES: dict[int, int] = {note: 36 + (note - 60) % 16
                               for note in range(60, 87)}


class MIDI:
    def __init__(self, port: str = 'IAC Driver Bus 1'):
        # mido reaches for python-rtmidi by default, which cannot build on
        # PyPy. portmidi talks to CoreMIDI through ctypes instead, so it needs
        # nothing compiled. An explicit MIDO_BACKEND still wins.
        if sys.implementation.name == 'pypy' and not os.environ.get('MIDO_BACKEND'):
            mido.set_backend('mido.backends.portmidi')

        self._m = mido.open_input(port)
        self._notes: dict[int, NoteState] = {}

        # Note number -> the pad it counts as. Applied on the way in and on
        # registration both, so an aliased number is the same pad everywhere
        # rather than a number that quietly watches nothing.
        self._pads = dict(PAD_ALIASES)

        # CC number -> what that knob last read. The primary store: every
        # number that says anything gets one, plugged into or not, which is
        # how a knob can be seen moving before it has been mapped.
        self._cc_by_id: dict[int, CCState] = {}

        # name -> which number it is listening to. A lookup, not a store.
        self._ccs: dict[str, CCMapping] = {}

        # One program per channel, not one per number, so a single state does.
        self._program = CCState()

    def tick(self):
        msg: mido.Message
        # Controls that moved this tick, and where they ended up. Latching once
        # at the end means a burst of messages keeps its last value - latching
        # per message would keep the first, since Event.after is a strict >.
        moved: dict[int, int] = {}
        # Likewise the program, if one was selected this tick.
        chosen: int | None = None
        # Consume any pending MIDI messages
        while msg := self._m.poll():
            match msg.type:
                case "note_on":
                    print(msg)
                    note = self._notes.get(self.pad(msg.note))
                    if note is not None:
                        if msg.velocity == 0:
                            note.off.put(0)             # a note-off in disguise
                        else:
                            note.off.clear()            # this press is not over
                            note.on.put(msg.velocity)
                            # How hard it was hit is where the pressure
                            # starts; polytouch takes it from there.
                            note.pressure = msg.velocity
                case "note_off":
                    note = self._notes.get(self.pad(msg.note))
                    if note is not None:
                        note.off.put(msg.velocity)
                case "control_change":
                    print(msg)
                    moved[msg.control] = msg.value
                case "polytouch":
                    note = self._notes.get(self.pad(msg.note))
                    if note is not None:
                        note.pressure = msg.value
                case "program_change":
                    print(msg)
                    chosen = msg.program

        for control, value in moved.items():
            # Every number, whether anything is listening or not: an unplugged
            # knob still has to be visible to be mapped onto.
            self._cc_state(control).event.put(value)

        if chosen is not None:
            self._program.event.put(chosen)

    def for_(self, prefix: str) -> "MIDIFor":
        """This same box, but everything asked of it says who asked.

        `for` is a keyword, hence the underscore. Hand one of these to a field
        instead of the MIDI object and its controls end up labelled with the
        field's name rather than just being watched by something unnamed.
        """
        return MIDIFor(prefix, self)

    def cc(self, default_id: int, comment: str,
           meta: CCMeta = FloatRange(0, 127),
           hidden: bool = False) -> Callable[[], Event[int]]:
        """
        Watch a control by name. Returns a getter for the latest event - its
        `data` is the 0-127 value, its `when` is when the control last moved.

        `comment` is the control's identity, not a label. `rotary.period` is
        that control wherever it is plugged in, and `default_id` is only where
        it starts out - a patch can move it somewhere else. Two things asking
        by the same name get the same control, which is how the phase-shifted
        copies of an effect share one knob.

        Seeded at zero, so it is never None. `hidden` marks the control as
        plumbing, which keeps it out of anything showing what just moved.
        """
        mapping = self._ccs.get(comment)

        if mapping is None:
            mapping = CCMapping(default_cc=default_id, hidden=hidden, meta=meta)
            self._ccs[comment] = mapping
            self._attach(comment, default_id)
        elif hidden:
            mapping.hidden = True

        # The value belongs to the knob, so the lookup happens on every read.
        # Two dict hops against a frame: not worth designing around.
        return lambda: self._cc_state(mapping.midi_cc).event.read()

    def _attach(self, comment: str, number: int):
        """Point a named control at a CC number, off whatever it was on."""
        mapping = self._ccs[comment]
        old = mapping.midi_cc

        if old is not None and old in self._cc_by_id:
            self._cc_by_id[old].comments.discard(comment)

        mapping.midi_cc = number
        self._cc_state(number).comments.add(comment)

    def cc_map(self) -> dict[str, int]:
        """Where every named control is plugged in, by name."""
        return {name: m.midi_cc for name, m in self._ccs.items()
                if m.midi_cc is not None}

    def cc_defaults(self) -> dict[str, int]:
        """Where every named control was declared to live."""
        return {name: m.default_cc for name, m in self._ccs.items()
                if m.default_cc is not None}

    def set_cc_map(self, mapping: dict[str, int]):
        """Move named controls. Anything the mapping leaves out goes back to
        the default it was declared with. Two controls may share a number -
        both end up on that knob's state and both read it."""
        for name, m in self._ccs.items():
            wanted = mapping.get(name, m.default_cc)

            if wanted is not None and wanted != m.midi_cc:
                self._attach(name, wanted)

    def program(self, comment: str | None = None) -> Callable[[], Event[int]]:
        """
        Watch the program. Returns a getter for the latest program change -
        its `data` is the 0-127 program number, its `when` is when it arrived.

        Seeded at zero like cc(), so it is never None. That seed is not a
        program change, though: it carries `when` 0, which nothing that watches
        for the number changing will mistake for a selection.
        """
        if comment:
            self._program.comments.add(comment)

        return self._program.event.read

    def get_mappings(self) -> dict[str, CCMapping]:
        """Every named control, and where it is listening."""
        return dict(self._ccs)

    def get_ccs_by_number(self) -> dict[int, CCState]:
        """Every CC number that has said anything, plugged into or not."""
        return dict(self._cc_by_id)

    def get_notes(self) -> dict[int, NoteState]:
        """Every note someone has watched, by note number."""
        return dict(self._notes)

    def set_cc(self, id: int, value: int):
        """Move a control from code - a preset being loaded, say. It lands as a
        change like any other, so anything watching `when` sees it move.

        Addressed by CC number, because that is what a preset records: where
        the knobs on the desk are sitting.

        Setting a knob to where it already is does nothing at all. A patch
        writes every control it carries whether or not any of them changed, so
        without this an edit to anything would make all thirty-odd look as
        though a hand had just been on them. Only the real path, through
        tick(), stamps a repeat - a button sending the same value twice is two
        presses.
        """
        state = self._cc_state(id)

        if state.value != value:
            state.event.put(value)

    def _cc_state(self, number: int) -> CCState:
        """What a CC number last read, made on demand. Every number that
        speaks gets one, so a knob nothing is plugged into is still visible."""
        state = self._cc_by_id.get(number)

        if state is None:
            state = CCState()
            self._cc_by_id[number] = state

        return state

    def pad(self, note: int) -> int:
        """Which pad a note counts as. Its own number, unless it is one of the
        aliases for a pad this box already has."""
        return self._pads.get(note, note)

    def _note_state(self, id: int, comment: str | None = None) -> NoteState:
        """The state of a note, made on demand. Making one is what makes tick()
        record that note at all, aftertouch included."""
        id = self.pad(id)
        state = self._notes.get(id)

        if state is None:
            state = NoteState()
            self._notes[id] = state

        if comment:
            state.comments.append(comment)

        return state

    def polytouch(self, id: int, comment: str | None = None) -> Callable[[], int]:
        """Watch how hard a note is being leaned on. Shares its state with
        note(), so either call registers the key."""
        state = self._note_state(id, comment)
        return lambda: state.pressure

    def note(self, id: int, comment: str | None = None) -> Callable[[], tuple[Event[int], Event[int] | None] | None]:
        """
        Watch a note. Returns a getter for the press and its release:

            (press, None)     while the note is held - press.data is velocity
            (press, release)  once it is let go - release.when is when

        The press is never disturbed by a release, so anything that only cares
        about presses can ignore the second half. None until the note is first
        played.

        Registering here is what makes tick() record the note at all.
        """
        state = self._note_state(id, comment)

        def get() -> tuple[Event[int], Event[int] | None] | None:
            pressed = state.on.read()
            return None if pressed is None else (pressed, state.off.read())

        return get


@dataclass
class MIDIFor:
    """A MIDI object that names what it is asking on behalf of.

    Straight passthrough, except that comments come out as `{prefix}.{comment}`
    - and a caller that leaves the comment off still says what kind of thing it
    took, so a control is never watched by something anonymous.
    """

    current_prefix: str
    midi: MIDI

    def cc(self, id: int, comment: str = "cc",
           meta: CCMeta = FloatRange(0, 127)) -> Callable[[], Event[int]]:
        return self.midi.cc(id, f"{self.current_prefix}.{comment}", meta)

    def note(self, id: int, comment: str = "note") -> Callable[
            [], tuple[Event[int], Event[int] | None] | None]:
        return self.midi.note(id, f"{self.current_prefix}.{comment}")

    def polytouch(self, id: int, comment: str = "polytouch") -> Callable[[], int]:
        return self.midi.polytouch(id, f"{self.current_prefix}.{comment}")
