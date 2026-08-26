from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
import math
import numbers
import time
from typing import Any, Generic, TypeVar

TData = TypeVar("TData")
UData = TypeVar("UData")

@dataclass
class Event(Generic[TData]):
    when: int
    data: TData | None
    
    @staticmethod
    def for_now(data: TData | None = None):
        return Event(int(time.monotonic() * 1000), data)

    def rand(self, salt: int = 0):
        """Deterministic 32-bit integer mixing function."""
        x = int(self.when * 65536 + salt)
        x = ((x >> 16) ^ x) * 0x45d9f3b
        x = ((x >> 16) ^ x) * 0x45d9f3b
        x = (x >> 16) ^ x
        return x & 0xFFFFFFFF  # Keep as 32-bit unsigned int
    
    def msec_after(self, ev: Event[Any]) -> int | None:
        if self.when is None or ev.when is None:
            return None
        return self.when - ev.when

    def with_data(self, data: UData) -> Event[UData]:
        return Event(self.when, data)

    def after(self, ev: Event[Any] | None) -> bool:
        # We happened

        if ev is None:
            # Other did not
            return True
        else:
            # Other did
            return self.when > ev.when
        
    def delay(self, t: int) -> Event[TData]:
        return Event(self.when + t, self.data)



def periodic(now: Event[Any], period: int, offset: int = 0) -> Event[int]:
    assert now.when is not None
    period_num = (now.when - offset) // period
    return Event(when = period_num * period + offset, data=period_num)


def sweep(now: Event[Any], trigger: Event[Any] | None, period: int, start: float, end: float, wait: float | None = None) -> float:
    if wait is None:
        wait = start
    
    if trigger is None or not now.after(trigger):
        return wait
    
    offset = now.when - trigger.when
    
    if offset > period:
        return end
    else:
        frac = offset / period
        dv = end - start
        return start + frac * dv
    
def seq(now: Event[Any], trigger: Event[Any] | None, period: int, arr: list[TData], wait: TData | None = None) -> TData:
    assert len(arr) > 0, "Empty input list"

    if wait is None:
        wait = arr[0]

    if not now.after(trigger):
        return wait
    

    i = sweep(now, trigger, period, 0, len(arr)-1)
    return arr[int(i)]

def seq_interp(now: Event[Any], trigger: Event[Any] | None, period: int, arr: list[float], wait: float | None = None) -> float:
    assert len(arr) > 0, "Empty input list"

    if wait is None:
        wait = arr[0]

    if trigger is None or not now.after(trigger):
        return wait
    
    if now.after(trigger.delay(period)):
        return arr[-1]
    
    values = len(arr)

    first = seq(now, trigger, period, arr[:-1])
    second = seq(now, trigger, period, arr[1:])

    step_len = int(period / (values - 1))
    p = periodic(now, step_len, trigger.when)

    print(f"{p} {first} {second}")

    return sweep(now, p, step_len, first, second)
    



def psweep(now: Event[Any], period: int, start: float, end: float, offset: int = 0) -> float:
    trigger = periodic(now, period, offset)

    e = sweep(now, trigger, period, start, end)
    return e


class EventLatch(Generic[TData]):
    def __init__(self):
        self.ev: Event[TData] | None = None

    def latch(self, ev: Event[TData], latch: bool = True) -> Event[TData] | None:
        """
        If latch = True (default), and ev is newer than that latched,
        latch the new event.
        Regardless, return latched event.
        """

        if latch and ev.after(self.ev):
            self.ev = ev

        return self.ev
    
    def maybe(self, now: Event[Any], salt: int, period: int, likelihood: float, offset: int = 0) -> Event[TData] | None:
        """
        Randomly latch a new event.
        Each period, likelihood dictates how likely we are to latch a new event
        """

        trigger = periodic(now, period, offset)

        rfloat = (trigger.rand(salt) % 100) / 100

        return self.latch(Event(trigger.when, None), rfloat < likelihood)

    def put(self, data: TData | None = None) -> Event[TData]:
        """
        Latch a new event now
        """
        x = self.latch(Event.for_now(data))
        assert x is not None
        return x
    
    def read(self) -> Event[TData] | None:
        return self.ev

class History(Generic[TData]):
    """
    Circular buffer of same-typed event latches
    """
    def __init__(self, len: int = 20):
        self._d = deque[EventLatch[TData]]()
        for _ in range(len):
            self._d.append(EventLatch())

    def events(self) -> Iterable[Event[TData]]:
        for el in self._d:
            yield el.read()
    
    def update(self) -> EventLatch[TData]:
        self._d.rotate()
        return self._d[0]
    
    def maybe_update(self, now: Event[Any], salt: int, period: int, likelihood: float, offset: int = 0):
        """
        TBD
        """
        ...


# t = 0
ZERO = Event.for_now()

A_SEC = ZERO.delay(1000)

el: EventLatch[None] = EventLatch()


while True:
    break
    now = Event.for_now()

    p = el.maybe(now, 20000, 0.7, A_SEC.when)
    print(p)

    obj = seq(now, p, 1000, [
        "one",
        "two",
        "three",
        "four"
    ])

    obj = seq_interp(now, p, 10000, [
        0,
        1,
        10,
        5
    ])

    print(obj)


    time.sleep(0.1)

