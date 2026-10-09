import os
import sys
from dataclasses import dataclass, field
from typing import Callable
import mido

from pylattice.examples.tempo import Event, EventLatch


@dataclass
class CCState:
    """A control: where it is, and what it is there for.

    `comments` is a list because a control is not owned by one thing - several
    fields can watch the same knob, and each one that names itself when it
    asks leaves its note here.
    """

    event: EventLatch[int] = field(default_factory=EventLatch)
    comments: list[str] = field(default_factory=list)
    # Plumbing rather than a knob - a preset selector, say. Still watched and
    # still latched, just not something to put in front of anyone. Once a
    # watcher calls it plumbing it stays that way; nothing unsets it.
    hidden: bool = False
    # Whether anything asked for this control, as opposed to it merely turning
    # up. A stray CC still gets a state - so it can be seen arriving - but it
    # is not part of the instrument and does not belong in a preset.
    watched: bool = False

    def __post_init__(self):
        # Seeded, so a control nobody has touched reads 0 rather than None.
        # Its `when` is 0, which nothing watching for movement counts as a move.
        self.event.latch(Event(when=0, data=0))

    @property
    def value(self) -> int:
        """Where the control is now."""
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


class MIDI:
    def __init__(self, port: str = 'IAC Driver Bus 1'):
        # mido reaches for python-rtmidi by default, which cannot build on
        # PyPy. portmidi talks to CoreMIDI through ctypes instead, so it needs
        # nothing compiled. An explicit MIDO_BACKEND still wins.
        if sys.implementation.name == 'pypy' and not os.environ.get('MIDO_BACKEND'):
            mido.set_backend('mido.backends.portmidi')

        self._m = mido.open_input(port)
        self._notes: dict[int, NoteState] = {}
        self._ccs: dict[int, CCState] = {}
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
                    note = self._notes.get(msg.note)
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
                    note = self._notes.get(msg.note)
                    if note is not None:
                        note.off.put(msg.velocity)
                case "control_change":
                    print(msg)
                    moved[msg.control] = msg.value
                case "polytouch":
                    note = self._notes.get(msg.note)
                    if note is not None:
                        note.pressure = msg.value
                case "program_change":
                    print(msg)
                    chosen = msg.program

        for control, value in moved.items():
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

    def cc(self, id: int, comment: str | None = None,
           hidden: bool = False) -> Callable[[], Event[int]]:
        """
        Watch a control. Returns a getter for the latest event - its `data` is
        the 0-127 value, its `when` is when the control last moved.

        Seeded at zero, so it is never None. A comment says what is watching
        it, and is kept on the control's state. `hidden` marks the control as
        plumbing, which keeps it out of anything showing what just moved.

        Asking here is also what makes a control part of the instrument, and
        so part of a preset.
        """
        return self._cc_state(id, comment, hidden, watched=True).event.read

    def program(self, comment: str | None = None) -> Callable[[], Event[int]]:
        """
        Watch the program. Returns a getter for the latest program change -
        its `data` is the 0-127 program number, its `when` is when it arrived.

        Seeded at zero like cc(), so it is never None. That seed is not a
        program change, though: it carries `when` 0, which nothing that watches
        for the number changing will mistake for a selection.
        """
        if comment:
            self._program.comments.append(comment)

        return self._program.event.read

    def get_ccs(self) -> dict[int, CCState]:
        """Every control someone has watched or that has moved, by CC number."""
        return dict(self._ccs)

    def set_cc(self, id: int, value: int):
        """Move a control from code - a preset being loaded, say. It lands as a
        change like any other, so anything watching `when` sees it move."""
        self._cc_state(id).event.put(value)

    def _cc_state(self, id: int, comment: str | None = None,
                  hidden: bool = False, watched: bool = False) -> CCState:
        """The state of a control, made on demand - by watching it or by it
        moving. Either way there is one store, so a control that moved before
        anyone watched it keeps its value. Knob positions across runs are a
        preset's job, not this one's."""
        state = self._ccs.get(id)

        if state is None:
            state = CCState()
            self._ccs[id] = state

        if comment:
            state.comments.append(comment)

        if hidden:
            state.hidden = True

        if watched:
            state.watched = True

        return state

    def _note_state(self, id: int, comment: str | None = None) -> NoteState:
        """The state of a note, made on demand. Making one is what makes tick()
        record that note at all, aftertouch included."""
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

    def cc(self, id: int, comment: str = "cc") -> Callable[[], Event[int]]:
        return self.midi.cc(id, f"{self.current_prefix}.{comment}")

    def note(self, id: int, comment: str = "note") -> Callable[
            [], tuple[Event[int], Event[int] | None] | None]:
        return self.midi.note(id, f"{self.current_prefix}.{comment}")

    def polytouch(self, id: int, comment: str = "polytouch") -> Callable[[], int]:
        return self.midi.polytouch(id, f"{self.current_prefix}.{comment}")
