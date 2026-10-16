// v3: presets first. A grid of 16, per-effect on/off and reset, a hue range
// slider that can wrap, and a hover view of what a preset holds.
const AXIS = 2;                         // the hue axis runs 0..2, so a range can wrap

const get = (p) => fetch(p).then(r => r.json());
const post = async (p, body) => {
  const r = await fetch(p, {method: 'POST', headers: {'Content-Type': 'application/json'},
                            body: body === undefined ? null : JSON.stringify(body)});
  if (!r.ok) { alert((await r.json()).detail); return null; }
  return r.json();
};

let rig = null;         // vocabulary, selection, dirty
let patch = null;       // what is playing
let all = {};           // every preset, for the hover view
let gradients = {};      // name -> stops: colour paths a hue+saturation pair can walk
let busy = false;       // a pointer is down in the effects - don't redraw under it

const effectOf = (key) => key.split('.')[0];
const slotOf = (key) => key.split('.').slice(1).join('.');
const isHue = (key) => slotOf(key).endsWith('hue');
const OPS = {add: '+', sub: '−', mul: '×', div: '÷', avg: '≈'};
const fmt = (n) => (Math.round(n * 100) / 100).toFixed(2);

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

const isGradient = (n) => n !== null && typeof n === 'object' && n.gradient !== undefined;

function describe(node) {
  if (node === null || node === undefined) return 'nothing';
  if (typeof node === 'number') return fmt(node);
  if (typeof node === 'string') return node;
  if (isGradient(node)) return `gradient ${node.gradient}(${describe(node.of)}).${node.ch ?? 'h'}`;
  return `(${describe(node.a)} ${OPS[node.op]} ${describe(node.b)})`;
}

// ---- hue: a slot as {field, start, width}, when it has that shape -----------
//
//   0.4                       a fixed hue         field null, width 0
//   param_a                   the field itself    start 0, width 1
//   mul(f, k) / div(f, k)     squeezed            start 0, width k
//   add(<any of those>, c)    shifted             start c
//
// Anything else is a custom expression, which the slider leaves alone.

function squeezed(t) {
  if (typeof t === 'string') return {field: t, width: 1};
  if (t && typeof t === 'object' && (t.op === 'mul' || t.op === 'div')) {
    const [f, k] = [t.a, t.b];
    if (typeof f === 'string' && typeof k === 'number' && (t.op === 'mul' || k !== 0))
      return {field: f, width: t.op === 'mul' ? k : 1 / k};
    if (t.op === 'mul' && typeof k === 'string' && typeof f === 'number')
      return {field: k, width: f};
  }
  return null;
}

function parseHue(t) {
  if (typeof t === 'number') return {field: null, start: t, width: 0};
  const core = squeezed(t);
  if (core) return {...core, start: 0};
  if (t && typeof t === 'object' && t.op === 'add') {
    for (const [x, c] of [[t.a, t.b], [t.b, t.a]]) {
      const inner = squeezed(x);
      if (inner && typeof c === 'number') return {...inner, start: c};
    }
  }
  return null;
}

function buildHue({field, start, width}) {
  if (field === null) return start;
  const w = Math.round(width * 1000) / 1000, s = Math.round(start * 1000) / 1000;
  let tree = field;
  if (w !== 1) tree = {op: 'mul', a: tree, b: w};
  if (s !== 0) tree = {op: 'add', a: tree, b: s};
  return tree;
}

const clampAxis = (x) => Math.max(0, Math.min(AXIS, x));

// The band between two thumbs, painted with the part of the wheel it covers.
function paintBand(band, from, to) {
  const lo = Math.min(from, to), hi = Math.max(from, to);
  const frac = Math.max((hi - lo) / AXIS, 0.002);
  band.style.left = `${lo / AXIS * 100}%`;
  band.style.width = `${frac * 100}%`;
  const inner = band.firstChild;
  inner.style.width = `${100 / frac}%`;
  inner.style.left = `${-(lo / AXIS) / frac * 100}%`;
}

function hueControl(key, hue) {
  const box = el('div', 'hue');
  const {field, start, width} = hue;

  const row = el('div', 'hue-row');
  const pick = makeFieldPicker('fixed');
  pick.value = field ?? '';
  const readout = el('span');
  row.append(el('span', null, 'driven by'), pick, readout);

  const bar = el('div', 'hue-bar');
  bar.append(el('div', 'wheel'));
  const band = el('div', 'band');
  band.append(el('div'));
  bar.append(band);

  const mk = (cls, value) => {
    const r = el('input', cls);
    r.type = 'range'; r.min = '0'; r.max = String(AXIS); r.step = '0.01';
    r.value = String(clampAxis(value));
    return r;
  };
  const a = mk('start', start), b = mk('end', start + width);
  b.disabled = field === null;          // a fixed hue has no range to set
  bar.append(a, b);

  const show = () => {
    const s = parseFloat(a.value), e = parseFloat(b.value);
    paintBand(band, s, field === null ? s : e);
    readout.textContent = field === null
      ? `hue ${fmt(s)}`
      : `${fmt(s)} ${e >= s ? '→' : '←'} ${fmt(e)}`;
  };
  show();

  const commit = () => {
    const s = parseFloat(a.value), e = parseFloat(b.value);
    write(key, buildHue({field: pick.value || null, start: s,
                         width: pick.value ? e - s : 0}));
  };
  a.oninput = b.oninput = show;
  a.onchange = b.onchange = commit;
  pick.onchange = () => {
    // Going from fixed to a field starts at width 1 - the whole wheel once.
    const f = pick.value || null;
    write(key, buildHue({field: f, start, width: f ? (field ? width : 1) : 0}));
  };

  box.append(row, bar);
  return box;
}

// ---- composing: the tree editor -----------------------------------------------
// A slot is a tree: a field name, a constant, or an operation over two of them.
// Edits that leave an operand empty are held here until every one is filled.

let editing = {};                       // "effect.slot" -> partial tree
const opened = new Set();               // slots showing the full editor

const at = (tree, path) => path.reduce((n, step) => n[step], tree);
const isLeaf = (n) => n === null || typeof n === 'string' || typeof n === 'number' || isGradient(n);
const complete = (n) => n === null ? false : isLeaf(n) ? true : complete(n.a) && complete(n.b);
const treeOf = (key) => key in editing ? editing[key] : (patch.slots[key] ?? null);

function replace(tree, path, value) {
  if (path.length === 0) return value;
  const [step, ...rest] = path;
  return {...tree, [step]: replace(tree[step], rest, value)};
}

function redrawSlot(key, tree) {
  editing[key] = tree;
  if (complete(tree)) { delete editing[key]; write(key, tree); }
  else drawAll();
}

const GROUPS = ['fields', 'faders', 'pads', 'artnet'];       // the order dropdowns list them in
const fieldNames = () => sortedFields().map(f => f.name);
function sortedFields() {
  const rank = (f) => { const i = GROUPS.indexOf(f.group); return i < 0 ? GROUPS.length : i; };
  return [...rig.fields].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
}

// Which controller's labels are drawn solid. Starts as the one the rig found at
// startup; the toggle in the effects bar overrides it, remembered per browser.
// It is only what the page highlights - the rig keeps the mapping it started with.
const CONTROLLERS = {akai: 'Akai', beatstep: 'BeatStep'};
const viewController = () => {
  let pref = null;
  try { pref = localStorage.getItem('v3.controller'); } catch {}
  return pref in CONTROLLERS ? pref : rig.controller;
};

// A field dropdown. Native selects cannot colour part of an option, and these
// show what plays each field on each controller - Akai in teal, BeatStep in
// violet, the one plugged in drawn solid. It stands in for a <select>: `value`
// reads and writes the field name ('' for the placeholder), `onchange` fires
// when one is picked, and `disabled` works.
function makeFieldPicker(placeholder, cls = '') {
  const box = el('div', 'fpick' + (cls ? ` ${cls}` : ''));
  const btn = el('button', 'fpick-btn');
  btn.type = 'button';
  let value = '', disabled = false;

  const chips = (name) => {
    const out = [];
    for (const [c, label] of Object.entries(rig.controls?.[name] ?? {}))
      out.push(el('span', `chip ${c}` + (c === viewController() ? ' live' : ''), label));
    return out;
  };
  const show = () => {
    btn.replaceChildren(el('span', 'fpick-name', value || placeholder || '…'), ...(value ? chips(value) : []),
                        el('span', 'fpick-caret', '▾'));
    btn.disabled = disabled;
  };

  const list = el('div', 'fpick-list');
  const close = () => { box.classList.remove('open'); list.remove(); document.removeEventListener('pointerdown', away, true); };
  const away = (ev) => { if (!box.contains(ev.target)) close(); };
  const choose = (name) => { value = name; show(); close(); box.onchange?.(); };

  const item = (name, label) => {
    const row = el('div', 'fpick-item' + (name === value ? ' on' : ''));
    row.append(el('span', 'fpick-name', label), ...chips(name));
    row.onclick = () => choose(name);
    return row;
  };
  btn.onclick = () => {
    if (box.classList.contains('open')) return close();
    list.replaceChildren();
    const legend = el('div', 'fpick-legend');
    legend.append(el('span', 'chip akai live', 'Akai'), el('span', 'chip beatstep live', 'BeatStep'));
    list.append(legend);
    if (placeholder) list.append(item('', placeholder));
    for (const group of GROUPS) {
      const mine = sortedFields().filter(f => f.group === group);
      if (!mine.length) continue;
      list.append(el('div', 'fpick-group', group));
      for (const f of mine) list.append(item(f.name, f.name));
    }
    box.classList.add('open');
    box.append(list);
    list.querySelector('.on')?.scrollIntoView({block: 'nearest'});
    document.addEventListener('pointerdown', away, true);
  };

  Object.defineProperty(box, 'value', {get: () => value, set: (v) => { value = v ?? ''; show(); }});
  Object.defineProperty(box, 'disabled', {get: () => disabled, set: (v) => { disabled = !!v; show(); }});
  box.append(btn);
  show();
  return box;
}

function leafEditor(key, tree, path) {
  const node = at(tree, path);
  const row = el('div', 'leaf');

  const pick = makeFieldPicker('field…', typeof node === 'string' ? 'on' : '');
  pick.title = 'a field';
  pick.value = typeof node === 'string' ? node : '';
  pick.onchange = () => { if (pick.value) redrawSlot(key, replace(tree, path, pick.value)); };

  // Whatever is here becomes the first operand, so this doubles as "wrap what I have".
  const math = el('button', 'op', '+ − × ÷');
  math.title = 'combine with something else';
  math.onclick = () => redrawSlot(key, replace(tree, path, {op: 'mul', a: node, b: null}));

  row.append(pick, math);

  if (typeof node === 'number') {
    const n = el('input', 'num on');
    n.type = 'number'; n.step = '0.01'; n.value = String(node);
    n.onchange = () => { if (n.value !== '') redrawSlot(key, replace(tree, path, parseFloat(n.value))); };
    row.append(n);
  } else {
    const c = el('button', null, '#');
    c.title = 'a constant';
    c.onclick = () => redrawSlot(key, replace(tree, path, 0.5));
    row.append(c);
  }
  if (node === null) row.append(el('span', 'dim', 'empty'));
  return row;
}

function nodeEditor(key, tree, path) {
  const node = at(tree, path);
  if (isGradient(node)) {      // made by the gradient picker, changed there
    const row = el('div', 'leaf');
    row.append(el('span', 'dim', describe(node)));
    return row;
  }
  if (isLeaf(node)) return leafEditor(key, tree, path);

  const box = el('div', 'node');
  const head = el('div', 'ops');
  for (const [name, glyph] of Object.entries(OPS)) {
    const b = el('button', name === node.op ? 'on' : '', glyph);
    b.title = name;
    b.onclick = () => redrawSlot(key, replace(tree, path, {...node, op: name}));
    head.append(b);
  }
  const drop = el('button', 'drop', '⨯');
  drop.title = 'drop this operation, keep the first operand';
  drop.onclick = () => redrawSlot(key, replace(tree, path, node.a));
  head.append(drop);

  const kids = el('div', 'kids');
  kids.append(nodeEditor(key, tree, [...path, 'a']), nodeEditor(key, tree, [...path, 'b']));
  box.append(head, kids);
  return box;
}

// ---- one slot ----------------------------------------------------------------

function slotRow(key) {
  const tree = treeOf(key);
  const hue = isHue(key) && tree !== null && complete(tree) ? parseHue(tree) : null;
  const custom = tree !== null && !hue && !isLeaf(tree);
  const showTree = opened.has(key) || key in editing || custom;

  const row = el('div', 'slot' + (tree === null ? ' empty' : ''));
  row.dataset.key = key;
  row.append(el('span', 'name', slotOf(key)));

  if (hue) {
    row.append(hueControl(key, hue));
  } else if (typeof tree === 'string') {
    const pick = makeFieldPicker(null);
    pick.value = tree;
    pick.onchange = () => write(key, pick.value);
    row.append(pick);
  } else if (typeof tree === 'number') {
    const wrap = el('div', 'quick');
    const s = el('input');
    s.type = 'range'; s.min = '0'; s.max = '1'; s.step = '0.01'; s.value = String(Math.min(tree, 1));
    const n = el('span', 'expr', fmt(tree));
    s.oninput = () => { n.textContent = fmt(parseFloat(s.value)); };
    s.onchange = () => write(key, parseFloat(s.value));
    wrap.append(s, n);
    row.append(wrap);
  } else {
    row.append(el('span', 'expr', tree === null ? 'nothing' : describe(tree)));
  }

  const f = el('button', 'fx' + (showTree ? ' on' : ''), 'ƒ');
  f.title = 'compose: combine fields and constants';
  f.disabled = custom || key in editing;      // an expression is only ever shown open
  f.onclick = () => { opened.has(key) ? opened.delete(key) : opened.add(key); drawAll(); };
  row.append(f);

  if (showTree) {
    const t = el('div', 'tree');
    t.append(nodeEditor(key, tree, []));
    row.append(t);
  }
  return row;
}

async function write(key, tree) {
  if (await post('/current', {ccs: {}, slots: {[key]: tree}})) await refresh();
}

// ---- effects: collapsible, down the left -------------------------------------

const store = {
  get() { try { return new Set(JSON.parse(localStorage.getItem('v3.expanded') ?? '[]')); }
          catch { return new Set(); } },
  put(s) { try { localStorage.setItem('v3.expanded', JSON.stringify([...s])); } catch {} },
};
const expanded = store.get();           // effects are collapsed unless opened

function expand(name) { expanded.add(name); store.put(expanded); }

// Effects that are on float to the top. The order is only recomputed when the
// set of off effects changes (a toggle or a preset load), so a card does not
// jump away from under the pointer on every poll.
let orderFor = null, order = [];
let stashedOn = [];     // what "all off" switched off, so it can put them back

function effectOrder(off) {
  const key = JSON.stringify([...off].sort());
  if (key !== orderFor) {
    orderFor = key;
    const names = [...new Set(rig.slots.map(effectOf))];
    order = [...names.filter(n => !off.has(n)), ...names.filter(n => off.has(n))];
  }
  return order;
}

function drawEffects() {
  const main = document.getElementById('effects');
  main.innerHTML = '';
  const off = new Set(patch.off ?? []);
  const names = effectOrder(off);

  const bar = el('div', 'effects-bar');
  const anyOn = names.some(n => !off.has(n));
  const allBtn = el('button', 'all-off', anyOn ? 'all off' : (stashedOn.length ? 'restore' : 'all on'));
  allBtn.title = anyOn ? 'switch every effect off' : 'switch the effects back on';
  allBtn.onclick = async () => {
    if (anyOn) stashedOn = names.filter(n => !off.has(n));
    const back = stashedOn.length ? stashedOn : null;
    const body = anyOn ? {enabled: false} : {enabled: true, names: back};
    if (await post('/effects/enabled', body)) { if (!anyOn) stashedOn = []; await refresh(); }
  };
  bar.append(allBtn, el('span', 'dim', `${names.filter(n => !off.has(n)).length}/${names.length} on`));

  const which = el('div', 'ctl-toggle');
  which.title = rig.controller
    ? `which controller's labels are lit in the field menus (the rig found: ${CONTROLLERS[rig.controller] ?? rig.controller})`
    : 'which controller\'s labels are lit in the field menus';
  which.append(el('span', 'dim', 'controller'));
  for (const [id, name] of Object.entries(CONTROLLERS)) {
    const b = el('button', `chip ${id}` + (viewController() === id ? ' live' : ''), name);
    b.onclick = () => { try { localStorage.setItem('v3.controller', id); } catch {} drawAll(); };
    which.append(b);
  }
  if (rig.controller) which.append(el('span', 'dim', `found ${CONTROLLERS[rig.controller] ?? rig.controller}`));
  bar.append(which);
  main.append(bar);

  for (const name of names) {
    const keys = rig.slots.filter(k => effectOf(k) === name);
    const open = expanded.has(name);
    const card = el('section', 'effect' + (off.has(name) ? ' off' : '') + (open ? ' open' : ''));
    card.dataset.effect = name;
    const head = el('div', 'effect-head');

    const title = el('button', 'title');
    title.append(el('span', 'chev', open ? '▾' : '▸'), el('b', null, name));
    const wired = keys.filter(k => (patch.slots[k] ?? null) !== null).length;
    title.append(el('span', 'dim', `${wired}/${keys.length}`));
    title.onclick = () => {
      open ? expanded.delete(name) : expanded.add(name);
      store.put(expanded);
      drawAll();
    };

    const sw = el('button', 'switch' + (off.has(name) ? '' : ' on'));
    sw.title = off.has(name) ? `turn ${name} on` : `turn ${name} off`;
    sw.onclick = async () => {
      if (await post(`/effects/${name}/enabled`, {enabled: off.has(name)})) await refresh();
    };

    const reset = el('button', 'reset', 'reset');
    reset.title = 'set every slot of this effect to 0 (revert undoes it)';
    reset.onclick = async () => {
      if (!confirm(`Set every slot of ${name} to 0?`)) return;
      for (const k of keys) { delete editing[k]; opened.delete(k); }
      if (await post(`/effects/${name}/reset`)) await refresh();
    };

    head.append(title, sw, reset);
    card.append(head);
    if (open) {
      for (const pair of gradientPairs(keys)) card.append(gradientPicker(pair));
      for (const key of keys) card.append(slotRow(key));
    }
    main.append(card);
  }
}

// ---- the control map: what each field is wired to, down the right ------------

function collect(node, out) {
  if (typeof node === 'string') out.add(node);
  else if (isGradient(node)) collect(node.of, out);
  else if (node && typeof node === 'object') { collect(node.a, out); collect(node.b, out); }
}

// A formula with one field picked out - the one this row is about.
function formula(node, hl, top = true) {
  const s = el('span', 'f');
  if (node === null || node === undefined) s.textContent = 'nothing';
  else if (typeof node === 'number') s.textContent = fmt(node);
  else if (typeof node === 'string') { s.textContent = node; if (node === hl) s.className = 'f hl'; }
  else if (isGradient(node)) {
    s.append(`gradient ${node.gradient}(`, formula(node.of, hl, true), `).${node.ch ?? 'h'}`);
  } else {
    if (!top) s.append('(');
    s.append(formula(node.a, hl, false), ` ${OPS[node.op]} `, formula(node.b, hl, false));
    if (!top) s.append(')');
  }
  return s;
}

// One place a field is used: "net (amp)", and the formula if it is more than
// the field on its own.
function useButton(key, tree, field, off) {
  const effect = effectOf(key);
  const u = el('button', 'use' + (off.has(effect) ? ' off' : ''));
  u.append(el('span', 'where', `${effect} (${slotOf(key)})`));
  if (tree !== field) u.append(formula(tree, field));
  u.onclick = () => reveal(key);
  return u;
}

// Every slot that mentions each field: field -> [{key, tree}]
function usesByField() {
  const uses = {};
  for (const [key, tree] of Object.entries(patch.slots)) {
    const found = new Set();
    collect(tree, found);
    for (const f of found) (uses[f] ??= []).push({key, tree});
  }
  return uses;
}

// One control on the unit: what it is called there, the field it sends, and
// everything that field drives.
function controlCell(kind, id, ctl, uses, off, detail) {
  const field = ctl?.field ?? null;
  const used = field ? (uses[field] ?? []) : [];
  const cell = el('div', `ctl ${kind}` + (field ? ' mapped' : '') + (used.length ? ' used' : ''));
  cell.append(el('span', 'ctl-id', id));
  if (!field) return cell;

  cell.append(el('b', 'ctl-field', field));
  if (detail) cell.append(el('span', 'dim', detail));
  for (const {key, tree} of used) cell.append(useButton(key, tree, field, off));
  if (!used.length) cell.append(el('span', 'dim', 'not patched'));
  if (rig.tunable?.[field]) cell.append(tuneButton(field));
  return cell;
}

function drawMap() {
  const side = document.getElementById('map');
  side.innerHTML = '';
  side.append(el('h3', null, `controls · ${AKAI.name}`));

  const off = new Set(patch.off ?? []);
  const uses = usesByField();
  const onUnit = new Set();

  // A row of controls. Unmapped ones squeeze to a sliver, so the mapped ones
  // get the width - and take it back as more get mapped.
  const row = (title, kind, ctls, prefix, detail) => {
    side.append(el('div', 'bank-title', title));
    const r = el('div', 'bank ' + kind);
    r.style.gridTemplateColumns = ctls.map(c => c ? 'minmax(0, 1fr)' : '34px').join(' ');
    ctls.forEach((c, i) => {
      if (c?.field) onUnit.add(c.field);
      r.append(controlCell(kind, `${prefix}${i + 1}`, c, uses, off, c && detail(c)));
    });
    side.append(r);
  };
  row('knobs', 'knob', AKAI.knobs, 'K', () => '');
  row('faders', 'fader', AKAI.faders, 'F', c => c.cc !== undefined ? `cc ${c.cc}` : '');
  row('buttons', 'button', AKAI.buttons, 'B', () => '');

  side.append(el('div', 'bank-title', 'pads'));
  const grid = el('div', 'pads');
  for (const padRow of AKAI.pads) for (const pad of padRow) {
    if (pad.field) onUnit.add(pad.field);
    grid.append(controlCell('pad', `pad ${pad.n}`, pad, uses, off,
                            pad.note !== undefined ? `note ${pad.note}` : ''));
  }
  side.append(grid);

  // Fields the unit has no control for (yet): still worth knowing where they go.
  const rest = rig.fields.filter(f => !onUnit.has(f.name));
  const placed = rest.filter(f => uses[f.name]);
  if (placed.length) side.append(el('div', 'bank-title', 'not on the controller'));
  for (const f of placed) {
    const box = el('div', 'field');
    const head = el('div', 'field-head');
    head.append(el('b', null, f.name), el('span', 'dim', f.kind.replace(/Field$/, '')));
    box.append(head);
    for (const {key, tree} of uses[f.name]) box.append(useButton(key, tree, f.name, off));
    side.append(box);
  }
  const idle = rest.filter(f => !uses[f.name]).map(f => f.name);
  if (idle.length) side.append(el('p', 'unused', `not patched: ${idle.join(', ')}`));
}

// Open the effect that owns a slot and bring the slot into view.
function reveal(key) {
  expand(effectOf(key));
  drawAll();
  const row = [...document.querySelectorAll('.slot')].find(r => r.dataset.key === key);
  if (!row) return;
  row.scrollIntoView({block: 'center', behavior: 'smooth'});
  row.classList.add('flash');
  setTimeout(() => row.classList.remove('flash'), 1200);
}

// ---- tunable fields: a bloom's envelope, dragged out ----------------------------

const SPAN = 10000;     // ms across the editor - the longest a bloom can take

function tuneButton(field) {
  const b = el('button', 'tune', 'envelope');
  b.title = `shape ${field}: how it comes on, holds and fades`;
  b.onclick = (ev) => { ev.stopPropagation(); openEnvelope(field); };
  return b;
}

function openEnvelope(field) {
  document.getElementById('env-modal')?.remove();
  const cur = {...rig.tunable[field], ...(patch.params?.[field] ?? {})};
  const W = 520, H = 190, PAD = 14;
  const X = (ms) => PAD + (ms / SPAN) * (W - 2 * PAD);
  const MS = (x) => Math.round(Math.min(Math.max((x - PAD) / (W - 2 * PAD), 0), 1) * SPAN);
  const Y1 = PAD, Y0 = H - PAD - 16;      // top (level 1) and bottom (level 0)

  const overlay = el('div', 'modal-overlay');
  overlay.id = 'env-modal';
  const box = el('div', 'modal');
  box.append(el('h4', null, `${field} · envelope`));

  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.classList.add('env');
  const area = document.createElementNS(svgNS, 'path'); area.setAttribute('class', 'env-area');
  const line = document.createElementNS(svgNS, 'path'); line.setAttribute('class', 'env-line');
  svg.append(area, line);
  // The hold handle is smaller and drawn last, so a short hold still leaves
  // the attack handle's rim to grab.
  const mkHandle = (r = 9) => {
    const c = document.createElementNS(svgNS, 'circle');
    c.setAttribute('r', String(r)); c.setAttribute('class', 'env-handle'); svg.append(c); return c;
  };
  const hAttack = mkHandle(), hDecay = mkHandle(), hHold = mkHandle(5);
  for (let s2 = 0; s2 <= SPAN; s2 += 1000) {
    const t = document.createElementNS(svgNS, 'text');
    t.setAttribute('x', X(s2)); t.setAttribute('y', H - 2); t.setAttribute('class', 'env-tick');
    t.setAttribute('text-anchor', s2 === 0 ? 'start' : s2 === SPAN ? 'end' : 'middle');
    t.textContent = `${s2 / 1000}s`; svg.append(t);
  }

  const ease = (x) => x * x * (3 - 2 * x);     // the same curve the rig uses
  const draw = () => {
    const a = cur.attack, h = cur.hold, d = cur.decay;
    const pts = [];
    for (let i = 0; i <= 24; i++) pts.push([a * i / 24, ease(i / 24)]);
    pts.push([a + h, 1]);
    for (let i = 1; i <= 24; i++) pts.push([a + h + d * i / 24, ease(1 - i / 24)]);
    const path = pts.map(([t, v], i) => `${i ? 'L' : 'M'}${X(t)},${Y0 - v * (Y0 - Y1)}`).join(' ');
    line.setAttribute('d', path);
    area.setAttribute('d', `${path} L${X(a + h + d)},${Y0} L${X(0)},${Y0} Z`);
    for (const [c, t, v] of [[hAttack, a, 1], [hHold, a + h, 1], [hDecay, a + h + d, 0]]) {
      c.setAttribute('cx', X(t)); c.setAttribute('cy', Y0 - v * (Y0 - Y1));
    }
    readout.textContent = `attack ${(a / 1000).toFixed(2)}s · hold ${(h / 1000).toFixed(2)}s · ` +
                          `decay ${(d / 1000).toFixed(2)}s`;
    dens.textContent = `${Math.round(cur.density * 100)}% of edges per press`;
  };

  // Each handle sets one time: where the attack ends, where the hold ends,
  // where the decay ends. The others keep their own lengths.
  const drag = (handle, set) => {
    handle.onpointerdown = (ev) => {
      handle.setPointerCapture(ev.pointerId);
      const move = (e) => {
        const r = svg.getBoundingClientRect();
        set(MS((e.clientX - r.left) * (W / r.width)));
        draw();
      };
      const up = async () => {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', up);
        await commit();
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', up);
    };
  };
  const MIN = 20;
  drag(hAttack, (t) => { cur.attack = Math.max(t, MIN); });
  drag(hHold, (t) => { cur.hold = Math.max(t - cur.attack, 0); });
  drag(hDecay, (t) => { cur.decay = Math.max(t - cur.attack - cur.hold, MIN); });

  const readout = el('div', 'env-readout');
  const dens = el('span', 'dim');
  const density = el('input'); density.type = 'range';
  density.min = '1'; density.max = '100'; density.step = '1';
  density.value = String(Math.round(cur.density * 100));
  density.oninput = () => { cur.density = density.value / 100; draw(); };
  density.onchange = () => commit();
  const densRow = el('div', 'env-density');
  densRow.append(el('span', null, 'how many'), density, dens);

  const commit = async () => {
    if (await post('/current', {ccs: {}, slots: {}, params: {[field]: {...cur}}})) await refresh();
  };

  const note = el('p', 'dim', 'Drag the dots: where the attack ends, where the hold ends, where the decay ends. ' +
                              'Pad presses and sequenced notes both bloom with this shape.');
  const reset = el('button', null, 'defaults');
  reset.onclick = async () => { Object.assign(cur, rig.tunable[field]); density.value = String(Math.round(cur.density * 100)); draw(); await commit(); };
  const close = el('button', null, 'close');
  close.onclick = () => overlay.remove();
  const foot = el('div', 'env-foot'); foot.append(reset, close);

  box.append(svg, readout, densRow, note, foot);
  overlay.append(box);
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  document.body.append(overlay);
  draw();
}

// ---- colour gradients ---------------------------------------------------------
// An effect that takes both a hue and a saturation can follow a gradient instead:
// pick one and a field to walk it, and both slots are written together.

function gradientPairs(keys) {
  const pairs = [];
  for (const hue of keys) {
    const name = slotOf(hue);
    if (!name.endsWith('hue')) continue;
    const prefix = name.slice(0, -3);
    const sat = [`${prefix}saturation`, `${prefix}sat`]
      .map(n => keys.find(k => slotOf(k) === n)).find(Boolean);
    if (sat) pairs.push({hue, sat, label: prefix.replace(/_$/, '') || 'colour'});
  }
  return pairs;
}

function gradientPicker({hue, sat, label}) {
  const cur = patch.slots[hue];
  const now = isGradient(cur) ? cur : null;
  const row = el('div', 'gradient-row');
  row.append(el('span', 'name', `${label} gradient`));

  const pick = el('select');
  pick.append(new Option('none', ''));
  for (const name of Object.keys(gradients).sort()) pick.append(new Option(name, name));
  pick.value = now && gradients[now.gradient] ? now.gradient : '';

  const driver = makeFieldPicker(null);
  driver.title = 'the field that says where along the gradient to be';
  const driverName = now && typeof now.of === 'string' ? now.of : null;
  if (driverName) driver.value = driverName;
  driver.disabled = !now;

  const apply = async (gradient, of) => {
    const slots = gradient
      ? {[hue]: {gradient, of, ch: 'h'}, [sat]: {gradient, of, ch: 's'}}
      : {[hue]: of, [sat]: 1};           // back to a plain hue, fully saturated
    if (await post('/current', {ccs: {}, slots})) await refresh();
  };
  pick.onchange = () => apply(pick.value || null, driver.value || fieldNames()[0]);
  driver.onchange = () => apply(pick.value, driver.value);

  const edit = el('button', null, pick.value ? 'edit' : 'new');
  edit.onclick = () => openGradient(pick.value || null);
  row.append(pick, el('span', 'dim', 'moved by'), driver, edit);
  if (now && driverName === null) row.append(el('span', 'dim', describe(now.of)));
  return row;
}

const hsv2rgb = (h, s, v) => {
  h = ((h % 1) + 1) % 1;
  const i = Math.floor(h * 6), f = h * 6 - i;
  const p = v * (1 - s), q = v * (1 - f * s), u = v * (1 - (1 - f) * s);
  return [[v, u, p], [q, v, p], [p, v, u], [p, q, v], [u, p, v], [v, p, q]][i % 6]
    .map(c => Math.round(c * 255));
};
const css = (h, s, v) => `rgb(${hsv2rgb(h, s, v).join(',')})`;

// The same walk the rig does: hue the short way round, the rest in a straight line.
function colourAt(stops, p) {
  if (p <= stops[0].at) return stops[0];
  for (let i = 1; i < stops.length; i++) {
    const a = stops[i - 1], b = stops[i];
    if (p <= b.at) {
      const t = b.at === a.at ? 0 : (p - a.at) / (b.at - a.at);
      const dh = (((b.h - a.h + 0.5) % 1) + 1) % 1 - 0.5;
      return {h: (((a.h + dh * t) % 1) + 1) % 1, s: a.s + (b.s - a.s) * t, v: a.v + (b.v - a.v) * t};
    }
  }
  return stops[stops.length - 1];
}

function openGradient(existing) {
  document.getElementById('gradient-modal')?.remove();
  let name = existing ?? '';
  const stops = (existing ? gradients[existing] : [
    {at: 0, h: 0.08, s: 1, v: 1}, {at: 1, h: 0.75, s: 1, v: 1}]).map(x => ({...x}));
  let sel = 0;

  const overlay = el('div', 'modal-overlay');
  overlay.id = 'gradient-modal';
  const box = el('div', 'modal');
  box.append(el('h4', null, existing ? `gradient · ${existing}` : 'new gradient'));

  const nameIn = el('input'); nameIn.placeholder = 'name (letters, digits, - _)';
  nameIn.value = name; nameIn.disabled = !!existing;
  box.append(nameIn);

  // the path itself: a gradient with a handle per stop
  const bar = el('div', 'jbar');
  const handles = el('div', 'jhandles');
  const sorted = () => [...stops].sort((a, b) => a.at - b.at);
  const drawBar = () => {
    const ss = sorted();
    const steps = 40, colours = [];
    for (let i = 0; i <= steps; i++) {
      const c = colourAt(ss, i / steps);
      colours.push(`${css(c.h, c.s, c.v)} ${i / steps * 100}%`);
    }
    bar.style.background = `linear-gradient(90deg, ${colours.join(',')})`;
    handles.innerHTML = '';
    stops.forEach((st, i) => {
      const h = el('div', 'jstop' + (i === sel ? ' on' : ''));
      h.style.left = `${st.at * 100}%`;
      h.style.background = css(st.h, st.s, st.v);
      h.onpointerdown = (ev) => {
        ev.stopPropagation(); sel = i; h.setPointerCapture(ev.pointerId);
        const move = (e) => {
          const r = bar.getBoundingClientRect();
          st.at = Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1);
          drawAll2();
        };
        const up = () => { h.removeEventListener('pointermove', move); h.removeEventListener('pointerup', up); };
        h.addEventListener('pointermove', move); h.addEventListener('pointerup', up);
        drawAll2();
      };
      handles.append(h);
    });
  };
  bar.onpointerdown = (ev) => {              // click the path to add a stop there
    const r = bar.getBoundingClientRect();
    const at = Math.min(Math.max((ev.clientX - r.left) / r.width, 0), 1);
    const c = colourAt(sorted(), at);
    stops.push({at, h: c.h, s: c.s, v: c.v});
    sel = stops.length - 1; drawAll2();
  };
  bar.append(handles);

  // the wheel: angle is hue, distance from the middle is saturation
  const SZ = 170, wheel = el('canvas', 'jwheel');
  wheel.width = wheel.height = SZ;
  const drawWheel = () => {
    const ctx = wheel.getContext('2d'), img = ctx.createImageData(SZ, SZ), r0 = SZ / 2;
    const v = stops[sel].v;
    for (let y = 0; y < SZ; y++) for (let x = 0; x < SZ; x++) {
      const dx = x - r0 + 0.5, dy = y - r0 + 0.5, d = Math.hypot(dx, dy) / r0;
      const i = (y * SZ + x) * 4;
      if (d > 1) { img.data[i + 3] = 0; continue; }
      const [R, G, B] = hsv2rgb(Math.atan2(dy, dx) / (2 * Math.PI), d, v);
      img.data.set([R, G, B, 255], i);
    }
    ctx.putImageData(img, 0, 0);
    const st = stops[sel], a = st.h * 2 * Math.PI, rr = st.s * r0;
    ctx.beginPath(); ctx.arc(r0 + Math.cos(a) * rr, r0 + Math.sin(a) * rr, 7, 0, 7);
    ctx.lineWidth = 2; ctx.strokeStyle = '#fff'; ctx.stroke();
  };
  const pickColour = (ev) => {
    const r = wheel.getBoundingClientRect(), k = SZ / r.width, r0 = SZ / 2;
    const dx = (ev.clientX - r.left) * k - r0, dy = (ev.clientY - r.top) * k - r0;
    stops[sel].h = (((Math.atan2(dy, dx) / (2 * Math.PI)) % 1) + 1) % 1;
    stops[sel].s = Math.min(Math.hypot(dx, dy) / r0, 1);
    drawAll2();
  };
  wheel.onpointerdown = (ev) => {
    wheel.setPointerCapture(ev.pointerId); pickColour(ev);
    wheel.onpointermove = pickColour;
    wheel.onpointerup = () => { wheel.onpointermove = null; wheel.onpointerup = null; };
  };

  const value = el('input'); value.type = 'range'; value.min = '0'; value.max = '1'; value.step = '0.01';
  value.oninput = () => { stops[sel].v = parseFloat(value.value); drawAll2(); };
  const at = el('input'); at.type = 'number'; at.min = '0'; at.max = '100'; at.step = '1';
  at.onchange = () => {
    stops[sel].at = Math.min(Math.max(parseFloat(at.value) / 100, 0), 1); drawAll2();
  };
  const del = el('button', null, 'remove stop');
  del.onclick = () => { if (stops.length > 1) { stops.splice(sel, 1); sel = 0; drawAll2(); } };

  const side = el('div', 'jside');
  const field = (label, input) => { const r = el('label', 'jfield'); r.append(el('span', null, label), input); return r; };
  side.append(field('stop at %', at), field('brightness', value), del,
              el('p', 'dim', 'Click the path to add a stop, drag one to move it, click the wheel to colour it. ' +
                             'Hue goes the short way round between stops.'));
  const body = el('div', 'jbody'); body.append(wheel, side);

  const drawAll2 = () => {
    drawBar(); drawWheel();
    value.value = String(stops[sel].v); at.value = String(Math.round(stops[sel].at * 100));
  };

  const save = el('button', null, 'save gradient');
  save.onclick = async () => {
    const n = nameIn.value.trim();
    if (!n) { alert('give the gradient a name'); return; }
    const r = await fetch(`/gradients/${encodeURIComponent(n)}`, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({stops: sorted()})});
    if (!r.ok) { alert((await r.json()).detail); return; }
    overlay.remove(); await refresh();
  };
  const close = el('button', null, 'close'); close.onclick = () => overlay.remove();
  const foot = el('div', 'env-foot'); foot.append(close, save);

  box.append(bar, body, foot);
  overlay.append(box);
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  document.body.append(overlay);
  drawAll2();
}

function drawAll() { drawEffects(); drawMap(); }

// ---- presets -----------------------------------------------------------------

function drawPresets() {
  const grid = document.getElementById('presets');
  grid.innerHTML = '';
  for (let n = 0; n < rig.size; n++) {
    const c = el('div', 'pcell' + (rig.presets.includes(n) ? ' saved' : '') +
                        (rig.dirty.includes(n) ? ' dirty' : '') +
                        (n === rig.selected ? ' on' : ''), String(n));
    c.onclick = async (ev) => {
      hidePeek();
      const path = ev.shiftKey ? `/presets/${n}/duplicate` : `/presets/${n}/load`;
      if (await post(path)) await refresh();
    };
    c.onmouseenter = () => showPeek(n, c);
    c.onmouseleave = hidePeek;
    grid.append(c);
  }

  const n = rig.selected, dirty = n !== null && rig.dirty.includes(n);
  for (const [id, verb] of [['save', 'save'], ['revert', 'revert']]) {
    const b = document.getElementById(id);
    b.disabled = !dirty;
    b.onclick = async () => { if (await post(`/presets/${n}/${verb}`)) await refresh(); };
  }
}

// ---- hover -------------------------------------------------------------------

function peekHue(tree) {
  const h = parseHue(tree);
  if (!h) return null;
  const mini = el('span', 'mini'), i = el('i');
  const from = clampAxis(h.start), to = clampAxis(h.start + h.width);
  i.style.left = `${Math.min(from, to) / AXIS * 100}%`;
  i.style.width = `${Math.max(Math.abs(to - from) / AXIS * 100, 1)}%`;
  mini.append(i);
  return mini;
}

function showPeek(n, anchor) {
  const p = all[n];
  if (!p) return;
  const box = document.getElementById('peek');
  box.innerHTML = '';
  box.append(el('h4', null, `preset ${n}${p.dirty ? ' · unsaved' : ''}`));

  const off = new Set(p.off ?? []);
  let quiet = 0;
  for (const name of [...new Set(rig.slots.map(effectOf))]) {
    const keys = rig.slots.filter(k => effectOf(k) === name && (p.slots[k] ?? null) !== null);
    const live = keys.filter(k => p.slots[k] !== 0);
    if (!live.length) { quiet++; continue; }

    const fx = el('div', 'fx' + (off.has(name) ? ' off' : ''));
    const b = el('b'); b.append(el('span', 'dot'), name);
    fx.append(b);
    for (const k of live) {
      const line = el('div', 'sl', `${slotOf(k)} = ${describe(p.slots[k])}`);
      if (isHue(k)) { const m = peekHue(p.slots[k]); if (m) line.append(m); }
      fx.append(line);
    }
    box.append(fx);
  }
  if (quiet) box.append(el('div', 'quiet', `${quiet} effect${quiet > 1 ? 's' : ''} with nothing patched`));

  box.hidden = false;
  const r = anchor.getBoundingClientRect();
  box.style.left = `${Math.min(r.left, window.innerWidth - 336)}px`;
  box.style.top = `${r.bottom + 8}px`;
}

function hidePeek() { document.getElementById('peek').hidden = true; }

// ---- page --------------------------------------------------------------------

async function refresh() {
  [rig, patch, all, gradients] = await Promise.all(
    [get('/rig'), get('/current'), get('/presets'), get('/gradients')]);
  drawPresets();
  drawAll();
}

async function drawStats() {
  const s = await get('/stats');
  document.getElementById('fps').textContent = `${s.fps.toFixed(0)} fps`;
}

const effectsEl = document.getElementById('effects');
effectsEl.addEventListener('pointerdown', () => { busy = true; });
window.addEventListener('pointerup', () => { busy = false; });

refresh(); drawStats();
setInterval(() => {
  drawStats();
  // The controller can change the preset or move a knob, so follow it - but
  // never redraw under a drag, an open menu, or a half-built formula.
  const focused = effectsEl.contains(document.activeElement) &&
                  document.activeElement.matches('select, input');
  const menuOpen = document.querySelector('.fpick.open') !== null;
  if (!busy && !focused && !menuOpen && Object.keys(editing).length === 0 && rig !== null) refresh();
}, 1000);
