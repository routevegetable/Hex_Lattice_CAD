
from typing import Callable
import mido


class MIDI:
    def __init__(self, port: str = 'IAC Driver Bus 1'):
        self._m = mido.open_input(port)
        self._note_map: dict[int, Callable[[int, bool]]] = {}
        self._clock_fns: list[Callable] = []
        self._start_fns: list[Callable] = []
        self._cc_map: dict[int, int] = {}

    def tick(self):
        msg: mido.Message
        # Consume any pending MIDI messages
        while msg := self._m.poll():
            match msg.type:
                case "start":
                    print("Start")
                case "clock":
                    [cf() for cf in self._clock_fns]
                case "note_on":
                    if msg.note in self._note_map:
                        self._note_map(msg.note, msg.velocity != 0)
                case "note_off":
                    if msg.note in self._note_map:
                        self._note_map(msg.note, False)
                case "control_change":
                    self._cc_map[msg.control] = msg.value

    def cc(self, id: int) -> Callable[[],int]:
        return lambda: self._cc_map.get(id, 0)

    def on_note(self, id: int, fn: Callable[[int, bool], None]):
        """
        Could return an event.
        Called on push and release
        """
        ...

    def on_clock(self, fn: Callable[[]]):
        """
        fn called on 1/24th clock pulse
        """
        ...