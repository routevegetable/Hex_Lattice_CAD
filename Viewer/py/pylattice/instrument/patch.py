"""Saving and restoring a patch: where the knobs are, and what drives what."""
import copy
import json
from collections.abc import Callable
import operator
from dataclasses import dataclass, field
from pathlib import Path

from pylattice.examples.midi import MIDI
from pylattice.fields.types import CombinedField, ConstantField, ScalarField, average, divide
from pylattice.instrument.types import Effect

# What drives a slot, as JSON. A live field cannot be pickled - the MIDI-backed
# ones hold closures, and a copy would be detached from the desk anyway - so
# what gets written is how to find or rebuild it:
#
#   "rotary"                                  a field declared in FIELDS
#   0.25                                      a constant
#   {"op": "mul", "a": "ripple", "b": 0.5}    a combination, nested freely
#
# The combination is a dataclass rather than a bare dict, so the shape is
# declared in one place - the REST schema is generated from it.


@dataclass
class Combination:
    """Two refs under an operator: `a` and `b` can be refs of any kind, so
    combinations nest."""
    op: str
    a: "FieldRef"
    b: "FieldRef"


FieldRef = str | float | Combination

OPS = {"add": operator.add, "sub": operator.sub, "mul": operator.mul,
       "div": divide, "avg": average}
OP_NAMES = {op: name for name, op in OPS.items()}


def encode_field(field: ScalarField, names: dict[int, str]) -> FieldRef:
    """A field as JSON, given the names of the fields worth naming."""
    name = names.get(id(field))
    if name is not None:
        return name

    if isinstance(field, ConstantField):
        return field.value

    if isinstance(field, CombinedField) and field.op in OP_NAMES:
        return Combination(op=OP_NAMES[field.op],
                           a=encode_field(field.a, names),
                           b=encode_field(field.b, names))

    raise ValueError(f"cannot write down a {type(field).__name__} that has no name")


def decode_field(ref: FieldRef, by_name: dict[str, ScalarField]) -> ScalarField:
    """The inverse: look the name up, or build what it describes."""
    if isinstance(ref, str):
        if ref not in by_name:
            raise ValueError(f"no field {ref!r}")
        return by_name[ref]

    if isinstance(ref, (int, float)):
        return ConstantField(ref)

    if isinstance(ref, Combination):
        if ref.op not in OPS:
            raise ValueError(f"no operator {ref.op!r} - try {', '.join(OPS)}")
        return CombinedField(OPS[ref.op],
                             decode_field(ref.a, by_name),
                             decode_field(ref.b, by_name))

    raise ValueError(f"cannot read a field from {ref!r}")


def as_json(ref: FieldRef):
    """A ref as plain JSON - a combination becomes its three keys."""
    if isinstance(ref, Combination):
        return {"op": ref.op, "a": as_json(ref.a), "b": as_json(ref.b)}

    return ref


def as_ref(raw) -> FieldRef:
    """The inverse, for reading a file back."""
    if isinstance(raw, dict):
        return Combination(op=raw.get("op", ""), a=as_ref(raw.get("a")), b=as_ref(raw.get("b")))

    return raw


def named(namespace: type, kind: type) -> dict[str, object]:
    """The `kind` things declared in a class body, in the order written."""
    return {name: value for name, value in vars(namespace).items()
            if isinstance(value, kind)}


@dataclass
class Patch:
    """Every setting there is: where the knobs are, and what drives what.

        Patch.load("preset.json").apply(midi, FIELDS, EFFECTS)

    Patches are made by whoever is editing one - the UI sends a whole patch,
    and the bank folds the knobs into whatever is playing. Nothing reads one
    back off the live objects.
    """

    # CC number -> value
    ccs: dict[int, int]

    # effect.slot -> what drives it
    slots: dict[str, FieldRef]

    # CC string id -> real MIDI CC number. Sparse: a control the map does not
    # name sits on the default it was declared with.
    cc_map: dict[str, int] = field(default_factory=dict)

    # Which effects draw, in order - a list rather than a set, because the
    # order they are named in is itself a setting. None means the patch does
    # not say - a file written before effects could be switched off - and
    # every effect is taken as on.
    active: list[str] | None = None

    # What to call it, if it is worth calling anything. A preset is addressed
    # by its number; this is only so there is something to read.
    name: str | None = None

    def apply(self, midi: MIDI, fields: type, effects: type):
        """Put the knobs back and re-patch the slots.

        A patch is the entire picture: a slot it does not mention ends up with
        nothing in it, rather than keeping whatever the patch before left
        there. That is what makes an empty patch mean something - it is a
        blank rig, and reverting to one clears it. Everything that applies a
        patch sends all of it, the UI included.
        """
        # Where the controls live comes first: the values below are addressed
        # by CC number, so they have to land after everything is plugged in.
        midi.set_cc_map(self.cc_map)

        for control, value in self.ccs.items():
            midi.set_cc(control, value)

        by_name = named(fields, ScalarField)
        by_effect = named(effects, Effect)

        # Nothing here says which effects draw, or when. `active` is that, and
        # whoever renders reads it off the patch - copying it onto the effects
        # would be a second record of the same thing, free to disagree.

        # Work the whole thing out before changing anything, so a patch naming
        # a field that has gone fails without half-applying.
        wanted: dict[str, dict[str, ScalarField]] = {}
        for target, ref in self.slots.items():
            effect_name, _, slot_name = target.partition(".")

            if effect_name not in by_effect:
                # A preset outlives the code it was written against. An effect
                # that has since gone is not a reason to drop everything else
                # the preset says - leave that slot out and carry on.
                print(f"{target}: no effect {effect_name!r}, skipped")
                continue

            if slot_name not in by_effect[effect_name].get_slots():
                print(f"{target}: {effect_name!r} has no slot {slot_name!r}, skipped")
                continue

            try:
                field = decode_field(ref, by_name)
            except ValueError as e:
                raise ValueError(f"{target}: {e}") from None

            wanted.setdefault(effect_name, {})[slot_name] = field

        for effect_name, effect in by_effect.items():
            mine = wanted.get(effect_name, {})

            for slot_name, slot in effect.get_slots().items():
                if slot_name not in mine:
                    slot.clear()

            if mine:
                effect.bind(**mine)

    def copy(self) -> "Patch":
        """An independent copy. The slot refs nest, so they go deep - two
        patches must never share a dict, or editing one edits the other."""
        return Patch(ccs=dict(self.ccs), slots=copy.deepcopy(self.slots),
                     cc_map=dict(self.cc_map),
                     active=None if self.active is None else list(self.active),
                     name=self.name)

    def save(self, path: str):
        slots = {name: as_json(ref) for name, ref in self.slots.items()}
        out = {"ccs": self.ccs, "slots": slots, "cc_map": self.cc_map,
               "active": self.active, "name": self.name}
        Path(path).write_text(json.dumps(out, indent=2))

    @classmethod
    def load(cls, path: str) -> "Patch":
        saved = json.loads(Path(path).read_text())
        # JSON keys are strings; CC numbers are not.
        active = saved.get("active")

        return cls(ccs={int(cc): v for cc, v in saved["ccs"].items()},
                   slots={name: as_ref(raw) for name, raw in saved["slots"].items()},
                   cc_map=saved.get("cc_map", {}),
                   active=None if active is None else list(active),
                   name=saved.get("name"))


@dataclass
class PresetBank:
    """A fixed set of preset slots, one file each, under `directory`.

    Every preset is held in memory as well as on disk. The cached copy is the
    live one - the instrument renders from the cached patch of whatever is
    selected - so turning a knob makes that entry drift from its file. The
    bank hands out both copies and says nothing about the drift; whoever is
    showing it decides what to make of it. Saving writes the cache out;
    reverting throws it away and reads the file back.
    """

    directory: Path
    # A program change carries 0-127, so that is the bank. Most slots have no
    # file and hold a patch that says nothing, which is what an empty preset
    # is - there is no other kind.
    size: int = 128

    def __post_init__(self):
        self.directory = Path(self.directory)
        self.directory.mkdir(parents=True, exist_ok=True)

        # number -> the patch as it is now, and as it is on disk. Two copies,
        # never the same object, so comparing them means something.
        self._cache: dict[int, Patch] = {}
        self._stored: dict[int, Patch] = {}

        # Which preset is playing, and where the knobs are right now. Knobs
        # move without anyone telling the bank, so it folds them into that
        # preset's copy whenever it hands one out - otherwise what it says is
        # behind the rig the moment anybody touches anything.
        self.current: int | None = None
        self.live_ccs: Callable[[], dict[int, int]] = dict

        self.reload()

    def _fold(self):
        """Put the knobs as they are into the preset that is playing."""
        if self.current is not None:
            self._cache[self.current].ccs.update(self.live_ccs())

    def playing(self) -> "Patch | None":
        """The patch that is playing, or None if nothing is selected.

        Handed over as it is, without folding the knobs in: this is for
        reading what is patched, and the knobs are the rig's own answer.
        """
        return None if self.current is None else self._cache[self.current]

    # -- the files --------------------------------------------------------

    def path(self, number: int) -> Path:
        self.check(number)
        return self.directory / f"{number:02d}.json"

    def check(self, number: int):
        if not 0 <= number < self.size:
            raise ValueError(f"preset {number} is outside 0-{self.size - 1}")

    def exists(self, number: int) -> bool:
        return self.path(number).exists()

    def reload(self):
        """Fill the cache from storage.

        Every slot gets a patch, file or no file - an unwritten one is a patch
        that says nothing, which applies cleanly and changes nothing. There is
        no such thing as an empty preset to guard against.
        """
        self._cache, self._stored = {}, {}

        for number in range(self.size):
            stored = self._from_storage(number)
            self._stored[number] = stored
            self._cache[number] = stored.copy()

    def _from_storage(self, number: int) -> Patch:
        """A preset's file, or a patch that does nothing if it has none."""
        if not self.exists(number):
            return Patch(ccs={}, slots={}, cc_map={})

        return Patch.load(self.path(number))

    # -- the cache --------------------------------------------------------

    def get_all(self) -> dict[int, Patch]:
        """Every preset the bank holds, copied - reading cannot disturb what
        the instrument is rendering."""
        self._fold()
        return {number: patch.copy() for number, patch in self._cache.items()}

    def read(self, number: int) -> Patch:
        """A preset as it stands, edits included."""
        self.check(number)
        self._fold()
        return self._cache[number].copy()

    def stored(self, number: int) -> Patch:
        """A preset as its file has it, edits left out."""
        self.check(number)
        return self._stored[number].copy()

    def put(self, number: int, patch: Patch):
        """Hold a patch as a preset's current state. Dirty from here if it
        differs from the file."""
        self.check(number)
        self._cache[number] = patch.copy()

    def save(self, number: int):
        """Write a preset's cached patch out. It stops being dirty."""
        self.check(number)
        self._fold()
        patch = self._cache[number]

        patch.save(self.path(number))
        self._stored[number] = patch.copy()

    def revert(self, number: int) -> Patch:
        """Throw a preset's edits away and read its file back - or empty it,
        if it has never been written."""
        self.check(number)

        stored = self._from_storage(number)
        self._stored[number] = stored
        self._cache[number] = stored.copy()

        return self._cache[number].copy()

