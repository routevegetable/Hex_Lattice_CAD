"""Saving and restoring a patch: where the knobs are, and what drives what."""
import copy
import json
from collections.abc import Callable
import operator
import re
from dataclasses import dataclass, field
from pathlib import Path
import traceback

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

        Patch.capture(midi, FIELDS, EFFECTS).save("preset.json")
        Patch.load("preset.json").apply(midi, FIELDS, EFFECTS)
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

    @classmethod
    def capture(cls, midi: MIDI, fields: type, effects: type) -> "Patch":
        """Read the current patch off the live objects."""
        field_names = {id(field): name for name, field in named(fields, ScalarField).items()}

        slots = {}
        for effect_name, effect in named(effects, Effect).items():
            for slot_name, slot in effect.get_slots().items():
                # A combination or a constant is written out as how to rebuild
                # it; anything else unnamed cannot be, and is left out.
                try:
                    slots[f"{effect_name}.{slot_name}"] = encode_field(slot.field, field_names)
                except ValueError:
                    traceback.print_exc()
                    #print(f"Error: ")
                    pass

        # Only the controls that have been moved away from where they were
        # declared. A preset that says nothing about a control brings it up on
        # its default, which is what lets an old preset meet a new control.
        defaults = midi.cc_defaults()
        cc_map = {name: number for name, number in midi.cc_map().items()
                  if number != defaults.get(name)}

        # A preset wants where each knob is sitting, by the number it sits on
        # - only the knobs something is plugged into, not every stray that has
        # turned up on the wire.
        ccs = {number: state.value
               for number, state in midi.get_ccs_by_number().items()
               if state.comments}

        return cls(ccs=ccs, slots=slots, cc_map=cc_map,
                   active=[name for name, effect in named(effects, Effect).items()
                           if effect.active])

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

        # An effect the patch does not name is off. A patch with no `active`
        # list at all predates being able to switch them off, so every effect
        # counts as named rather than none of them.
        active = list(by_effect) if self.active is None else self.active

        for name, effect in by_effect.items():
            effect.active = name in active

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
                     active=None if self.active is None else list(self.active))

    def save(self, path: str):
        slots = {name: as_json(ref) for name, ref in self.slots.items()}
        out = {"ccs": self.ccs, "slots": slots, "cc_map": self.cc_map,
               "active": self.active}
        Path(path).write_text(json.dumps(out, indent=2))

    @classmethod
    def load(cls, path: str) -> "Patch":
        saved = json.loads(Path(path).read_text())
        # JSON keys are strings; CC numbers are not.
        active = saved.get("active")

        return cls(ccs={int(cc): v for cc, v in saved["ccs"].items()},
                   slots={name: as_ref(raw) for name, raw in saved["slots"].items()},
                   cc_map=saved.get("cc_map", {}),
                   active=None if active is None else list(active))


# Where preset names are kept, beside the presets they name.
NAMES_FILE = "names.json"
NEXT_FILE = "next.txt"
MAX_NAME = 32


@dataclass
class PresetBank:
    """The presets, one file each, under `directory`.

    The first `controller_presets` slots - the ones the controller's sixteen
    projects pick - always exist, written or not. Past those, a preset
    exists only because somebody saved one - `create` makes it, at the next
    number past any used before (below `limit`, since a program change cannot
    say more than 127), and `delete` takes it away. A number that is neither is
    not a preset at all, rather than an empty one, so nothing can play it by
    accident. A deleted preset's number is not handed out again, because
    something upstream may still be sending it: only once every number has been
    used does `create` take the lowest free one.

    Every preset is held in memory as well as on disk. The cached copy is the
    live one - the instrument renders from the cached patch of whatever is
    selected - so turning a knob makes that entry drift from its file. The
    bank hands out both copies and says nothing about the drift; whoever is
    showing it decides what to make of it. Saving writes the cache out;
    reverting throws it away and reads the file back.
    """

    directory: Path
    controller_presets: int = 16
    limit: int = 128

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

        # number -> name. Not part of any patch: a name says which preset a slot
        # is, not what it looks like, so it is not copied with one, not undone
        # by a revert, and never shows up as an unsaved edit.
        self._names: dict[int, str] = self._read_names()

        self.reload()

        # A name for a preset whose file has gone is not a name for anything, and
        # the first sixteen are not named at all.
        self._names = {n: name for n, name in self._names.items()
                       if n in self._cache and n >= self.controller_presets}

        # The number the next saved preset gets.
        self._next: int = self._read_next()

    def _fold(self):
        """Put the knobs as they are into the preset that is playing."""
        if self.current is not None:
            self._cache[self.current].ccs.update(self.live_ccs())

    # -- the names --------------------------------------------------------

    @property
    def names_path(self) -> Path:
        return self.directory / NAMES_FILE

    def _read_names(self) -> dict[int, str]:
        if not self.names_path.exists():
            return {}

        # JSON keys are strings; preset numbers are not.
        return {int(number): name
                for number, name in json.loads(self.names_path.read_text()).items()}

    def names(self) -> dict[int, str]:
        """Every name there is, by preset number."""
        return dict(self._names)

    def name(self, number: int) -> str | None:
        self.check(number)
        return self._names.get(number)

    def number_of(self, name: str) -> int:
        """The preset with this name. Case does not matter."""
        wanted = name.strip().lower()

        for number, taken in self._names.items():
            if taken.lower() == wanted:
                return number

        raise ValueError(f"no preset named {name!r}")

    def check_name(self, name: str) -> str:
        """A name as it will be kept, or why it cannot be. A name is given once,
        when a copy is saved, and never changed after."""
        name = name.strip()

        if not name:
            raise ValueError("a name cannot be empty")

        if len(name) > MAX_NAME:
            raise ValueError(f"a name is at most {MAX_NAME} characters")

        # Letters, digits and dashes: no spaces, and nothing that needs escaping
        # in a URL.
        if not re.fullmatch(r"[A-Za-z0-9-]+", name):
            raise ValueError("a name can only use letters, digits and dashes")

        # Starting with a letter also means "3" can never be both a name and a
        # preset number.
        if not name[0].isalpha():
            raise ValueError("a name must begin with a letter")

        if "--" in name:
            raise ValueError("a name cannot have two dashes in a row")

        for other, taken in self._names.items():
            if taken.lower() == name.lower():
                raise ValueError(f"preset {other} is already called {taken!r}")

        return name

    def _write_names(self):
        ordered = {str(number): name for number, name in sorted(self._names.items())}
        self.names_path.write_text(json.dumps(ordered, indent=2))

    # -- the next number --------------------------------------------------

    @property
    def next_path(self) -> Path:
        return self.directory / NEXT_FILE

    def _read_next(self) -> int:
        """Past every number used before. It is kept in a file so that a number
        that was deleted is not forgotten with it; a file that is missing, or
        behind a preset someone copied in by hand, is covered by what is on
        disk."""
        remembered = int(self.next_path.read_text()) if self.next_path.exists() else 0
        return max(remembered, self.controller_presets, *(n + 1 for n in self.custom()))

    # -- the files --------------------------------------------------------

    def path(self, number: int) -> Path:
        return self.directory / f"{number:02d}.json"

    def check(self, number: int):
        """Say so if there is no such preset."""
        if number not in self._cache:
            raise ValueError(f"no preset {number}")

    def exists(self, number: int) -> bool:
        return self.path(number).exists()

    def numbers(self) -> list[int]:
        """Every preset there is."""
        return sorted(self._cache)

    def custom(self) -> list[int]:
        """The ones past the fixed slots, which somebody saved."""
        return [n for n in self.numbers() if n >= self.controller_presets]

    def saved(self) -> list[int]:
        """Which presets have a file."""
        return [n for n in self.numbers() if self.exists(n)]

    def _on_disk(self) -> list[int]:
        """The numbers of the custom presets with a file."""
        found = (int(f.stem) for f in self.directory.glob("*.json") if f.stem.isdigit())
        return sorted(n for n in found if self.controller_presets <= n < self.limit)

    def reload(self):
        """Fill the cache from storage.

        Every fixed slot gets a patch, file or no file - an unwritten one is a
        patch that says nothing, which applies cleanly and changes nothing.
        There is no such thing as an empty preset to guard against. A custom
        one is here because it has a file.
        """
        self._cache, self._stored = {}, {}

        for number in [*range(self.controller_presets), *self._on_disk()]:
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

    def create(self, patch: Patch, name: str) -> int:
        """Save a patch as a new, named preset, and say which number it got.

        It is written out at once: a custom preset exists because it has a
        file, so there is no such thing as one that was never saved.
        """
        name = self.check_name(name)

        if self._next < self.limit:
            number = self._next
        else:
            # Every number has been used once. Only now are the deleted ones
            # handed out again.
            number = next((n for n in range(self.controller_presets, self.limit)
                           if n not in self._cache), None)
            if number is None:
                raise ValueError(f"the bank is full - presets go up to {self.limit - 1}")

        # The file first: if writing it fails, nothing else has changed, and there
        # is no preset in the cache that has no file.
        stored = patch.copy()
        stored.save(self.path(number))

        self._stored[number] = stored
        self._cache[number] = stored.copy()
        self._names[number] = name
        self._write_names()

        self._next = max(self._next, number + 1)
        self.next_path.write_text(str(self._next))

        return number

    def delete(self, number: int):
        """Take a custom preset away, its file and its name with it."""
        self.check(number)

        if number < self.controller_presets:
            raise ValueError(f"preset {number} is one of the first {self.controller_presets} - those stay")

        if number == self.current:
            raise ValueError(f"preset {number} is playing - play another one first")

        self.path(number).unlink()
        del self._cache[number], self._stored[number]

        if self._names.pop(number, None) is not None:
            self._write_names()

    def revert(self, number: int) -> Patch:
        """Throw a preset's edits away and read its file back - or empty it,
        if it has never been written."""
        self.check(number)

        stored = self._from_storage(number)
        self._stored[number] = stored
        self._cache[number] = stored.copy()

        return self._cache[number].copy()

