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

function describe(node) {
  if (node === null || node === undefined) return 'nothing';
  if (typeof node === 'number') return fmt(node);
  if (typeof node === 'string') return node;
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
  const pick = el('select');
  pick.append(new Option('fixed', ''));
  for (const f of [...rig.fields].sort((a, b) => a.name.localeCompare(b.name)))
    pick.append(new Option(f.name, f.name));
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
const isLeaf = (n) => n === null || typeof n === 'string' || typeof n === 'number';
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

const fieldNames = () => [...rig.fields].map(f => f.name).sort((a, b) => a.localeCompare(b));

function leafEditor(key, tree, path) {
  const node = at(tree, path);
  const row = el('div', 'leaf');

  const pick = el('select', typeof node === 'string' ? 'on' : '');
  pick.title = 'a field';
  pick.append(new Option('field…', ''));
  for (const name of fieldNames()) pick.append(new Option(name, name));
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
    const pick = el('select');
    for (const name of fieldNames()) pick.append(new Option(name, name));
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

function drawEffects() {
  const main = document.getElementById('effects');
  main.innerHTML = '';
  const off = new Set(patch.off ?? []);
  const names = [...new Set(rig.slots.map(effectOf))];

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
    if (open) for (const key of keys) card.append(slotRow(key));
    main.append(card);
  }
}

// ---- the control map: what each field is wired to, down the right ------------

function collect(node, out) {
  if (typeof node === 'string') out.add(node);
  else if (node && typeof node === 'object') { collect(node.a, out); collect(node.b, out); }
}

// A formula with one field picked out - the one this row is about.
function formula(node, hl, top = true) {
  const s = el('span', 'f');
  if (node === null || node === undefined) s.textContent = 'nothing';
  else if (typeof node === 'number') s.textContent = fmt(node);
  else if (typeof node === 'string') { s.textContent = node; if (node === hl) s.className = 'f hl'; }
  else {
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
  [rig, patch, all] = await Promise.all([get('/rig'), get('/current'), get('/presets')]);
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
  if (!busy && !focused && Object.keys(editing).length === 0 && rig !== null) refresh();
}, 1000);
