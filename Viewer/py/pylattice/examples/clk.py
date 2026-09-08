import time
from py.pylattice.examples.tempo import Event, EventLatch


import mido



mido.open_input()


class ClockGenerator:
    """
    MIDI-synced clock generator
    """

    def __init__(self, ppqn: int=24):
        # number of pulses per quarter note
        self.ppqn = ppqn

        # number of quarter notes since reset()
        self.pulse_count = 0

        # Current start of quarter note timer
        self.last_pulse_time_usec = 0

        # Whether we are in the last half of the 
        self.first_half = True

        # Previous pulse len in usec
        self.last_pulse_len_usec = 1250000     # 12.5msec (@ 24ppqn that's 120 BPM)

    def reset(self):
        now = time.monotonic_ns() / 1000 # usec
        self.pulse_count = 0
        self.last_pulse_time_usec = now
        self.last_pulse_len_usec = 1250000
        self.first_half = True

    def get_qn(self) -> int:
        return self.pulse_count / self.ppqn
    
    def on_pulse(self):

        now = int(time.monotonic_ns() / 1000) # usec


        self.tick()

        if not self.first_half:
            self.pulse_count = self.pulse_count + 1
            print(f"PC={self.pulse_count % 24} P")
            #print(f"{now/1000}: second half pulse {self.last_pulse_len_usec} PC={self.pulse_count}")
            # This came in in the second half, before the expected hit, increment the pulse count
        else:
            #print(f"{now/1000}: first half pulse {self.last_pulse_len_usec} PC={self.pulse_count}")
            ...

        self.last_pulse_len_usec = now - self.last_pulse_time_usec
        self.last_pulse_time_usec = now
        self.first_half = True
        

    def tick(self):

        now = int(time.monotonic_ns() / 1000) # usec

        # How long since last pulse
        dt = now - self.last_pulse_time_usec

        # How far into the current pulse window
        pulse_offset_usec = dt % self.last_pulse_len_usec

        # Are we in the first half of this pulse window?
        prev_first_half = self.first_half
        self.first_half = pulse_offset_usec < (self.last_pulse_len_usec / 2)

        if not prev_first_half and self.first_half:
            print(f"PC={self.pulse_count % 24} R")
            self.pulse_count = self.pulse_count + 1
            #print(f"{now/1000}: roll over dt = {dt} offset = {pulse_offset_usec} PC={self.pulse_count}")
            # Rolled over - reset the timer, increment qn
            # Now we are in first half


class QNLFO:
    """
    LFO synced to MIDI clock
    """

    def __init__(self, gen: ClockGenerator):
        self._gen = gen
        self._last_sync_qn = 0
        self._latch = EventLatch()

        self._last_cycle = 0

    def tick(self, period_qn: int, offset_qn: int) -> Event:
        qn = self._gen.get_qn()

        if qn < self._last_sync_qn:
            # A reset happened - resync with 0
            self._last_sync_qn = 0

        current_cycle = (qn + offset_qn) / period_qn

        # Generate an event if we roll over
        if current_cycle > self._last_cycle:
            self._last_cycle = current_cycle
            self._latch.put()

        return self._latch.read()
        
        


