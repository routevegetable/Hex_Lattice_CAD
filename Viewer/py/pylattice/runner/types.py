"""What an effect is: something with slots, that draws."""
import inspect
from typing import Protocol, Self

from pylattice.fields.types import ScalarField, Slot
from pylattice.examples.tempo import Event
from pylattice.graph import Graph
from pylattice.lattice_writer import LatticeWriter


class Effect(Protocol):
    """Draws onto the lattice, reading the fields plugged into its slots.

    An effect declares its slots as annotations, and gets a cell for each:

        class Pluck(Effect):
            a_amp: Slot
            period: Slot

            def render(self, now, lattice, graph):
                self.a_amp.get(now, vertex)

    Fields go in through bind, at wiring time or later - the cells are mutable,
    so a running effect can be re-patched:

        pluck = Pluck().bind(a_amp=rotary, period=param)
        pluck.bind(a_amp=note_wipe)
    """

    def __init__(self, **fields: ScalarField | float):
        for name in self.declared_slots():
            setattr(self, name, Slot(name))
        if fields:
            self.bind(**fields)

    @classmethod
    def declared_slots(cls) -> list[str]:
        """Slot names this effect declares, base classes first."""
        names: list[str] = []
        for klass in reversed(cls.__mro__):
            try:
                # get_annotations, not vars(): annotations are lazy (PEP 649),
                # and this doesn't fall through to a base class's.
                annotations = inspect.get_annotations(klass)
            except Exception:
                continue                    # annotations that won't evaluate
            for name, annotation in annotations.items():
                if (annotation is Slot or annotation == "Slot") and name not in names:
                    names.append(name)
        return names

    def render(self, now: Event, lattice: LatticeWriter, graph: Graph): ...

    def get_slots(self) -> dict[str, Slot]:
        """The slots this effect owns, by name - and each Slot knows its own
        name too, so it can say which one it is at runtime."""
        return {name: value for name, value in vars(self).items() if isinstance(value, Slot)}

    def bind(self, **fields: ScalarField | float) -> Self:
        """Attach fields to slots by name, and hand the effect back:

            Pluck().bind(a_amp=rotary, period=param)

        Rebinding a slot that is already filled just re-points it.
        """
        slots = self.get_slots()
        unknown = fields.keys() - slots.keys()
        if unknown:
            raise AttributeError(
                f"{type(self).__name__} has no slot "
                f"{', '.join(repr(u) for u in sorted(unknown))}"
                f" - its slots are {', '.join(sorted(slots)) or 'none'}")

        for name, field in fields.items():
            slots[name].set(field)

        return self


class PersistentEffect(Effect, Protocol):
    fader: Slot # Persistent Effects have a fader