// Touch UI: stats, a bar of effects, that effect's slots stacked below, and a
// modal that covers the slots (never the effects bar) for choosing a field.
const OPS = {add: '+', sub: '−', mul: '×', div: '÷', avg: '≈'};

const get = (p) => fetch(p).then(r => r.json());
const send = (method, p, body) => fetch(p, {method, headers: {'Content-Type': 'application/json'},
                                           body: body === undefined ? null : JSON.stringify(body)});
const post = (p, body) => send('POST', p, body);
const put = (p, body) => send('PUT', p, body);

// Three tabs up top; the bar under them is whatever that tab needs.
const TABS = [['effects', 'Effects'], ['controls', 'Controls'], ['system', 'System']];
const SECTIONS = [['stats', 'Stats'], ['timing', 'Timing'], ['midi', 'MIDI'],
                  ['presets', 'Presets'], ['surface', 'Surface']];

let rig = null;
let patch = null;           // what is playing, bar the knobs - see heldPatch
let stored = null;          // the same preset as its file has it
let dirty = false;          // whether those two differ
let views = {};             // every preset, live against stored - fetched on demand
let controls = [];          // every knob and pad the instrument watches
let tab = 'effects';        // which tab is showing
let chosen = null;          // field showing its details, on Controls
let section = 'stats';      // which part of System
let active = null;          // effect showing its slots
let open = null;            // "effect.slot" of the expanded slot, one at a time
let picking = null;         // {key, path} while the field picker is up
let presetsUp = false;      // the preset list uses the same modal
let addingUp = false;       // so does the list of effects to add
let renamingUp = false;     // and the box for naming what is playing
let texting = null;         // the slot being typed at rather than tapped
let mapping = null;         // a control waiting for a knob to be turned at it
let mappingSince = 0;       // ... and when it started waiting
let knobs = {};             // every cc number as it stands - the only CC store
// Which box is on the desk, and the picture of it. The instrument has no
// opinion about this - it is a drawing and a lookup, kept here and remembered
// per browser.
const SURFACES = '/static/surfaces.json';
let surfaces = {};
let surfaceId = localStorage.getItem('surface') || 'beatstep-pro';
let surfaceSvg = '';       // the picture, fetched once per choice
let wire = null;            // the socket, for sending a knob back the other way
let editing = {};           // slot edits, held until every operand is filled

// Whether a preset has drifted from its file is a question about two patches,
// so it is answered here rather than by the server, which would only be able
// to say yes or no.
function same(a, b) {
  if (a === b) return true;
  if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') return false;

  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every(k => same(a[k], b[k]));
}

const isDirty = (view) => !!view && !same(view.live, view.stored);

// Which effects are in the chain. A patch that says nothing about it - one
// written before they could be switched off - means all of them.
const activeEffects = () =>
    patch.active === null ? Object.keys(rig.effects) : patch.active;

// Adding and removing are both just a different active list on the same
// patch, written the same way any other edit is.
async function setActive(names) {
  remember();
  const r = await put(`/presets/${rig.selected}`,
                      {...patch, ccs: liveCCs(), active: names});
  if (!r.ok) { alert((await r.json()).detail); return; }
  await load();
}

// Every field named anywhere in an expression, however deep.
function fieldsIn(node) {
  if (typeof node === 'string') return [node];
  if (node && typeof node === 'object') return node.args.flatMap(fieldsIn);
  return [];
}

// Every operator named anywhere in an expression, however deep. An operator
// can own knobs of its own - a fader has the one it is riding - so what is
// behind an expression is not only what its fields own.
function opsIn(node) {
  if (node && typeof node === 'object') return [node.op, ...node.args.flatMap(opsIn)];
  return [];
}

// The fields the effects in the chain name. Anything else is not part of
// what is playing, so it has no business in the list.
function fieldsInUse() {
  const on = activeEffects();
  const names = new Set();

  for (const [key, tree] of Object.entries(patch.slots))
    if (on.includes(effectOf(key))) for (const n of fieldsIn(tree)) names.add(n);

  return [...names].sort((a, b) => a.localeCompare(b));
}

// The controls something owns. A comment is `owner.role`, and the owner can
// be a field or an effect - whichever asked the box for the knob. So an
// effect that takes controls of its own is found the same way a field is.
const controlsOwnedBy = (name) => controls.filter(
    c => c.kind === 'cc' && c.comments.some(t => t.startsWith(name + '.')));

// The CC numbers one of them listens to.
const knobsOf = (name) => new Set(controlsOwnedBy(name).map(c => c.number));

// What a CC number is for. /controls says, one entry per named control, so a
// number two things listen to turns up twice. The socket carries values only:
// a name changes when a patch moves a mapping, not ten times a second.
const commentsOn = (cc) => controls.filter(c => c.kind === 'cc' && c.number === cc)
                                   .flatMap(c => c.comments);

// What sort of control sits on a CC number: a sweep, a hue, or a list of named
// options. /rig says, per control name, so the number is resolved through the
// names listening to it. A stray nothing is pointed at is a plain knob - it is
// still shown moving, and 0-127 is all anyone knows about it.
const PLAIN = {kind: 'float_range', start: 0, end: 127, unit: null};

// A bare knob: 0-127 and nothing said about it. Worth knowing because a knob
// two controls share may be described by only one of them.
const isPlain = (m) => m.kind === 'float_range' && !m.unit
                       && m.start === 0 && m.end === 127;

// By name, which is exact - a control is what its own meta says.
const metaFor = (name) => rig?.control_meta?.[name] ?? PLAIN;

// By CC number, for when a knob moved and that is all anybody knows. Several
// controls can share a knob and only some of them say anything about it, so a
// described one wins: `burst.decay` is 100-2000 ms on a knob `rotary.shape`
// also listens to and has nothing to say about.
const metaOn = (cc) => {
  for (const name of commentsOn(cc)) {
    const meta = metaFor(name);
    if (!isPlain(meta)) return meta;
  }
  return PLAIN;
};

// The values a control can be put on, in order. A gradient and a custom list
// are both chosen from rather than swept, so these are the only places a drag
// is allowed to stop. Empty means it sweeps: there is nothing in between.
const DISCRETE = ['custom', 'gradient'];

const optionsOf = (meta) => DISCRETE.includes(meta.kind)
    ? Object.keys(meta.items ?? {}).map(Number).sort((a, b) => a - b)
    : [];

// Which option a value is on. The wire carries 0-127 whatever the list holds,
// and a field clamps, so the nearest one is what it will actually act on.
const nearestAt = (options, value) => options.reduce(
    (best, k, i) => Math.abs(k - value) < Math.abs(options[best] - value) ? i : best, 0);

// Where a value sits in its own range, 0-1, which is what a dial draws.
function fracOf(meta, value) {
  const options = optionsOf(meta);

  if (options.length)
    return options.length < 2 ? 0 : nearestAt(options, value) / (options.length - 1);

  return Math.max(0, Math.min(1, value / 127));
}

// What to print for a value. A FloatRange is the range to read it in, so the
// default (0, 127) prints the knob position and anything else prints what the
// knob means.
function readOut(meta, value) {
  const options = optionsOf(meta);

  if (options.length) return meta.items[options[nearestAt(options, value)]];
  if (meta.kind === 'gradient') return value;       // no list declared yet

  // The same curve FloatRange.at() uses on the other side.
  const at = meta.geometric
      ? meta.start * (meta.end / meta.start) ** (value / 127)
      : meta.start + (meta.end - meta.start) * (value / 127);

  const shown = Math.abs(at) >= 10 ? String(Math.round(at))
                                   : (Number.isInteger(at) ? String(at) : at.toFixed(2));

  return meta.unit ? `${shown} ${meta.unit}` : shown;
}

// The colour a hue control is sitting on, for the swatch and the dial arc.
const hueAt = (value) => `hsl(${Math.round(value / 127 * 360)} 90% 55%)`;

const PER_STEP_PX = 24;             // a thumb's worth of travel per option

// Where a drag lands: the next option along for something chosen from a list,
// or anywhere at all for a sweep.
function dragTo(meta, from, dy) {
  const options = optionsOf(meta);

  if (!options.length) return clamp(Math.round(from + dy * DRAG_PER_PX));

  const at = nearestAt(options, from) + Math.round(dy / PER_STEP_PX);
  return options[Math.max(0, Math.min(options.length - 1, at))];
}

// The effects in the chain that took knobs of their own. They earn a place on
// the controls screen for the same reason a field does - something on the desk
// moves them - so they are listed beside the fields rather than only being
// reachable through the effect they belong to.
const effectsWithControls = () => activeEffects()
    .filter(name => controlsOwnedBy(name).length)
    .sort((a, b) => a.localeCompare(b));

// The knobs behind an expression: every control belonging to a field or an
// operator it names. It grows as either is added, because it is read off the
// tree being edited.
//
// A control is owned by whatever is in front of its dot - `ripple.speed` is
// ripple's.
//
// A field owns the ones named after it and no others. Several are named after
// another field with something on the end - `random_lines` is not a kind of
// `random`, `trace_lines` not a kind of `trace` - and matching those loosely
// would hand each of them the other's knobs.
//
// An operator takes any control whose prefix it carries, because several of
// them share one and it is named after none of them: both choosers of a
// gradient ask for `gradient_1.select`. No operator is named after another
// field or operator with a suffix, so nothing is swept up that way.
function controlsFor(tree) {
  const fields = fieldsIn(tree);
  const ops = opsIn(tree);

  return controls.filter(c => c.kind === 'cc' && c.comments.some((t) => {
    const prefix = t.split('.')[0];
    return fields.includes(prefix)
        || ops.some(n => n === prefix || n.startsWith(prefix + '_'));
  }));
}

const effectOf = (key) => key.split('.')[0];
// A Patch names a slot `effect.slot`; the rig keeps the two halves apart.
const slotKeys = (name) =>
    (rig.effects[name]?.slots ?? []).map(slot => `${name}.${slot}`);
const slotOf = (key) => key.split('.').slice(1).join('.');
const isLeaf = (n) => n === null || typeof n === 'string' || typeof n === 'number';

// How many operands an operator is written with, as the rig describes it.
// Undefined for one the rig does not have - an operator a preset names that
// has since gone is shown and laid out as the general case rather than being
// guessed at.
const arityOf = (op) => rig.operators.find(o => o.name === op)?.arity;

// Whether to write an operation as a sum rather than as a call. Only a binary
// operator is one: it is written with two operands, and `glyphs` has the mark
// to put between them. A unary or nary operator reads `name(arg, arg)` - the
// same shape the editor lays it out in, and what parse() takes back.
const infix = (node, glyphs) => arityOf(node.op) === 'binary'
    && node.args.length === 2 && node.op in glyphs;

// The same operation under a different operator, with its operands fitted to
// what that one is written with: a unary operator gets one box, not however
// many the last one had. Nothing is moved that can stay - the operands keep
// their positions, a short list gains an empty one, and a long one loses the
// tail, which undo has if it was wanted. An operator written with any number
// keeps whatever it is given.
function withOp(node, name) {
  const arity = arityOf(name);
  const want = arity === 'unary' ? 1 : arity === 'binary' ? 2 : node.args.length;
  const args = node.args.slice(0, want);

  while (args.length < want) args.push(null);

  return {...node, op: name, args};
}

function describe(node, nested = false) {
  if (node === null) return 'nothing';
  if (typeof node === 'number') return String(node);
  if (typeof node === 'string') return node;

  // Brackets on every operator but the outermost. The tree has no precedence
  // - it is nested, not parsed - so `a + b * c` would read as something it is
  // not, and which `b * c` belongs to has to be shown rather than assumed.
  // A call brackets its own arguments and separates them with commas, so an
  // operation inside one needs no brackets of its own; between two operands
  // with only a glyph to go on, it does.
  if (!infix(node, OPS))
    return `${node.op}(${node.args.map(arg => describe(arg)).join(', ')})`;

  const parts = node.args.map(arg => describe(arg, true));
  const shown = `${parts[0]} ${OPS[node.op]} ${parts[1]}`;

  return nested ? `(${shown})` : shown;
}

// ---- the expression as text ----------------------------------------------

// On screen the operators are the ones a sum is written with; typed, they are
// the ones a keyboard has.
const TEXT_OPS = {add: '+', sub: '-', mul: '*', div: '/', avg: '~'};
const FROM_TEXT = Object.fromEntries(Object.entries(TEXT_OPS).map(([k, v]) => [v, k]));

// Brackets on every operator but the outermost, as the preview does - so what
// comes out reads back in as the same tree whatever precedence says.
function toText(node, nested = false) {
  if (node === null) return '';
  if (typeof node === 'number') return String(node);
  if (typeof node === 'string') return node;

  if (!infix(node, TEXT_OPS))
    return `${node.op}(${node.args.map(arg => toText(arg)).join(', ')})`;

  const parts = node.args.map(arg => toText(arg, true));
  const shown = `${parts[0]} ${TEXT_OPS[node.op]} ${parts[1]}`;

  return nested ? `(${shown})` : shown;
}

function tokens(text) {
  const grab = /\s*([(),]|[+\-*/~]|[A-Za-z_][\w.]*|\d*\.?\d+)/y;
  const out = [];
  let at = 0;

  while (at < text.length) {
    grab.lastIndex = at;
    const m = grab.exec(text);

    if (!m) throw new Error(`cannot read "${text.slice(at).trim().split(/\s/)[0]}"`);

    out.push(m[1]);
    at = grab.lastIndex;
  }

  return out;
}

// The tree itself has no precedence - it is nested, not parsed - but someone
// typing expects × to bind tighter than +, so that is what is read here, and
// toText puts the brackets back in so nothing is left to assume.
function parse(text) {
  const t = tokens(text.trim());
  let i = 0;

  const operand = () => {
    const tok = t[i++];

    if (tok === undefined) throw new Error('the expression stops short');

    if (tok === '(') {
      const inner = sum();
      if (t[i++] !== ')') throw new Error('a ( with no )');
      return inner;
    }

    if (tok === ')') throw new Error('a ) with no (');
    if (tok === ',') throw new Error('a , outside an operation');
    if (FROM_TEXT[tok]) throw new Error(`"${tok}" needs something in front of it`);
    if (/^[\d.]/.test(tok)) return parseFloat(tok);

    // `add(x, y, z)` - the only way to write an operation of any arity other
    // than two, since there is no glyph to put between three things. A name
    // followed by a ( is an operator, not a field, so it is checked against
    // the operators rather than the field list.
    if (t[i] === '(') {
      if (!rig.operators.some(o => o.name === tok))
        throw new Error(`no operator called "${tok}"`);
      i++;
      const args = [sum()];
      while (t[i] === ',') { i++; args.push(sum()); }
      if (t[i++] !== ')') throw new Error(`"${tok}(" with no )`);
      return {op: tok, args};
    }

    if (!rig.fields.some(f => f.name === tok)) throw new Error(`no field called "${tok}"`);

    return tok;
  };

  const binary = (ops, next) => () => {
    let left = next();

    while (ops.includes(t[i]))
      left = {op: FROM_TEXT[t[i++]], args: [left, next()]};

    return left;
  };

  const product = binary(['*', '/'], operand);
  const sum = binary(['+', '-', '~'], product);

  const tree = sum();

  if (i < t.length) throw new Error(`"${t[i]}" is one too many`);

  return tree;
}

// Brackets coloured by how deep they are, so a long expression can be read
// without counting. One beyond the last colour wraps round to the first.
const PAREN_COLOURS = 5;

function highlight(text) {
  const safe = (c) => c === '&' ? '&amp;' : c === '<' ? '&lt;' : c === '>' ? '&gt;' : c;
  let depth = 0;
  let out = '';

  for (const ch of text) {
    if (ch === ')') depth -= 1;

    out += (ch === '(' || ch === ')')
        ? `<span class="${depth < 0 ? 'bad' : 'p' + (depth % PAREN_COLOURS)}">${safe(ch)}</span>`
        : safe(ch);

    if (ch === '(') depth += 1;
  }

  return out;
}

// A textarea with its own text made invisible, over a pre holding the same
// text with the brackets coloured. The two have to be laid out identically or
// the caret drifts off the letters.
function textEditor(key, tree) {
  const wrap = document.createElement('div');
  wrap.className = 'typing';

  const box = document.createElement('div');
  box.className = 'exprbox';

  const shown = document.createElement('pre');
  const area = document.createElement('textarea');
  area.value = toText(tree);
  area.spellcheck = false;

  const bad = document.createElement('div');
  bad.className = 'hint';

  const paint = () => {
    shown.innerHTML = highlight(area.value) + ' ';   // a space, or the last line collapses
    area.style.height = 'auto';
    area.style.height = shown.offsetHeight + 'px';
  };

  const apply = () => {
    if (!area.value.trim()) { texting = null; write(key, null); return; }

    let parsed;
    try { parsed = parse(area.value); }
    catch (e) { bad.textContent = e.message; return; }

    texting = null;
    write(key, parsed);
  };

  area.oninput = () => { paint(); bad.textContent = ''; };
  area.onkeydown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); apply(); }
    if (e.key === 'Escape') { texting = null; drawSlots(); }
  };

  const set = document.createElement('button');
  set.className = 'setexpr';
  set.textContent = 'set';
  set.onclick = apply;

  box.append(shown, area);
  wrap.append(box, set, bad);

  setTimeout(() => { paint(); area.focus(); }, 0);
  return wrap;
}

// ---- reading and writing one node of a slot's tree ------------------------

const at = (tree, path) => path.reduce((n, step) => n[step], tree);

// The tree a slot is showing: what is being edited if it is open, otherwise
// what the patch says. Asked for again at every click rather than carried
// along, so a knob turned meanwhile is not written back as it was.
const treeFor = (key) => key in editing ? editing[key] : (patch.slots[key] ?? null);

function replace(tree, path, value) {
  if (path.length === 0) return value;

  const [step, ...rest] = path;
  const inner = replace(tree[step], rest, value);

  // An operation's arguments are a list, and spreading a list into an object
  // turns it into one - so the two halves of a path step are rebuilt in kind.
  if (Array.isArray(tree)) return tree.map((n, i) => (i === step ? inner : n));

  return {...tree, [step]: inner};
}

// The knobs as they stand, in the shape a patch records them. Read off the
// store the socket keeps rather than carried along from the last GET, so a
// knob turned while a slot was open is written as it is now and not as it was
// when the slot was opened.
//
// Only the ones something is listening to: every stray the box has ever sent
// is in the store too, and a preset is a set of settings rather than a log of
// what came down the wire.
const liveCCs = () => Object.fromEntries(
    Object.entries(knobs).filter(([cc]) => commentsOn(Number(cc)).length)
                         .map(([cc, k]) => [cc, k.value]));

// A patch as the page holds it: everything the server said about it except the
// knobs. Those live in `knobs` and nowhere else, so there is no second copy to
// go stale and no way to send one by accident - a write puts them back from
// the store, through liveCCs(), or sends none at all.
const heldPatch = ({ccs, ...rest}) => rest;

// What the store holds before the first frame arrives. /controls has the same
// numbers with the same comments, and its values are where the knobs actually
// are, so the store starts current. `age_ms` is high because none of this is
// anybody having just turned something.
const seedKnobs = () => Object.fromEntries(
    controls.filter(c => c.kind === 'cc')
            .map(c => [String(c.number), {cc: c.number, value: c.value,
                                          age_ms: Infinity}]));

// Send the whole patch, not just the slot that changed: a write replaces a
// preset's live side outright and nothing is merged, so a field left out is
// not left alone - it goes back to its default. That is every field, not just
// the knobs: leave `active` out and every effect comes back on, leave
// `cc_map` out and every control jumps back to the CC it was declared with.
async function write(key, tree) {
  const slots = {...patch.slots};

  if (tree === null) delete slots[key];
  else slots[key] = tree;

  remember();
  const r = await put(`/presets/${rig.selected}`, {...patch, ccs: liveCCs(), slots});
  if (!r.ok) alert((await r.json()).detail);
  await load();
}

// ---- the slot list -------------------------------------------------------

const fmt = (n) => (Math.round(n * 100) / 100).toFixed(2);

// Every leaf carries its three choices: a named field, a math node, or a
// constant. The one it currently is, is lit. Only picking *which* field needs
// the modal - the list is too long for a row.
function leaf(key, tree, path) {
  const node = at(tree, path);
  const row = document.createElement('div');
  row.className = 'row-wrap';

  const kinds = document.createElement('div');
  kinds.className = 'kindsel';

  // field - the chosen name sits inside this segment
  const field = document.createElement('button');
  field.title = 'field';
  field.className = typeof node === 'string' ? 'on' : '';
  field.textContent = '\u{1D453}(x)';
  if (typeof node === 'string') {
    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = node;
    field.append(name);
  }
  field.onclick = () => openPicker(key, path);

  // math - whatever is here already becomes the first operand, so this
  // doubles as "wrap what I have in an operation"
  const math = document.createElement('button');
  math.title = 'math';
  math.className = 'math';                  // two short rows of operators
  math.innerHTML = '<span>+\u2212</span><span>\u00d7\u00f7</span>';
  math.onclick = () => redrawSlot(key, replace(tree, path,
                                                {op: 'mul', args: [node, null]}));


  // const - the slider lives in this segment, and takes the icon's place
  if (typeof node === 'number') {
    const seg = document.createElement('div');
    seg.className = 'on knob';

    const slider = document.createElement('input');
    slider.type = 'range'; slider.min = '0'; slider.max = '1'; slider.step = '0.01';
    slider.value = String(node);

    const shown = document.createElement('span');
    shown.className = 'num';
    shown.textContent = fmt(node);

    // Follow the drag on screen, send once it is let go.
    slider.oninput = () => { shown.textContent = fmt(parseFloat(slider.value)); };
    slider.onchange = () => redrawSlot(key, replace(tree, path, parseFloat(slider.value)));

    seg.append(slider, shown);
    kinds.append(field, math, seg);         // the one in use goes last
  } else if (typeof node === 'string') {
    kinds.append(math, konst(), field);
  } else {
    kinds.append(field, math, konst());
  }

  function konst() {
    const b = document.createElement('button');
    b.title = 'const';
    b.textContent = '\u{1F39A}';
    b.onclick = () => redrawSlot(key, replace(tree, path, 0.5));
    return b;
  }

  row.append(kinds);

  if (node === null) {
    const hint = document.createElement('span');
    hint.className = 'hint';
    hint.textContent = 'empty';
    row.append(hint);
  }
  return row;
}


function nodeView(key, tree, path) {
  const node = at(tree, path);
  if (isLeaf(node)) return leaf(key, tree, path);

  const box = document.createElement('div');
  box.className = 'node';

  // The operation is adjustable in place - the current one is lit.
  const head = document.createElement('div');
  head.className = 'row-wrap';

  const ops = document.createElement('div');
  ops.className = 'opsel';
  for (const [name, glyph] of Object.entries(OPS)) {
    const b = document.createElement('button');
    b.textContent = glyph;
    b.title = name;
    if (name === node.op) b.className = 'on';
    b.onclick = () => redrawSlot(key, replace(tree, path, withOp(node, name)));
    ops.append(b);
  }

  // The row has room for the operators a sum is written with. The rig knows
  // the rest, and this is the way to them. When the operation is one of those
  // others, the button says which rather than leaving nothing lit.
  const more = document.createElement('button');
  const glyphed = node.op in OPS;
  more.textContent = glyphed ? '\u2026' : node.op;
  more.title = glyphed ? 'every operator' : node.op;

  // A name needs room either side of it, where a glyph is happy centred in
  // the same 28px every other button in the row gets.
  more.className = glyphed ? '' : 'named on';
  more.onclick = () => openOps(key, path);
  ops.append(more);

  // Turn the operands round. Only ÷ and − care, but they care a lot, and
  // rebuilding both sides by hand to turn one around is a chore. Reversed
  // rather than swapped, so it still means something with more than two, and
  // left out entirely where there is nothing to turn round.
  const swap = document.createElement('button');
  swap.className = 'swap';
  swap.textContent = '\u21c4';
  swap.title = 'turn the operands round';
  swap.onclick = () => redrawSlot(key, replace(tree, path,
                                               {...node, args: [...node.args].reverse()}));

  // Put this whole operation inside a new one, as its first operand - the
  // same move the leaf's math button makes, for something already nested.
  const wrap = document.createElement('button');
  wrap.className = 'wrap';
  wrap.textContent = '\u2283';
  wrap.title = 'wrap this in a new operation';
  wrap.onclick = () => redrawSlot(key, replace(tree, path,
                                               {op: 'mul', args: [node, null]}));

  const drop = document.createElement('button');
  drop.className = 'unwrap';
  drop.textContent = '⨯';
  drop.title = 'drop this operation, keep the first operand';
  drop.onclick = () => redrawSlot(key, replace(tree, path, node.args[0]));

  // An operator written with any number of operands can be given another.
  // The rest are written with the number they are written with, so there is
  // nothing to add to them.
  const plus = document.createElement('button');
  plus.className = 'plus';
  plus.textContent = '+';
  plus.title = 'another operand';
  plus.onclick = () => redrawSlot(key, replace(tree, path,
                                               {...node, args: [...node.args, null]}));

  const arity = arityOf(node.op);

  head.append(ops, ...(arity === 'nary' ? [plus] : []),
              ...(node.args.length > 1 ? [swap] : []), wrap, drop);

  // A binary operator sits between the two operands it joins rather than
  // above them, because which way round they are is the whole point of - and
  // ÷. Anything else has no between: the row goes on top and the operands
  // follow it in order, numbered, since position is all that tells them apart.
  //
  // Which it is comes from what the operator is written with, not from how
  // many arguments this node happens to hold - an operator of any arity with
  // two of them is still a list. A binary one that somehow holds another
  // number also stacks, so that nothing is left off the screen.
  const kids = document.createElement('div');
  kids.className = 'kids';
  const operands = node.args.map(
      (_, i) => nodeView(key, tree, [...path, 'args', i]));

  if (arity === 'binary' && operands.length === 2) {
    kids.append(operands[0], head, operands[1]);
  } else {
    kids.append(head);
    operands.forEach((view, i) => {
      const line = document.createElement('div');
      line.className = 'operand';
      const n = document.createElement('i');
      n.textContent = i + 1;
      line.append(n, view);

      // An operand of an operator written with any number of them can go
      // again - down to one, because an operation with nothing in it is not
      // an operation. The others are written with the number they are written
      // with, so there is nothing there to take away.
      if (arity === 'nary' && operands.length > 1) {
        const cut = document.createElement('button');
        cut.className = 'cut';
        cut.textContent = '\u2a2f';
        cut.title = `drop operand ${i + 1}`;
        cut.onclick = () => redrawSlot(key, replace(tree, path,
            {...node, args: node.args.filter((_, which) => which !== i)}));
        line.append(cut);
      }

      kids.append(line);
    });
  }

  box.append(kids);
  return box;
}

function redrawSlot(key, tree) {
  editing[key] = tree;
  const done = (function whole(n) {
    return n === null ? false : isLeaf(n) ? true : n.args.every(whole);
  })(tree);
  if (done) { delete editing[key]; write(key, tree); }
  else drawSlots();
}

function drawSlots() {
  const box = document.getElementById('page');
  box.innerHTML = '';

  // Knobs the effect itself owns, as against the ones behind whatever is
  // patched into its slots. They belong to the effect rather than to any
  // expression, so they are on show the whole time it is.
  const own = controlsOwnedBy(active);
  if (own.length) box.append(controlList(own));

  for (const key of slotKeys(active)) {
    const tree = treeFor(key);

    const el = document.createElement('div');
    el.className = 'slot' + (open === key ? ' open' : '') + (tree === null ? ' empty' : '');

    const row = document.createElement('div');
    row.className = 'row';
    row.innerHTML = `<span class="name">${slotOf(key)}</span>` +
                    `<span class="value">${describe(tree)}</span>` +
                    `<span class="chev">${open === key ? '▾' : '▸'}</span>`;
    row.onclick = () => {
      open = open === key ? null : key;
      texting = null;
      delete editing[key];
      drawSlots();
    };

    if (open === key) {
      // Type it instead of tapping it. One or the other, never both.
      const pencil = document.createElement('button');
      pencil.className = 'pencil' + (texting === key ? ' on' : '');
      pencil.textContent = '\u270e';
      pencil.title = texting === key ? 'back to tapping' : 'type the expression';
      pencil.onclick = (e) => {
        e.stopPropagation();
        texting = texting === key ? null : key;
        drawSlots();
      };
      row.append(pencil);
    }

    el.append(row);

    if (open === key && texting === key) {
      el.append(textEditor(key, tree));
    } else if (open === key) {
      const tree_ = document.createElement('div');
      tree_.className = 'tree';
      tree_.append(nodeView(key, tree, []));
      el.append(tree_);

      // What is behind the expression, and a way to move any of it onto a
      // different knob. Only while the slot is open.
      const found = controlsFor(tree);
      if (found.length) el.append(controlList(found));
    }
    box.append(el);
  }
}

// A control, looking like the knob readout does: its dial, what it is for,
// where it sits. Tapping one waits for a knob to be turned at it.
// What a knob is reading right now, which is the socket's answer if it has
// said anything yet and the one from /controls until then.
const liveValue = (c) => knobs[c.number]?.value ?? c.value;

const DRAG_PER_PX = 0.8;            // a touch over 150px for the whole range
const clamp = (v) => Math.max(0, Math.min(127, v));

// Turn a knob from here. It goes out over the same socket the values arrive
// on and lands as a knob move, so the preset that is playing takes it up.
function turnKnob(cc, value) {
  if (knobs[cc]) knobs[cc].value = value;     // show it now, not in 200ms
  refreshControls();

  if (wire && wire.readyState === WebSocket.OPEN)
    wire.send(JSON.stringify({cc: Number(cc), value}));
}

// The rows are redrawn only when the expression changes; between times the
// socket moves their dials, so they follow the desk rather than showing what
// was true when the slot was opened.
function refreshControls() {
  for (const el of document.querySelectorAll('[data-cc] .dial')) {
    // Hold the host before swapping the dial out: replaceChild detaches the
    // old node, and a detached node has no parent to ask afterwards.
    const host = el.closest('[data-cc]');
    const knob = knobs[host.dataset.cc];

    if (!knob) continue;

    const meta = metaFor(host.dataset.name);
    host.replaceChild(makeDial(knob.value, meta), el);

    const now = host.querySelector('.now');
    if (now) now.textContent = readOut(meta, knob.value);
  }
}

function controlList(found) {
  const box = document.createElement('div');
  box.className = 'ctrls';

  for (const c of found) {
    const name = c.comments[0] ?? `cc ${c.number}`;
    const waiting = mapping === name;
    const meta = metaFor(name);

    const row = document.createElement('button');
    row.className = 'ctrl' + (waiting ? ' waiting' : '');
    row.dataset.cc = c.number;
    row.dataset.name = name;
    row.title = waiting ? 'turn the knob you want'
                        : `${optionsOf(meta).length ? 'drag to choose' : 'drag to turn'}`
                          + `, tap to put ${name} on another knob`;

    // Drag it like a knob; a tap that went nowhere is the assign gesture.
    let from = null;

    row.onpointerdown = (e) => {
      from = {y: e.clientY, value: liveValue(c), turned: false};
      row.setPointerCapture(e.pointerId);
    };

    row.onpointermove = (e) => {
      if (from === null) return;

      const want = dragTo(meta, from.value, from.y - e.clientY);
      if (want === liveValue(c)) return;

      from.turned = true;
      turnKnob(c.number, want);
    };

    row.onpointerup = () => {
      const tapped = from !== null && !from.turned;
      from = null;

      if (!tapped) return;              // a turn, not an assign

      mapping = waiting ? null : name;
      mappingSince = Date.now();
      drawSlots();
    };

    row.append(makeDial(liveValue(c), meta));

    const label = document.createElement('b');
    label.textContent = name;

    const where = document.createElement('span');
    where.className = 'at';
    where.textContent = waiting ? 'turn a knob\u2026'
                                : `cc ${c.number}${c.number === c.default ? '' : ' \u00b7 moved'}`;

    const val = document.createElement('span');
    val.className = 'now';
    val.textContent = readOut(meta, liveValue(c));

    row.append(label, val, where);
    box.append(row);
  }

  return box;
}

// ---- the picker modal ----------------------------------------------------

function openPicker(key, path) {
  picking = {key, path};
  showFields();
  document.getElementById('modal').hidden = false;
}

// The effects not in the chain, to pick one back in.
function openAdd() {
  addingUp = true;
  const picker = document.getElementById('picker');
  document.getElementById('modal-title').textContent = 'add an effect';
  back(null);
  picker.className = 'picker';
  picker.innerHTML = '';

  const on = activeEffects();
  const off = Object.keys(rig.effects).filter(n => !on.includes(n));

  if (!off.length) {
    picker.innerHTML = '<p class="hint">every effect is already in.</p>';
  }

  for (const name of off) {
    const b = document.createElement('button');
    b.textContent = name;
    b.onclick = () => { closePicker(); setActive([...on, name]); };
    picker.append(b);
  }

  document.getElementById('modal').hidden = false;
}

function closePicker() {
  picking = null;
  presetsUp = false;
  addingUp = false;
  renamingUp = false;
  document.getElementById('modal').hidden = true;
}

// ---- undo ----------------------------------------------------------------

// A ring of what the rig looked like, so a wrong turn can be walked back.
// Nothing the instrument knows about: the page keeps the history, and every
// step is an ordinary write of an ordinary patch.
const UNDO_DEPTH = 64;

let records = [];       // {number, patch}, oldest first
let cursor = 0;         // index of the record that is live, or records.length
                        // when what is live is newer than anything recorded

// What is playing, as a record - the whole patch, knobs included.
const snapshot = () => ({number: rig.selected,
                         patch: {...patch, ccs: liveCCs()}});

function keep(rec) {
  records.push(rec);

  if (records.length > UNDO_DEPTH) {
    records.shift();                      // the ring: the oldest falls off
    cursor = Math.max(0, cursor - 1);
  }
}

// Called before an edit lands, so the buffer holds the state being left
// behind. Afterwards the end of the buffer is current, which is what puts
// redo out of reach.
function remember() {
  if (rig.selected === null) return;

  keep(snapshot());
  cursor = records.length;
}

const canUndo = () => records.length > 0
                      && (cursor >= records.length ? true : cursor > 0);
const canRedo = () => cursor < records.length - 1;

// Put a record back: write its patch to its preset, then play that preset.
// Writing first means the preset is already right when it starts playing,
// rather than flashing whatever it held before.
async function recall(rec) {
  const r = await put(`/presets/${rec.number}`, rec.patch);
  if (!r.ok) { alert((await r.json()).detail); return; }

  if (rig.selected !== rec.number) {
    const s = await post(`/presets/${rec.number}/select`);
    if (!s.ok) { alert((await s.json()).detail); return; }
  }

  open = null;
  editing = {};
  await load();
}

async function undo() {
  // The first step back has to record where it is stepping back from, or
  // there would be nothing for redo to come forward to.
  if (cursor >= records.length) {
    if (!records.length) return;
    keep(snapshot());
    cursor = records.length - 1;
  }

  if (cursor <= 0) return;

  cursor -= 1;
  await recall(records[cursor]);
}

async function redo() {
  if (!canRedo()) return;

  cursor += 1;
  await recall(records[cursor]);
}

// ---- naming what is playing ---------------------------------------------

// A name is a field of the patch, so it is written the way any other edit is:
// the whole patch, knobs and all. Nothing special happens to it on the way.
function openRename() {
  if (rig.selected === null) return;

  renamingUp = true;
  const picker = document.getElementById('picker');
  document.getElementById('modal-title').textContent = `name preset ${rig.selected}`;
  back(null);
  picker.className = 'picker rename';
  picker.innerHTML = '';

  const row = document.createElement('form');
  const input = document.createElement('input');
  input.type = 'text';
  input.value = patch.name ?? '';
  input.placeholder = 'unnamed';
  input.maxLength = 40;

  const ok = document.createElement('button');
  ok.type = 'submit';
  ok.textContent = 'name it';

  row.onsubmit = async (e) => {
    e.preventDefault();
    // Blank clears it rather than storing an empty string: a preset with no
    // name is the same thing it was before anyone typed.
    const called = input.value.trim() || null;
    closePicker();

    const r = await put(`/presets/${rig.selected}`,
                        {...patch, ccs: liveCCs(), name: called});
    if (!r.ok) { alert((await r.json()).detail); return; }
    await load();
  };

  row.append(input, ok);
  picker.append(row);
  document.getElementById('modal').hidden = false;
  input.focus();
  input.select();
}

// ---- the preset list -----------------------------------------------------

// Whether a slot holds anything. There is no such thing as an empty preset -
// a number with no file holds a patch that says nothing - so "written" is a
// question about the content rather than about the file.
const written = (view) => !!view && (view.stored.name
                                     || Object.keys(view.stored.slots).length > 0);

async function openPresets() {
  presetsUp = true;
  views = await get('/presets');
  const picker = document.getElementById('picker');
  document.getElementById('modal-title').textContent = 'presets';
  back(null);
  picker.className = 'picker presets';
  picker.innerHTML = '';

  for (let n = 0; n < rig.size; n++) {
    // Every slot holds a patch, written or not, so every one can be switched
    // to. Saving and reverting are up in the header, on whatever is playing.
    const cell = document.createElement('div');
    cell.className = 'pcell' + (written(views[n]) ? ' saved' : '') +
                     (isDirty(views[n]) ? ' dirty' : '') +
                     (n === rig.selected ? ' on' : '');

    const label = document.createElement('b');
    const called = views[n]?.live?.name;
    label.textContent = called ? `${n} \u00b7 ${called}` : n;

    // The name is the switch - there is nothing else to do to a preset from
    // here, so a separate play button was only taking room from the name.
    label.title = `switch to preset ${n}`;
    label.onclick = () => act(`/presets/${n}/select`);

    // Copying is a write followed by a select: the write puts what is playing
    // into that preset, and the select is what makes it the one you are on.
    const copyHere = (to) => {
      const b = document.createElement('button');
      b.textContent = '\u29c9';
      b.title = `copy what is playing into preset ${to}`;
      b.onclick = async () => {
        const r = await put(`/presets/${to}`, {...patch, ccs: liveCCs()});
        if (!r.ok) { alert((await r.json()).detail); return; }
        act(`/presets/${to}/select`);
      };
      return b;
    };

    cell.append(label, copyHere(n));
    picker.append(cell);
  }
}

// Storing also switches - the console marks what it just wrote as selected.
async function act(path) {
  const r = await post(path);
  if (!r.ok) { alert((await r.json()).detail); return; }
  closePicker();
  open = null;
  editing = {};
  await load();
}

function back(to) {
  const b = document.getElementById('modal-back');
  b.style.visibility = to ? 'visible' : 'hidden';
  b.onclick = to ?? null;
}

// Picking the operator of an operation, rather than what is inside one.
function openOps(key, path) {
  picking = {key, path};
  showOperators();
  document.getElementById('modal').hidden = false;
}

// How an operator is written, which says more about it than its name does: a
// binary one is the sum it makes, and the rest are the call they are written
// as - with the single argument a unary takes, or an ellipsis for however many
// an nary does. A binary operator with no glyph of its own goes between its
// operands by name, since that is still where it sits.
const writtenAs = (o) => o.arity === 'binary'
    ? `a ${OPS[o.name] ?? o.name} b`
    : `${o.name}(${o.arity === 'unary' ? 'x' : '...'})`;

// Every operator the rig has, A to Z by name, the one in use lit.
function showOperators() {
  const picker = document.getElementById('picker');
  document.getElementById('modal-title').textContent = 'which operator?';
  back(null);
  picker.className = 'picker';
  picker.innerHTML = '';

  const node = at(treeFor(picking.key), picking.path);
  const named = [...rig.operators].sort((x, y) => x.name.localeCompare(y.name));

  for (const o of named) {
    const b = document.createElement('button');
    b.textContent = writtenAs(o);
    b.title = `${o.name} \u00b7 ${o.kind} \u00b7 ${o.arity}`;

    if (o.name === node.op) b.className = 'on';
    b.onclick = () => chooseOp(o.name);
    picker.append(b);
  }
}

function chooseOp(name) {
  const {key, path} = picking;
  const tree = treeFor(key);
  closePicker();
  redrawSlot(key, replace(tree, path, withOp(at(tree, path), name)));
}

// One flat list, A to Z. The kind rides along as a hint rather than a category.
function showFields() {
  const picker = document.getElementById('picker');
  document.getElementById('modal-title').textContent = 'which field?';
  back(null);
  picker.className = 'picker';
  picker.innerHTML = '';

  for (const f of [...rig.fields].sort((x, y) => x.name.localeCompare(y.name))) {
    const b = document.createElement('button');
    b.textContent = f.name;
    b.onclick = () => choose(f.name);
    picker.append(b);
  }
}


function choose(value) {
  const {key, path} = picking;
  const tree = treeFor(key);
  closePicker();
  redrawSlot(key, replace(tree, path, value));
}

// ---- page ----------------------------------------------------------------

async function load() {
  [rig, controls, surfaces] = await Promise.all(
      [get('/rig'), get('/controls'), get(SURFACES)]);

  if (!(surfaceId in surfaces)) surfaceId = Object.keys(surfaces)[0] ?? null;
  await loadSurface();

  if (!Object.keys(knobs).length) knobs = seedKnobs();

  const view = await get(`/presets/${rig.selected}`);
  patch = heldPatch(view.live);
  stored = view.stored;
  dirty = isDirty(view);

  const shown = activeEffects();
  if (!shown.includes(active)) active = shown[0] ?? null;
  if (!rig.fields.some(f => f.name === chosen)) chosen = null;

  drawTabs();
  drawSubBar();
  drawPage();
  drawChip();
}

function drawTabs() {
  const bar = document.getElementById('tabs');
  bar.innerHTML = '';

  for (const [key, label] of TABS) {
    const b = document.createElement('button');
    b.textContent = label;
    b.className = key === tab ? 'on' : '';
    b.onclick = () => {
      if (tab === key) return;
      tab = key;
      open = null;
      closePicker();
      drawTabs(); drawSubBar(); drawPage();
    };
    bar.append(b);
  }
}

// The sub bar is whatever the tab indexes: effects, fields, or the parts of
// the setup worth looking at.
function drawSubBar() {
  const bar = document.getElementById('subbar');
  bar.innerHTML = '';

  const cell = (label, hint, on, pick) => {
    const b = document.createElement('button');
    b.innerHTML = hint ? `${label}<small>${hint}</small>` : label;
    b.className = on ? 'on' : '';
    b.onclick = pick;
    bar.append(b);
  };

  if (tab === 'effects') {
    // Only the effects in the chain; the + adds one of the others back.
    for (const name of activeEffects()) {
      const box = document.createElement('div');
      box.className = 'subcell' + (name === active ? ' on' : '');

      const pick = document.createElement('button');
      pick.className = 'pick';
      pick.textContent = name;
      pick.onclick = () => {
        active = name; open = null; closePicker(); drawSubBar(); drawPage();
      };

      const kill = document.createElement('button');
      kill.className = 'kill';
      kill.textContent = '\u{1F5D1}\uFE0F';
      kill.title = `take ${name} out`;
      kill.onclick = () => setActive(activeEffects().filter(n => n !== name));

      box.append(kill, pick);
      bar.append(box);
    }

    const add = document.createElement('button');
    add.className = 'add';
    add.textContent = '\u2795';
    add.title = 'add an effect';
    add.onclick = openAdd;
    bar.append(add);
  } else if (tab === 'controls') {
    for (const name of fieldsInUse())
      cell(name, `${usedBy(name).length} in use`, name === chosen,
           () => { chosen = name; drawSubBar(); drawPage(); });

    for (const name of effectsWithControls())
      cell(name, 'effect', name === chosen,
           () => { chosen = name; drawSubBar(); drawPage(); });
  } else {
    for (const [key, label] of SECTIONS)
      cell(label, '', key === section,
           () => { section = key; drawSubBar(); drawPage(); });
  }
}

// Whether the page is being used right now, rather than just looked at. An
// open select keeps focus, which is the case that matters.
const inUse = () => document.activeElement?.closest?.('#page') != null;

function drawPage() {
  if (tab === 'effects') return drawSlots();
  if (tab === 'controls') return drawFieldPage();
  return drawSystemPage();
}

// Every slot whose expression names a field, however deep in it.
function usedBy(name) {
  const mentions = (n) => n === name ||
      (n !== null && typeof n === 'object' && n.args.some(mentions));
  return Object.keys(patch.slots).filter(k => mentions(patch.slots[k]));
}

function infoRow(name, value) {
  const el = document.createElement('div');
  el.className = 'slot';
  const row = document.createElement('div');
  row.className = 'row';
  row.innerHTML = `<span class="name">${name}</span><span class="value">${value}</span>`;
  el.append(row);
  return el;
}

// ---- Controls: what a field is, what drives it, and who listens ----------

// The picture is fetched rather than built, so a different box is a different
// file rather than different code.
async function loadSurface() {
  const chosenBox = surfaces[surfaceId];
  surfaceSvg = '';

  if (!chosenBox) return;

  try {
    surfaceSvg = await fetch(chosenBox.svg).then(r => r.text());
  } catch (e) { /* no picture; the page still works without one */ }
}

// The box, with whatever the chosen field listens to lit up. The mapping says
// which element in the drawing each CC number is.
function knobDiagram() {
  const box = document.createElement('div');
  box.className = 'surface';

  if (!surfaceSvg) {
    box.innerHTML = '<p class="hint">no picture of this box.</p>';
    return box;
  }

  box.innerHTML = surfaceSvg;

  const where = surfaces[surfaceId].ccs ?? {};
  const lit = chosen === null ? new Set() : knobsOf(chosen);

  for (const cc of lit) {
    // A control can sit on a CC this box has no knob for - something mapped
    // by hand, or an effect's own knob that was never on the desk. There is
    // nothing to light, and `#` on its own is not a selector.
    const id = where[cc];
    if (!id) continue;

    const spot = box.querySelector(`#${CSS.escape(id)}`);
    if (spot) spot.classList.add('lit');
  }

  return box;
}

// Every control whose CC or knob position differs between live and stored.
function controlChanges() {
  const byName = new Map(controls.filter(c => c.kind === 'cc')
                                 .map(c => [c.comments[0], c]));
  const names = new Set([...byName.keys(), ...Object.keys(patch.cc_map),
                         ...Object.keys(stored.cc_map)]);

  return [...names].sort().flatMap((name) => {
    const c = byName.get(name);
    const from = stored.cc_map[name] ?? c?.default;
    const to = patch.cc_map[name] ?? c?.default;
    const was = stored.ccs[from];
    const now = c && liveValue(c);

    return from !== to || (c && was !== now) ? [{name, from, to, was, now}] : [];
  });
}

function changesList() {
  const box = document.createElement('div');
  const found = controlChanges();

  box.append(infoRow('changed since saved', found.length || 'nothing'));

  for (const {name, from, to, was, now} of found) {
    const meta = metaFor(name);
    const parts = [];

    if (from !== to) parts.push(`cc ${from ?? 'default'} \u2192 ${to ?? 'default'}`);

    if (now !== undefined && was !== now) {
      const before = was === undefined ? 'unset' : readOut(meta, was);
      parts.push(`${before} \u2192 ${readOut(meta, now)}`);
    }

    box.append(infoRow(name, parts.join(' \u00b7 ')));
  }

  return box;
}

function drawFieldPage() {
  const box = document.getElementById('page');
  box.innerHTML = '';
  box.append(knobDiagram());

  if (chosen === null) {
    box.insertAdjacentHTML('beforeend',
        '<p class="hint">Pick a field or an effect above to see which knobs it '
        + 'listens to.</p>');
    box.append(changesList());
    return;
  }

  const info = rig.fields.find(f => f.name === chosen);
  const asEffect = !info && chosen in rig.effects;
  box.append(infoRow('kind', info ? info.kind : (asEffect ? 'effect' : '?')));

  // A control says what it is for as `owner.role`, so its own name is the
  // prefix to look for - an effect's and a field's read the same way.
  const mine = controlsOwnedBy(chosen);

  const where = surfaces[surfaceId]?.ccs ?? {};

  for (const c of mine) {
    const role = c.comments.filter(t => t.startsWith(chosen + '.'))
                           .map(t => t.slice(chosen.length + 1)).join(', ');
    // Nothing lights up for a CC this box has no knob for, so the row says so
    // rather than leaving the picture looking broken.
    const off = c.kind === 'cc' && !where[c.number] ? ' \u00b7 not on this box' : '';
    box.append(infoRow(`${c.kind} ${c.number}`, `${role} \u00b7 ${c.value}${off}`));
  }

  if (!mine.length) box.append(infoRow('driven by', 'nothing on the box'));

  if (asEffect) {
    // An effect is not plugged into anything, so what it has instead of a
    // list of users is the list of slots it offers.
    const slots = slotKeys(chosen).map(slotOf);
    box.append(infoRow('slots', slots.join(', ') || 'none'));
  } else {
    box.append(infoRow('used by', usedBy(chosen).join(', ') || 'nothing'));
  }

  box.append(changesList());
}

// ---- System --------------------------------------------------------------

async function drawSystemPage() {
  const box = document.getElementById('page');
  box.innerHTML = '';

  if (section === 'stats') {
    const s = await get('/stats');
    box.append(infoRow('frame rate', `${s.fps.toFixed(1)} fps`));
    box.append(infoRow('render', `${s.render_ms.toFixed(2)} ms`));
    box.append(infoRow('gc', `${s.gc_ms.toFixed(2)} ms`));
    box.append(infoRow('fields', rig.fields.length));
    box.append(infoRow('effects', Object.keys(rig.effects).length));
    box.append(infoRow('slots', Object.values(rig.effects)
                                      .reduce((n, e) => n + e.slots.length, 0)));
  } else if (section === 'timing') {
    const s = await get('/stats');
    const slots = Object.entries(s.slots ?? {});
    const load = slots.reduce((ms, [, t]) => ms + t.mean * t.calls / 1000, 0);

    // Against the whole second, not one frame: a slot's cost is what it adds
    // up to over all the frames it was asked in.
    const spent = s.render_ms * s.fps;

    box.append(infoRow('slots measured', slots.length));

    const percent = spent / 10;
    const rendering = infoRow('rendering',
        `${spent.toFixed(0)} ms of every second \u00b7 ${percent.toFixed(0)}%`);
    const track = document.createElement('div');
    track.className = 'usage';
    const bar = document.createElement('div');
    bar.style.width = `${percent.toFixed(1)}%`;
    track.append(bar);
    rendering.append(track);
    box.append(rendering);

    box.append(infoRow('their share', `${load.toFixed(2)} ms`
        + (spent ? ` \u00b7 ${(100 * load / spent).toFixed(0)}% of it` : '')));
    box.append(timingTable(slots));
  } else if (section === 'midi') {
    for (const c of controls) {
      const what = (c.comments.join(' \u00b7 ') || 'unnamed') + (c.hidden ? ' \u00b7 hidden' : '');
      box.append(infoRow(`${c.kind} ${c.number}`, `${what} \u2014 ${c.value}`));
    }
  } else if (section === 'surface') {
    const row = infoRow('box', '');
    const pick = document.createElement('select');

    for (const [id, box_] of Object.entries(surfaces)) {
      const opt = document.createElement('option');
      opt.value = id;
      opt.textContent = box_.name;
      opt.selected = id === surfaceId;
      pick.append(opt);
    }

    pick.onchange = async () => {
      surfaceId = pick.value;
      localStorage.setItem('surface', surfaceId);   // this browser's desk
      await loadSurface();
      drawPage();
    };

    row.querySelector('.value').append(pick);
    box.append(row);
    box.append(infoRow('controls mapped',
                       Object.keys(surfaces[surfaceId]?.ccs ?? {}).length));
    box.append(knobDiagram());
  } else {
    box.append(infoRow('bank size', rig.size));
    box.append(infoRow('playing', rig.selected === null ? '\u2014' : `preset ${rig.selected}`));
    views = await get('/presets');
    box.append(infoRow('written',
                       Object.keys(views).filter(n => written(views[n])).join(', ') || 'none'));
    const edited = Object.keys(views).filter(n => isDirty(views[n]));
    box.append(infoRow('unsaved edits', edited.join(', ') || 'none'));
  }
}

// What each slot's gets cost. Every number is one second's worth smoothed
// across seconds by the instrument, in microseconds, bar `gets`, which is that
// second's count, and the load, which is the two multiplied - the share of the
// second the slot spent answering. Worst load first: that is the one to look
// at, and a slot asked 2,600 times for 2us apiece costs more than a slot asked
// twice for 200.
const TIMING_COLUMNS = [
  ['mean', 'mean', 'what one get costs on average'],
  ['min', 'best', 'the quickest get of the second'],
  ['max', 'worst', 'the slowest get of the second - one end, one frame'],
  ['sd', 'spread', 'how far the gets fall either side of the mean'],
  ['calls', 'gets', 'how many times it was asked, in the second'],
  ['per_end', 'per end', 'gets of one end in one frame: the mean, then the most if that differs'],
];

const SHORT = (v) => v.toFixed(v < 10 ? 2 : v < 100 ? 1 : 0);

const perEnd = (t) => t.per_end === t.per_end_max ? String(t.per_end_max)
                                                  : `${t.per_end.toFixed(1)} / ${t.per_end_max}`;

function timingTable(slots) {
  if (!slots.length)
    return infoRow('timing', 'nothing is being computed');

  const rows = slots
      .map(([name, t]) => ({name, ...t, load: t.mean * t.calls / 1000}))
      .sort((a, b) => b.load - a.load);

  const table = document.createElement('table');
  table.className = 'timing';

  const head = table.insertRow();
  const labels = [['slot', 'the effect and the slot of it'],
                  ...TIMING_COLUMNS.map(([, label, why]) => [label, why]),
                  ['ms/s', 'the mean times the gets: what the slot costs a second']];

  for (const [label, why] of labels) {
    const th = document.createElement('th');
    th.textContent = label;
    th.title = why;                  // microseconds, bar the gets and the load
    head.append(th);
  }

  // The bar is each slot's load against the heaviest one, so the shape of it
  // reads at a glance without having to compare the numbers.
  const worst = rows[0].load;

  for (const row of rows) {
    const tr = table.insertRow();
    tr.insertCell().textContent = row.name;

    for (const [key] of TIMING_COLUMNS) {
      const td = tr.insertCell();
      td.className = 'num';
      td.textContent = key === 'calls' ? row.calls
                     : key === 'per_end' ? perEnd(row) : SHORT(row[key]);
    }

    const td = tr.insertCell();
    td.className = 'load';
    const bar = document.createElement('div');
    bar.className = 'bar';
    bar.style.width = `${worst ? (row.load / worst * 100).toFixed(1) : 0}%`;
    const text = document.createElement('span');
    text.textContent = row.load.toFixed(2);
    td.append(bar, text);
  }

  return table;
}

async function drawStats() {
  const s = await get('/stats');
  document.getElementById('fps').textContent = `${s.fps.toFixed(0)} fps`;
}

function drawChip() {
  const chip = document.getElementById('preset-chip');
  const n = rig.selected;

  // The same pill the preset list is made of, minus the two buttons - so
  // what is playing reads the way it reads in the list.
  const called = patch?.name;
  const label = document.createElement('b');
  label.textContent = n === null ? 'preset —'
                                 : (called ? `${n} \u00b7 ${called}` : String(n));

  chip.innerHTML = '';
  chip.append(label);
  chip.className = (n === null ? 'none' : '') + (dirty ? ' dirty' : '');

  // Saving and reverting act on whatever is playing, so they live up here
  // rather than once per row.
  for (const [id, verb] of [['save-chip', 'commit'], ['revert-chip', 'revert']]) {
    const b = document.getElementById(id);
    b.disabled = !dirty;
    b.title = dirty ? `${verb} preset ${n}` : `nothing to ${verb}`;
  }

  // Naming does not wait on there being an edit to save - it needs only
  // something to name.
  for (const [id, go, label] of [['undo-chip', canUndo(), 'undo'],
                                 ['redo-chip', canRedo(), 'redo']]) {
    const b = document.getElementById(id);
    b.disabled = !go;
    b.title = go ? `${label} the last change` : `nothing to ${label}`;
  }

  const rename = document.getElementById('rename-chip');
  rename.disabled = n === null;
  rename.title = n === null ? 'nothing playing'
                            : `name preset ${n}${patch?.name ? ` (${patch.name})` : ''}`;
}

for (const [id, path] of [['save-chip', 'commit'], ['revert-chip', 'revert']]) {
  document.getElementById(id).onclick = () => {
    if (rig.selected !== null) act(`/presets/${rig.selected}/${path}`);
  };
}
document.getElementById('modal-close').onclick = closePicker;
document.getElementById('undo-chip').onclick = undo;
document.getElementById('redo-chip').onclick = redo;
document.getElementById('rename-chip').onclick = () => {
  if (renamingUp) { closePicker(); return; }
  openRename();
};
document.getElementById('preset-chip').onclick = () => {
  if (presetsUp) { closePicker(); return; }
  openPresets();
  document.getElementById('modal').hidden = false;
};

load(); drawStats();
setInterval(async () => {
  drawStats();

  // The preset can change from the controller - a program change - so the
  // chip follows it rather than showing what it was at load.
  if (rig !== null) {
    const fresh = await get('/rig');
    const moved = fresh.selected !== rig.selected;
    rig = fresh;
    drawChip();
    if (moved && presetsUp) openPresets();   // the marker moves with it
  }

  if (open === null && picking === null && !presetsUp && !addingUp && !renamingUp) {
    const view = await get(`/presets/${rig.selected}`);
    patch = heldPatch(view.live);
    stored = view.stored;
    dirty = isDirty(view);
    controls = await get('/controls');

    // Keeping the page current is no good if it rebuilds what somebody has
    // hold of: a dropdown lives in the page, and redrawing it shuts it.
    if (!inUse()) drawPage();
  }
}, 1000);


// --- the knob that moved last -------------------------------------------
// Polled faster than the rest: it is only up for two seconds, so a one-second
// poll would catch some of them late and miss others entirely.
const CC_SHOWN = 2000;              // ms a move stays on screen

const ccbar = document.getElementById('ccbar');
const ccNum = document.getElementById('cc-num');
const ccVal = document.getElementById('cc-val');
const ccComments = document.getElementById('cc-comments');
const dialTrack = document.getElementById('dial-track');
const dialValue = document.getElementById('dial-value');
const dialPin = document.getElementById('dial-pin');

// A rev counter: three quarters of a turn with the gap at the bottom.
const DIAL_FROM = Math.PI * 0.75, DIAL_SWEEP = Math.PI * 1.5, DIAL_R = 15;
const dialAt = (r, a) => [20 + r * Math.cos(a), 20 + r * Math.sin(a)];

function arc(from, to) {
  const [x0, y0] = dialAt(DIAL_R, from), [x1, y1] = dialAt(DIAL_R, to);
  const big = to - from > Math.PI ? 1 : 0;
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${DIAL_R} ${DIAL_R} 0 ${big} 1 ` +
         `${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

dialTrack.setAttribute('d', arc(DIAL_FROM, DIAL_FROM + DIAL_SWEEP));

// The same rev counter the readout uses, as a standalone element so any row
// can have one.
function makeDial(value, meta = PLAIN) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 40 40');
  svg.setAttribute('class', 'dial');

  const frac = fracOf(meta, value);
  const a = DIAL_FROM + DIAL_SWEEP * frac;

  const path = (d, stroke) => {
    const el = document.createElementNS(ns, 'path');
    el.setAttribute('d', d);
    el.setAttribute('fill', 'none');
    el.setAttribute('stroke', stroke);
    el.setAttribute('stroke-width', '4');
    return el;
  };

  svg.append(path(arc(DIAL_FROM, DIAL_FROM + DIAL_SWEEP), '#39414d'));
  if (frac > 0.002)
    svg.append(path(arc(DIAL_FROM, a),
                    meta.kind === 'gradient' ? hueAt(value) : '#6a8fd0'));

  const [x1, y1] = dialAt(5, a), [x2, y2] = dialAt(13, a);
  const pin = document.createElementNS(ns, 'line');
  pin.setAttribute('x1', x1.toFixed(2)); pin.setAttribute('y1', y1.toFixed(2));
  pin.setAttribute('x2', x2.toFixed(2)); pin.setAttribute('y2', y2.toFixed(2));
  pin.setAttribute('stroke', '#cfe3ff');
  pin.setAttribute('stroke-width', '2');
  pin.setAttribute('stroke-linecap', 'round');
  svg.append(pin);

  return svg;
}

let ccHide = null;

function drawKnob(k) {
  const meta = metaOn(k.cc);
  const frac = fracOf(meta, k.value);
  const a = DIAL_FROM + DIAL_SWEEP * frac;

  // An arc of zero length still draws a cap, so leave it out entirely.
  dialValue.setAttribute('d', frac > 0.002 ? arc(DIAL_FROM, a) : '');
  dialValue.setAttribute('stroke', meta.kind === 'gradient' ? hueAt(k.value) : '#6a8fd0');

  const [x1, y1] = dialAt(5, a), [x2, y2] = dialAt(13, a);
  dialPin.setAttribute('x1', x1.toFixed(2));
  dialPin.setAttribute('y1', y1.toFixed(2));
  dialPin.setAttribute('x2', x2.toFixed(2));
  dialPin.setAttribute('y2', y2.toFixed(2));

  ccNum.textContent = `cc ${k.cc}`;
  ccVal.textContent = readOut(meta, k.value);
  const what = commentsOn(k.cc);
  ccComments.textContent = what.length ? what.join(' · ') : 'not mapped';
  ccComments.className = what.length ? '' : 'none';
  ccbar.hidden = false;
}

// Controls the instrument treats as plumbing. The stream says what moved and
// leaves the judgement here, so this is where anything declared hidden gets
// ignored.
const isPlumbing = (cc) =>
    controls.some(c => c.kind === 'cc' && c.number === cc && c.hidden);

async function applyMapping(name, number) {
  mapping = null;
  remember();
  const r = await put(`/presets/${rig.selected}`,
                      {...patch, ccs: liveCCs(),
                       cc_map: {...patch.cc_map, [name]: number}});
  if (!r.ok) alert((await r.json()).detail);
  await load();
}

// Whichever knob moved most recently, out of the last frame.
function lastMoved() {
  let best = null;

  for (const knob of Object.values(knobs))
    if (best === null || knob.age_ms < best.age_ms) best = knob;

  return best;
}

function onFrame() {
  refreshControls();

  const k = lastMoved();
  if (k === null) return;

  // Waiting to be told which knob: the first one moved since the asking.
  if (mapping !== null && k.age_ms < Date.now() - mappingSince) {
    applyMapping(mapping, k.cc);
    return;
  }

  if (k.age_ms >= CC_SHOWN || isPlumbing(k.cc)) {
    if (!ccHide) ccbar.hidden = true;
    return;
  }

  drawKnob(k);
  clearTimeout(ccHide);
  ccHide = setTimeout(() => { ccbar.hidden = true; ccHide = null; },
                      CC_SHOWN - k.age_ms);
}

// Pushed, not polled: the knobs move continuously, and asking often enough to
// keep up would be most of the traffic on the page.
function listen() {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  wire = new WebSocket(`${scheme}://${location.host}/ws/knobs`);

  wire.onmessage = (e) => { knobs = JSON.parse(e.data); onFrame(); };
  wire.onclose = () => setTimeout(listen, 1000);      // the app restarts; so do we
}

listen();
