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

// ---- gradients -------------------------------------------------------------

// STUB. The server stores no gradients yet, so every tree it sends is a field,
// a constant or a combination, and this page can neither make nor edit a
// gradient. These three are the only places that know the shape of one -
// {gradient, of, ch} - so that one that turns up is shown as an opaque leaf and
// not mistaken for a formula. The editor and its storage come with the server
// side of gradients; they replace this section and nothing else.
const isGradient = (n) => n !== null && typeof n === 'object' && n.gradient !== undefined;
const describeGradient = (n) => `gradient ${n.gradient}(${describe(n.of)}).${n.ch ?? 'h'}`;
const gradientFields = (n) => fieldsIn(n.of);

// A slot as text: what is plugged into it, however deep.
function describe(node) {
  if (node === null || node === undefined) return 'nothing';
  if (typeof node === 'number') return fmt(node);
  if (typeof node === 'string') return node;
  if (isGradient(node)) return describeGradient(node);
  return `(${describe(node.a)} ${OPS[node.op]} ${describe(node.b)})`;
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
async function writeSlot(key, tree) {
  const n = rig.selected;
  if (n === null) return;

  const fresh = await get(`/presets/${n}`);
  remember(n, fresh.live);
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
    menu.append(search, onMap, body);

    let rows = [], cursor = 0;

    const item = (text, hint, value, on, remove) => {
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
        body.append(item(e.text, e.hint, e.value, e.value === current, e.remove));
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
// It is null when that cannot be said: an operand left empty, a gradient, or a
// division by anything but a fixed number.
function reach(n) {
  if (typeof n === 'number') return [n, n];
  if (typeof n === 'string') return [0, 1];
  if (n === null || typeof n !== 'object' || n.op === undefined) return null;

  const a = reach(n.a), b = reach(n.b);
  if (!a || !b) return null;

  switch (n.op) {
    case 'add': return [a[0] + b[0], a[1] + b[1]];
    case 'sub': return [a[0] - b[1], a[1] - b[0]];
    case 'avg': return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    case 'mul': {
      const p = [a[0] * b[0], a[0] * b[1], a[1] * b[0], a[1] * b[1]];
      return [Math.min(...p), Math.max(...p)];
    }
    case 'div': {
      if (b[0] !== b[1] || b[0] === 0) return null;
      const q = [a[0] / b[0], a[1] / b[0]];
      return [Math.min(...q), Math.max(...q)];
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
  if (x && typeof x === 'object' && (x.op === 'mul' || x.op === 'div')) {
    const [f, k] = [x.a, x.b];
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
  if (t && typeof t === 'object' && t.op === 'add') {
    for (const [x, c] of [[t.a, t.b], [t.b, t.a]])
      if (typeof c === 'number') options.push({...peelWidth(x), start: c});
  }
  options.push({...peelWidth(t), start: 0}, {field: t, width: 1, start: 0});

  return options.find(o => usableSource(o.field)) ?? null;
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
const isLeaf = (n) => n === null || typeof n !== 'object' || isGradient(n);
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
  if (isGradient(n)) return describe(n);
  return `(${explain(n)})`;
}

function explain(n) {
  if (n === null || n === undefined) return 'nothing yet';
  if (isNum(n)) return `the constant ${fmt(n)}`;
  if (typeof n === 'string') return n;
  if (isGradient(n)) return describe(n);

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
  // Which side is which matters for - and the others read left to right.
  const flip = document.createElement('button');
  flip.className = 'flip';
  flip.textContent = '\u21c4';
  flip.title = 'swap the two sides';
  flip.onclick = () => setFormula(key, replace(tree, path, {...node, a: node.b, b: node.a}));

  // The + on a single value pairs that value with another, which nests the new term
  // inside. This is its counterpart for a whole operation: the operation, with
  // everything in it, becomes the first half of a new one, so a term goes around
  // the outside - at the top of the formula, around the lot.
  const outer = document.createElement('button');
  outer.className = 'outer';
  outer.textContent = '+ outer';
  outer.title = 'add a term outside this whole operation: all of it becomes the first half of a new operation, and you choose the other half';
  outer.onclick = () => setFormula(key, replace(tree, path, {op: 'mul', a: node, b: null}));
  head.append(outer, flip);

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
    : n !== null && typeof n === 'object'
      ? (isGradient(n) ? gradientFields(n) : [...fieldsIn(n.a), ...fieldsIn(n.b)])
      : [];

// A turned copy of a rotary (rotary180, v_rotary90...) is the same rotation
// seen from elsewhere and shares its knobs, which are named for the original.
const knobOwner = (name) => name.replace(/^((?:v_)?rotary)\d+$/, '$1');

// The knobs behind a formula: a control's comment is `field.role`, so it
// belongs to a field when it begins with that field's name.
const controlsFor = (tree) => {
  const names = fieldsIn(tree).map(knobOwner);
  return controls.filter(c => c.kind === 'cc' && !c.hidden &&
      c.comments.some(t => names.some(n => t.startsWith(n + '.'))));
};

const CC_MAX = 127;
const DRAG_PER_PX = 0.8;            // a touch over 150px for the whole range
const clampCC = (v) => Math.max(0, Math.min(CC_MAX, v));
const liveValue = (c) => knobs[c.number]?.value ?? c.value;

// A rev counter: three quarters of a turn with the gap at the bottom.
const DIAL_FROM = Math.PI * 0.75, DIAL_SWEEP = Math.PI * 1.5, DIAL_R = 15;
const dialAt = (r, a) => [20 + r * Math.cos(a), 20 + r * Math.sin(a)];

function arc(from, to) {
  const [x0, y0] = dialAt(DIAL_R, from), [x1, y1] = dialAt(DIAL_R, to);
  const big = to - from > Math.PI ? 1 : 0;
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${DIAL_R} ${DIAL_R} 0 ${big} 1 ` +
         `${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

function makeDial(value) {
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

  setDial(svg, value);
  return svg;
}

function setDial(svg, value) {
  const frac = Math.max(0, Math.min(1, value / CC_MAX));
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

function knobList(found) {
  const box = document.createElement('div');
  box.className = 'knobs';

  for (const c of found) {
    const name = c.comments[0] ?? `cc ${c.number}`;

    const row = document.createElement('div');
    row.className = 'knob';
    row.dataset.cc = c.number;
    row.dataset.name = c.comments[0];
    row.title = `drag up and down to turn, tap to put ${c.comments[0]} on another knob`;

    const label = document.createElement('b');
    label.textContent = name;
    const now = document.createElement('span');
    now.className = 'now';
    now.textContent = liveValue(c);
    const at = document.createElement('span');
    at.className = 'at';
    at.dataset.was = `cc ${c.number}${c.number === c.default ? '' : ' \u00b7 moved'}`;
    row.append(makeDial(liveValue(c)), label, now, at);

    let from = null;
    row.onpointerdown = (e) => {
      from = {y: e.clientY, value: liveValue(c), turned: false};
      row.setPointerCapture(e.pointerId);
      e.preventDefault();
    };
    row.onpointermove = (e) => {
      if (from === null) return;
      const want = clampCC(Math.round(from.value + (from.y - e.clientY) * DRAG_PER_PX));
      if (want === liveValue(c)) return;
      from.turned = true;
      turnKnob(c.number, want);
      setDial(row.querySelector('.dial'), want);
      now.textContent = want;
    };
    // A frame already on its way may still carry the value from before the last
    // turn, so the dial is left to the drag for a moment after letting go.
    const done = () => {
      from = null;
      setTimeout(() => { if (turning?.cc === c.number) turning = null; }, 300);
    };
    row.onpointerup = () => {
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

// After a frame from the socket: every dial on the page follows the desk.
function syncKnobs() {
  for (const el of document.querySelectorAll('#effects .knob')) {
    const k = knobs[el.dataset.cc];
    if (!k) continue;
    setDial(el.querySelector('.dial'), k.value);
    el.querySelector('.now').textContent = k.value;
  }
}

// Pushed, not polled: the knobs move continuously.
function listen() {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  wire = new WebSocket(`${scheme}://${location.host}/ws/knobs`);

  wire.onmessage = (e) => {
    knobs = JSON.parse(e.data);
    if (turning && knobs[turning.cc]) knobs[turning.cc].value = turning.value;
    syncKnobs();
    syncMapKnobs();

    const moved = mapping && lastMoved();
    if (moved && moved.knob.age_ms < Date.now() - mapping.since) assign(mapping.name, moved.cc);
  };
  wire.onclose = () => setTimeout(listen, 1000);      // the app restarts; so do we
}

listen();

function slotRow(key, saved) {
  // A formula half-built in the editor is what is on show, not what is saved.
  let tree = key in editing ? editing[key] : saved;

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
    writeSlot(key, !hue ? v : buildHue({field: v, start: hue.start, width: hue.field ? hue.width : 1}));
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
         editing[key] = {op: 'add', a: {op: 'mul', a: null, b: 1}, b: hue.start};
       } else if (!hue && isLeaf(tree)) {
         // A single operand becomes the first of two; the second is left to fill in.
         editing[key] = {op: 'mul', a: tree ?? 0, b: null};
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
            const range = {field: hue.field, start: s0, width: e0 - s0};
            const t = trimmed.has(key) ? buildHue(range) : hueTree(range);
            summary.replaceChildren(groupedText(t));
            words.textContent = hueWords({field: hue.field, start: s0, width: e0 - s0});
            editor.replaceChildren(nodeEditor(key, t, []));
          }
        },
        (s0, e0) => writeSlot(key, buildHue({field: hue.field, start: s0, width: e0 - s0}))));
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

  row.append(head, ctl);

  const found = controlsFor(shown);
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

    head.append(cardGrip(card, head, name, names), title, count, sw, bin);
    cardDropTarget(card, name);

    card.append(head);

    if (open) {
      for (const key of keys) card.append(slotRow(key, view.live.slots[key] ?? null));
    }
    list.append(card);
  }
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

// A preset with nothing plugged in: every effect is in the chain, so there is a
// card for each to open, and every slot is blank, so nothing draws until one is
// filled. No knobs are listed - a patch that says nothing about them leaves them
// where they are - and nothing is muted.
const blankPatch = (name) => ({ccs: {}, slots: {}, cc_map: {}, active: Object.keys(rig.effects),
                               muted: [], name});

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

// A control's comment is `field.role`. Only the ones that name a field of the
// rig can be plugged into a slot.
const fieldOwners = (c) => {
  const names = new Set(rig.fields.map(f => f.name));
  return [...new Set(c.comments.map(t => knobOwner(t.split('.')[0])).filter(n => names.has(n)))];
};

// The fields the playing preset's slots name, whatever their depth.
function fieldsInUse() {
  const live = views[rig.selected]?.live;
  const used = new Set();
  for (const tree of Object.values(live?.slots ?? {})) fieldsIn(tree).forEach(n => used.add(knobOwner(n)));
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
  const here = controls.filter(c => !c.hidden);
  const key = JSON.stringify([surfaceId, [...used], here.map(c => [c.kind, c.number, c.comments])]);
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

  const off = [];
  const roles = new Map();          // spot -> the [field, role] of everything on it
  for (const c of here) {
    // A note can be several pads: the Akai's pads fold onto fewer BSP notes.
    const ids = [].concat((c.kind === 'cc' ? surface.ccs : surface.notes ?? {})[c.number] ?? []);
    const spots = ids.map(id => holder.querySelector(`#${CSS.escape(id)}`)).filter(Boolean);
    if (!spots.length) { if (c.comments.length) off.push(c); continue; }

    for (const spot of spots) {
      spot.classList.add('assigned');
      if (fieldOwners(c).some(n => used.has(n))) spot.classList.add('lit');
      if (c.kind === 'cc') spot.dataset.cc = c.number;
      spot.dataset.owners = JSON.stringify([...new Set([...JSON.parse(spot.dataset.owners ?? '[]'), ...fieldOwners(c)])]);
      roles.set(spot, [...(roles.get(spot) ?? []), ...c.comments.map(t => t.split('.'))]);
    }
  }

  for (const [spot, rs] of roles) {
    if (!rs.length) continue;
    const tag = spot.querySelector('.tag');
    const x = tag.getAttribute('x'), y = Number(tag.getAttribute('y'));
    [rs[0][0] + (rs.length > 1 ? ` +${rs.length - 1}` : ''), rs[0][1] ?? '']
      .forEach((text, i) => {
        const t = document.createElementNS(SVG_NS, 'text');
        t.setAttribute('class', i ? 'what role' : 'what');
        t.setAttribute('x', x); t.setAttribute('y', y + 12 + 11 * i);
        t.textContent = short(text, Number(spot.dataset.chars ?? 8));
        spot.append(t);
      });
    const title = document.createElementNS(SVG_NS, 'title');
    title.textContent = rs.map(r => r.join('.')).join('\n');
    spot.append(title);
  }
  for (const spot of holder.querySelectorAll('.spot.assigned')) spot.onclick = () => pressedOnMap(spot);

  if (off.length) {
    const note = document.createElement('p');
    note.className = 'dim map-off';
    note.textContent = `not on this box: ${off.map(c => c.comments[0]).join(', ')}`;
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
    if (!k) continue;
    const frac = Math.max(0, Math.min(1, k.value / CC_MAX));
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

// ---- keeping up ----------------------------------------------------------

// Which preset the half-built formulas belong to. Another one has its own slots.
let formulasFor = null;

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
  if (!adding && !picking && !dragging && !reordering && !turning && !inUse()) drawEffects();
}

async function drawStats() {
  const s = await get('/stats');
  document.getElementById('fps').textContent = `${s.fps.toFixed(0)} fps`;
}

loadSurfaces().then(refresh); drawStats();

// The preset can change from the controller - a program change - so the bar
// follows it rather than showing what it was at load.
setInterval(() => { refresh(); drawStats(); }, 1000);
