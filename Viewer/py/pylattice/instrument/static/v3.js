// v3: effects down the left, whatever they hold on the right.

const get = (p) => fetch(p).then(r => r.json());
const post = (p, body) => fetch(p, body === undefined ? {method: 'POST'} :
                                 {method: 'POST', headers: {'Content-Type': 'application/json'},
                                  body: JSON.stringify(body)});
const put = (p, body) => fetch(p, {method: 'PUT', headers: {'Content-Type': 'application/json'},
                                   body: JSON.stringify(body)});

let rig = null;             // what can be patched, and which preset is playing
let views = {};             // every preset, live against what its file has

// Whether a preset has drifted from its file is a question about two patches,
// so it is answered here rather than by the server.
function same(a, b) {
  if (a === b) return true;
  if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') return false;

  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every(k => same(a[k], b[k]));
}

// A knob the file does not list is not an edit. The live copy of a preset
// records every knob the rig watches, so one added since the file was written
// turns up in it as soon as the preset is played - nobody moved anything.
const edited = (live, stored) =>
    ({...live, ccs: Object.fromEntries(Object.entries(live.ccs).filter(([cc]) => cc in stored.ccs))});

const isDirty = (view) => !!view && !same(edited(view.live, view.stored), view.stored);

async function act(path) {
  const r = await post(path);
  if (!r.ok) { alert((await r.json()).detail); return; }
  await refresh();
}

// ---- the preset bar ------------------------------------------------------

// The same glyphs as the touch layout.
const ICONS = {save: '\u{1F4BE}', revert: '\u21ba', undo: '\u21b6', redo: '\u21b7'};

// The bank holds a patch for every number, written or not. The bar shows the
// first sixteen; the rest are reached by name, from the menu beside it.
const BAR = 16;

// Whether a preset holds anything. A number with no file holds a patch that says
// nothing, so this is a question about the content and not about the file.
const written = (view) => !!view && (!!view.stored.name || Object.keys(view.stored.slots).length > 0);

const bar = document.getElementById('presets');
let cells = [];             // built once, so a redraw never swallows a click
let save = null, revert = null, undoBtn = null, redoBtn = null;

function buildPresets() {
  bar.innerHTML = '';
  cells = [];

  for (let n = 0; n < BAR; n++) {
    const b = document.createElement('button');
    b.textContent = n;
    b.onclick = () => act(`/presets/${n}/select`);
    cells.push(b);
    bar.append(b);
  }

  // Both act on whatever is playing, so there is one of each, not one per cell.
  for (const [verb, icon] of [['commit', ICONS.save], ['revert', ICONS.revert],
                              ['undo', ICONS.undo], ['redo', ICONS.redo]]) {
    const b = document.createElement('button');
    b.className = 'pcell act';
    b.textContent = icon;
    b.onclick = verb === 'undo' ? undo : verb === 'redo' ? redo
              : () => { if (rig.selected !== null) act(`/presets/${rig.selected}/${verb}`); };
    b.dataset.verb = verb;
    bar.append(b);
  }
  [save, revert, undoBtn, redoBtn] = bar.querySelectorAll('.act');
}

// What a preset is called, if it has a name: it is a field of the patch, so it
// comes with the preset like anything else in it. The page gives one when it makes
// a copy and offers no way to change it after - to call a preset something else,
// save another copy.
const nameOf = (n) => views[n]?.live.name ?? null;
const namedNumbers = () => Object.keys(views).map(Number).filter(nameOf).sort((a, b) => a - b);

const nameBox = document.getElementById('preset-name');
const numBox = document.getElementById('preset-num');
const namedBox = document.getElementById('named');
const namedOpen = document.getElementById('named-open');

function drawName() {
  const n = rig.selected;
  nameBox.textContent = nameOf(n) ?? '';
  nameBox.classList.toggle('dirty', n !== null && isDirty(views[n]));
  numBox.textContent = n === null ? '' : `#${n}`;
  namedOpen.disabled = !namedNumbers().length;
}

function drawPresets() {
  if (cells.length !== BAR) buildPresets();

  cells.forEach((b, n) => {
    b.className = 'pcell' + (written(views[n]) ? ' saved' : '') +
                  (isDirty(views[n]) ? ' dirty' : '') +
                  (n === rig.selected ? ' on' : '');
  });

  drawName();

  const n = rig.selected;
  const dirty = n !== null && isDirty(views[n]);
  for (const b of [save, revert]) {
    b.disabled = !dirty;
    b.title = dirty ? `${b.dataset.verb} preset ${n}` : `nothing to ${b.dataset.verb}`;
  }

  for (const [b, go, label] of [[undoBtn, canUndo(), 'undo'], [redoBtn, canRedo(), 'redo']]) {
    b.disabled = !go;
    b.title = go ? `${label} the last change` : `nothing to ${label}`;
  }
}

// Two decimals, or three when the number has them: a value typed as 0.123 is shown
// as 0.123, not as the 0.12 it would round to. Three is as fine as the page keeps.
const fmt = (n) => {
  const three = n.toFixed(3);
  return three.endsWith('0') ? n.toFixed(2) : three;
};
const OPS = {add: '+', sub: '\u2212', mul: '\u00d7', div: '\u00f7', avg: '\u2248'};

// ---- operators -------------------------------------------------------------
// An operation is {op, args: [...]}: an operator and however many operands it is
// written with. Which operators there are, and how many operands each takes, is
// the rig's to say - `rig.operators` - so nothing here keeps a list that could
// disagree with it. The glyphs above are only the ones a sum is written with.

// How many operands an operator is written with: 'unary', 'binary' or 'nary'.
// Undefined for one the rig does not have - an operator a preset names that has
// since gone is laid out as the general case rather than guessed at.
const arityOf = (op) => rig?.operators?.find(o => o.name === op)?.arity;

// Whether to write an operation as a sum rather than as a call. Only a binary
// operator is one: it has two operands and a glyph to put between them. The rest
// read `name(a, b, c)`, which is also what parseText takes back.
const infix = (node, glyphs) => arityOf(node.op) === 'binary'
    && node.args.length === 2 && node.op in glyphs;

// The same operation under another operator, with its operands fitted to what
// that one is written with: a unary gets one box, a binary two. Operands keep
// their positions, a short list gains empty ones and a long one loses its tail
// (undo has it, if it was wanted). One written with any number keeps what it has.
function withOp(node, name) {
  const arity = arityOf(name);
  const want = arity === 'unary' ? 1 : arity === 'binary' ? 2 : node.args.length;
  const args = node.args.slice(0, want);
  while (args.length < want) args.push(null);
  return {...node, op: name, args};
}

// A slot as text: what is plugged into it, however deep.
function describe(node) {
  if (node === null || node === undefined) return 'nothing';
  if (typeof node === 'number') return fmt(node);
  if (typeof node === 'string') return node;

  const mod = node.mod ? ' mod 1' : '';
  if (infix(node, OPS))
    return `(${describe(node.args[0])} ${OPS[node.op]} ${describe(node.args[1])})${mod}`;
  return `${node.op}(${node.args.map(describe).join(', ')})${mod}`;
}

// ---- undo ----------------------------------------------------------------

// A ring of what a preset looked like before each edit, so a wrong turn can be
// walked back. Nothing the instrument knows about: the page keeps the history,
// and every step is an ordinary write of an ordinary patch.
const UNDO_DEPTH = 64;

let records = [];       // {number, patch}, oldest first
let cursor = 0;         // index of the record that is live, or records.length
                        // when what is live is newer than anything recorded

function keep(rec) {
  records.push(rec);

  if (records.length > UNDO_DEPTH) {
    records.shift();                      // the ring: the oldest falls off
    cursor = Math.max(0, cursor - 1);
  }
}

// Called with the patch as it stands, before an edit lands on it, so the buffer
// holds the state being left behind. Afterwards the end of the buffer is current,
// which is what puts redo out of reach.
function remember(number, patch) {
  keep({number, patch});
  cursor = records.length;
}

const canUndo = () => records.length > 0 && (cursor >= records.length ? true : cursor > 0);
const canRedo = () => cursor < records.length - 1;

// What is playing, whole and just now - knobs included, as they are.
const snapshot = async () => ({number: rig.selected, patch: (await get(`/presets/${rig.selected}`)).live});

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

  editing = {};
  await refresh();
}

async function undo() {
  if (rig.selected === null) return;

  // The first step back has to record where it is stepping back from, or
  // there would be nothing for redo to come forward to.
  if (cursor >= records.length) {
    if (!records.length) return;
    keep(await snapshot());
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

// ---- muting --------------------------------------------------------------

// A muted effect stays in the preset, slots and all, and is not drawn. Which
// ones are muted is a field of the patch, so muting is an edit like any other:
// it goes into the live side and shows as edited until it is saved.
const mutedIn = (n) => views[n]?.live.muted ?? [];
const muted = () => mutedIn(rig.selected);
const isMuted = (name) => muted().includes(name);

// A line of the player's own words about an effect, kept in the preset beside
// its name. Nothing renders from it.
async function setNote(name, text) {
  const n = rig.selected;
  if (n === null) return;

  const fresh = await get(`/presets/${n}`);
  remember(n, fresh.live);
  const {[name]: _gone, ...rest} = fresh.live.notes ?? {};
  const notes = text ? {...rest, [name]: text} : rest;
  const r = await put(`/presets/${n}`, {...fresh.live, notes});
  if (!r.ok) { alert((await r.json()).detail); return; }
  await refresh();
}

async function setMuted(names) {
  const n = rig.selected;
  if (n === null) return;

  // Read just now: a patch carries where the knobs are, and sending a stale one
  // back would move them.
  const fresh = await get(`/presets/${n}`);
  remember(n, fresh.live);
  const r = await put(`/presets/${n}`, {...fresh.live, muted: names});
  if (!r.ok) { alert((await r.json()).detail); return; }
  await refresh();
}

// What "mute all" silenced, so "unmute all" brings back those and nothing else.
let silenced = [];
let silencedFor = null;

function allOff(names) {
  const anyOn = names.some(n => !isMuted(n));

  if (anyOn) {
    silenced = names.filter(n => !isMuted(n));
    silencedFor = rig.selected;
    return setMuted([...new Set([...muted(), ...names])]);
  }

  const back = silencedFor === rig.selected && silenced.length ? silenced : names;
  silenced = [];
  return setMuted(muted().filter(n => !back.includes(n)));
}

// ---- which effects are in the preset ------------------------------------

// The chain is the patch's `active` list, so adding or removing is an edit to
// the preset like any other: it goes into the live side, and shows as edited
// until it is saved. Everything else in the patch is sent back as it is - and
// read just now, because a patch carries where the knobs are, and sending a
// stale one back would move them.
async function setActive(names) {
  const n = rig.selected;
  if (n === null) return;

  const fresh = await get(`/presets/${n}`);
  // The order is the order they draw in, so it is kept as given.
  const active = names.filter(e => e in rig.effects);

  remember(n, fresh.live);
  const r = await put(`/presets/${n}`, {...fresh.live, active});
  if (!r.ok) { alert((await r.json()).detail); return; }
  await refresh();
}

// ---- one slot ------------------------------------------------------------

// Change one slot of the playing preset, and nothing else - read just now, as
// with the chain, so the knobs in it are where they are.
//
// A `value` slot can have a fader as its outermost step. The editor never shows
// it, so what is written here is the rest of the expression and the fader the
// slot already has is put back around it - unless one is passed, `null` for none.
async function writeSlot(key, tree, fader) {
  const n = rig.selected;
  if (n === null) return;

  const fresh = await get(`/presets/${n}`);
  remember(n, fresh.live);
  if (isValueSlot(key)) {
    const outer = fader === undefined ? splitFader(fresh.live.slots[key] ?? null).fader : fader;
    tree = withFader(tree, outer);
  }
  const slots = {...fresh.live.slots, [key]: tree};
  // Controls a field brings are not placed on the box: that is done by hand, on
  // the map (or with "assign them").
  const r = await put(`/presets/${n}`, {...fresh.live, slots});
  if (!r.ok) { alert((await r.json()).detail); return; }
  await refresh();
}

// A constant: a slider to drag and a box to type in, kept in step. The slider's
// range stretches to hold whatever is typed (a constant can be 1.4 or -0.3), and
// nothing is sent until you let go of the slider or leave the box.
function constantControl(value, commit) {
  const wrap = document.createElement('div');
  wrap.className = 'const';

  const slider = document.createElement('input');
  slider.type = 'range';
  slider.step = '0.01';

  const box = document.createElement('input');
  box.className = 'num';
  box.type = 'text';
  box.inputMode = 'decimal';
  box.spellcheck = false;
  box.title = 'type a value';

  const fit = (v) => {
    slider.min = String(Math.min(0, Math.floor(v)));
    slider.max = String(Math.max(1, Math.ceil(v)));
    slider.value = String(v);
  };
  fit(value);
  box.value = fmt(value);

  slider.oninput = () => { box.value = fmt(parseFloat(slider.value)); };
  slider.onchange = () => commit(parseFloat(slider.value));

  const typed = () => {
    const v = parseFloat(box.value);
    if (!Number.isFinite(v)) { box.value = fmt(parseFloat(slider.value)); return; }
    fit(v);
    box.value = fmt(v);
    commit(v);
  };
  box.onchange = typed;
  box.onkeydown = (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); typed(); box.blur(); } };
  box.onfocus = () => box.select();

  wrap.append(slider, box);
  return wrap;
}

// A menu of the rig's fields to plug into a slot, with a box to search them.
// The page does not redraw while one is open, since it lives in the page.
let picking = null;         // the closer of the open one

// The order the menu lists them in: the rest, then faders, pads and artnet.
const GROUPS = ['fields', 'faders', 'pads', 'artnet'];

// Where a slot's slider starts when it is switched to a constant and has not
// been one before.
const DEFAULT_CONSTANT = 0.5;

// Which group a field sits in is worked out here, from what /rig says of it: its
// name and its kind (the name of its class). The rest - rotary, scope, masks -
// are 'fields'; a CC read straight off a control is a fader; anything a note or a
// pad's pressure drives is a pad; and artnet goes last. A new kind of field that
// a note drives has to be added to PAD_KINDS to be listed with the pads.
const FADER_KINDS = new Set(['CCField', 'FaderField', 'PolyTouchField']);
const PAD_KINDS = new Set(['FireField', 'StrobeField', 'BurstField', 'LoopsField', 'NoteRandomField',
                           'NoteRippleField', 'NoteWipeField', 'RandomTraceField']);

const groupOf = (f) => f.name.startsWith('artnet') ? 'artnet'
                     : FADER_KINDS.has(f.kind) ? 'faders'
                     : PAD_KINDS.has(f.kind) ? 'pads'
                     : 'fields';

// The order an effect's slots are listed in, whatever order it declares them:
// hue slots, then value slots, then sat slots, then every other slot A to Z. A
// slot is of a kind if it is called that, or that and an underscore and more, so
// hue_1 and hue_2 count as hue and a_hue does not.
const SLOTS_FIRST = ['hue', 'value', 'sat'];
const slotRank = (name) => {
  const rank = SLOTS_FIRST.findIndex(kind => name === kind || name.startsWith(kind + '_'));
  return rank < 0 ? SLOTS_FIRST.length : rank;
};
const slotsOf = (effect) => [...rig.effects[effect].slots]
    .sort((a, b) => slotRank(a) - slotRank(b) || (a < b ? -1 : a > b ? 1 : 0));

// What the menu lists. Each entry has the group it sits under, the text to show
// and a hint beside it, and the value that is handed back when it is chosen. The
// order of the entries is the order shown; the search looks in all three words.
// An entry can also carry `remove`, to be called when its bin is pressed.
const fieldSource = {
  placeholder: 'search fields, faders, pads',
  entries: () => GROUPS.flatMap(group =>
      rig.fields.filter(f => groupOf(f) === group)
                .sort((a, b) => a.name.localeCompare(b.name))
                .map(f => ({group, text: f.name, hint: '', value: f.name}))),
};

// The operators, as a menu: grouped by what they do, each with how it is written -
// a sum for a binary one, the call it is typed as for the rest. Nothing here lists
// them; what there is to choose from is whatever /rig says.
const OPERATOR_GROUPS = [
  ['arithmetic', (o) => o.kind === 'Math'],
  ['pick one', (o) => ['Select', 'Cycle', 'Randomize'].includes(o.kind)],
  ['gradients', (o) => o.kind === 'GradientChooser'],
];
const operatorGroup = (o) => OPERATOR_GROUPS.find(([, is]) => is(o))?.[0] ?? 'other';
const writtenAs = (o) => o.arity === 'binary'
    ? `a ${OPS[o.name] ?? o.name} b`
    : `${o.name}(${o.arity === 'unary' ? 'x' : '…'})`;

const operatorSource = {
  placeholder: 'search operators',
  noMap: true,                  // an operator is not something a control drives
  entries: () => [...OPERATOR_GROUPS.map(([g]) => g), 'other'].flatMap(group =>
      rig.operators.filter(o => operatorGroup(o) === group)
                   .sort((a, b) => a.name.localeCompare(b.name))
                   .map(o => ({group, text: o.name, hint: writtenAs(o), value: o.name}))),
};

// The menu hangs off `box`, which the caller places and whatever opens it sits
// in. This returns the thing that opens it, or closes it if it is already up.
function fieldMenu(box, current, onPick, source = fieldSource) {
  const close = () => {
    document.removeEventListener('pointerdown', away, true);
    box.querySelector('.fpick-list')?.remove();
    box.classList.remove('open');
    box.closest('.slot')?.classList.remove('menu-open');
    picking = null;
  };
  const away = (ev) => { if (!box.contains(ev.target)) close(); };
  const choose = (value) => { close(); onPick(value); };

  return () => {
    if (picking === close) { close(); return; }
    picking?.();
    picking = close;

    // What is chosen now, worked out as the menu opens: for a control that can be
    // turned at the desk, it is not what it was when the page was drawn.
    const selected = typeof current === 'function' ? current() : current;

    const menu = document.createElement('div');
    menu.className = 'fpick-list';
    const search = document.createElement('input');
    search.className = 'fpick-search';
    search.type = 'search';
    search.placeholder = source.placeholder;
    const body = document.createElement('div');
    body.className = 'fpick-body';
    // The same choice, made by pressing the control that drives the field.
    const onMap = document.createElement('button');
    onMap.className = 'fpick-map';
    onMap.textContent = 'pick on the controller map';
    onMap.onclick = () => { close(); startMapPick(onPick); };
    menu.append(search, ...(source.noMap ? [] : [onMap]), body);

    let rows = [], cursor = 0;

    const item = (text, hint, value, on, remove, swatch, edit) => {
      const row = document.createElement('div');
      row.className = 'fpick-item' + (on ? ' on' : '');
      // A gradient shows what it looks like, drawn by the same walk the rig does.
      if (swatch) row.append(strip(swatch, 72, 12));
      const t = document.createElement('span');
      t.textContent = text;
      t.className = 'fpick-text';
      row.append(t);
      if (hint) {
        const h = document.createElement('span');
        h.className = 'dim';
        h.textContent = hint;
        row.append(h);
      }
      row.onclick = () => choose(value);

      // An entry that can be opened without choosing it - a gradient to look at
      // or change - has a button for that, which does not also choose it.
      if (edit) {
        const open = document.createElement('button');
        open.className = 'fpick-edit';
        open.textContent = edit.label ?? 'edit';
        open.title = edit.title ?? 'open';
        open.onclick = (ev) => { ev.stopPropagation(); close(); edit.run(); };
        row.append(open);
      }

      // An entry that can be taken away has a bin of its own, which does not
      // also choose it.
      if (remove) {
        const bin = document.createElement('button');
        bin.className = 'bin';
        bin.textContent = '\u2715';
        bin.title = 'delete';
        bin.onclick = (ev) => { ev.stopPropagation(); close(); remove(); };
        row.append(bin);
      }
      return row;
    };

    const render = () => {
      const terms = search.value.toLowerCase().split(/\s+/).filter(Boolean);
      const hit = (e) => terms.every(t => `${e.text} ${e.group} ${e.hint}`.toLowerCase().includes(t));

      body.replaceChildren();
      let group = null;
      for (const e of source.entries().filter(hit)) {
        if (e.group !== group) {
          group = e.group;
          const head = document.createElement('div');
          head.className = 'fpick-group';
          head.textContent = group;
          body.append(head);
        }
        body.append(item(e.text, e.hint, e.value, e.value === selected, e.remove, e.swatch, e.edit));
      }

      rows = [...body.querySelectorAll('.fpick-item')];
      if (!rows.length) {
        const none = document.createElement('div');
        none.className = 'fpick-none';
        none.textContent = 'nothing matches';
        body.append(none);
      }
      cursor = Math.min(cursor, Math.max(rows.length - 1, 0));
      mark();
    };
    const mark = () => rows.forEach((r, i) => r.classList.toggle('hi', i === cursor));

    search.oninput = () => { cursor = 0; render(); };
    search.onkeydown = (ev) => {
      if (ev.key === 'ArrowDown') cursor = Math.min(cursor + 1, rows.length - 1);
      else if (ev.key === 'ArrowUp') cursor = Math.max(cursor - 1, 0);
      else if (ev.key === 'Enter') { rows[cursor]?.click(); return; }
      else if (ev.key === 'Escape') { close(); return; }
      else return;
      ev.preventDefault();
      mark();
      rows[cursor]?.scrollIntoView({block: 'nearest'});
    };

    render();
    box.append(menu);
    box.classList.add('open');
    box.closest('.slot')?.classList.add('menu-open');
    const now = body.querySelector('.on');
    if (now) { cursor = rows.indexOf(now); mark(); now.scrollIntoView({block: 'nearest'}); }
    search.focus({preventScroll: true});
    document.addEventListener('pointerdown', away, true);
  };
}

// What a slot held as a plain number last, so switching back to a value finds
// it as it was rather than at 0. Per session, and per page - it is not a setting.
const lastValue = {};

// Which slots have their formula folded to just the arithmetic - a habit of the
// person looking, so it is kept in the browser rather than in the preset.
const loadSet = (k) => { try { return new Set(JSON.parse(localStorage.getItem(k) ?? '[]')); }
                         catch { return new Set(); } };
const saveSet = (k, set) => { try { localStorage.setItem(k, JSON.stringify([...set])); } catch {} };
const folded = loadSet('v3.folded');

// ---- hue ------------------------------------------------------------------
// A hue slot is a position on a wheel that runs 0..2, so a range can wrap. It
// is held as a number, or as a source squeezed into a stretch of the wheel. The
// source is a field, or any formula that stays within 0..1:
//
//   0.4                       a fixed hue         no source
//   param_a                   the field itself    start 0, width 1
//   v_rotary x rotary         a formula           start 0, width 1
//   mul(s, k) / div(s, k)     squeezed            start 0, width k
//   add(<any of those>, c)    shifted             start c
//
// Anything else is a formula, which the hue control leaves alone.
const AXIS = 2;
const clampAxis = (x) => Math.max(0, Math.min(AXIS, x));
const isHueSlot = (key) => key.split('.').slice(1).join('.').includes('hue');

// What a formula can reach, as [lowest, highest], taking every field to run 0..1.
// It is null when that cannot be said: an operand left empty, an operator whose
// output is not a function of its operands' ranges (a gradient, a zap), or a
// division by anything but a fixed number.
function reach(n) {
  if (typeof n === 'number') return [n, n];
  if (typeof n === 'string') return [0, 1];
  if (n === null || typeof n !== 'object' || n.op === undefined) return null;

  const rs = n.args.map(reach);
  if (!rs.length || rs.some(r => !r)) return null;
  const [a, b] = rs;
  const two = rs.length === 2;

  switch (n.op) {
    case 'add': return two ? [a[0] + b[0], a[1] + b[1]] : null;
    case 'sub': return two ? [a[0] - b[1], a[1] - b[0]] : null;
    case 'avg': return [rs.reduce((s, r) => s + r[0], 0) / rs.length,
                        rs.reduce((s, r) => s + r[1], 0) / rs.length];
    case 'mul': {
      if (!two) return null;
      const p = [a[0] * b[0], a[0] * b[1], a[1] * b[0], a[1] * b[1]];
      return [Math.min(...p), Math.max(...p)];
    }
    case 'div': {
      if (!two || b[0] !== b[1] || b[0] === 0) return null;
      const q = [a[0] / b[0], a[1] / b[0]];
      return [Math.min(...q), Math.max(...q)];
    }
    // One operand comes out, whichever it is: anything any of them can reach.
    // select reads 0 when its knob points past the last operand, so 0 is in range.
    case 'cycle':
    case 'randomize':
    case 'select': {
      const lo = Math.min(...rs.map(r => r[0])), hi = Math.max(...rs.map(r => r[1]));
      return n.op === 'select' ? [Math.min(lo, 0), Math.max(hi, 0)] : [lo, hi];
    }
  }
  return null;
}

const withinUnit = (n) => {
  const r = reach(n);
  return r !== null && r[0] >= -1e-9 && r[1] <= 1 + 1e-9;
};

// A source the wheel can speak for: a field, or a formula with a field in it that
// cannot leave 0..1, so the thumbs say what it really sweeps.
const usableSource = (src) => typeof src === 'string' ||
    (src !== null && typeof src === 'object' && fieldsIn(src).length > 0 && withinUnit(src));

// A source and the width it is squeezed into: x x k, x / k, or k x x. Anything
// else is a source of its own, at width 1.
function peelWidth(x) {
  // A layer that wraps round is a source of its own: the wheel has no way to say so.
  if (x && typeof x === 'object' && !x.mod && x.args.length === 2
      && (x.op === 'mul' || x.op === 'div')) {
    const [f, k] = x.args;
    if (typeof k === 'number' && (x.op === 'mul' || k !== 0))
      return {field: f, width: x.op === 'mul' ? k : 1 / k};
    if (x.op === 'mul' && typeof f === 'number') return {field: k, width: f};
  }
  return {field: x, width: 1};
}

// The most it can take off the outside wins: a start and a width, then a width,
// then the whole of it as the source. The first whose source stays within 0..1.
function parseHue(t) {
  if (typeof t === 'number') return {field: null, start: t, width: 0};

  const options = [];
  if (t && typeof t === 'object' && t.op === 'add' && t.args.length === 2) {
    for (const [x, c] of [[t.args[0], t.args[1]], [t.args[1], t.args[0]]])
      if (typeof c === 'number') options.push({...peelWidth(x), start: c, mod: !!t.mod});
  }
  options.push({...peelWidth(t), start: 0, mod: !!t?.mod}, {field: t, width: 1, start: 0});

  return options.find(o => usableSource(o.field)) ?? null;
}

function buildHue({field, start, width, mod}) {
  if (field === null) return start;
  const w = Math.round(width * 1000) / 1000, st = Math.round(start * 1000) / 1000;
  let tree = field;
  if (w !== 1) tree = {op: 'mul', args: [tree, w]};
  if (st !== 0) tree = {op: 'add', args: [tree, st]};
  // The wrap-round switch belongs to the outermost step, whichever that turned out to be.
  if (mod && tree !== null && typeof tree === 'object') tree = {...tree, mod: true};
  return tree;
}

// The band between two thumbs, painted with the part of the wheel it covers. The
// formula can say more than the wheel has (a start of 2.4, a width of 3); the band
// stops at the ends of the axis, 0 and 2, and the formula is left as typed.
function paintBand(band, from, to) {
  const lo = clampAxis(Math.min(from, to)), hi = clampAxis(Math.max(from, to));
  const frac = Math.max((hi - lo) / AXIS, 0.002);
  band.style.left = `${lo / AXIS * 100}%`;
  band.style.width = `${frac * 100}%`;
  band.firstChild.style.width = `${100 / frac}%`;
  band.firstChild.style.left = `${-(lo / AXIS) / frac * 100}%`;
}

// The wheel with one thumb for a fixed hue, or two for the range a field is
// squeezed into. `onInput` says what to show while dragging, `onCommit` is
// what to save when a thumb is let go.
function hueBar(start, end, single, onInput, onCommit) {
  const bar = document.createElement('div');
  bar.className = 'hue-bar' + (single ? '' : ' wide');

  const wheel = document.createElement('div');
  wheel.className = 'wheel';
  const band = document.createElement('div');
  band.className = 'band';
  band.append(document.createElement('div'));
  bar.append(wheel, band);

  const thumb = (cls, value) => {
    const r = document.createElement('input');
    r.className = cls;
    r.type = 'range';
    r.min = '0';
    r.max = String(AXIS);
    r.step = '0.01';
    r.value = String(clampAxis(value));
    return r;
  };
  const a = thumb('start', start), b = thumb('end', end);
  // A fixed hue has one thumb. The other is hidden rather than disabled: it sits
  // exactly on the first and a disabled one still swallows the drag.
  if (single) { b.disabled = true; b.style.display = 'none'; }
  bar.append(a, b);

  const read = () => [parseFloat(a.value), parseFloat(single ? a.value : b.value)];
  const show = (s0, e0) => { paintBand(band, s0, e0); onInput(s0, e0); };

  // The first time it says what it was handed, not where the thumbs ended up: they
  // can only sit on a hundredth, and a hue of 0.615 is not 0.62.
  show(start, end);

  a.oninput = b.oninput = () => show(...read());
  a.onchange = b.onchange = () => onCommit(...read());

  // Typing a hue moves the one thumb, and keeps what was typed rather than the
  // hundredth the thumb rounds it to.
  bar.setHue = (v) => {
    const x = clampAxis(v);
    a.value = String(x);
    show(x, x);
    onCommit(x, x);
  };
  return bar;
}

// ---- formulas --------------------------------------------------------------
// A slot can hold a tree: an operation over two operands, each a number, a field
// or another operation. An edit that leaves an operand empty is held here until
// every one is filled, since the rig will not take half a formula.
let editing = {};                       // "effect.slot" -> a formula with an empty operand
const formulaOpen = new Set();          // slots showing the formula editor

const at = (tree, path) => path.reduce((n, step) => n[step], tree);
const isLeaf = (n) => n === null || typeof n !== 'object';
const complete = (n) => n === null ? false : isLeaf(n) ? true : n.args.every(complete);

function replace(tree, path, value) {
  if (path.length === 0) return value;
  const [step, ...rest] = path;
  const inner = replace(tree[step], rest, value);

  // An operation's operands are a list, and spreading a list into an object
  // makes it one - so the two halves of a path step are rebuilt in kind.
  if (Array.isArray(tree)) return tree.map((n, i) => (i === step ? inner : n));
  return {...tree, [step]: inner};
}

// Hue slots opened as a formula read (field x squeeze) + start in full. Once a
// section has been taken out by hand the formula is shown as it is, so the section
// stays gone instead of coming back at 1 and 0.
const trimmed = new Set();

// Take the editor away, and whatever half-built formula it was holding.
function leaveFormula(key) {
  delete editing[key];
  formulaOpen.delete(key);
  trimmed.delete(key);
}

function setFormula(key, tree) {
  trimmed.add(key);                     // edited by hand: show it as it is from here on
  if (isLeaf(tree)) {            // down to one operand: no longer a formula
    leaveFormula(key);
    if (tree === null) drawEffects(); else writeSlot(key, tree);
    return;
  }

  editing[key] = tree;
  if (complete(tree)) { delete editing[key]; writeSlot(key, tree); }
  else drawEffects();
}

// ---- the expression as text ------------------------------------------------

// The same text as the mobile page: on screen the operators are the ones a sum is
// written with; typed, they are the ones a keyboard has.
const TEXT_OPS = {add: '+', sub: '-', mul: '*', div: '/', avg: '~'};
const FROM_TEXT = Object.fromEntries(Object.entries(TEXT_OPS).map(([k, v]) => [v, k]));

const texting = new Set();              // slots whose formula is being typed

// Brackets on every operator but the outermost, so what comes out reads back in
// as the same tree whatever precedence says.
function toText(node, nested = false) {
  if (node === null || node === undefined) return '';
  if (typeof node === 'number') return String(node);
  if (typeof node === 'string') return node;

  // Anything but a binary operator is a call: `select(a, b, c)`. Its brackets
  // are its own, so an operation inside one needs none.
  const shown = infix(node, TEXT_OPS)
      ? `${toText(node.args[0], true)} ${TEXT_OPS[node.op]} ${toText(node.args[1], true)}`
      : `${node.op}(${node.args.map(a => toText(a)).join(', ')})`;
  // A % in front of the bracket wraps the result round instead of holding it to 0-1.
  if (node.mod) return `%(${shown})`;
  return nested && infix(node, TEXT_OPS) ? `(${shown})` : shown;
}

function tokens(text) {
  const grab = /\s*([(),%]|[+\-*/~]|[A-Za-z_][\w.]*|\d*\.?\d+)/y;
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
// typing expects * to bind tighter than +, so that is what is read here.
function parseText(text) {
  const t = tokens(text.trim());
  const names = new Set(rig.fields.map(f => f.name));
  let i = 0;

  const operand = () => {
    const tok = t[i++];
    if (tok === undefined) throw new Error('the expression stops short');

    if (tok === '(' || tok === '%') {
      if (tok === '%' && t[i++] !== '(') throw new Error('a % goes in front of a ( ... )');
      const inner = sum();
      if (t[i++] !== ')') throw new Error('a ( with no )');
      if (tok === '%') {
        if (isLeaf(inner)) throw new Error('a % needs an operation in its brackets');
        return {...inner, mod: true};
      }
      return inner;
    }
    if (tok === ')') throw new Error('a ) with no (');
    if (tok === ',') throw new Error('a , outside an operation');
    if (FROM_TEXT[tok]) throw new Error(`"${tok}" needs something in front of it`);
    if (/^[\d.]/.test(tok)) return parseFloat(tok);

    // `select(x, y, z)`: a name followed by a ( is an operator, not a field, so
    // it is checked against the operators. The only way to write an operation
    // of any number of operands but two, since there is no glyph for three.
    if (t[i] === '(') {
      if (!rig.operators.some(o => o.name === tok)) throw new Error(`no operator called "${tok}"`);
      i++;
      const args = [sum()];
      while (t[i] === ',') { i++; args.push(sum()); }
      if (t[i++] !== ')') throw new Error(`"${tok}(" with no )`);
      return {op: tok, args};
    }

    if (!names.has(tok)) throw new Error(`no field called "${tok}"`);
    return tok;
  };

  const binary = (ops, next) => () => {
    let left = next();
    while (ops.includes(t[i])) left = {op: FROM_TEXT[t[i++]], args: [left, next()]};
    return left;
  };

  const sum = binary(['+', '-', '~'], binary(['*', '/'], operand));
  const tree = sum();
  if (i < t.length) throw new Error(`"${t[i]}" is one too many`);
  return tree;
}

// Brackets coloured by how deep they are; one beyond the last colour wraps round.
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

// A textarea with its own text made invisible, over a pre holding the same text
// with the brackets coloured. The two have to be laid out identically or the
// caret drifts off the letters.
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
    if (!area.value.trim()) {
      texting.delete(key);
      leaveFormula(key);
      writeSlot(key, null);
      return;
    }

    let parsed;
    try { parsed = parseText(area.value); }
    catch (e) { bad.textContent = e.message; return; }

    texting.delete(key);
    if (!isLeaf(parsed)) formulaOpen.add(key);
    setFormula(key, parsed);
  };

  area.oninput = () => { paint(); bad.textContent = ''; };
  area.onkeydown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); apply(); }
    if (e.key === 'Escape') { texting.delete(key); drawEffects(); }
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

// The faders a value slot can be put on, in the order they are offered.
const FADERS = ['fader_a', 'fader_b', 'fader_c', 'fader_d', 'fader_e', 'fader_f', 'fader_g', 'fader_h'];

// The slot called `value` is the brightness - not hue, sat, or an effect's own
// parameter.
const isValueSlot = (key) => key.split('.').slice(1).join('.') === 'value';

// A value slot taken apart: the fader it is multiplied by as the outermost step
// (null for none) and the rest of the expression (null when the fader is all).
function splitFader(tree) {
  if (typeof tree === 'string' && FADERS.includes(tree)) return {fader: tree, inner: null};
  if (tree !== null && typeof tree === 'object' && tree.op === 'mul' && tree.args.length === 2) {
    const [a, b] = tree.args;
    if (FADERS.includes(a)) return {fader: a, inner: b};
    if (FADERS.includes(b)) return {fader: b, inner: a};
  }
  return {fader: null, inner: tree};
}

// ... and put back together.
const withFader = (inner, fader) =>
    fader === null || fader === undefined ? inner
    : inner === null || inner === undefined ? fader
    : {op: 'mul', args: [inner, fader]};

// A small constant | field switch, the same idea as a slot's own.
function makeSeg(mode, parts, small) {
  const seg = document.createElement('span');
  seg.className = 'seg' + (small ? ' small' : '');
  for (const {label, id, title, onclick} of parts) {
    const b = document.createElement('button');
    b.className = [].concat(mode).includes(id) ? 'on' : '';
    b.dataset.id = id;
    b.textContent = label;
    b.title = title;
    if (onclick) b.onclick = onclick; else b.disabled = true;
    seg.append(b);
  }
  return seg;
}

// ---- moving parts of a formula ---------------------------------------------
// A part is a whole subtree: an operand, or an operation with everything under
// it. Drag one onto another operand of the same formula and the two trade
// places, so nothing is lost and a part can be moved to the other side of an
// operation. Moving a part to another slot is not here.
let dragging = null;                    // {from: {key, path, tree}}
let overEl = null;

const startsWith = (path, prefix) => prefix.every((step, i) => path[i] === step);

function setOver(el) {
  if (overEl === el) return;
  overEl?.classList.remove('over');
  overEl = el;
  el.classList.add('over');
}
const clearOver = () => { overEl?.classList.remove('over'); overEl = null; };

// Whether a part can be put down here: in the same formula, and not onto itself,
// inside itself, or onto a part that holds it (there would be no room for what
// was there).
function canTrade(from, to) {
  return from.key === to.key
      && !startsWith(to.path, from.path)
      && !startsWith(from.path, to.path);
}

function moveSegment(from, to) {
  if (!canTrade(from, to)) return;
  const part = at(from.tree, from.path);
  const there = at(from.tree, to.path);
  setFormula(to.key, replace(replace(from.tree, from.path, there), to.path, part));
}

// Picking a part up, whichever way it was grabbed.
function beginDrag(e, box, from) {
  dragging = {from};
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', 'part of a formula');
  e.dataTransfer.setDragImage(box, 8, 8);
  box.classList.add('lifted');
}

function endDrag(box) {
  dragging = null;
  box.classList.remove('lifted');
  box.draggable = false;
  clearOver();
  drawEffects();
}

// The handle on a part. A whole operation can also be grabbed by its box - see
// boxDrag - so this is how you pick up a single operand, or an operation by its
// corner.
function grip(box, from) {
  const g = document.createElement('span');
  g.className = 'grip';
  g.textContent = '\u283f';
  g.draggable = true;
  g.title = 'drag this part onto another operand to trade places';
  g.ondragstart = (e) => { e.stopPropagation(); beginDrag(e, box, from); };
  g.ondragend = (e) => { e.stopPropagation(); endDrag(box); };
  return g;
}

// A whole operation, by its box: anywhere on it that is not a control. The
// innermost box under the pointer is the one that moves. The outermost box is the
// whole formula, which has nowhere to go, so it is not picked up.
function boxDrag(box, from) {
  if (!from.path.length) return;
  box.onmousedown = (e) => {
    e.stopPropagation();
    box.draggable = !e.target.closest('input, button, select, textarea');
  };
  box.onmouseup = () => { box.draggable = false; };
  box.ondragstart = (e) => {
    if (e.target !== box) return;                // a grip or chip inside has its own
    e.stopPropagation();
    beginDrag(e, box, from);
  };
  box.ondragend = (e) => { if (e.target === box) endDrag(box); };
}

function dropTarget(el, to) {
  el.ondragover = (e) => {
    if (!dragging || !canTrade(dragging.from, to)) return;
    e.preventDefault();
    e.stopPropagation();                        // the innermost one under the pointer wins
    setOver(el);
  };
  el.ondrop = (e) => {
    if (!dragging || !canTrade(dragging.from, to)) return;
    e.preventDefault();
    e.stopPropagation();
    const carried = dragging;
    dragging = null;
    clearOver();
    moveSegment(carried.from, to);
  };
}

// A constant that was swapped for a field, by where it was in the formula, so
// switching that operand back to a constant puts the number back and not the
// default.
const swappedOut = new Map();

function leafEditor(key, tree, path) {
  const node = at(tree, path);
  const row = document.createElement('div');
  row.className = 'leaf fpick';
  const spot = `${key}|${path.join('.')}`;

  const toggle = fieldMenu(row, typeof node === 'string' ? node : null, (v) => {
    if (typeof node === 'number') swappedOut.set(spot, node);
    setFormula(key, replace(tree, path, v));
  });
  const mode = typeof node === 'number' ? 'value' : typeof node === 'string' ? 'field' : null;

  dropTarget(row, {key, path, tree});
  if (path.length && node !== null) row.append(grip(row, {key, path, tree}));

  row.append(makeSeg(mode, [
    {label: 'constant', id: 'value', title: 'a plain number',
     onclick: () => {
       if (mode === 'value') return;
       const back = swappedOut.get(spot) ?? DEFAULT_CONSTANT;
       swappedOut.delete(spot);
       setFormula(key, replace(tree, path, back));
     }},
    {label: 'field', id: 'field', title: 'follow a field', onclick: toggle},
  ], true));

  if (typeof node === 'number') {
    row.append(constantControl(node, (v) => setFormula(key, replace(tree, path, v))));
  } else if (typeof node === 'string') {
    const chip = document.createElement('button');
    chip.className = 'chip';
    chip.textContent = `${node} \u25be`;
    chip.onclick = toggle;
    row.append(chip);
  } else {
    const note = document.createElement('span');
    note.className = 'dim';
    note.textContent = node === null ? 'choose one' : describe(node);
    row.append(note);
  }

  // Whatever is here becomes the first operand, so this doubles as "wrap what I have".
  if (node !== null) {
    const wrap = document.createElement('button');
    wrap.className = 'wrap';
    wrap.textContent = '+';
    wrap.title = 'add a term next to this value: it and the new term become one operation (to add a term around a whole operation, use + outer on its box)';
    wrap.onclick = () => setFormula(key, replace(tree, path, {op: 'mul', args: [node, null]}));
    row.append(wrap);
  }
  return row;
}

// ---- what a formula says, in words --------------------------------------------
// A plain reading of the arithmetic, built from its shape and the names in it. It
// does not know what a field does beyond its name, so a rotary is just "rotary".
const MASKS = {v_edges: 'the vertical edges', h_edges: 'the horizontal edges',
               d1_edges: 'the first diagonal edges', d2_edges: 'the second diagonal edges'};

const isNum = (n) => typeof n === 'number';
const isMask = (n) => typeof n === 'string' && n in MASKS;
const pct = (k) => `${Math.round(k * 100)}%`;

// A leaf as a phrase, or an operation in brackets so it can sit inside another.
function operand(n) {
  if (n === null || n === undefined) return '(empty)';
  if (isNum(n)) return fmt(n);
  if (typeof n === 'string') return n;
  return `(${explain(n)})`;
}

function explain(n) {
  if (n === null || n === undefined) return 'nothing yet';
  if (isNum(n)) return `the constant ${fmt(n)}`;
  if (typeof n === 'string') return n;

  const {op, args} = n;
  const [a, b] = args;
  const two = args.length === 2;
  const inverse = (x) => x && typeof x === 'object' && x.op === 'sub'
      && x.args.length === 2 && x.args[0] === 1 ? x.args[1] : null;

  // The arithmetic below is only about two operands; an operation that somehow
  // holds another number falls through to the general reading.
  if (!two && ['mul', 'add', 'sub', 'div'].includes(op)) return describe(n);
  const list = args.map(operand).join(', ');
  if (op === 'select') return `one of ${list}, picked by the select knob`;
  if (op === 'cycle') return `${args.map(operand).join(' then ')}, each for a turn on the clock`;
  if (op === 'randomize') return `one of ${list}, picked at random on every pad press`;
  if (op === 'prob_zap') return `${operand(a)} sets how often an end flashes`;
  if (/^gradient_\d+_[hs]$/.test(op))
    return `gradient ${op.split('_')[1]} read at ${operand(a)}, ${op.endsWith('_h') ? 'for hue' : 'for saturation'}`;

  if (op === 'mul') {
    for (const [x, y] of [[a, b], [b, a]]) {
      if (isMask(y)) return `${operand(x)}, only on ${MASKS[y]}`;
      if (isNum(y) && y === 0) return 'always 0';
      if (isNum(y) && y > 0 && y < 1) return `${operand(x)} at ${pct(y)} strength`;
      if (isNum(y) && y > 1) return `${operand(x)} boosted ${fmt(y)} times`;
      if (isNum(y) && y < 0) return `${operand(x)} flipped and scaled by ${fmt(-y)}`;
      if (inverse(y) !== null) return `${operand(x)}, fading out as ${operand(inverse(y))} rises`;
    }
    return `${operand(a)} scaled by ${operand(b)}`;
  }
  if (op === 'add') {
    for (const [x, y] of [[a, b], [b, a]])
      if (isNum(y)) return y >= 0 ? `${operand(x)}, lifted by ${fmt(y)}` : `${operand(x)}, lowered by ${fmt(-y)}`;
    return `${operand(a)} plus ${operand(b)}`;
  }
  if (op === 'sub') {
    if (a === 1) return `the opposite of ${operand(b)} (high where it is low)`;
    if (isNum(b)) return `${operand(a)}, lowered by ${fmt(b)}`;
    return `${operand(a)} minus ${operand(b)}`;
  }
  if (op === 'div') {
    if (isNum(b) && b !== 0) return `${operand(a)} divided by ${fmt(b)}`;
    return `${operand(a)} divided by ${operand(b)} (0 where that is 0)`;
  }
  if (op === 'avg') return two ? `halfway between ${operand(a)} and ${operand(b)}`
                               : `the average of ${list}`;
  return describe(n);
}

// A formula as text, with each level's brackets in the colour of its box in the
// editor, so the two can be matched up at a glance.
function groupedText(node, depth = 0) {
  const out = document.createElement('span');
  if (isLeaf(node)) { out.textContent = describe(node); return out; }

  const paren = (c) => {
    const p = document.createElement('span');
    p.className = `paren d${depth % DEPTHS}`;
    p.textContent = c;
    return p;
  };
  if (infix(node, OPS)) {
    out.append(paren('('), groupedText(node.args[0], depth + 1), ` ${OPS[node.op]} `,
               groupedText(node.args[1], depth + 1), paren(')'));
  } else {
    // A call: its name, then its operands between brackets of the box's colour.
    out.append(`${node.op}`, paren('('));
    node.args.forEach((arg, i) => {
      if (i) out.append(', ');
      out.append(groupedText(arg, depth + 1));
    });
    out.append(paren(')'));
  }
  if (node.mod) out.append(' mod 1');
  return out;
}

// Each level of a formula is a box of its own, coloured by how deep it is. There
// is no limit to how deep: any operand can be wrapped in another operation.
const DEPTHS = 4;

function nodeEditor(key, tree, path, depth = 0) {
  const node = at(tree, path);
  if (isLeaf(node)) return leafEditor(key, tree, path);

  const box = document.createElement('div');
  box.className = `node d${depth % DEPTHS}`;

  dropTarget(box, {key, path, tree});
  boxDrag(box, {key, path, tree});

  const head = document.createElement('div');
  head.className = 'ops fpick';       // fpick: the operator menu hangs off this row
  const arity = arityOf(node.op);
  if (path.length) head.append(grip(box, {key, path, tree}));
  for (const [name, glyph] of Object.entries(OPS)) {
    const b = document.createElement('button');
    b.className = name === node.op ? 'on' : '';
    b.textContent = glyph;
    b.title = name;
    b.onclick = () => setFormula(key, replace(tree, path, withOp(node, name)));
    head.append(b);
  }
  // The row has room for the operators a sum is written with. The rig has more,
  // and this is the way to them; when the operation is one of those, the button
  // says which, rather than leaving nothing lit.
  const glyphed = node.op in OPS;
  const more = document.createElement('button');
  more.className = glyphed ? '' : 'named on';
  more.textContent = glyphed ? '…' : node.op;
  more.title = glyphed ? 'every operator' : `${node.op} - pick another operator`;
  more.onclick = fieldMenu(head, node.op, (name) => setFormula(key, replace(tree, path, withOp(node, name))),
                           operatorSource);
  head.append(more);

  // Which side is which matters for - and the others read left to right. Reversed
  // rather than swapped, so it still means something with more than two.
  const flip = document.createElement('button');
  flip.className = 'flip';
  flip.textContent = '\u21c4';
  flip.title = 'turn the operands round';
  flip.onclick = () => setFormula(key, replace(tree, path, {...node, args: [...node.args].reverse()}));

  // The + on a single value pairs that value with another, which nests the new term
  // inside. This is its counterpart for a whole operation: the operation, with
  // everything in it, becomes the first half of a new one, so a term goes around
  // the outside - at the top of the formula, around the lot.
  const outer = document.createElement('button');
  outer.className = 'outer';
  outer.textContent = '+ outer';
  outer.title = 'add a term outside this whole operation: all of it becomes the first half of a new operation, and you choose the other half';
  outer.onclick = () => setFormula(key, replace(tree, path, {op: 'mul', args: [node, null]}));
  // Held to 0-1 by default; with this on, the result wraps round instead (1.1 is 0.1).
  const mod = document.createElement('button');
  mod.className = 'modsw' + (node.mod ? ' on' : '');
  mod.setAttribute('role', 'switch');
  mod.setAttribute('aria-checked', String(!!node.mod));
  const knob = document.createElement('span');
  knob.className = 'modknob';
  const word = document.createElement('span');
  word.textContent = 'mod';
  mod.append(knob, word);
  mod.title = node.mod ? 'mod is on: past 1 this wraps round (1.1 becomes 0.1). Click to clamp to 0-1 instead'
                       : 'mod is off: this is clamped to 0-1. Click to wrap round past 1 instead (1.1 becomes 0.1)';
  mod.onclick = () => {
    const {mod: was, ...rest} = node;
    setFormula(key, replace(tree, path, was ? rest : {...rest, mod: true}));
  };
  // An operator written with any number of operands can be given another. The
  // rest have the number they are written with, so there is nothing to add.
  const plus = document.createElement('button');
  plus.className = 'plus';
  plus.textContent = '+ operand';
  plus.title = 'another operand';
  plus.onclick = () => setFormula(key, replace(tree, path, {...node, args: [...node.args, null]}));

  head.append(...(arity === 'nary' ? [plus] : []), outer, mod, ...(node.args.length > 1 ? [flip] : []));

  const drop = document.createElement('button');
  drop.className = 'drop';
  drop.textContent = '\u00d7';
  drop.title = 'remove this operation and keep only its first operand';
  drop.onclick = () => setFormula(key, replace(tree, path, node.args[0]));
  head.append(drop);

  const kids = document.createElement('div');
  kids.className = 'kids';
  const operands = node.args.map((_, i) => nodeEditor(key, tree, [...path, 'args', i], depth + 1));

  if (arity === 'binary' && operands.length === 2) {
    kids.append(...operands);
  } else {
    // Anything else lists its operands in order, numbered, since position is all
    // that tells them apart - and for a select it is the number on the knob. A
    // binary operator that somehow holds another count also lands here, so that
    // nothing is left off the screen.
    operands.forEach((view, i) => {
      const line = document.createElement('div');
      line.className = 'operand';
      if (operands.length > 1) {
        const n = document.createElement('i');
        n.textContent = i;
        line.append(n);
      }
      line.append(view);

      // Down to one, because an operation with nothing in it is not one. The
      // others are written with the number they have, so none can be dropped.
      if (arity === 'nary' && operands.length > 1) {
        const cut = document.createElement('button');
        cut.className = 'cut';
        cut.textContent = '×';
        cut.title = `drop operand ${i}`;
        cut.onclick = () => setFormula(key, replace(tree, path,
            {...node, args: node.args.filter((_, which) => which !== i)}));
        line.append(cut);
      }
      kids.append(line);
    });
  }
  box.append(head, kids);
  return box;
}

// Which way a slot is driven: a number, a field, or a formula.
const modeOf = (tree) => typeof tree === 'string' ? 'field'
                       : tree === null || typeof tree === 'number' ? 'value' : 'formula';

// What the wheel says, as the formula it stands for: the field squeezed into a
// width, then moved to a start. Spelled out in full even when the width is 1
// and the start is 0, so the editor always shows the same three things.
const hueTree = (h) => ({op: 'add',
                         args: [{op: 'mul', args: [h.field, Math.round(h.width * 1000) / 1000]},
                                Math.round(h.start * 1000) / 1000],
                         ...(h.mod ? {mod: true} : {})});

// ---- turning a field's knobs ----------------------------------------------
// A field takes its values from knobs on the desk, and its slot can show them:
// a dial for each control one of its fields asks for. Drag a dial up and down
// to turn it - the preset that is playing takes it up as if a hand had - and it
// follows the desk when the knob is turned there. Both go over /ws/knobs, which
// sends every cc ten times a second and takes {cc, value} to move one.
let controls = [];          // every knob and pad the instrument watches
let knobs = {};             // every cc as the socket last said
let wire = null;            // the socket, for sending a turn back the other way
let turning = null;         // {cc, value} while a dial is being dragged
let mapping = null;         // {name, since}: a control waiting for a knob to be turned at it

// The fields a formula names, however deep.
const fieldsIn = (n) => typeof n === 'string' ? [n]
    : n !== null && typeof n === 'object' ? n.args.flatMap(fieldsIn)
    : [];

// The operators a formula names, however deep. An operator can own knobs of its
// own - a select has the one that picks - so what is behind a formula is not only
// what its fields own.
const opsIn = (n) => n !== null && typeof n === 'object'
    ? [n.op, ...n.args.flatMap(opsIn)] : [];

// A turned copy of a rotary (rotary180, v_rotary90...) is the same rotation
// seen from elsewhere and shares its knobs, which are named for the original.
const knobOwner = (name) => name.replace(/^((?:v_)?rotary)\d+$/, '$1');

// The knobs behind a formula: a control's comment is `owner.role`, so it belongs
// to whatever is in front of the dot (see docs/CONTROLS.md).
//
// A field owns exactly the controls named after it. Several fields are named
// after another with something on the end - `random_lines` is not a kind of
// `random` - and matching loosely would hand each the other's knobs.
//
// An operator takes any control whose owner it carries as a prefix, because
// several share one that is named after none of them: `gradient_1_h` and
// `gradient_1_s` both ask for `gradient_1.select`. No operator is named after
// another field or operator plus a suffix, so nothing is swept up that way.
const controlsFor = (tree) => {
  const fields = fieldsIn(tree).map(knobOwner);
  const ops = opsIn(tree);

  return controls.filter(c => c.kind === 'cc' && !c.hidden && c.comments.some((t) => {
    const owner = t.split('.')[0];
    return fields.includes(owner) || ops.some(o => o === owner || o.startsWith(owner + '_'));
  }));
};

// The controls an effect owns itself, as against the ones behind whatever is patched
// into its slots. A comment is `owner.role` and the owner can be an effect - whichever
// asked the box for the knob. These shape how the effect draws rather than what
// drives it (a zap's length, the ambient light's target), so they belong to the
// effect and not to any slot's formula. Exact, like a field: `bg_waves` takes
// `bg_waves.*` and not `bg_waves2.*`. docs/CONTROLS.md has the rest.
const controlsOwnedBy = (name) => controls.filter(
    c => c.kind === 'cc' && !c.hidden && c.comments.some(t => t.split('.')[0] === name));

// The effects that are drawing in a patch: in its chain, and not muted. A muted
// effect is silent, so what it owns is not in play.
const drawingEffects = (live) => chain(live).filter(n => !(live.muted ?? []).includes(n));

const CC_MAX = 127;
const DRAG_PER_PX = 0.8;            // a touch over 150px for the whole range
const clampCC = (v) => Math.max(0, Math.min(CC_MAX, v));
const liveValue = (c) => knobs[c.number]?.value ?? c.value;

// What a CC number is for, so its legend can say "bowtie" or "100 ms" rather
// than 0-127. /rig says, per control name, what sort of control it is: a sweep,
// a hue, or a list of named options. A knob two controls share may be described
// by only one of them, so a described one wins; a stray knob is a plain 0-127.
const PLAIN = {kind: 'float_range', start: 0, end: 127, unit: null};
const isPlain = (m) => m.kind === 'float_range' && !m.unit && m.start === 0 && m.end === 127;
// A gradient control lists no options of its own: what it can be on is whichever
// gradients exist right now - the declared ones, and the playing preset's own - at
// the position each is written down at. Given as items, it is then a list like any
// other, and is stepped through and read out the same way.
const withGradientItems = (m) => m.kind !== 'gradient' ? m
    : {...m, items: Object.fromEntries(allGradients().map(g => [g.position, g.name]))};
const metaFor = (name) => withGradientItems(rig?.control_meta?.[name] ?? PLAIN);
const metaOf = (names) => names.map(metaFor).find(m => !isPlain(m)) ?? PLAIN;
const metaOn = (cc) => metaOf(controls.filter(c => c.kind === 'cc' && c.number === Number(cc))
                                      .flatMap(c => c.comments));

// A gradient and a custom list are chosen from rather than swept, so these are
// the only places a drag is allowed to stop. Empty means it sweeps.
const DISCRETE = ['custom', 'gradient'];
const isDiscrete = (meta) => DISCRETE.includes(meta.kind);
const optionsOf = (meta) => DISCRETE.includes(meta.kind)
    ? Object.keys(meta.items ?? {}).map(Number).sort((a, b) => a - b)
    : [];

// The wire carries 0-127 whatever the list holds, and a field clamps, so the
// nearest option is what it will actually act on.
const nearestAt = (options, value) => options.reduce(
    (best, k, i) => Math.abs(k - value) < Math.abs(options[best] - value) ? i : best, 0);

// Where a value sits in its own range, 0-1, which is what a dial draws.
function fracOf(meta, value) {
  const options = optionsOf(meta);
  if (options.length)
    return options.length < 2 ? 0 : nearestAt(options, value) / (options.length - 1);
  return Math.max(0, Math.min(1, value / CC_MAX));
}

// What to print for a value: the option's name, or the knob read in its own range.
function readOut(meta, value) {
  const options = optionsOf(meta);
  // A gradient is exactly the one written down at the position, or none: the
  // knob is not read as the nearest of them.
  if (meta.kind === 'gradient') return meta.items[value] ?? 'no gradient';
  if (options.length) return meta.items[options[nearestAt(options, value)]];

  // The same curve FloatRange.at() uses on the other side.
  const at = meta.geometric
      ? meta.start * (meta.end / meta.start) ** (value / CC_MAX)
      : meta.start + (meta.end - meta.start) * (value / CC_MAX);
  const shown = Math.abs(at) >= 10 ? String(Math.round(at))
                                   : (Number.isInteger(at) ? String(at) : at.toFixed(2));
  return meta.unit ? `${shown} ${meta.unit}` : shown;
}

// Where a drag lands: the next option along for a list, anywhere for a sweep.
const PER_STEP_PX = 24;             // a thumb's worth of travel per option
function dragTo(meta, from, dy) {
  const options = optionsOf(meta);
  if (!options.length && isDiscrete(meta)) return from;          // nothing to step to
  if (!options.length) return clampCC(Math.round(from + dy * DRAG_PER_PX));
  const at = nearestAt(options, from) + Math.round(dy / PER_STEP_PX);
  return options[Math.max(0, Math.min(options.length - 1, at))];
}

// A rev counter: three quarters of a turn with the gap at the bottom.
const DIAL_FROM = Math.PI * 0.75, DIAL_SWEEP = Math.PI * 1.5, DIAL_R = 15;
const dialAt = (r, a) => [20 + r * Math.cos(a), 20 + r * Math.sin(a)];

function arc(from, to) {
  const [x0, y0] = dialAt(DIAL_R, from), [x1, y1] = dialAt(DIAL_R, to);
  const big = to - from > Math.PI ? 1 : 0;
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${DIAL_R} ${DIAL_R} 0 ${big} 1 ` +
         `${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

function makeDial(value, meta = PLAIN) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 40 40');
  svg.setAttribute('class', 'dial');

  const track = document.createElementNS(ns, 'path');
  track.setAttribute('class', 'track');
  track.setAttribute('d', arc(DIAL_FROM, DIAL_FROM + DIAL_SWEEP));
  const fill = document.createElementNS(ns, 'path');
  fill.setAttribute('class', 'fill');
  const pin = document.createElementNS(ns, 'line');
  pin.setAttribute('class', 'pin');
  svg.append(track, fill, pin);

  setDial(svg, value, meta);
  return svg;
}

function setDial(svg, value, meta = PLAIN) {
  const frac = fracOf(meta, value);
  const a = DIAL_FROM + DIAL_SWEEP * frac;
  svg.querySelector('.fill').setAttribute('d', frac > 0.002 ? arc(DIAL_FROM, a) : '');

  const [x1, y1] = dialAt(5, a), [x2, y2] = dialAt(13, a);
  const pin = svg.querySelector('.pin');
  pin.setAttribute('x1', x1.toFixed(2)); pin.setAttribute('y1', y1.toFixed(2));
  pin.setAttribute('x2', x2.toFixed(2)); pin.setAttribute('y2', y2.toFixed(2));
}

// Turn a knob from here: it shows at once, and goes out over the socket.
function turnKnob(cc, value) {
  turning = {cc, value};
  if (knobs[cc]) knobs[cc].value = value;
  if (wire && wire.readyState === WebSocket.OPEN) wire.send(JSON.stringify({cc: Number(cc), value}));
}

function knobList(found, compact = false) {
  const box = document.createElement('div');
  box.className = compact ? 'knobs mini' : 'knobs';

  for (const c of found) {
    const name = c.comments[0] ?? `cc ${c.number}`;

    const row = document.createElement('div');
    row.className = 'knob';
    row.dataset.cc = c.number;
    row.dataset.name = c.comments[0];
    row.title = `drag up and down to turn, tap to put ${c.comments[0]} on another knob`;

    const label = document.createElement('b');
    label.textContent = name;
    const meta = metaOf(c.comments);
    const now = document.createElement('span');
    now.className = 'now';
    now.textContent = readOut(meta, liveValue(c));
    const at = document.createElement('span');
    at.className = 'at';
    at.dataset.was = `cc ${c.number}${c.number === c.default ? '' : ' \u00b7 moved'}`;
    // The raw 0-127 the knob sits at, to type over: it lands the same as a turn.
    const typed = document.createElement('input');
    typed.type = 'number';
    typed.className = 'cc-box';
    typed.min = '0'; typed.max = String(CC_MAX); typed.step = '1';
    typed.value = liveValue(c);
    typed.title = 'type a value, 0-127';
    // Only a continuous control can be put anywhere in 0-127. One that picks from a
    // list has places that mean something and places that do not.
    typed.hidden = isDiscrete(meta);
    typed.onchange = () => {
      const want = Math.max(0, Math.min(CC_MAX, Math.round(Number(typed.value))));
      if (Number.isNaN(want) || typed.value === '') { typed.value = liveValue(c); return; }
      typed.value = want;
      turnKnob(c.number, want);
      setDial(row.querySelector('.dial'), want, meta);
      now.textContent = readOut(meta, want);
      setTimeout(() => { if (turning?.cc === c.number) turning = null; }, 300);
    };
    typed.onkeydown = (e) => { if (e.key === 'Enter') typed.blur(); };
    row.append(makeDial(liveValue(c), meta), label, now, typed, at);

    // A gradient is chosen by looking at it, not by turning to a number: the
    // preview and its menu go where the bare name would, and the name is theirs.
    if (meta.kind === 'gradient') {
      now.hidden = true;
      row.insertBefore(gradientPicker(c.number, (position) => {
        turnKnob(c.number, position);
        setDial(row.querySelector('.dial'), position, meta);
        syncGradientPickers();
        typed.value = position;
        setTimeout(() => { if (turning?.cc === c.number) turning = null; }, 300);
      }), typed);
    }

    let from = null;
    row.onpointerdown = (e) => {
      if (e.target === typed || e.target.closest('.gpickwrap')) return;   // typing and picking are not drags
      from = {y: e.clientY, value: liveValue(c), turned: false};
      row.setPointerCapture(e.pointerId);
      e.preventDefault();
    };
    row.onpointermove = (e) => {
      if (from === null) return;
      const want = dragTo(meta, from.value, from.y - e.clientY);
      if (want === liveValue(c)) return;
      from.turned = true;
      turnKnob(c.number, want);
      setDial(row.querySelector('.dial'), want, meta);
      now.textContent = readOut(meta, want);
      syncGradientPickers();
    };
    // A frame already on its way may still carry the value from before the last
    // turn, so the dial is left to the drag for a moment after letting go.
    const done = () => {
      from = null;
      setTimeout(() => { if (turning?.cc === c.number) turning = null; }, 300);
    };
    row.onpointerup = (e) => {
      if (e.target === typed) return;
      const tapped = from !== null && !from.turned;
      done();

      // A tap that went nowhere is the assign gesture: the next knob moved
      // at the desk is the one this control listens to. Tapping again lets go.
      if (!tapped) return;
      const name = c.comments[0];
      mapping = mapping?.name === name ? null : {name, since: Date.now()};
      paintWaiting();
    };
    row.onpointercancel = done;

    box.append(row);
  }
  paintWaiting(box);
  return box;
}

// Whichever control is waiting says so; the rest show where they are.
function paintWaiting(within = document) {
  for (const el of within.querySelectorAll('.knob')) {
    const waiting = mapping !== null && el.dataset.name === mapping.name;
    el.classList.toggle('waiting', waiting);
    const at = el.querySelector('.at');
    at.textContent = waiting ? 'turn a knob\u2026' : at.dataset.was;
  }
}

// The first knob moved since the asking is the one: the whole patch goes back
// with the control pointed at it, the same write the touch layout makes.
async function assign(name, cc) {
  mapping = null;
  paintWaiting();

  const n = rig.selected;
  if (n === null) return;

  const fresh = await get(`/presets/${n}`);
  remember(n, fresh.live);
  const r = await put(`/presets/${n}`,
                      {...fresh.live, cc_map: {...fresh.live.cc_map, [name]: Number(cc)}});
  if (!r.ok) { alert((await r.json()).detail); return; }
  await refresh();
}

// Whichever knob moved most recently.
function lastMoved() {
  let best = null;
  for (const [cc, knob] of Object.entries(knobs))
    if (best === null || knob.age_ms < best.knob.age_ms) best = {cc, knob};
  return best;
}

// Frames can come faster than the screen draws; the page paints the newest once a frame.
let knobsQueued = false;
function paintKnobs() {
  if (knobsQueued) return;
  knobsQueued = true;
  requestAnimationFrame(() => {
    knobsQueued = false;
    syncKnobs();
    syncGradientPickers();
    syncMapKnobs();
  });
}

// After a frame from the socket: every dial on the page follows the desk.
function syncKnobs() {
  for (const el of document.querySelectorAll('#effects .knob')) {
    const k = knobs[el.dataset.cc];
    if (!k) continue;
    const meta = metaOn(el.dataset.cc);
    setDial(el.querySelector('.dial'), k.value, meta);
    el.querySelector('.now').textContent = readOut(meta, k.value);
    const box = el.querySelector('.cc-box');
    if (box && document.activeElement !== box) box.value = k.value;
  }
}

// Pushed, not polled: the knobs move continuously.
function listen() {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  wire = new WebSocket(`${scheme}://${location.host}/ws/knobs`);

  wire.onmessage = (e) => {
    knobs = JSON.parse(e.data);
    if (turning && knobs[turning.cc]) knobs[turning.cc].value = turning.value;
    paintKnobs();

    const moved = mapping && lastMoved();
    if (moved && moved.knob.age_ms < Date.now() - mapping.since) assign(mapping.name, moved.cc);
  };
  wire.onclose = () => setTimeout(listen, 1000);      // the app restarts; so do we
}

listen();

function slotRow(key, saved) {
  // A formula half-built in the editor is what is on show, not what is saved.
  const {fader, inner} = isValueSlot(key) ? splitFader(saved) : {fader: null, inner: saved};
  let tree = key in editing ? editing[key] : inner;

  // A hue slot in a shape the wheel can show gets the wheel, and keeps it while
  // the formula editor is open below, for as long as the formula stays valid. An
  // empty one is a fixed hue of 0, like any other empty slot.
  const hue = isHueSlot(key) ? parseHue(tree ?? 0) : null;

  // The wheel can also speak for a source that is a formula (see parseHue). There
  // is no single field to name then, and the formula is always on show.
  const compound = hue !== null && hue.field !== null && typeof hue.field !== 'string';

  // The editor is open for a half-built formula, or for one that is saved. A slot
  // that has since turned back into a plain number or field - reverted, or changed
  // from the desk - has nothing to edit, so it is not open any more.
  const open = key in editing || compound ||
      (formulaOpen.has(key) && (hue ? hue.field !== null : !isLeaf(tree)));

  // The formula of a hue that has a field in it reads (field x squeeze) + start.
  const shown = hue && hue.field !== null && !(key in editing) && !trimmed.has(key) ? hueTree(hue) : tree;

  const mode = hue ? (hue.field === null ? 'value' : compound ? 'formula' : 'field') : open ? 'formula' : modeOf(tree);
  if (mode === 'value') lastValue[key] = hue ? hue.start : (tree ?? 0);

  const row = document.createElement('div');
  row.className = `slot mode-${mode}` + (tree === null ? ' empty' : '');

  const name = document.createElement('span');
  name.className = 'name';
  name.textContent = key.split('.').slice(1).join('.');

  // The control sits in a box of its own, so the field menu has something to
  // hang off.
  const ctl = document.createElement('div');
  ctl.className = 'ctl fpick';
  const toggle = fieldMenu(ctl, compound ? null : (hue?.field ?? tree), (v) => {
    if (compound && !confirm('Replace this formula with that field? The formula is lost.')) return;
    // A hue keeps its editor open across a new field; anything else is done with it.
    if (hue) delete editing[key]; else leaveFormula(key);
    writeSlot(key, !hue ? v : buildHue({field: v, start: hue.start, width: hue.field ? hue.width : 1, mod: hue.mod}));
  });

  const seg = makeSeg(open && hue ? [mode, 'formula'] : mode, [
    {label: 'constant', id: 'value', title: 'a plain number',
     onclick: () => {
       if (mode === 'value') return;
       leaveFormula(key);
       writeSlot(key, lastValue[key] ?? DEFAULT_CONSTANT);
     }},
    {label: 'field', id: 'field', title: 'follow a field', onclick: toggle},
    {label: '\u0192', id: 'formula',
     title: compound ? 'this hue is a formula' : open && hue ? 'close the formula' : 'combine fields and constants',
     onclick: () => {
       if (open) {
         // A hue the wheel can read can close it; any other formula has no way back.
         if (hue && !compound) { leaveFormula(key); drawEffects(); }
         return;
       }
       if (mode === 'formula') return;
       formulaOpen.add(key);
       if (hue && hue.field === null) {
         // A fixed hue becomes the start; the field is left to choose.
         editing[key] = {op: 'add', args: [{op: 'mul', args: [null, 1]}, hue.start]};
       } else if (!hue && isLeaf(tree)) {
         // A single operand becomes the first of two; the second is left to fill in.
         editing[key] = {op: 'mul', args: [tree ?? 0, null]};
       }
       drawEffects();
     }},
  ]);


  // A formula shows as arithmetic, with the editor under it when it is open. The
  // editor can be folded away, leaving only the arithmetic.
  const showsEditor = mode === 'formula' || (open && hue);
  let summary = null, editor = null, words = null;
  const hueWords = (h) => `${describe(h.field)} sweeps the hue from ${fmt(h.start)} to ${fmt(h.start + h.width)}`;
  if (showsEditor) {
    summary = document.createElement('span');
    summary.className = 'expr';
    summary.append(groupedText(shown));

    words = document.createElement('div');
    words.className = 'words';
    words.textContent = hue && hue.field !== null ? hueWords(hue) : explain(shown);

    editor = document.createElement('div');
    editor.className = 'tree';
    editor.hidden = folded.has(key);
    editor.append(nodeEditor(key, shown, []));
  }

  // The wheel for a range: two thumbs, with the formula following them.
  const addRangeBar = () => {
    const readout = document.createElement('span');
    readout.className = 'dim';
    ctl.append(readout);
    ctl.append(hueBar(hue.start, hue.start + hue.width, false,
        (s0, e0) => {
          readout.textContent = `${fmt(s0)} ${e0 >= s0 ? '\u2192' : '\u2190'} ${fmt(e0)}`;

          // The formula follows the thumbs as they move, not when they are let go.
          if (editor) {
            const range = {field: hue.field, start: s0, width: e0 - s0, mod: hue.mod};
            const t = trimmed.has(key) ? buildHue(range) : hueTree(range);
            summary.replaceChildren(groupedText(t));
            words.textContent = hueWords({field: hue.field, start: s0, width: e0 - s0});
            editor.replaceChildren(nodeEditor(key, t, []));
          }
        },
        (s0, e0) => writeSlot(key, buildHue({field: hue.field, start: s0, width: e0 - s0, mod: hue.mod}))));
  };

  if (mode === 'field') {
    const chip = document.createElement('button');
    chip.className = 'chip';
    chip.textContent = `${hue?.field ?? tree} \u25be`;
    chip.title = 'pick another field';
    chip.onclick = toggle;
    ctl.append(chip);

    if (hue) addRangeBar();
  } else if (compound) {
    addRangeBar();
  } else if (mode === 'value' && hue) {
    const box = document.createElement('input');
    box.className = 'num';
    box.type = 'text';
    box.inputMode = 'decimal';
    box.spellcheck = false;
    box.title = 'type a hue (0-2)';

    const bar = hueBar(hue.start, hue.start, true,
        (s0) => { if (document.activeElement !== box) box.value = fmt(s0); },
        (s0) => writeSlot(key, s0));
    box.onchange = () => {
      const v = parseFloat(box.value);
      if (Number.isFinite(v)) bar.setHue(v); else box.value = fmt(hue.start);
    };
    box.onkeydown = (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); box.blur(); } };
    box.onfocus = () => box.select();
    ctl.append(bar, box);
  } else if (mode === 'value') {
    ctl.append(constantControl(tree ?? 0, (v) => writeSlot(key, v)));
  }

  // The arithmetic, then the editor: always for a formula, and below the hue
  // slider when it opens one.
  if (showsEditor) {
    const line = document.createElement('div');
    line.className = 'formula-line';

    const fold = document.createElement('button');
    fold.className = 'fold';
    const mark = () => {
      fold.textContent = editor.hidden ? '\u25b8' : '\u25be';
      fold.title = editor.hidden ? 'show the editor' : 'show only the arithmetic';
    };
    mark();
    fold.onclick = () => {
      editor.hidden = !editor.hidden;
      if (editor.hidden) folded.add(key); else folded.delete(key);
      saveSet('v3.folded', folded);
      mark();
    };

    const lines = document.createElement('div');
    lines.className = 'lines';
    lines.append(summary, words);
    line.append(fold, lines);

    // A formula with an empty operand is held here and not sent to the rig.
    if (key in editing) {
      const note = document.createElement('span');
      note.className = 'unapplied';
      note.textContent = 'not applied yet';
      note.title = 'fill in every empty operand and it goes to the rig';
      line.append(note);
    }
    ctl.append(line, editor);
  }

  // Each slot is a box of its own: the name and how it is driven along the top,
  // and everything that belongs to it - the control, the formula, the words about
  // it - inside.
  const head = document.createElement('div');
  head.className = 'slot-head';
  head.append(name, seg);

  // Type the formula instead of building it. On a value slot the fader is not
  // part of the text, as it is not part of the editor.
  const pencil = document.createElement('button');
  pencil.className = 'pencil' + (texting.has(key) ? ' on' : '');
  pencil.textContent = '\u270e';
  pencil.title = texting.has(key) ? 'back to the editor' : 'type the formula';
  pencil.onclick = () => {
    if (texting.has(key)) texting.delete(key); else texting.add(key);
    drawEffects();
  };
  head.append(pencil);

  // A fader over the whole of a brightness slot, as the outermost step. It is
  // not drawn in the expression; it is chosen here, and only here.
  if (isValueSlot(key)) {
    const pick = document.createElement('select');
    pick.className = 'fade';
    pick.title = 'multiply the whole slot by a fader, as the outermost step';
    // A fader another slot already reads - another effect's brightness, or
    // anything else - is greyed out; this slot's own is not "elsewhere".
    const elsewhere = new Set();
    for (const [k, t] of Object.entries(views[rig.selected]?.live.slots ?? {})) {
      if (k === key) continue;
      fieldsIn(t).forEach(n => elsewhere.add(n));
    }
    for (const f of [null, ...FADERS]) {
      const o = document.createElement('option');
      if (f !== null && elsewhere.has(f)) {
        o.disabled = true;
        o.title = 'already used by another slot';
      }
      o.value = f ?? '';
      o.textContent = f ?? 'no fader';
      pick.append(o);
    }
    pick.value = fader ?? '';
    pick.onchange = () => writeSlot(key, inner, pick.value || null);
    head.append(pick);
  }

  row.append(head, ctl);
  if (texting.has(key)) {
    ctl.hidden = true;
    row.append(textEditor(key, shown));
  }

  // The fader is not in the expression, but it is still turned from here.
  const found = controlsFor(fader === null ? shown : withFader(shown, fader));
  if (found.length) row.append(knobList(found));
  return row;
}

// Which effects are open is a habit of the person looking, not part of the
// preset, so it is kept in the browser.
const store = {
  get() { try { return new Set(JSON.parse(localStorage.getItem('v3.expanded') ?? '[]')); }
          catch { return new Set(); } },
  put(set) { try { localStorage.setItem('v3.expanded', JSON.stringify([...set])); } catch {} },
};
const expanded = store.get();

// How wide the effects run is the same kind of habit: the left half, or the whole
// window. It is only a class on the layout, so nothing has to be drawn again.
const columns = document.querySelector('.cols');
const wideButton = document.getElementById('wide');
const widthStore = {
  get() { try { return localStorage.getItem('v3.wide') === '1'; } catch { return false; } },
  put(on) { try { localStorage.setItem('v3.wide', on ? '1' : '0'); } catch {} },
};

function setWide(on) {
  columns.classList.toggle('wide', on);
  wideButton.setAttribute('aria-pressed', String(on));
  wideButton.textContent = on ? 'half width' : 'full width';
  wideButton.title = on ? 'put the effects back in the left half'
                        : 'let the effects take the whole width of the window';
}

setWide(widthStore.get());
wideButton.onclick = () => {
  const on = !columns.classList.contains('wide');
  widthStore.put(on);
  setWide(on);
};

// A drag or a half-typed number lives in the page, and a redraw would take it away.
const inUse = () => document.activeElement?.closest?.('#effects') != null &&
                    document.activeElement.tagName === 'INPUT';

// ---- the effects ---------------------------------------------------------

const list = document.getElementById('effects');

// The effects a patch has in its chain, in the order they draw: the first is
// painted first, so the last paints over the rest. An effect that is not in
// the chain is not shown - it is what the plus offers.
//
// A patch with no `active` list says nothing about it. One with slots was
// written before effects could be switched off, so everything it wires is on;
// one with none is a preset nobody has written, and has no effects.
//
// An `active` list is also the order they are drawn in, one on top of the next, so
// it is the order shown. Without one they are in the order the rig declares them.
function chain(patch) {
  if (patch.active !== null) return patch.active.filter(n => n in rig.effects);

  const wired = new Set(Object.keys(patch.slots).map(k => k.split('.')[0]));
  return Object.keys(rig.effects).filter(n => wired.has(n));
}

// Reordering: the cards are drawn in this order, so moving one is an edit to the
// patch's `active` list and nothing else. Dragged by the grip on its header.
let reordering = null;      // {name, names} while a card is in the air

// `names` with `name` taken out and put before `before` - or last, for null.
function moved(names, name, before) {
  const rest = names.filter(n => n !== name);
  const at = before === null ? rest.length : rest.indexOf(before);
  return [...rest.slice(0, at), name, ...rest.slice(at)];
}

const clearMarks = () => {
  for (const el of list.querySelectorAll('.drop-before, .drop-after, .moving'))
    el.classList.remove('drop-before', 'drop-after', 'moving');
};

// Which half of a card the pointer is over says whether it lands before or after it.
const lowerHalf = (e, card) => {
  const r = card.getBoundingClientRect();
  return e.clientY > r.top + r.height / 2;
};

function cardGrip(card, head, name, names) {
  const g = document.createElement('span');
  g.className = 'grip card-grip';
  g.textContent = '\u283f';
  g.draggable = true;
  g.title = `drag to change when ${name} is drawn`;

  g.ondragstart = (e) => {
    reordering = {name, names};
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', name);
    e.dataTransfer.setDragImage(head, 12, 12);
    card.classList.add('moving');
  };
  g.ondragend = () => { reordering = null; clearMarks(); };
  return g;
}

function cardDropTarget(card, name) {
  card.ondragover = (e) => {
    if (!reordering || reordering.name === name) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';

    const after = lowerHalf(e, card);
    card.classList.toggle('drop-before', !after);
    card.classList.toggle('drop-after', after);
  };
  card.ondragleave = (e) => {
    if (!card.contains(e.relatedTarget)) card.classList.remove('drop-before', 'drop-after');
  };
  card.ondrop = (e) => {
    if (!reordering || reordering.name === name) return;
    e.preventDefault();

    const {name: dragged, names} = reordering;
    const after = lowerHalf(e, card);
    reordering = null;
    clearMarks();

    // After this card is before the one that follows it, if there is one.
    const next = names[names.indexOf(name) + 1] ?? null;
    const order = moved(names, dragged, after ? next : name);
    if (order.some((n, i) => n !== names[i])) setActive(order);
  };
}

// The plus: what is not in the preset yet, to pick from.
let adding = false;         // the menu is up, so the page must not redraw under it

function plusButton(names) {
  const box = document.createElement('div');
  box.className = 'plus';

  const b = document.createElement('button');
  b.textContent = '+';
  b.title = 'add an effect to this preset';
  b.onclick = (ev) => {
    ev.stopPropagation();
    if (adding) { closeMenu(); return; }
    adding = true;

    const menu = document.createElement('div');
    menu.className = 'menu';
    menu.onclick = (e) => e.stopPropagation();
    const rest = Object.keys(rig.effects).filter(e => !names.includes(e));

    for (const name of rest) {
      const item = document.createElement('button');
      item.className = 'item';
      item.textContent = name;
      item.onclick = () => { closeMenu(); setActive([...names, name]); };
      menu.append(item);
    }
    if (!rest.length) {
      const none = document.createElement('div');
      none.className = 'dim';
      none.textContent = 'every effect is in this preset';
      menu.append(none);
    }
    box.append(menu);
  };

  box.append(b);
  return box;
}

function closeMenu() {
  adding = false;
  drawEffects();
}

document.addEventListener('click', () => { if (adding) closeMenu(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && adding) closeMenu(); });

function drawEffects() {
  list.innerHTML = '';
  const view = views[rig.selected];
  if (!view) return;

  const names = chain(view.live);

  const bar = document.createElement('div');
  bar.className = 'effects-bar';
  const anyOn = names.some(n => !isMuted(n));
  const all = document.createElement('button');
  all.textContent = anyOn ? 'mute all' : 'unmute all';
  all.disabled = !names.length;
  all.title = anyOn ? 'mute every effect, to look at them one at a time - they stay in the preset'
                    : 'unmute the effects that mute all silenced';
  all.onclick = () => allOff(names);
  const tally = document.createElement('span');
  tally.className = 'dim';
  tally.textContent = `${names.filter(n => !isMuted(n)).length}/${names.length} on`;
  bar.append(all, tally, plusButton(names));
  list.append(bar);

  if (!names.length) {
    const none = document.createElement('p');
    none.className = 'dim';
    none.textContent = 'no effects';
    list.append(none);
  }

  for (const name of names) {
    const keys = slotsOf(name).map(s => `${name}.${s}`);
    const wired = keys.filter(k => (view.live.slots[k] ?? null) !== null).length;

    const card = document.createElement('section');
    card.className = 'effect' + (isMuted(name) ? ' off' : '') + (expanded.has(name) ? ' open' : '');
    card.dataset.effect = name;

    const head = document.createElement('div');
    head.className = 'effect-head';
    const open = expanded.has(name);
    const title = document.createElement('button');
    title.className = 'title';
    const chev = document.createElement('span');
    chev.className = 'chev';
    chev.textContent = open ? '\u25be' : '\u25b8';
    const label = document.createElement('b');
    label.textContent = name;
    title.append(chev, label);
    title.onclick = () => {
      open ? expanded.delete(name) : expanded.add(name);
      store.put(expanded);
      drawEffects();
    };
    const count = document.createElement('span');
    count.className = 'dim';
    count.textContent = `${wired}/${keys.length}`;
    const sw = document.createElement('button');
    sw.className = 'switch' + (isMuted(name) ? '' : ' on');
    sw.title = isMuted(name) ? `unmute ${name}` : `mute ${name}`;
    sw.onclick = () => setMuted(isMuted(name) ? muted().filter(n => n !== name)
                                              : [...muted(), name]);

    // Taking it out of the preset is the real edit; the switch only mutes. Its
    // wiring stays in the patch, so adding it again finds it as it was.
    const bin = document.createElement('button');
    bin.className = 'bin';
    bin.textContent = '\u2715';
    bin.title = `take ${name} out of this preset`;
    bin.onclick = async () => {
      if (isMuted(name)) await setMuted(muted().filter(n => n !== name));
      setActive(names.filter(n => n !== name));
    };

    // The fader over the brightness stays in view when the effect is folded.
    const faders = keys.filter(isValueSlot)
        .map(k => splitFader(view.live.slots[k] ?? null).fader).filter(f => f !== null);
    const fadeTag = faders.map(f => {
      const tag = document.createElement('span');
      tag.className = 'fade-tag';
      tag.textContent = f;
      tag.title = `brightness is on ${f}`;
      return tag;
    });

    // Beside the name, so a folded effect still says what it is for.
    const note = document.createElement('input');
    note.className = 'note';
    note.type = 'text';
    note.placeholder = 'add a note';
    note.spellcheck = false;
    note.value = view.live.notes?.[name] ?? '';
    note.onchange = () => setNote(name, note.value.trim());
    note.onkeydown = (ev) => {
      if (ev.key === 'Enter') { ev.preventDefault(); note.blur(); }
      if (ev.key === 'Escape') { note.value = view.live.notes?.[name] ?? ''; note.blur(); }
    };

    // ... and so does its dial, to turn it without opening the effect.
    const faderDials = controlsFor(faders.reduce((t, f) => t === null ? f : {op: 'add', args: [t, f]}, null));
    const dials = faderDials.length ? knobList(faderDials, true) : null;

    head.append(cardGrip(card, head, name, names), title, note, ...fadeTag, ...(dials ? [dials] : []),
                count, sw, bin);
    cardDropTarget(card, name);

    card.append(head);

    if (open) {
      // A colour is a hue and a saturation, so each pair gets a row of its own
      // to put a gradient on both at once. Both slots stay editable below it.
      // What the effect itself listens to comes first: it is not behind any slot.
      const own = controlsOwnedBy(name);
      if (own.length) card.append(knobList(own));

      for (const pair of gradientPairs(keys)) card.append(gradientRow(name, pair, view.live));
      for (const key of keys) card.append(slotRow(key, view.live.slots[key] ?? null));
    }
    list.append(card);
  }
}

// ---- colour gradients ------------------------------------------------------
// A gradient is stops of [frac, hue, sat]: what colour every place along 0..1 is.
// One knob (gradient_1 to gradient_3) picks which gradient a pair of operators
// reads, by position. The pair row puts those operators in a hue and a saturation
// slot together, and the editor makes and changes a preset's own.
//
// The server only plays what it is given: the declared gradients, with a
// preset's own laid over them. The rules about what a preset's own may be are
// this page's, and it keeps them - see GRADIENT_POSITIONS and the editor's save.

// Declared in the server's code at 0-63. A preset's own are kept to 64-127, so
// the two never share a position and neither moves when the other changes.
const GRADIENT_POSITIONS = {declared: [0, 63], own: [64, 127]};
const GRADIENT_NAME = /^[A-Za-z0-9_-]{1,40}$/;

const mk = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};
const round4 = (x) => Math.round(x * 10000) / 10000;
const clamp01 = (x) => Math.max(0, Math.min(1, x));

// The same walk as gradient_hs on the server: eased with smoothstep between
// stops, two stops at one frac make a hard step, and the ends clamp.
function gradientHs(stops, t) {
  if (t <= stops[0][0]) return [stops[0][1], stops[0][2]];
  for (let i = 1; i < stops.length; i++) {
    const [f0, h0, s0] = stops[i - 1], [f1, h1, s1] = stops[i];
    if (f0 <= t && t < f1) {
      const u = (t - f0) / (f1 - f0);
      const k = u * u * (3 - 2 * u);
      return [h0 + (h1 - h0) * k, s0 + (s1 - s0) * k];
    }
  }
  const last = stops[stops.length - 1];
  return [last[1], last[2]];
}

// Full brightness: a gradient has no value of its own, so what is drawn here is
// the colour before whatever draws it says how bright.
function hsvRgb(h, s, v = 1) {
  h = ((h % 1) + 1) % 1;
  const i = Math.floor(h * 6), f = h * 6 - i;
  const p = v * (1 - s), q = v * (1 - f * s), u = v * (1 - (1 - f) * s);
  return [[v, u, p], [q, v, p], [p, v, u], [p, q, v], [u, p, v], [v, p, q]][i % 6]
      .map(c => Math.round(c * 255));
}
const rgbCss = (h, s) => `rgb(${hsvRgb(h, s).join(',')})`;

// One column per pixel, so a hard step is a hard step.
function paintStrip(canvas, stops) {
  const ctx = canvas.getContext('2d');
  for (let x = 0; x < canvas.width; x++) {
    const [h, s] = gradientHs(stops, canvas.width > 1 ? x / (canvas.width - 1) : 0);
    ctx.fillStyle = rgbCss(h, s);
    ctx.fillRect(x, 0, 1, canvas.height);
  }
}

function strip(stops, w = 96, h = 14) {
  const c = mk('canvas', 'gstrip');
  c.width = w;
  c.height = h;
  paintStrip(c, stops);
  return c;
}

// ---- which gradients there are

const localGradients = () => Object.entries(views[rig.selected]?.live.gradients ?? {})
    .map(([name, g]) => ({name, position: g.position, stops: g.stops, scope: 'preset'}))
    .sort((a, b) => a.position - b.position);
const globalGradients = () => (rig?.gradients ?? []).map(g => ({...g, scope: 'global'}));
const allGradients = () => [...globalGradients(), ...localGradients()]
    .sort((a, b) => a.position - b.position);

// What a knob at `value` is on: the gradient written down at exactly that
// position, or none. Not the nearest - what a knob between two of them makes the
// rig play is the server's business, and this page does not guess at it.
const gradientAt = (value) => allGradients().find(g => g.position === Number(value)) ?? null;

const freePosition = (range, taken) => {
  for (let p = range[0]; p <= range[1]; p++) if (!taken.includes(p)) return p;
  return null;
};

// The CC a gradient knob is on, which a preset may have moved.
const channelCC = (n) => controls.find(c => c.kind === 'cc'
                                            && c.comments.includes(`gradient_${n}.select`))?.number ?? null;
const ccValue = (cc) => knobs[cc]?.value
    ?? controls.find(c => c.kind === 'cc' && c.number === Number(cc))?.value ?? 0;

// Point a gradient knob at a position, as turning it would.
function setChannel(n, position) {
  const cc = channelCC(n);
  if (cc === null) return;
  turnKnob(cc, position);
  syncGradientPickers();                // now, as a dial is, not when the desk next says
  setTimeout(() => { if (turning?.cc === cc) turning = null; }, 300);
}

// ---- writing

// Change the playing preset's own gradients: `change` is handed a copy of them
// and returns what they should be. Nothing checks them but the editor that made
// them, so it has already seen to the name, the position and the stops.
async function writeGradients(change) {
  const n = rig.selected;
  if (n === null) return false;

  const fresh = await get(`/presets/${n}`);
  remember(n, fresh.live);
  const r = await put(`/presets/${n}`, {...fresh.live, gradients: change({...(fresh.live.gradients ?? {})})});
  if (!r.ok) { alert((await r.json()).detail); return false; }
  await refresh();
  return true;
}

// Change several slots of the playing preset in one write.
async function writeSlots(changes) {
  const n = rig.selected;
  if (n === null) return false;

  const fresh = await get(`/presets/${n}`);
  remember(n, fresh.live);
  const r = await put(`/presets/${n}`, {...fresh.live, slots: {...fresh.live.slots, ...changes}});
  if (!r.ok) { alert((await r.json()).detail); return false; }
  await refresh();
  return true;
}

// ---- the picker: a gradient as it looks, and a menu of the rest

// Every gradient there is, the preset's own first, each with what it looks like.
// Choosing one is choosing its position; the first entry makes a new one.
const gradientSource = {
  placeholder: 'search gradients',
  noMap: true,
  entries: () => {
    const entry = (g, group, label, title) => ({
      group, text: g.name, hint: `at ${g.position}`, value: g.position, swatch: g.stops,
      edit: {label, title, run: () => openGradientEditor({gradient: g})},
    });
    return [
      {group: 'new', text: 'new gradient…', hint: '', value: 'new'},
      ...localGradients().map(g => entry(g, 'this preset', 'edit', 'change this gradient')),
      ...globalGradients().map(g => entry(g, 'global', 'view', 'look at it, or copy it')),
    ];
  },
};

// A button showing what the knob on `cc` is on, opening the menu of gradients.
// `pick` is told the position chosen - or made, if it was a new one.
function gradientPicker(cc, pick) {
  const wrap = mk('span', 'gpickwrap fpick');
  wrap.dataset.cc = cc;
  const btn = mk('button', 'gpick');
  btn.title = 'choose a gradient';
  wrap.append(btn);

  btn.onclick = fieldMenu(wrap, () => gradientAt(ccValue(cc))?.position ?? null, (value) => {
    if (value === 'new') openGradientEditor({onSaved: (g) => pick(g.position)});
    else pick(value);
  }, gradientSource);

  paintGradientPicker(wrap);
  return wrap;
}

// Redrawn only when what it shows has changed: a socket frame comes ten times a second.
function paintGradientPicker(wrap) {
  const g = gradientAt(ccValue(wrap.dataset.cc));
  const shown = g ? `${g.name}|${g.position}|${JSON.stringify(g.stops)}` : '';
  if (wrap._shown === shown) return;
  wrap._shown = shown;

  const btn = wrap.querySelector('.gpick');
  btn.replaceChildren(...(g ? [strip(g.stops, 64, 12), mk('span', 'gname', g.name)]
                            : [mk('span', 'gname dim', 'no gradient')]),
                      mk('span', 'caret', '▾'));
}

function syncGradientPickers() {
  for (const wrap of document.querySelectorAll('.gpickwrap[data-cc]')) paintGradientPicker(wrap);
}

// ---- a hue and a saturation, together

const slotName = (key) => key.split('.').slice(1).join('.');

// Slots that make a colour: `hue` with `sat`, `hue_1` with `sat_1`. An effect with
// only a hue, like prob_zaps, has no pair.
function gradientPairs(keys) {
  const pairs = [];
  for (const hue of keys) {
    const m = /^hue(_.+)?$/.exec(slotName(hue));
    if (!m) continue;
    const suffix = m[1] ?? '';
    const sat = keys.find(k => ['sat', 'saturation'].some(n => n + suffix === slotName(k)));
    if (sat) pairs.push({hue, sat, label: suffix ? `colour ${suffix.slice(1)}` : 'colour'});
  }
  return pairs;
}

const gradientOp = (n, channel, driver) => ({op: `gradient_${n}_${channel}`, args: [driver], mod: false});

// {n, driver} if a tree is `gradient_N_h(...)` or `_s`, as asked for.
function gradientOf(tree, channel) {
  if (tree === null || typeof tree !== 'object') return null;
  const m = /^gradient_(\d+)_([hs])$/.exec(tree.op);
  return m && m[2] === channel && tree.args.length === 1 ? {n: Number(m[1]), driver: tree.args[0]} : null;
}

// A pair is on a gradient when its hue and saturation are the two operators of one
// channel reading the same thing. Anything else is the pair doing its own thing.
function pairState(live, pair) {
  const h = live.slots[pair.hue] ?? null, s = live.slots[pair.sat] ?? null;
  const gh = gradientOf(h, 'h'), gs = gradientOf(s, 's');

  if (gh && gs && gh.n === gs.n && JSON.stringify(gh.driver) === JSON.stringify(gs.driver))
    return {on: true, n: gh.n, driver: gh.driver};

  return {on: false, driver: typeof h === 'string' ? h : null,
          formula: [h, s].some(t => t !== null && typeof t === 'object')};
}

// Effects that read channel `n` somewhere other than `except`.
function channelUsers(live, n, except) {
  const out = new Set();
  for (const [key, tree] of Object.entries(live.slots))
    if (!except.includes(key) && opsIn(tree).some(o => o.startsWith(`gradient_${n}_`)))
      out.add(key.split('.')[0]);
  return [...out];
}

// Channels are shared - a dozen pairs and three knobs - so a new pair takes one
// nothing else reads if there is one, and says so if it has to share.
const defaultChannel = (live, pair) =>
    [1, 2, 3].find(n => channelUsers(live, n, [pair.hue, pair.sat]).length === 0) ?? 1;

function gradientRow(effect, pair, live) {
  const state = pairState(live, pair);
  const row = mk('div', 'slot gpair');
  const head = mk('div', 'slot-head');
  head.append(mk('span', 'name', `${pair.label} gradient`));
  row.append(head);

  // With no gradient on yet there is one thing to do. The driver is the field the
  // hue was already following, or a fader, and can be changed straight after.
  if (!state.on) {
    const wrap = mk('span', 'fpick');
    const btn = mk('button', 'gpick', 'use a gradient ▾');
    btn.title = `put a gradient on this effect's ${pair.label}: its hue and saturation are set together`;
    btn.onclick = fieldMenu(wrap, null, async (value) => {
      if (state.formula && !confirm(`Replace the ${slotName(pair.hue)} and ${slotName(pair.sat)} `
                                    + 'formulas with a gradient? They are lost.')) return;

      const n = defaultChannel(live, pair);
      const driver = state.driver ?? FADERS[0];
      const apply = async (position) => {
        if (await writeSlots({[pair.hue]: gradientOp(n, 'h', driver),
                              [pair.sat]: gradientOp(n, 's', driver)}))
          setChannel(n, position);
      };

      if (value === 'new') openGradientEditor({onSaved: (g) => apply(g.position)});
      else apply(value);
    }, gradientSource);
    wrap.append(btn);
    head.append(wrap);
    return row;
  }

  const {n, driver} = state;
  const cc = channelCC(n);
  const move = (changes) => writeSlots(changes);

  head.append(cc === null ? mk('span', 'dim', `gradient_${n} has no knob`)
                          : gradientPicker(cc, (position) => setChannel(n, position)));

  head.append(makeSeg(String(n), [1, 2, 3].map(m => ({
    label: String(m), id: String(m), title: `read gradient knob ${m}`,
    onclick: () => move({[pair.hue]: gradientOp(m, 'h', driver), [pair.sat]: gradientOp(m, 's', driver)}),
  })), true));

  // The field that says where along the gradient to be, for both slots at once.
  head.append(mk('span', 'dim', 'moved by'));
  const by = mk('span', 'fpick');
  const chip = mk('button', 'chip', `${describe(driver)} ▾`);
  chip.onclick = fieldMenu(by, typeof driver === 'string' ? driver : null, (field) =>
      move({[pair.hue]: gradientOp(n, 'h', field), [pair.sat]: gradientOp(n, 's', field)}));
  by.append(chip);
  head.append(by);

  const edit = mk('button', null, 'edit');
  edit.title = 'change the gradient this knob is on';
  edit.onclick = () => { const g = gradientAt(ccValue(cc)); if (g) openGradientEditor({gradient: g}); };
  const off = mk('button', 'bin', '✕');
  off.title = 'take the gradient off: back to a plain hue';
  off.onclick = () => move({[pair.hue]: typeof driver === 'string' ? driver : 0, [pair.sat]: 1});
  head.append(...(cc === null ? [] : [edit]), off);

  // One knob for every pair on the channel, so choosing here chooses there.
  const others = channelUsers(live, n, [pair.hue, pair.sat]);
  if (others.length) {
    const note = mk('div', 'dim gshared',
                    `knob ${n} is shared: the gradient moves ${others.join(', ')} too`);
    row.append(note);
  }
  return row;
}

// ---- the editor

// Make a gradient of the preset's own, change one, or look at a global one and
// take a copy. Stops are dragged along the bar and coloured on the wheel; two
// stops at one place make a hard step.
function openGradientEditor({gradient = null, copy = false, onSaved = null} = {}) {
  document.getElementById('gradient-dialog')?.remove();

  const readonly = gradient?.scope === 'global' && !copy;
  const existing = gradient?.scope === 'preset' ? gradient : null;
  const locals = localGradients();
  const takenNames = [...globalGradients(), ...locals].map(g => g.name);

  const unique = (base) => {
    let name = base, i = 2;
    while (takenNames.includes(name)) name = `${base}_${i++}`;
    return name;
  };
  const startName = existing ? existing.name
      : readonly ? gradient.name                  // looking at it: its own name, not a copy's
      : unique(gradient ? `${gradient.name}_copy` : 'gradient');

  const stops = (gradient?.stops ?? [[0, 0.08, 1], [1, 0.75, 1]])
      .map(([frac, hue, sat]) => ({frac, hue, sat}));
  let sel = stops[0];
  const sorted = () => [...stops].sort((a, b) => a.frac - b.frac);     // stable: a hard step keeps its sides
  const asStops = () => sorted().map(s => [s.frac, s.hue, s.sat]);

  const dlg = mk('dialog', 'gdlg');
  dlg.id = 'gradient-dialog';
  const shut = () => { dlg.close(); dlg.remove(); };
  const title = readonly ? `global gradient · ${gradient.name}`
      : existing ? `gradient · ${existing.name}` : 'new gradient';
  dlg.append(mk('h3', null, title));

  const nameIn = mk('input');
  nameIn.type = 'text';
  nameIn.maxLength = 40;
  nameIn.value = startName;
  nameIn.disabled = readonly;
  nameIn.placeholder = 'letters, digits, - and _';
  const where = existing ? `position ${existing.position}`
      : readonly ? `position ${gradient.position}, global`
      : `position ${freePosition(GRADIENT_POSITIONS.own, locals.map(g => g.position)) ?? 'none free'}`;
  const nameRow = mk('label', 'gfield');
  nameRow.append(mk('span', null, 'name'), nameIn, mk('span', 'dim', `${where} · the knob value that picks it`));
  dlg.append(nameRow);

  // the path: the gradient itself, with a handle for each stop
  const bar = mk('div', 'gbar');
  const barCanvas = mk('canvas', 'gbarstrip');
  barCanvas.width = 480;
  barCanvas.height = 34;
  const handles = mk('div', 'ghandles');
  bar.append(barCanvas, handles);

  const chips = mk('div', 'gchips');
  const wheel = mk('canvas', 'gwheel');
  const SZ = 150;
  wheel.width = wheel.height = SZ;
  const fracIn = mk('input');
  fracIn.type = 'number';
  fracIn.min = '0'; fracIn.max = '100'; fracIn.step = '0.5';
  const readout = mk('span', 'dim');
  const removeBtn = mk('button', null, 'remove stop');
  const splitBtn = mk('button', null, 'hard step');
  splitBtn.title = 'put a copy of this stop at the same place: the two make a hard edge, and you colour each side';

  // the wheel: angle is hue, distance from the middle is saturation
  const wheelImg = document.createElement('canvas');
  wheelImg.width = wheelImg.height = SZ;
  {
    const ctx = wheelImg.getContext('2d'), img = ctx.createImageData(SZ, SZ), r0 = SZ / 2;
    for (let y = 0; y < SZ; y++) for (let x = 0; x < SZ; x++) {
      const dx = x - r0 + 0.5, dy = y - r0 + 0.5, d = Math.hypot(dx, dy) / r0, i = (y * SZ + x) * 4;
      if (d > 1) continue;
      img.data.set([...hsvRgb(Math.atan2(dy, dx) / (2 * Math.PI), d), 255], i);
    }
    ctx.putImageData(img, 0, 0);
  }

  const drawBar = () => paintStrip(barCanvas, asStops());
  const drawWheel = () => {
    const ctx = wheel.getContext('2d'), r0 = SZ / 2;
    ctx.clearRect(0, 0, SZ, SZ);
    ctx.drawImage(wheelImg, 0, 0);
    const a = sel.hue * 2 * Math.PI, rr = sel.sat * r0;
    ctx.beginPath();
    ctx.arc(r0 + Math.cos(a) * rr, r0 + Math.sin(a) * rr, 7, 0, 7);
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#fff';
    ctx.stroke();
  };

  // Handles are rebuilt only when the stops or their order change, never when one
  // is picked up: replacing the element under the pointer would end the drag.
  const drawHandles = () => {
    handles.replaceChildren();
    stops.forEach((s) => {
      const hd = mk('div', 'ghandle' + (s === sel ? ' on' : ''));
      hd.style.left = `${s.frac * 100}%`;
      hd.style.background = rgbCss(s.hue, s.sat);

      hd.onpointerdown = (ev) => {
        ev.stopPropagation();
        select(s);
        if (readonly) return;

        hd.setPointerCapture(ev.pointerId);
        hd.onpointermove = (e) => {
          const r = bar.getBoundingClientRect();
          s.frac = round4(clamp01((e.clientX - r.left) / r.width));
          hd.style.left = `${s.frac * 100}%`;
          fracIn.value = String(round4(s.frac * 100));
          drawBar();
          drawChips();
        };
        // Let go: now that nothing is held, put the stops in order.
        hd.onpointerup = hd.onpointercancel = () => {
          hd.onpointermove = hd.onpointerup = hd.onpointercancel = null;
          stops.sort((a, b) => a.frac - b.frac);
          redraw();
        };
      };
      handles.append(hd);
    });
  };

  // Stops can sit on top of each other (a hard step), so each also has a chip.
  const drawChips = () => {
    chips.replaceChildren();
    stops.forEach((s, i) => {
      const c = mk('button', 'gchip' + (s === sel ? ' on' : ''), `${i + 1} \u00b7 ${round4(s.frac * 100)}%`);
      c.style.borderBottomColor = rgbCss(s.hue, s.sat);
      c.onclick = () => select(s);
      chips.append(c);
    });
  };

  // What shows the picked stop: its chip, the wheel, the boxes. Not the handles.
  function paintSelection() {
    drawChips();
    drawWheel();
    fracIn.value = String(round4(sel.frac * 100));
    readout.textContent = `hue ${sel.hue.toFixed(3)} \u00b7 sat ${sel.sat.toFixed(3)}`;
    removeBtn.disabled = readonly || stops.length <= 1;
    splitBtn.disabled = readonly;
  }

  // Pick a stop without rebuilding the handles. They are in the order of `stops`.
  function select(s) {
    sel = s;
    [...handles.children].forEach((el, i) => el.classList.toggle('on', stops[i] === sel));
    paintSelection();
  }

  function redraw() {
    drawBar();
    drawHandles();
    paintSelection();
  }

  if (!readonly) {
    bar.onpointerdown = (ev) => {              // click the path to add a stop there
      const r = bar.getBoundingClientRect();
      const frac = round4(clamp01((ev.clientX - r.left) / r.width));
      const [hue, sat] = gradientHs(asStops(), frac);
      sel = {frac, hue: round4(hue), sat: round4(sat)};
      stops.push(sel);
      stops.sort((a, b) => a.frac - b.frac);
      redraw();
    };

    const pickColour = (ev) => {
      const r = wheel.getBoundingClientRect(), k = SZ / r.width, r0 = SZ / 2;
      const dx = (ev.clientX - r.left) * k - r0, dy = (ev.clientY - r.top) * k - r0;
      sel.hue = round4((((Math.atan2(dy, dx) / (2 * Math.PI)) % 1) + 1) % 1);
      sel.sat = round4(Math.min(Math.hypot(dx, dy) / r0, 1));
      redraw();
    };
    wheel.onpointerdown = (ev) => {
      wheel.setPointerCapture(ev.pointerId);
      pickColour(ev);
      wheel.onpointermove = pickColour;
      wheel.onpointerup = () => { wheel.onpointermove = wheel.onpointerup = null; };
    };

    fracIn.onchange = () => {
      sel.frac = round4(clamp01(parseFloat(fracIn.value) / 100 || 0));
      stops.sort((a, b) => a.frac - b.frac);
      redraw();
    };
    removeBtn.onclick = () => {
      stops.splice(stops.indexOf(sel), 1);
      sel = stops[0];
      redraw();
    };
    splitBtn.onclick = () => {
      const copyOf = {...sel};
      stops.splice(stops.indexOf(sel) + 1, 0, copyOf);
      sel = copyOf;
      redraw();
    };
  }

  const side = mk('div', 'gside');
  const fracRow = mk('label', 'gfield');
  fracRow.append(mk('span', null, 'stop at %'), fracIn);
  side.append(fracRow, readout, mk('div', 'gbtns'), mk('p', 'dim',
      readonly ? 'A global gradient is declared in the server\'s code and cannot be changed here. '
                 + 'Make a copy to change it for this preset, or copy it as Python.'
               : 'Click the path to add a stop, drag one to move it, click the wheel to colour it. '
                 + 'Hue is not wrapped between stops. A hard step is two stops at one place.'));
  side.querySelector('.gbtns').append(removeBtn, splitBtn);

  const body = mk('div', 'gbody');
  body.append(wheel, side);
  dlg.append(bar, chips, body);

  // ---- the foot: what can be done with it
  const err = mk('div', 'hint');
  const python = mk('textarea', 'gpython');
  python.readOnly = true;
  python.hidden = true;
  python.rows = 8;

  const cleanName = () => nameIn.value.trim();
  const say = (text) => { err.textContent = text; };

  // The same gradient as a line of Python to paste into GLOBAL_GRADIENTS, at the
  // lowest global position that is free.
  const copyPython = async () => {
    // A global one being looked at is already declared, at its own position; any
    // other is offered the lowest global position that is free.
    const position = readonly ? gradient.position
        : freePosition(GRADIENT_POSITIONS.declared, globalGradients().map(g => g.position));
    const name = readonly ? gradient.name : cleanName() || 'gradient';
    const rows = asStops().map(s => `    (${s.map(x => x.toFixed(4)).join(', ')}),`).join('\n');
    python.value = `# in instrument/gradients.py, GLOBAL_GRADIENTS - `
        + (readonly ? 'already declared at this position\n' : `position ${position ?? '(none free)'} is free\n`)
        + `Gradient("${name}", ${position ?? 0}, (\n${rows}\n)),`;
    python.hidden = false;
    python.select();
    try { await navigator.clipboard.writeText(python.value); say('copied'); }
    catch { say('select the text and copy it'); }
  };

  const save = async () => {
    const name = cleanName();
    if (!GRADIENT_NAME.test(name)) return say('a name is letters, digits, - and _, 40 at most');
    if (globalGradients().some(g => g.name === name))
      return say(`${name} is a global gradient's name - a preset cannot give its own the same name`);
    if (locals.some(g => g.name === name && g.name !== existing?.name))
      return say(`this preset already has a gradient called ${name}`);

    const position = existing?.position
        ?? freePosition(GRADIENT_POSITIONS.own, locals.map(g => g.position));
    if (position === null) return say('this preset has no free gradient positions left');

    // The server sorts what it is given but trusts the rest, so a stop that is not
    // a place, a hue and a saturation between 0 and 1 stops here.
    const out = asStops().map(s => s.map(round4));
    if (!out.length || out.some(s => s.length !== 3 || s.some(x => !(x >= 0 && x <= 1))))
      return say('every stop needs a place, a hue and a saturation, each between 0 and 1');

    const done = await writeGradients((gs) => {
      if (existing && existing.name !== name) delete gs[existing.name];
      gs[name] = {position, stops: out};
      return gs;
    });
    if (!done) return;
    shut();
    onSaved?.({name, position});
  };

  const drop = async () => {
    const on = [1, 2, 3].filter(n => channelCC(n) !== null && gradientAt(ccValue(channelCC(n)))?.name === existing.name);
    const note = on.length ? ` ${on.length > 1 ? 'Knobs' : 'Knob'} ${on.join(', ')} ${on.length > 1 ? 'are' : 'is'} on it`
        + ' and will be on none of the others until you choose one.' : '';
    if (!confirm(`Delete ${existing.name} from this preset?${note}`)) return;
    if (await writeGradients((gs) => { delete gs[existing.name]; return gs; })) shut();
  };

  const close = mk('button', null, 'close');
  close.onclick = shut;
  const foot = mk('div', 'gfoot');
  const pyBtn = mk('button', null, 'copy as Python');
  pyBtn.title = 'a line to paste into the server\'s global gradients';
  pyBtn.onclick = copyPython;

  if (readonly) {
    const dup = mk('button', null, 'make a copy for this preset…');
    dup.onclick = () => openGradientEditor({gradient, copy: true, onSaved});
    foot.append(pyBtn, dup, close);
  } else {
    const ok = mk('button', 'primary', 'save');
    ok.onclick = save;
    const del = mk('button', 'bin', 'delete');
    del.onclick = drop;
    foot.append(pyBtn, ...(existing ? [del] : []), close, ok);
  }
  dlg.append(err, python, foot);

  dlg.onclose = () => dlg.remove();         // Escape closes it too
  // The backdrop is the dialog itself, and so is its padding: only a click out
  // past its edge is a click on the backdrop.
  dlg.onclick = (ev) => {
    const r = dlg.getBoundingClientRect();
    const outside = ev.clientX < r.left || ev.clientX > r.right
                 || ev.clientY < r.top || ev.clientY > r.bottom;
    if (ev.target === dlg && outside) shut();
  };
  document.body.append(dlg);
  dlg.showModal();
  redraw();
}

// ---- presets by name -------------------------------------------------------

// Every preset with a name, in the menu the fields use. Only the ones saved
// past the first sixteen are likely to have names, so the menu lists whichever do,
// each by number.
const presetSource = {
  placeholder: 'search presets by name or number',
  entries: () => namedNumbers()
      .map(n => ({group: 'saved', text: nameOf(n), hint: `#${n}`, value: n})),
};

// Playing one is what its cell does, so it is the same call.
namedOpen.onclick = fieldMenu(namedBox, null, (n) => act(`/presets/${n}/select`), presetSource);

// A name begins with a letter, then letters, digits and single dashes, and is not
// one another preset has, ignoring case. Beginning with a letter means a name can
// never be mistaken for a preset number. `into` is the number it is for, which
// may keep the name it already has. Returns why not, or null.
const MAX_NAME = 32;
function nameProblem(name, into = null) {
  if (!name) return 'a name cannot be empty';
  if (name.length > MAX_NAME) return `a name is at most ${MAX_NAME} characters`;
  if (!/^[A-Za-z0-9-]+$/.test(name)) return 'a name can only use letters, digits and dashes';
  if (!/^[A-Za-z]/.test(name)) return 'a name must begin with a letter';
  if (name.includes('--')) return 'a name cannot have two dashes in a row';

  const taken = namedNumbers().find(n => n !== into && nameOf(n).toLowerCase() === name.toLowerCase());
  return taken === undefined ? null : `preset ${taken} is already called "${nameOf(taken)}"`;
}

// The lowest number past the bar that nothing holds, offered to begin with. Any
// number can be chosen instead, so this is only where the choice starts.
function freeNumber() {
  for (let n = BAR; n < rig.size; n++) if (!written(views[n]) && !isDirty(views[n])) return n;
  return null;
}

// Keep a copy of what is playing under a name, at a number you pick: read it,
// write it to that number with the name in it, and commit that. The server only
// holds what it is given. This preset keeps playing, so a line beside the button
// says what the copy was called and where it went, for a few seconds.
const savedNote = document.getElementById('saved');
const copyDialog = document.getElementById('copy-dialog');
const copyName = document.getElementById('copy-name');
const copyGrid = document.getElementById('copy-grid');
const copyWhy = document.getElementById('copy-why');
const copyOk = document.getElementById('copy-ok');
let savedTimer = null;
let target = null;          // the number picked in the dialog
let making = 'copy';        // what the dialog is for: 'copy' of what is playing, or a blank 'new' one

// The numbers to choose from: every one the bank holds, each saying what it holds.
function drawCopyGrid() {
  copyGrid.innerHTML = '';

  for (let n = 0; n < rig.size; n++) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'pcell wide' + (written(views[n]) ? ' saved' : '') +
                  (isDirty(views[n]) ? ' dirty' : '') +
                  (n === rig.selected ? ' on' : '') + (n === target ? ' pick' : '');
    b.textContent = nameOf(n) ? `${n} \u00b7 ${nameOf(n)}` : n;
    b.title = n === rig.selected ? `${n}: the one playing`
            : written(views[n]) ? `${n}: already holds something - it would be replaced`
            : `${n}: empty`;
    b.onclick = () => { target = n; drawCopyGrid(); checkCopy(); };
    copyGrid.append(b);
  }
}

// Say what is wrong, or what choosing this number will do, and only let it go
// ahead when there is nothing wrong.
function checkCopy() {
  const name = copyName.value.trim();
  // An empty box is not a problem to nag about: save just waits for a name.
  const problem = name ? nameProblem(name, target) : null;

  copyWhy.textContent = problem
      ?? (target !== null && written(views[target])
          ? `preset ${target} already holds something, and would be replaced`
          : '');
  copyWhy.classList.toggle('bad', !!problem);
  copyOk.disabled = !name || !!problem || target === null;
}

copyName.oninput = checkCopy;
document.getElementById('copy-cancel').onclick = () => copyDialog.close();

async function openCopy(kind = 'copy') {
  if (kind === 'copy' && rig.selected === null) { alert('Nothing is playing to copy.'); return; }
  making = kind;
  document.getElementById('copy-title').textContent = kind === 'new' ? 'new preset' : 'save a copy';

  // What is on the page may be a second old; the choices are about what is there now.
  views = await get('/presets');
  if (freeNumber() === null && !confirm('Every number past the bar holds something. Pick one to replace?')) return;

  target = freeNumber();
  copyName.value = '';
  drawCopyGrid();
  checkCopy();
  copyDialog.showModal();
  copyName.focus();
}

document.getElementById('save-copy').onclick = () => openCopy('copy');
document.getElementById('new-preset').onclick = () => openCopy('new');

// A preset with nothing plugged in: the chain is empty, so no effect has a card
// until it is added from the menu, and nothing is muted. No knobs are listed - a
// patch that says nothing about them leaves them where they are - and nothing is
// mapped: every control starts on the CC it was declared with, wherever the box on
// the desk has its knobs.
const blankPatch = (name) => ({ccs: {}, slots: {}, cc_map: {}, active: [], muted: [], name});

copyDialog.querySelector('form').onsubmit = async (e) => {
  e.preventDefault();
  const name = copyName.value.trim();
  const number = target;
  if (copyOk.disabled || number === null) return;

  // The dialog may have been open a while.
  views = await get('/presets');
  const problem = nameProblem(name, number);
  if (problem) { checkCopy(); return; }

  if (written(views[number]) &&
      !confirm(`Replace preset ${number}${nameOf(number) ? ` "${nameOf(number)}"` : ''}? Its file is written over.`)) return;
  copyDialog.close();

  // A copy is the playing preset with a name; a new one is a blank patch with one.
  const patch = making === 'new' ? blankPatch(name)
                                 : {...(await get(`/presets/${rig.selected}`)).live, name};
  let r = await put(`/presets/${number}`, patch);
  if (!r.ok) { alert((await r.json()).detail); return; }

  r = await post(`/presets/${number}/commit`);
  if (!r.ok) { alert((await r.json()).detail); return; }

  // A copy leaves what is playing alone. A blank one is made to be filled in, so
  // it is the one to play.
  if (making === 'new') await act(`/presets/${number}/select`);
  else await refresh();

  savedNote.textContent = making === 'new' ? `made ${name} as #${number}` : `saved ${name} as #${number}`;
  clearTimeout(savedTimer);
  savedTimer = setTimeout(() => { savedNote.textContent = ''; }, 4000);
};

// ---- the controller map -------------------------------------------------

// A picture of the box on the desk, with each of its controls labelled by what
// the playing preset has it drive. The picture and the table that says which
// CC or note is which part of it come from surfaces.json; what the controls
// drive is /controls, so assigning a knob changes the map on the next refresh.
const SURFACES = '/static/surfaces.json';
let surfaces = {};
let surfaceId = (() => { try { return localStorage.getItem('surface'); } catch { return null; } })();
const surfaceSvg = {};      // the pictures, fetched once each
let mapPick = null;         // the callback waiting for a control to be pressed on the map
const mapBox = document.getElementById('map');
let mapDrawn = '';          // what the map was last drawn from, so a quiet second draws nothing

const SVG_NS = 'http://www.w3.org/2000/svg';
const short = (t, n = 8) => t.length > n ? t.slice(0, n - 1) + '…' : t;

// Whether a control owner is an operator's: its name, or a prefix of it - several
// operators share one named after none of them (`gradient_1` for `gradient_1_h`).
// The same rule as controlsFor, and docs/CONTROLS.md says why.
const isOperatorOwner = (owner) => rig.operators.some(o => o.name === owner || o.name.startsWith(owner + '_'));

// A control's comment is `owner.role`. The ones owned by a field of the rig, or by
// an operator, are the ones a formula can bring in; the ones owned by an effect are
// the effect's own.
const fieldOwners = (c) => {
  const names = new Set(rig.fields.map(f => f.name));
  return [...new Set(c.comments.map(t => knobOwner(t.split('.')[0]))
                              .filter(n => names.has(n) || isOperatorOwner(n) || n in rig.effects))];
};

// What a formula owns controls through: the fields it names, and the owners of the
// operators it names, however deep. An operator keeps a knob of its own - a select
// has the one that picks - so the desk is not only what its fields own.
const ownersIn = (tree) => {
  const ops = opsIn(tree);
  const viaOps = [...new Set(controls.flatMap(c => c.comments.map(t => t.split('.')[0])))]
      .filter(o => ops.some(n => n === o || n.startsWith(o + '_')));
  return [...fieldsIn(tree).map(knobOwner), ...viaOps];
};

// The effects each owner is used by in the playing preset: a slot is
// `effect.slot`, and its formula names the fields and operators it reads.
function effectsUsing() {
  const live = views[rig.selected]?.live;
  const by = new Map();
  for (const [key, tree] of Object.entries(live?.slots ?? {}))
    for (const f of ownersIn(tree)) by.set(f, (by.get(f) ?? new Set()).add(key.split('.')[0]));

  // An effect that owns controls is its own user: they are in play while it draws.
  if (live) for (const name of drawingEffects(live)) by.set(name, (by.get(name) ?? new Set()).add(name));
  return by;
}

// The owners the playing preset's slots reach, whatever their depth.
function fieldsInUse() {
  const live = views[rig.selected]?.live;
  const used = new Set();
  for (const tree of Object.values(live?.slots ?? {})) ownersIn(tree).forEach(n => used.add(n));
  if (live) drawingEffects(live).forEach(n => used.add(n));
  return used;
}

async function loadSurfaces() {
  try {
    surfaces = await get(SURFACES);
    if (!(surfaceId in surfaces)) surfaceId = Object.keys(surfaces)[0] ?? null;
    if (surfaceId && !surfaceSvg[surfaceId])
      surfaceSvg[surfaceId] = await fetch(surfaces[surfaceId].svg).then(r => r.text());
  } catch (e) { /* no map; the rest of the page works without one */ }
}

function drawMap() {
  const surface = surfaces[surfaceId];
  if (!surface || !surfaceSvg[surfaceId]) return;

  const used = fieldsInUse();
  const effectsBy = effectsUsing();
  const here = controls.filter(c => !c.hidden);
  const key = JSON.stringify([surfaceId, [...used], [...effectsBy].map(([f, e]) => [f, [...e]]), here.map(c => [c.kind, c.number, c.comments])]);
  if (key === mapDrawn) return;
  mapDrawn = key;

  mapBox.replaceChildren();
  const head = document.createElement('div');
  head.className = 'map-head';
  const pick = document.createElement('select');
  for (const [id, s] of Object.entries(surfaces)) {
    const opt = document.createElement('option');
    opt.value = id; opt.textContent = s.name; opt.selected = id === surfaceId;
    pick.append(opt);
  }
  pick.onchange = async () => {
    surfaceId = pick.value;
    try { localStorage.setItem('surface', surfaceId); } catch { /* remembering is a courtesy */ }
    mapDrawn = '';
    await loadSurfaces();
    drawMap();
  };
  head.append(pick);
  mapBox.append(head);

  const holder = document.createElement('div');
  holder.className = 'surface';
  holder.innerHTML = surfaceSvg[surfaceId];
  mapBox.append(holder);

  // Every knob and fader the picture has follows the desk.
  for (const [cc, id] of Object.entries(surface.ccs)) {
    const spot = holder.querySelector(`#${CSS.escape(id)}`);
    if (spot) spot.dataset.cc = cc;
  }

  const off = [];
  const roles = new Map();          // spot -> the [field, role] of everything on it
  for (const c of here) {
    // A note can be several pads: the Akai's pads fold onto fewer BSP notes.
    const ids = [].concat((c.kind === 'cc' ? surface.ccs : surface.notes ?? {})[c.number] ?? []);
    const spots = ids.map(id => holder.querySelector(`#${CSS.escape(id)}`)).filter(Boolean);
    if (!spots.length) { if (c.kind === 'cc' && fieldOwners(c).some(n => used.has(n))) off.push(c); continue; }

    for (const spot of spots) {
      spot.classList.add('assigned');
      if (fieldOwners(c).some(n => used.has(n))) spot.classList.add('lit');
      spot.dataset.owners = JSON.stringify([...new Set([...JSON.parse(spot.dataset.owners ?? '[]'), ...fieldOwners(c)])]);
      roles.set(spot, [...(roles.get(spot) ?? []), ...c.comments.map(t => t.split('.'))]);
    }
  }

  for (const [spot, rs] of roles) {
    if (!rs.length) continue;
    const tag = spot.querySelector('.tag');
    const x = tag.getAttribute('x'), y = Number(tag.getAttribute('y'));
    const fx = [...new Set(rs.flatMap(r => [...(effectsBy.get(knobOwner(r[0])) ?? [])]))];
    spot.dataset.effects = fx.join(', ');
    [rs[0][0] + (rs.length > 1 ? ` +${rs.length - 1}` : ''), rs[0][1] ?? '', fx.join(', ')]
      .forEach((text, i) => {
        if (!text || (i && spot.classList.contains('pad'))) return;   // pads have no room; the legend has the role and effects
        const t = document.createElementNS(SVG_NS, 'text');
        t.setAttribute('class', i ? 'what role' + (i > 1 ? ' fx' : '') : 'what');
        t.setAttribute('x', x); t.setAttribute('y', y + 12 + 11 * i);
        t.textContent = short(text, Number(spot.dataset.chars ?? 8));
        spot.append(t);
      });
    const title = document.createElementNS(SVG_NS, 'title');
    title.textContent = rs.map(r => r.join('.')).join('\n') + (spot.dataset.effects ? `\nin ${spot.dataset.effects}` : '');
    spot.append(title);
    // A tooltip belongs to the shape under the pointer, so the whole pad, not
    // just its text, needs one.
    for (const shape of spot.querySelectorAll('rect, circle, line'))
      shape.append(title.cloneNode(true));
  }
  for (const [spot, rs] of roles) spot.dataset.names = JSON.stringify(rs.map(r => r.join('.')));
  for (const spot of holder.querySelectorAll('.spot.assigned')) spot.onclick = () => {
    if (mapPick) pressedOnMap(spot); else if (spot.dataset.cc) unassignBar(spot);
  };
  // Clicking a knob or fader nothing is on offers a control for it. Turning one
  // never asks anything.
  for (const spot of holder.querySelectorAll('.spot[data-cc]:not(.assigned)'))
    spot.onclick = () => { if (!mapPick) assignMenu(spot); };

  // The picture has no room for whole names, so the same assignments are listed
  // in full beneath it: control, what it moves, and the effects that use it.
  // Pads come first, in the Akai's own numbering, then the knobs and faders as drawn.
  const isPad = s => s.classList.contains('pad');
  const padNo = s => Number(s.id.replace(/\D/g, ''));
  const rows = [...holder.querySelectorAll('.spot.assigned')].filter(s => roles.get(s)?.length)
    .sort((a, b) => isPad(b) - isPad(a) || (isPad(a) && padNo(a) - padNo(b)));
  if (rows.length) {
    const legend = document.createElement('table');
    legend.className = 'map-legend';
    for (const spot of rows) {
      const rs = roles.get(spot);
      const tr = legend.insertRow();
      tr.classList.toggle('lit', spot.classList.contains('lit'));
      const hover = on => { tr.classList.toggle('hover', on); spot.classList.toggle('hover', on); };
      tr.onmouseenter = () => hover(true); tr.onmouseleave = () => hover(false);
      spot.onmouseenter = () => hover(true); spot.onmouseleave = () => hover(false);
      const cells = [
        spot.querySelector('.tag')?.textContent ?? spot.id,
        rs.map(r => r.join('.')).join(', '),
        spot.dataset.effects || '',
      ];
      cells.forEach((text, i) => {
        const td = tr.insertCell();
        td.textContent = text;
        if (i === 2) td.className = 'fx';
      });
    }
    mapBox.append(legend);
  }

  if (off.length) {
    const note = document.createElement('p');
    note.className = 'dim map-off';
    note.textContent = `used, but not on this box: ${off.map(c => c.comments[0]).join(', ')} `;
    const go = document.createElement('button');
    go.textContent = 'assign them';
    go.onclick = assignUsed;
    note.append(go);
    mapBox.append(note);
  }

  mapBox.classList.toggle('picking', mapPick !== null);
  if (mapPick) showMapPrompt();
  syncMapKnobs();
}

// The knobs and faders follow the desk.
function syncMapKnobs() {
  for (const spot of mapBox.querySelectorAll('.spot.assigned[data-cc]')) {
    const k = knobs[spot.dataset.cc];
    if (!k || spot._shown === k.value) continue;
    spot._shown = k.value;
    const frac = fracOf(metaOn(spot.dataset.cc), k.value);
    const pointer = spot.querySelector('.pointer');
    const cap = spot.querySelector('.cap');
    if (pointer) pointer.setAttribute('transform',
        `rotate(${-135 + 270 * frac} ${cap.getAttribute('cx')} ${cap.getAttribute('cy')})`);
    const thumb = spot.querySelector('.thumb');
    if (thumb) {
      const lo = Number(spot.dataset.lo), hi = Number(spot.dataset.hi);
      thumb.setAttribute('y', lo - (lo - hi) * frac);
    }
  }
}

// ---- picking a field by pressing its control

function startMapPick(onPick) {
  mapPick = onPick;
  mapDrawn = '';
  drawMap();
  mapBox.scrollIntoView({block: 'nearest', behavior: 'smooth'});
}

function endMapPick() {
  mapPick = null;
  mapDrawn = '';
  drawMap();
}

function showMapPrompt(choices = null) {
  mapBox.querySelector('.map-prompt')?.remove();
  const bar = document.createElement('div');
  bar.className = 'map-prompt';
  const msg = document.createElement('span');
  msg.textContent = choices ? 'which field?' : 'press a control on the map to plug its field in';
  bar.append(msg);
  for (const name of choices ?? []) {
    const b = document.createElement('button');
    b.textContent = name;
    b.onclick = () => finishMapPick(name);
    bar.append(b);
  }
  const cancel = document.createElement('button');
  cancel.textContent = 'cancel';
  cancel.onclick = endMapPick;
  bar.append(cancel);
  mapBox.prepend(bar);
}

function finishMapPick(name) {
  const done = mapPick;
  endMapPick();
  done?.(name);
}

function pressedOnMap(spot) {
  if (!mapPick) return;
  const owners = JSON.parse(spot.dataset.owners ?? '[]');
  if (owners.length === 1) finishMapPick(owners[0]);
  else if (owners.length) showMapPrompt(owners);
}

document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape' && mapPick) endMapPick(); });

// ---- putting a new field's controls on the box

const fieldOf = (name) => name.split('.')[0];
const fieldsOfSlots = (slots) => new Set(Object.values(slots).flatMap(ownersIn));
// ... and what the effects that are drawing own themselves.
const ownersOfPatch = (patch, slots) => new Set([...fieldsOfSlots(slots), ...drawingEffects(patch)]);

// The patch's cc_map once every control the slots use is on a fader or knob of
// the box on the map. One already on the box stays where it is, and the CCs
// those are on are taken; the rest go to the next free knob, then the next free
// fader, in the order they are listed. The box has no preferences of its own - no
// control is meant for any one knob or fader. Returns what was said about each
// one placed.
function withControls(patch, slots) {
  const surface = surfaces[surfaceId];
  const cc_map = {...patch.cc_map};
  const said = [];
  if (!surface) return {cc_map, said};

  const now = ownersOfPatch(patch, slots);
  const effective = (c) => cc_map[c.comments[0]] ?? c.number;
  const ours = controls.filter(c => c.kind === 'cc' && !c.hidden && c.comments.length
                                    && now.has(knobOwner(fieldOf(c.comments[0]))));
  const wanting = ours.filter(c => !(effective(c) in surface.ccs));
  if (!wanting.length) return {cc_map, said};

  const taking = new Set(wanting.map(c => c.comments[0]));
  const taken = new Set(ours.filter(c => !taking.has(c.comments[0])).map(effective));

  const faders = (surface.faders ?? []).filter(cc => !taken.has(cc));
  const knobs = (surface.knobs ?? []).filter(cc => !taken.has(cc));
  for (const c of wanting) {
    const name = c.comments[0];
    const cc = knobs.length ? knobs.shift() : faders.length ? faders.shift() : undefined;

    if (cc === undefined) { said.push(`no free knob for ${name}`); continue; }
    cc_map[name] = cc;
    said.push(`${name} \u2192 ${surface.ccs[cc]}`);
  }
  return {cc_map, said};
}

// Put every control the playing preset uses, and that is not on the box, there.
async function assignUsed() {
  const n = rig.selected;
  if (n === null) return;
  const fresh = await get(`/presets/${n}`);
  const {cc_map, said} = withControls(fresh.live, fresh.live.slots);
  if (!said.length) return;
  const r = await put(`/presets/${n}`, {...fresh.live, cc_map});
  if (!r.ok) { alert((await r.json()).detail); return; }
  savedNote.textContent = said.join(', ');
  clearTimeout(savedTimer);
  savedTimer = setTimeout(() => { savedNote.textContent = ''; }, 6000);
  await refresh();
}

// A CC nothing sends and nothing listens to: not on the box, not declared by
// any control, not where the patch has put one.
function freeCC(cc_map) {
  const used = new Set([...Object.keys(surfaces[surfaceId].ccs).map(Number),
                        ...Object.values(cc_map),
                        ...controls.filter(c => c.kind === 'cc').flatMap(c => [c.number, c.default])]);
  for (let cc = CC_MAX; cc >= 0; cc--) if (!used.has(cc)) return cc;
  return CC_MAX;
}

// Take a control off the knob or fader that was clicked: it goes back to the CC
// it was declared with, which is not on this box.
function unassignBar(spot) {
  mapBox.querySelector('.map-menu')?.remove();
  mapBox.querySelector('.map-prompt')?.remove();
  const bar = document.createElement('div');
  bar.className = 'map-prompt';
  const msg = document.createElement('span');
  msg.textContent = `${surfaces[surfaceId].ccs[spot.dataset.cc]}: take off`;
  bar.append(msg);
  for (const name of JSON.parse(spot.dataset.names ?? '[]')) {
    const b = document.createElement('button');
    b.textContent = name;
    b.onclick = async () => {
      const n = rig.selected;
      if (n === null) return;
      const fresh = await get(`/presets/${n}`);
      const {[name]: _, ...cc_map} = fresh.live.cc_map;
      // Left out of the map a control goes back to the CC it was declared with, and
      // one declared on this very knob would never leave it, so it is parked.
      const declared = controls.find(c => c.kind === 'cc' && c.comments[0] === name)?.default;
      if (declared === Number(spot.dataset.cc)) cc_map[name] = freeCC(cc_map);
      const r = await put(`/presets/${n}`, {...fresh.live, cc_map});
      if (!r.ok) { alert((await r.json()).detail); return; }
      await refresh();
    };
    bar.append(b);
  }
  const cancel = document.createElement('button');
  cancel.textContent = 'cancel';
  cancel.onclick = () => bar.remove();
  bar.append(cancel);
  mapBox.prepend(bar);
}

// A menu of the controls, to put one on the knob or fader that was clicked.
function assignMenu(spot) {
  const cc = Number(spot.dataset.cc);
  mapBox.querySelector('.map-menu')?.remove();
  const box = document.createElement('div');
  box.className = 'fpick map-menu';
  mapBox.prepend(box);

  const surface = surfaces[surfaceId];
  const where = (c) => surface.ccs[(patchMap()[c.comments[0]]) ?? c.number] ?? '';
  const open = fieldMenu(box, null, async (name) => {
    box.remove();
    const n = rig.selected;
    if (n === null) return;
    const fresh = await get(`/presets/${n}`);
    const r = await put(`/presets/${n}`, {...fresh.live, cc_map: {...fresh.live.cc_map, [name]: cc}});
    if (!r.ok) { alert((await r.json()).detail); return; }
    await refresh();
  }, {
    placeholder: `put on ${surface.ccs[cc]}: search controls`,
    noMap: true,
    entries: () => controls.filter(c => c.kind === 'cc' && !c.hidden && c.comments.length)
        .map(c => ({group: fieldOf(c.comments[0]), text: c.comments[0], hint: where(c), value: c.comments[0]}))
        .sort((a, b) => a.group.localeCompare(b.group) || a.text.localeCompare(b.text)),
  });
  open();
}
const patchMap = () => views[rig.selected]?.live?.cc_map ?? {};

// ---- keeping up ----------------------------------------------------------

// Which preset the half-built formulas belong to. Another one has its own slots.
let formulasFor = null;

// What the effects list was last drawn from. The poll comes every second; a list that
// is torn down and rebuilt with nothing new in it flickers under the scrolling.
let effectsDrawn = '';

async function refresh() {
  [rig, views, controls] = await Promise.all([get('/rig'), get('/presets'), get('/controls')]);
  if (rig.selected !== formulasFor) {
    editing = {};
    formulaOpen.clear();
    trimmed.clear();
    formulasFor = rig.selected;
  }
  drawPresets();
  drawMap();
  if (!adding && !picking && !dragging && !reordering && !turning && !inUse()) {
    // Where the knobs sit is not part of what the list shows - the dials follow
    // the socket - so a knob moving must not tear the list down.
    const key = JSON.stringify([
      rig,
      Object.values(views).map(v => ({...v, live: {...v.live, ccs: null}})),
      controls.map(({value, ...c}) => c),
    ]);
    if (key !== effectsDrawn) { effectsDrawn = key; drawEffects(); }
  }
}

async function drawStats() {
  const s = await get('/stats');
  document.getElementById('fps').textContent = `${s.fps.toFixed(0)} fps`;
}

loadSurfaces().then(refresh); drawStats();

// The preset can change from the controller - a program change - so the bar
// follows it rather than showing what it was at load.
setInterval(() => { refresh(); drawStats(); }, 1000);
