
import math
import threading
import time
from py.pylattice.examples import clk
from py.pylattice.examples.tempo import Event, EventLatch, psweep, sweep
from py.pylattice.graph import EndRef, Graph
from py.pylattice.lattice_writer import LatticeWriter


COLS = 16
ROWS = 3

graph = Graph(COLS, ROWS)

lattice = LatticeWriter(COLS / 2, ROWS)


# MIDI clock should provide 'now'.

# Need to be able to sync LFO with the incoming midi clock.
# Need to be able to also adjust the LFO in realtime

# The midi clock is an event that happens periodically
# When it happens it resets the LFOs that are synced to it.

# A period can be provided in terms of the midi clock

# To sync the midi clock to the common timebase we need to be able to speed up or slow down
# the latter until they are in sync.

import mido


m = mido.open_input('IAC Driver Bus 1')
last_qn: int = 1

gen = clk.ClockGenerator(24)

lfo = clk.QNLFO(gen)

def midi_thread():
    global last_qn
    msg: mido.Message

    while True:
        # Consume any pending MIDI messages
        while msg := m.poll():
            print("MSG " + str(msg))
            match msg.type:
                case "start":
                    gen.reset()
                case "clock":
                    gen.on_pulse()
                case "note_on":
                    ...
                case "note_off":
                    ...
        
        gen.tick()

        qn = int(gen.get_qn())

        if qn != last_qn:
            print(f"QN: {qn}")
            last_qn = qn

        time.sleep(0.001)



# Want a MIDI wrapper that exposes a number of events:
# * Clock
# * Note On
# * Note Off
# Clock event should be produced every N clock messages
# Multiple divisors should be available

class PLL:
    # Exposes an event for any given fraction of the clock
    def __init__(self):
        self._ctr = 0
        self._last_tick = Event()

    def run(self, now: Event, input: Event, ppqn: int):
        """
        input is the clock input
        div is the prescaler
        """

        if not input.after(self._last_tick):
            return
        else:
            # New tick
            self._ctr = self._ctr + 1
            if self._ctr != ppqn:
                # Don't do anything yet
                return
            else:
                # Reset
                self._ctr = 0

        # Do something
        tick_len = now.when - input.when


    def __getitem__(self, mult: float) -> Event:
        """
        mult may be 1, in which case, we should get a new thing
        every note.
        mult may be 1/2 (0.5), in which case, we should get a new thing every half note.
        mult may be 3, in which case we should get a new thing every 3 notes.
        """
        # Since

# A clock generator thing has an input scaler (how many beats in a clock period)
# and how many divisions
"""
When you receive a tick from MIDI, you know the next one is coming in 12.5msec.
If the timer is more than 50% complete, we haven't quite hit the local tick yet - increment the phase accumulator by 1/24.
If the timer is less than 50% complete, we already hit the local tick - don't increment the phase accumulator.

If the clock comes in just before expected, we manually reset the timer, incrementing the accumulator.
If the clock comes in just after expected, we reset the timer without incrementing the accumulator.


We want a monotonic function to tell us our notion of time.

Once we have this locally sync'd clock, we can get events and values out of it.

The phase accumulator is monotonic. We need things smaller than that to be monotonic.
Should be bring in some kind of pause?

At 120BPM, 12.5ms, that means 80 events per second.
A discrete visual event can't be identified with that kind of granularity.

Whenever a phase accumulation event happens, we should trigger events and re-measure.

A phase accumulation event is a 24th of a quarter note.
So we need a quarter note counter. that's the phase accumulator thingy.

We can get an LFO that's synced with the start of that.
Want to modulo the quarter note counter by whatever length we care about.
When the result of that rolls over to 0, we fire that event.

Each "LFO" object we get from the clock generator has a measured clock length, and an event.


12.

Each frame, we have a msec value that's the current time.

When the phase accumulator hits 1, that's a beat.

"""

class ClockGenerator:

    def __init__(self, ppqn):
        # number of pulses per quarter note
        self.ppqn = ppqn

        # number of quarter notes since reset()
        self.qn = 0

        # Current start of quarter note timer
        self.qn_start = 0

        # Whether we are in the last half of the 
        self.first_half = True

    def reset(self, now: Event):
        self.qn = 0
        self.qn_start = now
        self.first_half = True

    def tick(self, now: int, last_qn: int):

        # Called every superloop thingy
        
        # How long since last quarter note start
        dt = now - self.qn_start

        # Offset into quarter note time
        qn_offset = dt % self.ppqn

        # Are we in the first half?
        first_half = qn_offset < self.ppqn / 2

        if not self.first_half and first_half:
            # Rolled over - reset the timer, increment qn
            self.first_half = False # Now we are in first half
            self.qn_start = last_qn
            self.qn = self.qn + 1

        elif last_qn != self.qn_start:
            # Didn't roll over - got a new tick

            if not self.first_half:
                # Came in before we hit - reset the timer, increment qn
                self.qn = self.qn + 1
            
            # Reset the timer
            self.qn_start = last_qn
            self.first_half = True



class MidiControl:
    def __init__(self, port: str):
        self._port = mido.open_input(port)

        self.BPM = {}

# So a midi clock is just an event.
# An LFO needs to be able to change frequency seamlessly
# Can't just 'periodic' about it
# Every period a new trigger point should be set.


def get_value_for_filament(now: Event, end: EndRef, filament_idx: int) -> float:
    period = 3000
    offset = (end.__hash__() + filament_idx * (period/4)) % period
    x = psweep(now, period, 0, 2 * math.pi, offset)

    #print(x)

    return math.sin(x) / 2 + 0.5


threading.Thread(target=midi_thread, daemon=True).start()


while True:
    lattice.clear()

    now = Event.for_now()

    #print(lfo._last_cycle)

    for end in graph.ends():
        for i in range(4):
            v = get_value_for_filament(now, end, i)
            x = v
            if x < 0.9:
                x = 0
            lattice[end][i] = [get_value_for_filament(now, end, i, ), x/2, x/2]

    lattice.show()

    #time.sleep(0.01)
    ...