"""What an effect is: something with slots, that draws."""
import inspect
from typing import Protocol, Self, runtime_checkable

from pylattice.fields.types import ScalarField, Slot
from pylattice.examples.tempo import Event
from pylattice.graph import Graph
from pylattice.lattice_writer import LatticeWriter


# The kinds of slot every effect lists first, in this order. The rest follow,
# A to Z. A slot is of a kind if it is called that, or that and an underscore
# and more: hue, hue_1 and hue_2 are all hue.
SLOTS_FIRST = ("hue", "value", "sat")


def slot_order(name: str) -> tuple[int, str]:
    """Sort key for slot names: hue slots, value slots, sat slots, then
    everything else by name. Within a kind, plain `hue` comes before `hue_1`."""
    for rank, kind in enumerate(SLOTS_FIRST):
        if name == kind or name.startswith(kind + "_"):
            return rank, name
    return len(SLOTS_FIRST), name


@runtime_checkable
class Effect(Protocol):
    """Draws onto the lattice, reading the fields plugged into its slots.

    An effect declares its slots as annotations, and gets a cell for each:

        class Pluck(Effect):
            a_amp: Slot
            period: Slot

            def render(self, now, lattice, graph):
                self.a_amp.get(now, vertex)

    Building one takes no arguments: every slot starts on a constant 0, which
    is a perfectly good field and draws nothing much. What goes in them is a
    patch's business, and the cells are mutable, so a running effect can be
    re-patched at any point:

        pluck = Pluck()
        pluck.bind(a_amp=rotary, period=param)
    """

    def __init__(self):
        # Silenced for now, without leaving the patch. Not a setting: it is
        # never saved, and a patch applying leaves it alone.
        self.muted = False

        for name in self.declared_slots():
            setattr(self, name, Slot(name))

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

    muted: bool

    def render(self, now: Event, lattice: LatticeWriter, graph: Graph): ...

    def get_slots(self) -> dict[str, Slot]:
        """The slots this effect owns, by name - and each Slot knows its own
        name too, so it can say which one it is at runtime. Always in the same
        order whatever the effect declares: see slot_order."""
        owned = {name: value for name, value in vars(self).items() if isinstance(value, Slot)}
        return dict(sorted(owned.items(), key=lambda item: slot_order(item[0])))

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