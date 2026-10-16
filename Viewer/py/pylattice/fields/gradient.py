"""Colour gradients: a path through colour space, walked by a driving field.

A gradient is a few stops, each a colour (hue, saturation, value) at a place
along 0..1. A field that goes 0..1 - a knob, a wipe, a bloom - picks where on
the path to be, and the gradient says what colour that is. They live in a JSON
file in the repo, so a good one is kept (and reviewed) like any other code.
"""

import json
import re
import threading
from pathlib import Path

from pylattice.examples.tempo import Event
from pylattice.fields.types import ScalarField
from pylattice.graph import EndRef

CHANNELS = {"h": 0, "s": 1, "v": 2}
NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def _clean(stops: list[dict]) -> list[dict]:
    """Stops as plain numbers, in order along the path. At least one."""
    if not stops:
        raise ValueError("a gradient needs at least one stop")
    cleaned = []
    for stop in stops:
        try:
            at, h, s, v = (float(stop[k]) for k in ("at", "h", "s", "v"))
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"a stop needs at, h, s and v: {stop!r}") from None
        cleaned.append(
            {
                "at": min(max(at, 0.0), 1.0),
                "h": h % 1.0,
                "s": min(max(s, 0.0), 1.0),
                "v": min(max(v, 0.0), 1.0),
            }
        )
    return sorted(cleaned, key=lambda stop: stop["at"])


class Gradient:
    def __init__(self, name: str, stops: list[dict]):
        self.name = name
        self.stops = _clean(stops)

    def set_stops(self, stops: list[dict]):
        """Replace the path in place, so every field walking it follows."""
        self.stops = _clean(stops)

    def colour_at(self, p: float) -> tuple[float, float, float]:
        """(hue, saturation, value) at p, clamped to the ends of the path.

        Hue takes the short way round the wheel between two stops, so orange to
        purple goes through red and magenta, not through green and blue.
        """
        stops = self.stops
        if p <= stops[0]["at"]:
            first = stops[0]
            return first["h"], first["s"], first["v"]
        for a, b in zip(stops, stops[1:]):
            if p <= b["at"]:
                span = b["at"] - a["at"]
                t = 0.0 if span <= 0 else (p - a["at"]) / span
                dh = ((b["h"] - a["h"] + 0.5) % 1.0) - 0.5
                return (
                    (a["h"] + dh * t) % 1.0,
                    a["s"] + (b["s"] - a["s"]) * t,
                    a["v"] + (b["v"] - a["v"]) * t,
                )
        last = stops[-1]
        return last["h"], last["s"], last["v"]


class GradientBank:
    """Every gradient, by name, kept in one JSON file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._gradients: dict[str, Gradient] = {}
        self.reload()

    def reload(self):
        with self._lock:
            self._gradients = {}
            if self.path.exists():
                for name, stops in json.loads(self.path.read_text()).items():
                    self._gradients[name] = Gradient(name, stops)

    def _adopt_from_disk(self):
        """Pick up gradients that are in the file but not in memory yet, so a
        save never writes the file back without them."""
        if not self.path.exists():
            return
        for name, stops in json.loads(self.path.read_text()).items():
            if name not in self._gradients:
                self._gradients[name] = Gradient(name, stops)

    def get(self, name: str) -> Gradient:
        with self._lock:
            if name not in self._gradients:
                raise ValueError(f"no gradient {name!r}")
            return self._gradients[name]

    def all(self) -> dict[str, list[dict]]:
        with self._lock:
            return {name: [dict(s) for s in j.stops] for name, j in self._gradients.items()}

    def put(self, name: str, stops: list[dict]):
        """Make or change a gradient, and write the file."""
        if not NAME.match(name):
            raise ValueError("a gradient name is letters, digits, - and _ (40 at most)")
        with self._lock:
            self._adopt_from_disk()  # keep anything added to the file behind our back
            if name in self._gradients:
                self._gradients[name].set_stops(stops)
            else:
                self._gradients[name] = Gradient(name, stops)
            saved = {n: j.stops for n, j in sorted(self._gradients.items())}
            self.path.write_text(json.dumps(saved, indent=2) + "\n")


# One file per rig, next to presets/ (the instrument runs from Viewer/py).
GRADIENTS = GradientBank("gradients.json")


class GradientField(ScalarField):
    """One channel (h, s or v) of a gradient, at the place `driver` says."""

    def __init__(self, gradient: Gradient, driver: ScalarField, channel: str):
        if channel not in CHANNELS:
            raise ValueError(f"no channel {channel!r} - try h, s or v")
        self.gradient = gradient
        self.driver = driver
        self.channel = channel

    def get(self, now: Event, end: EndRef) -> float:
        p = min(max(self.driver.get(now, end), 0.0), 1.0)
        return self.gradient.colour_at(p)[CHANNELS[self.channel]]
