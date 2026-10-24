// v3: effects down the left, whatever they hold on the right.

const get = (p) => fetch(p).then(r => r.json());
const post = (p) => fetch(p, {method: 'POST'});
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
const ICONS = {save: '\u{1F4BE}', revert: '\u21ba'};

const bar = document.getElementById('presets');
let cells = [];             // built once, so a redraw never swallows a click
let save = null, revert = null;

function buildPresets() {
  bar.innerHTML = '';
  cells = [];

  for (let n = 0; n < rig.size; n++) {
    const b = document.createElement('button');
    b.textContent = n;
    b.onclick = () => act(`/presets/${n}/select`);
    cells.push(b);
    bar.append(b);
  }

  // Both act on whatever is playing, so there is one of each, not one per cell.
  for (const [verb, icon] of [['commit', ICONS.save], ['revert', ICONS.revert]]) {
    const b = document.createElement('button');
    b.className = 'pcell act';
    b.textContent = icon;
    b.onclick = () => { if (rig.selected !== null) act(`/presets/${rig.selected}/${verb}`); };
    b.dataset.verb = verb;
    bar.append(b);
  }
  [save, revert] = bar.querySelectorAll('.act');
}

// What the playing preset is called. It is a box rather than a button that opens
// one, so there is nothing to open: type, and Enter or leaving it keeps the name.
// Clearing it takes the name away. A name is not part of the patch, so renaming
// is never an edit and the preset does not go dirty.
const nameBox = document.getElementById('preset-name');
const numBox = document.getElementById('preset-num');

async function rename(n, name) {
  const r = await put(`/presets/${n}/name`, {name});
  if (!r.ok) alert((await r.json()).detail);
  await refresh();                      // a name that was refused goes back to what it was
}

nameBox.onchange = () => { if (rig.selected !== null) rename(rig.selected, nameBox.value); };
nameBox.onkeydown = (ev) => {
  if (ev.key === 'Enter') nameBox.blur();
  else if (ev.key === 'Escape') { nameBox.value = rig.names[rig.selected] ?? ''; nameBox.blur(); }
};
nameBox.onfocus = () => nameBox.select();

function drawName() {
  const n = rig.selected;
  // The first sixteen are known by number; only the saved ones past them are named.
  const nameable = n !== null && n >= rig.size;
  nameBox.disabled = !nameable;
  nameBox.placeholder = n === null ? '' : nameable ? 'name this preset' : `no name for 0\u2013${rig.size - 1}`;
  nameBox.classList.toggle('dirty', n !== null && isDirty(views[n]));
  numBox.textContent = n === null ? '' : `#${n}`;

  // Half-typed text is not for the poll to take away.
  if (document.activeElement !== nameBox) nameBox.value = rig.names[n] ?? '';
}

function drawPresets() {
  if (cells.length !== rig.size) buildPresets();

  cells.forEach((b, n) => {
    b.className = 'pcell' + (rig.presets.includes(n) ? ' saved' : '') +
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
}

const fmt = (n) => (Math.round(n * 100) / 100).toFixed(2);
const OPS = {add: '+', sub: '\u2212', mul: '\u00d7', div: '\u00f7', avg: '\u2248'};

// A slot as text: what is plugged into it, however deep.
function describe(node) {
  if (node === null || node === undefined) return 'nothing';
  if (typeof node === 'number') return fmt(node);
  if (typeof node === 'string') return node;
  if (node.gradient !== undefined) return `gradient ${node.gradient}(${describe(node.of)}).${node.ch ?? 'h'}`;
  return `(${describe(node.a)} ${OPS[node.op]} ${describe(node.b)})`;
}

// ---- muting --------------------------------------------------------------

// Silencing an effect is for looking at one thing at a time. It is not part of
// the preset - the effect stays in it and nothing goes dirty - and the rig
// clears it when another preset is selected.
async function setMuted(names) {
  const r = await put('/muted', names);
  if (!r.ok) { alert((await r.json()).detail); return; }
  await refresh();
}

const isMuted = (name) => rig.muted.includes(name);

// What "mute all" silenced, so "unmute all" brings back those and nothing else. The
// rig clears every mute when a preset is selected, so this goes with it.
let silenced = [];
let silencedFor = null;

function allOff(names) {
  const anyOn = names.some(n => !isMuted(n));

  if (anyOn) {
    silenced = names.filter(n => !isMuted(n));
    silencedFor = rig.selected;
    return setMuted([...new Set([...rig.muted, ...names])]);
  }

  const back = silencedFor === rig.selected && silenced.length ? silenced : names;
  silenced = [];
  return setMuted(rig.muted.filter(n => !back.includes(n)));
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
  const active = Object.keys(rig.effects).filter(e => names.includes(e));

  const r = await put(`/presets/${n}`, {...fresh.live, active});
  if (!r.ok) { alert((await r.json()).detail); return; }
  await refresh();
}

// ---- one slot ------------------------------------------------------------

// Change one slot of the playing preset, and nothing else - read just now, as
// with the chain, so the knobs in it are where they are.
async function writeSlot(key, tree) {
  const n = rig.selected;
  if (n === null) return;

  const fresh = await get(`/presets/${n}`);
  const r = await put(`/presets/${n}`, {...fresh.live, slots: {...fresh.live.slots, [key]: tree}});
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

// What the rig holds in a slot with nothing plugged in, where that is not 0 - a
// saturation, say, which would draw white. A slot the preset says nothing about
// shows as that, since that is what is playing.
const slotDefault = (key) => {
  const [effect, ...slot] = key.split('.');
  return rig.effects[effect]?.defaults?.[slot.join('.')];
};
const emptyValue = (key) => slotDefault(key) ?? 0;
const startValue = (key) => slotDefault(key) ?? DEFAULT_CONSTANT;
const groupOf = (f) => f.group ?? 'fields';

// The menu hangs off `box`, which the caller places and whatever opens it sits
// in. This returns the thing that opens it, or closes it if it is already up.
function fieldMenu(box, current, onPick) {
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

    const menu = document.createElement('div');
    menu.className = 'fpick-list';
    const search = document.createElement('input');
    search.className = 'fpick-search';
    search.type = 'search';
    search.placeholder = 'search fields, faders, pads';
    const body = document.createElement('div');
    body.className = 'fpick-body';
    menu.append(search, body);

    let rows = [], cursor = 0;

    const item = (text, hint, value, on) => {
      const row = document.createElement('div');
      row.className = 'fpick-item' + (on ? ' on' : '');
      const t = document.createElement('span');
      t.textContent = text;
      row.append(t);
      if (hint) {
        const h = document.createElement('span');
        h.className = 'dim';
        h.textContent = hint;
        row.append(h);
      }
      row.onclick = () => choose(value);
      return row;
    };

    const render = () => {
      const terms = search.value.toLowerCase().split(/\s+/).filter(Boolean);
      const hit = (f) => terms.every(t => `${f.name} ${groupOf(f)}`.toLowerCase().includes(t));

      body.replaceChildren();
      for (const group of GROUPS) {
        const mine = rig.fields.filter(f => groupOf(f) === group && hit(f))
                               .sort((a, b) => a.name.localeCompare(b.name));
        if (!mine.length) continue;

        const head = document.createElement('div');
        head.className = 'fpick-group';
        head.textContent = group;
        body.append(head);
        for (const f of mine) body.append(item(f.name, '', f.name, f.name === current));
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
// is held as a number, or as a field squeezed into a stretch of the wheel:
//
//   0.4                       a fixed hue         no field
//   param_a                   the field itself    start 0, width 1
//   mul(f, k) / div(f, k)     squeezed            start 0, width k
//   add(<any of those>, c)    shifted             start c
//
// Anything else is a formula, which the hue control leaves alone.
const AXIS = 2;
const clampAxis = (x) => Math.max(0, Math.min(AXIS, x));
const isHueSlot = (key) => key.split('.').slice(1).join('.').endsWith('hue');

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
  const w = Math.round(width * 1000) / 1000, st = Math.round(start * 1000) / 1000;
  let tree = field;
  if (w !== 1) tree = {op: 'mul', a: tree, b: w};
  if (st !== 0) tree = {op: 'add', a: tree, b: st};
  return tree;
}

// The band between two thumbs, painted with the part of the wheel it covers.
function paintBand(band, from, to) {
  const lo = Math.min(from, to), hi = Math.max(from, to);
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
  const show = () => { const [s0, e0] = read(); paintBand(band, s0, e0); onInput(s0, e0); };
  show();

  a.oninput = b.oninput = show;
  a.onchange = b.onchange = () => onCommit(...read());

  // Typing a hue moves the one thumb.
  bar.setHue = (v) => { a.value = String(clampAxis(v)); show(); onCommit(...read()); };
  return bar;
}

// ---- formulas --------------------------------------------------------------
// A slot can hold a tree: an operation over two operands, each a number, a field
// or another operation. An edit that leaves an operand empty is held here until
// every one is filled, since the rig will not take half a formula.
let editing = {};                       // "effect.slot" -> a formula with an empty operand
const formulaOpen = new Set();          // slots showing the formula editor

const at = (tree, path) => path.reduce((n, step) => n[step], tree);
const isLeaf = (n) => n === null || typeof n !== 'object' || n.gradient !== undefined;
const complete = (n) => n === null ? false : isLeaf(n) ? true : complete(n.a) && complete(n.b);

function replace(tree, path, value) {
  if (path.length === 0) return value;
  const [step, ...rest] = path;
  return {...tree, [step]: replace(tree[step], rest, value)};
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

// ---- the parking lot -------------------------------------------------------
// Parts of a formula can be lifted out and set aside, then put back somewhere
// else. A part is a whole subtree - an operand or an operation with everything
// under it. The lot is a habit of the person working, not part of any preset, so
// it lives in the browser and follows you from slot to slot and preset to preset.
let parked = (() => { try { return JSON.parse(localStorage.getItem('v3.parked') ?? '[]'); }
                      catch { return []; } })();
const saveParked = () => { try { localStorage.setItem('v3.parked', JSON.stringify(parked)); } catch {} };
const newId = () => Math.random().toString(36).slice(2, 10);

// What is being carried: the part itself, and where it came from - a place in a
// formula ({key, path, tree}) or a spot in the lot ({lot: id}).
let dragging = null;
let overEl = null;

const startsWith = (path, prefix) => prefix.every((step, i) => path[i] === step);

function setOver(el) {
  if (overEl === el) return;
  overEl?.classList.remove('over');
  overEl = el;
  el.classList.add('over');
}
const clearOver = () => { overEl?.classList.remove('over'); overEl = null; };

function park(tree) {
  if (tree === null || tree === undefined) return;
  parked.push({id: newId(), tree});
  saveParked();
}

// Move a part: out of a formula into the lot, or out of a formula or the lot into
// an operand. Whatever was sitting in that operand is parked, so nothing is lost.
function moveSegment(from, to) {
  const part = from.lot ? parked.find(p => p.id === from.lot)?.tree : at(from.tree, from.path);
  if (part === undefined) return;

  // Picking up a whole formula copies it: the slot keeps what it has.
  const whole = !from.lot && from.path.length === 0;

  if (to.lot) {
    if (from.lot) return;                       // already there
    park(part);
    if (!whole) setFormula(from.key, replace(from.tree, from.path, null));
    drawParking();
    return;
  }

  if (!from.lot && from.key === to.key) {
    // One formula, two places in it: both edits land on the same tree.
    if (startsWith(to.path, from.path)) return;           // onto itself, or inside itself
    if (whole) return;                                    // the whole of it, into itself

    // Two places that do not contain each other trade: what was there goes to
    // where this came from, so a part can be moved to the other side of an operation.
    if (!startsWith(from.path, to.path)) {
      const there = at(from.tree, to.path);
      let swapped = replace(from.tree, from.path, there);
      swapped = replace(swapped, to.path, part);
      setFormula(to.key, swapped);
      return;
    }

    let t = replace(from.tree, from.path, null);
    park(at(t, to.path));
    t = replace(t, to.path, part);
    setFormula(to.key, t);
    drawParking();
    return;
  }

  if (from.lot) parked = parked.filter(p => p.id !== from.lot);
  else if (!whole) setFormula(from.key, replace(from.tree, from.path, null));

  park(at(to.tree, to.path));
  saveParked();
  setFormula(to.key, replace(to.tree, to.path, part));
  drawParking();
}

// Picking a part up, whichever way it was grabbed.
function beginDrag(e, box, from) {
  dragging = {from, part: from.lot ? null : at(from.tree, from.path)};
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
  g.title = 'drag this part to the parking lot, or onto another operand';
  g.ondragstart = (e) => { e.stopPropagation(); beginDrag(e, box, from); };
  g.ondragend = (e) => { e.stopPropagation(); endDrag(box); };
  return g;
}

// A whole operation, by its box: anywhere on it that is not a control. The
// innermost box under the pointer is the one that moves. The outermost box is the
// whole formula, and picking that up copies it rather than taking it out, since a
// slot cannot be left without one.
function boxDrag(box, from) {
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
    if (!dragging) return;
    e.preventDefault();
    e.stopPropagation();                        // the innermost one under the pointer wins
    setOver(el);
  };
  el.ondrop = (e) => {
    if (!dragging) return;
    e.preventDefault();
    e.stopPropagation();
    const carried = dragging;
    dragging = null;
    clearOver();
    moveSegment(carried.from, to);
  };
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

function leafEditor(key, tree, path) {
  const node = at(tree, path);
  const row = document.createElement('div');
  row.className = 'leaf fpick';

  const toggle = fieldMenu(row, typeof node === 'string' ? node : null,
                           (v) => setFormula(key, replace(tree, path, v)));
  const mode = typeof node === 'number' ? 'value' : typeof node === 'string' ? 'field' : null;

  dropTarget(row, {key, path, tree});
  if (path.length && node !== null) row.append(grip(row, {key, path, tree}));

  row.append(makeSeg(mode, [
    {label: 'constant', id: 'value', title: 'a plain number',
     onclick: () => { if (mode !== 'value') setFormula(key, replace(tree, path, DEFAULT_CONSTANT)); }},
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
    wrap.onclick = () => setFormula(key, replace(tree, path, {op: 'mul', a: node, b: null}));
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
  if (n.gradient !== undefined) return describe(n);
  return `(${explain(n)})`;
}

function explain(n) {
  if (n === null || n === undefined) return 'nothing yet';
  if (isNum(n)) return `the constant ${fmt(n)}`;
  if (typeof n === 'string') return n;
  if (n.gradient !== undefined) return describe(n);

  const {op, a, b} = n;
  const inverse = (x) => x && typeof x === 'object' && x.op === 'sub' && x.a === 1 ? x.b : null;

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
  if (op === 'avg') return `halfway between ${operand(a)} and ${operand(b)}`;
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
  out.append(paren('('), groupedText(node.a, depth + 1), ` ${OPS[node.op]} `,
             groupedText(node.b, depth + 1), paren(')'));
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
  head.className = 'ops';
  if (path.length) head.append(grip(box, {key, path, tree}));
  for (const [name, glyph] of Object.entries(OPS)) {
    const b = document.createElement('button');
    b.className = name === node.op ? 'on' : '';
    b.textContent = glyph;
    b.title = name;
    b.onclick = () => setFormula(key, replace(tree, path, {...node, op: name}));
    head.append(b);
  }
  // The + on a single value pairs that value with another, which nests the new term
  // inside. This is its counterpart for a whole operation: the operation, with
  // everything in it, becomes the first half of a new one, so a term goes around
  // the outside - at the top of the formula, around the lot.
  const outer = document.createElement('button');
  outer.className = 'outer';
  outer.textContent = '+ outer';
  outer.title = 'add a term outside this whole operation: all of it becomes the first half of a new operation, and you choose the other half';
  outer.onclick = () => setFormula(key, replace(tree, path, {op: 'mul', a: node, b: null}));
  head.append(outer);

  // Which side is which matters for - and the others read left to right.
  const flip = document.createElement('button');
  flip.className = 'flip';
  flip.textContent = '\u21c4';
  flip.title = 'swap the two sides';
  flip.onclick = () => setFormula(key, replace(tree, path, {...node, a: node.b, b: node.a}));
  head.append(flip);

  const drop = document.createElement('button');
  drop.className = 'drop';
  drop.textContent = '\u00d7';
  drop.title = 'remove this operation and keep only its first operand';
  drop.onclick = () => setFormula(key, replace(tree, path, node.a));
  head.append(drop);

  const kids = document.createElement('div');
  kids.className = 'kids';
  kids.append(nodeEditor(key, tree, [...path, 'a'], depth + 1),
              nodeEditor(key, tree, [...path, 'b'], depth + 1));
  box.append(head, kids);
  return box;
}

// Which way a slot is driven: a number, a field, or a formula.
const modeOf = (tree) => typeof tree === 'string' ? 'field'
                       : tree === null || typeof tree === 'number' ? 'value' : 'formula';

// What the wheel says, as the formula it stands for: the field squeezed into a
// width, then moved to a start. Spelled out in full even when the width is 1
// and the start is 0, so the editor always shows the same three things.
const hueTree = (h) => ({op: 'add', a: {op: 'mul', a: h.field, b: Math.round(h.width * 1000) / 1000},
                         b: Math.round(h.start * 1000) / 1000});

function slotRow(key, saved) {
  // A formula half-built in the editor is what is on show, not what is saved.
  let tree = key in editing ? editing[key] : saved;

  // A hue slot in a shape the wheel can show gets the wheel, and keeps it while
  // the formula editor is open below, for as long as the formula stays valid. An
  // empty one is a fixed hue of 0, like any other empty slot.
  const hue = isHueSlot(key) ? parseHue(tree ?? emptyValue(key)) : null;

  // The editor is open for a half-built formula, or for one that is saved. A slot
  // that has since turned back into a plain number or field - reverted, or changed
  // from the desk - has nothing to edit, so it is not open any more.
  const open = key in editing ||
      (formulaOpen.has(key) && (hue ? hue.field !== null : !isLeaf(tree)));

  // The formula of a hue that has a field in it reads (field x squeeze) + start.
  const shown = hue && hue.field !== null && !(key in editing) && !trimmed.has(key) ? hueTree(hue) : tree;

  const mode = hue ? (hue.field === null ? 'value' : 'field') : open ? 'formula' : modeOf(tree);
  if (mode === 'value') lastValue[key] = hue ? hue.start : (tree ?? emptyValue(key));

  const row = document.createElement('div');
  row.className = `slot mode-${mode}` + (tree === null ? ' empty' : '');

  const name = document.createElement('span');
  name.className = 'name';
  name.textContent = key.split('.').slice(1).join('.');

  // The control sits in a box of its own, so the field menu has something to
  // hang off.
  const ctl = document.createElement('div');
  ctl.className = 'ctl fpick';
  const toggle = fieldMenu(ctl, hue?.field ?? tree, (v) => {
    // A hue keeps its editor open across a new field; anything else is done with it.
    if (hue) delete editing[key]; else leaveFormula(key);
    writeSlot(key, !hue ? v : buildHue({field: v, start: hue.start, width: hue.field ? hue.width : 1}));
  });

  const seg = makeSeg(open && hue ? [mode, 'formula'] : mode, [
    {label: 'constant', id: 'value', title: 'a plain number',
     onclick: () => {
       if (mode === 'value') return;
       leaveFormula(key);
       writeSlot(key, lastValue[key] ?? startValue(key));
     }},
    {label: 'field', id: 'field', title: 'follow a field', onclick: toggle},
    {label: '\u0192', id: 'formula',
     title: open && hue ? 'close the formula' : 'combine fields and constants',
     onclick: () => {
       if (open) {
         // A hue the wheel can read can close it; any other formula has no way back.
         if (hue) { leaveFormula(key); drawEffects(); }
         return;
       }
       if (mode === 'formula') return;
       formulaOpen.add(key);
       if (hue && hue.field === null) {
         // A fixed hue becomes the start; the field is left to choose.
         editing[key] = {op: 'add', a: {op: 'mul', a: null, b: 1}, b: hue.start};
       } else if (!hue && isLeaf(tree)) {
         // A single operand becomes the first of two; the second is left to fill in.
         editing[key] = {op: 'mul', a: tree ?? emptyValue(key), b: null};
       }
       drawEffects();
     }},
  ]);


  // A formula shows as arithmetic, with the editor under it when it is open. The
  // editor can be folded away, leaving only the arithmetic.
  const showsEditor = mode === 'formula' || (open && hue);
  let summary = null, editor = null, words = null;
  const hueWords = (h) => `${h.field} sweeps the hue from ${fmt(h.start)} to ${fmt(h.start + h.width)}`;
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

  if (mode === 'field') {
    const chip = document.createElement('button');
    chip.className = 'chip';
    chip.textContent = `${hue?.field ?? tree} \u25be`;
    chip.title = 'pick another field';
    chip.onclick = toggle;
    ctl.append(chip);

    if (hue) {
      const readout = document.createElement('span');
      readout.className = 'dim';
      ctl.append(readout);
      ctl.append(hueBar(hue.start, hue.start + hue.width, false,
          (s0, e0) => {
            readout.textContent = `${fmt(s0)} ${e0 >= s0 ? '\u2192' : '\u2190'} ${fmt(e0)}`;

            // The formula follows the thumbs as they move, not when they are let go.
            if (editor) {
              const range = {field: hue.field, start: s0, width: e0 - s0};
              const t = trimmed.has(key) ? buildHue(range) : hueTree(range);
              summary.replaceChildren(groupedText(t));
              words.textContent = hueWords({field: hue.field, start: s0, width: e0 - s0});
              editor.replaceChildren(nodeEditor(key, t, []));
            }
          },
          (s0, e0) => writeSlot(key, buildHue({field: hue.field, start: s0, width: e0 - s0}))));
    }
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
    ctl.append(constantControl(tree ?? emptyValue(key), (v) => writeSlot(key, v)));
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

  row.append(head, ctl);
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
function chain(patch) {
  const wired = new Set(Object.keys(patch.slots).map(k => k.split('.')[0]));
  const on = patch.active === null ? wired : new Set(patch.active);

  return Object.keys(rig.effects).filter(n => on.has(n));
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
    const keys = rig.effects[name].slots.map(s => `${name}.${s}`);
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
    sw.onclick = () => setMuted(isMuted(name) ? rig.muted.filter(n => n !== name)
                                              : [...rig.muted, name]);

    // Taking it out of the preset is the real edit; the switch only mutes. Its
    // wiring stays in the patch, so adding it again finds it as it was.
    const bin = document.createElement('button');
    bin.className = 'bin';
    bin.textContent = '\u2715';
    bin.title = `take ${name} out of this preset`;
    bin.onclick = async () => {
      if (isMuted(name)) await setMuted(rig.muted.filter(n => n !== name));
      setActive(names.filter(n => n !== name));
    };

    head.append(title, count, sw, bin);

    card.append(head);

    if (open) {
      for (const key of keys) card.append(slotRow(key, view.live.slots[key] ?? null));
    }
    list.append(card);
  }
}

// ---- the parking lot, on the page ---------------------------------------------

const lot = document.getElementById('parking');

function drawParking() {
  lot.innerHTML = '';

  const head = document.createElement('div');
  head.className = 'lot-head';
  const title = document.createElement('b');
  title.textContent = 'parking lot';
  const hint = document.createElement('span');
  hint.className = 'dim';
  hint.textContent = parked.length ? '' : 'drag a part of a formula here to set it aside';
  head.append(title, hint);

  if (parked.length) {
    const clear = document.createElement('button');
    clear.className = 'discard';
    clear.textContent = 'empty';
    clear.title = 'throw everything in the lot away';
    clear.onclick = () => { parked = []; saveParked(); drawParking(); };
    head.append(clear);
  }
  lot.append(head);

  const bay = document.createElement('div');
  bay.className = 'bay';
  for (const p of parked) {
    const chip = document.createElement('div');
    chip.className = 'parked';
    chip.draggable = true;
    chip.title = 'drag back onto an operand in a formula';
    const body = document.createElement('div');
    const arithmetic = document.createElement('div');
    arithmetic.append(groupedText(p.tree));
    const words = document.createElement('div');
    words.className = 'words';
    words.textContent = explain(p.tree);
    body.append(arithmetic, words);
    chip.append(body);

    const x = document.createElement('button');
    x.className = 'discard';
    x.textContent = 'discard';
    x.onclick = () => { parked = parked.filter(q => q.id !== p.id); saveParked(); drawParking(); };
    chip.append(x);

    chip.ondragstart = (e) => {
      dragging = {from: {lot: p.id}, part: p.tree};
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', 'part of a formula');
      chip.classList.add('lifted');
    };
    chip.ondragend = () => { dragging = null; chip.classList.remove('lifted'); clearOver(); drawEffects(); };
    bay.append(chip);
  }
  lot.append(bay);

  // A part from a formula can be put down anywhere on the lot.
  lot.ondragover = (e) => {
    if (!dragging || dragging.from.lot) return;
    e.preventDefault();
    setOver(lot);
  };
  lot.ondrop = (e) => {
    if (!dragging || dragging.from.lot) return;
    e.preventDefault();
    const carried = dragging;
    dragging = null;
    clearOver();
    moveSegment(carried.from, {lot: true});
  };
}

// ---- keeping up ----------------------------------------------------------

// Which preset the half-built formulas belong to. Another one has its own slots.
let formulasFor = null;

async function refresh() {
  [rig, views] = await Promise.all([get('/rig'), get('/presets')]);
  if (rig.selected !== formulasFor) {
    editing = {};
    formulaOpen.clear();
    trimmed.clear();
    formulasFor = rig.selected;
  }
  drawPresets();
  if (!adding && !picking && !dragging && !inUse()) drawEffects();
}

async function drawStats() {
  const s = await get('/stats');
  document.getElementById('fps').textContent = `${s.fps.toFixed(0)} fps`;
}

drawParking();
refresh(); drawStats();

// The preset can change from the controller - a program change - so the bar
// follows it rather than showing what it was at load.
setInterval(() => { refresh(); drawStats(); }, 1000);
