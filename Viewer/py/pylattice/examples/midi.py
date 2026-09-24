
import os
import pickle
import sys
from pathlib import Path
from typing import Callable
import mido

from pylattice.examples.tempo import Event, EventLatch


class MIDI:
    def __init__(self, port: str = 'IAC Driver Bus 1', state: str | Path | None = 'midi_cc.pickle'):
        # mido reaches for python-rtmidi by default, which cannot build on
        # PyPy. portmidi talks to CoreMIDI through ctypes instead, so it needs
        # nothing compiled. An explicit MIDO_BACKEND still wins.
        if sys.implementation.name == 'pypy' and not os.environ.get('MIDO_BACKEND'):
            mido.set_backend('mido.backends.portmidi')

        self._m = mido.open_input(port)
        # A note is two latches: when it went down, and when it came up.
        self._note_on: dict[int, EventLatch[int]] = {}
        self._note_off: dict[int, EventLatch[int]] = {}
        self._cc_events: dict[int, EventLatch[int]] = {}
        self._polytouch_map: dict[int, int] = {}

        # Where the knobs were last time, kept open for the life of the run.
        self._state = None
        if state is not None:
            path = Path(state)
            path.touch(exist_ok=True)
            self._state = open(path, 'r+b')
            self._load()

    def _load(self):
        """Put the knobs back where they were. Only the values are kept - an
        Event's `when` is monotonic time, which means nothing across runs, so
        restored controls read as having last moved at 0."""
        self._state.seek(0)
        saved = self._state.read()
        if not saved:
            return

        try:
            values = pickle.loads(saved)
        except Exception as e:
            print(f'ignoring unreadable MIDI state: {e}')
            return

        for control, value in values.items():
            self._cc_latch(control, value)

    def _save(self):
        """Hand the current values to the OS. No fsync - if the machine dies,
        a knob position is not worth the wait."""
        values = {control: latch.read().data for control, latch in self._cc_events.items()}

        self._state.seek(0)
        pickle.dump(values, self._state)
        self._state.truncate()
        self._state.flush()

    def tick(self):
        msg: mido.Message
        # Controls that moved this tick, and where they ended up. Latching once
        # at the end means a burst of messages keeps its last value - latching
        # per message would keep the first, since Event.after is a strict >.
        moved: dict[int, int] = {}
        # Consume any pending MIDI messages
        while msg := self._m.poll():
            match msg.type:
                case "note_on":
                    print(msg)
                    if msg.note in self._note_on:
                        if msg.velocity == 0:
                            self._note_off[msg.note].put(0)     # a note-off in disguise
                        else:
                            self._note_off[msg.note].clear()    # this press is not over
                            self._note_on[msg.note].put(msg.velocity)
                case "note_off":
                    if msg.note in self._note_off:
                        self._note_off[msg.note].put(msg.velocity)
                case "control_change":
                    print(msg)
                    moved[msg.control] = msg.value
                case "polytouch":
                    self._polytouch_map[msg.note] = msg.value

        for control, value in moved.items():
            self._cc_latch(control).put(value)

        if self._state is not None:
            self._save()

    def cc(self, id: int) -> Callable[[], Event[int]]:
        """
        Watch a control. Returns a getter for the latest event - its `data` is
        the 0-127 value, its `when` is when the control last moved.

        Seeded at zero, so it is never None.
        """
        return self._cc_latch(id).read

    def get_ccs(self) -> dict[int, int]:
        """Every control's current value, by CC number."""
        return {control: latch.read().data for control, latch in self._cc_events.items()}

    def set_cc(self, id: int, value: int):
        """Move a control from code - a preset being loaded, say. It lands as a
        change like any other, so anything watching `when` sees it move."""
        self._cc_latch(id).put(value)
        if self._state is not None:
            self._save()

    def _cc_latch(self, id: int, value: int = 0) -> EventLatch[int]:
        """The latch for a control, made on demand - by watching it, by it
        moving, or by being restored from file. Either way there is one store,
        and a control that moved before anyone watched it keeps its value."""
        latch = self._cc_events.get(id)
        if latch is None:
            latch = EventLatch()
            latch.latch(Event(when=0, data=value))
            self._cc_events[id] = latch
        return latch
    
    def polytouch(self, id: int) -> Callable[[], int]:
        return lambda: self._polytouch_map.get(id, 0)

    def note(self, id: int) -> Callable[[], tuple[Event[int], Event[int] | None] | None]:
        """
        Watch a note. Returns a getter for the press and its release:

            (press, None)     while the note is held - press.data is velocity
            (press, release)  once it is let go - release.when is when

        The press is never disturbed by a release, so anything that only cares
        about presses can ignore the second half. None until the note is first
        played.

        Registering here is what makes tick() record the note at all.
        """
        on = self._note_on.setdefault(id, EventLatch())
        off = self._note_off.setdefault(id, EventLatch())

        def get() -> tuple[Event[int], Event[int] | None] | None:
            pressed = on.read()
            return None if pressed is None else (pressed, off.read())

        return get
