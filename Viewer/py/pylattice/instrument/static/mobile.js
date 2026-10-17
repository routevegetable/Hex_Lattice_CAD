// Touch UI: stats, a bar of effects, that effect's slots stacked below, and a
// modal that covers the slots (never the effects bar) for choosing a field.
const OPS = {add: '+', sub: '−', mul: '×', div: '÷', avg: '≈'};

const get = (p) => fetch(p).then(r => r.json());
const send = (method, p, body) => fetch(p, {method, headers: {'Content-Type': 'application/json'},
                                           body: body === undefined ? null : JSON.stringify(body)});
const post = (p, body) => send('POST', p, body);
const put = (p, body) => send('PUT', p, body);

// Three tabs up top; the bar under them is whatever that tab needs.
const TABS = [['controls', 'Controls'], ['effects', 'Effects'], ['config', 'Configuration']];
const SECTIONS = [['stats', 'Stats'], ['midi', 'MIDI'], ['presets', 'Presets']];

let rig = null;
let patch = null;           // what is playing
let stored = null;          // the same preset as its file has it
let dirty = false;          // whether those two differ
let views = {};             // every preset, live against stored - fetched on demand
let controls = [];          // every knob and pad the instrument watches
let tab = 'effects';        // which tab is showing
let chosen = null;          // field showing its details, on Controls
let section = 'stats';      // which part of Configuration
let active = null;          // effect showing its slots
let open = null;            // "effect.slot" of the expanded slot, one at a time
let picking = null;         // {key, path} while the field picker is up
let presetsUp = false;      // the preset list uses the same modal
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

const effectOf = (key) => key.split('.')[0];
// A Patch names a slot `effect.slot`; the rig keeps the two halves apart.
const slotKeys = (name) =>
    (rig.effects[name]?.slots ?? []).map(slot => `${name}.${slot}`);
const slotOf = (key) => key.split('.').slice(1).join('.');
const isLeaf = (n) => n === null || typeof n === 'string' || typeof n === 'number';

function describe(node) {
  if (node === null) return 'nothing';
  if (typeof node === 'number') return String(node);
  if (typeof node === 'string') return node;
  return `${describe(node.a)} ${OPS[node.op]} ${describe(node.b)}`;
}

// ---- reading and writing one node of a slot's tree ------------------------

const at = (tree, path) => path.reduce((n, step) => n[step], tree);

function replace(tree, path, value) {
  if (path.length === 0) return value;
  const [step, ...rest] = path;
  return {...tree, [step]: replace(tree[step], rest, value)};
}

// Send the whole patch, not just the slot that changed, and the knobs with
// it: a write replaces a preset's live side outright, nothing is merged.
async function write(key, tree) {
  const slots = {...patch.slots};

  if (tree === null) delete slots[key];
  else slots[key] = tree;

  const r = await put(`/presets/${rig.selected}`, {ccs: patch.ccs, slots});
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
  math.onclick = () => redrawSlot(key, replace(tree, path, {op: 'mul', a: node, b: null}));


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
    b.onclick = () => redrawSlot(key, replace(tree, path, {...node, op: name}));
    ops.append(b);
  }

  const drop = document.createElement('button');
  drop.className = 'unwrap';
  drop.textContent = '⨯';
  drop.title = 'drop this operation, keep the first operand';
  drop.onclick = () => redrawSlot(key, replace(tree, path, node.a));

  head.append(ops, drop);

  const kids = document.createElement('div');
  kids.className = 'kids';
  kids.append(nodeView(key, tree, [...path, 'a']), nodeView(key, tree, [...path, 'b']));

  box.append(head, kids);
  return box;
}

function redrawSlot(key, tree) {
  editing[key] = tree;
  const done = (function whole(n) {
    return n === null ? false : isLeaf(n) ? true : whole(n.a) && whole(n.b);
  })(tree);
  if (done) { delete editing[key]; write(key, tree); }
  else drawSlots();
}

function drawSlots() {
  const box = document.getElementById('page');
  box.innerHTML = '';
  for (const key of slotKeys(active)) {
    const tree = key in editing ? editing[key] : (patch.slots[key] ?? null);

    const el = document.createElement('div');
    el.className = 'slot' + (open === key ? ' open' : '') + (tree === null ? ' empty' : '');

    const row = document.createElement('div');
    row.className = 'row';
    row.innerHTML = `<span class="name">${slotOf(key)}</span>` +
                    `<span class="value">${describe(tree)}</span>` +
                    `<span class="chev">${open === key ? '▾' : '▸'}</span>`;
    row.onclick = () => { open = open === key ? null : key; delete editing[key]; drawSlots(); };
    el.append(row);

    if (open === key) {
      const tree_ = document.createElement('div');
      tree_.className = 'tree';
      tree_.append(nodeView(key, tree, []));
      el.append(tree_);
    }
    box.append(el);
  }
}

// ---- the picker modal ----------------------------------------------------

function openPicker(key, path) {
  picking = {key, path};
  showFields();
  document.getElementById('modal').hidden = false;
}

function closePicker() {
  picking = null;
  presetsUp = false;
  document.getElementById('modal').hidden = true;
}

// ---- the preset list -----------------------------------------------------

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
    cell.className = 'pcell' + (rig.presets.includes(n) ? ' saved' : '') +
                     (isDirty(views[n]) ? ' dirty' : '') +
                     (n === rig.selected ? ' on' : '');

    const label = document.createElement('b');
    label.textContent = n;

    const key = (glyph, title, path) => {
      const b = document.createElement('button');
      b.textContent = glyph;
      b.title = title;
      b.onclick = () => act(path);
      return b;
    };

    // Copying is a write followed by a select: the write puts what is playing
    // into that preset, and the select is what makes it the one you are on.
    const copyHere = (to) => {
      const b = document.createElement('button');
      b.textContent = '\u29c9';
      b.title = `copy what is playing into preset ${to}`;
      b.onclick = async () => {
        const r = await put(`/presets/${to}`, {ccs: patch.ccs, slots: patch.slots});
        if (!r.ok) { alert((await r.json()).detail); return; }
        act(`/presets/${to}/select`);
      };
      return b;
    };

    cell.append(label,
                key('\u25b6', `switch to preset ${n}`, `/presets/${n}/select`),
                copyHere(n));
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
  const tree = key in editing ? editing[key] : (patch.slots[key] ?? null);
  closePicker();
  redrawSlot(key, replace(tree, path, value));
}

// ---- page ----------------------------------------------------------------

async function load() {
  [rig, controls] = await Promise.all([get('/rig'), get('/controls')]);

  const view = await get(`/presets/${rig.selected}`);
  ({live: patch, stored} = view);
  dirty = isDirty(view);

  const effects = Object.keys(rig.effects);
  if (!effects.includes(active)) active = effects[0] ?? null;
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
    // An effect entry is its name and a switch to turn it off. Neither the
    // switch nor the + at the end is wired up to anything yet.
    for (const name of Object.keys(rig.effects)) {
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
      kill.title = `turn ${name} off`;

      box.append(pick, kill);
      bar.append(box);
    }

    const add = document.createElement('button');
    add.className = 'add';
    add.textContent = '\u2795';
    add.title = 'add an effect';
    bar.append(add);
  } else if (tab === 'controls') {
    for (const f of [...rig.fields].sort((x, y) => x.name.localeCompare(y.name))) {
      const used = usedBy(f.name).length;
      cell(f.name, used ? `${used} in use` : 'spare', f.name === chosen,
           () => { chosen = f.name; drawSubBar(); drawPage(); });
    }
  } else {
    for (const [key, label] of SECTIONS)
      cell(label, '', key === section,
           () => { section = key; drawSubBar(); drawPage(); });
  }
}

function drawPage() {
  if (tab === 'effects') return drawSlots();
  if (tab === 'controls') return drawFieldPage();
  return drawConfigPage();
}

// Every slot whose expression names a field, however deep in it.
function usedBy(name) {
  const mentions = (n) => n === name ||
      (n !== null && typeof n === 'object' && (mentions(n.a) || mentions(n.b)));
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

function drawFieldPage() {
  const box = document.getElementById('page');
  box.innerHTML = '';

  if (chosen === null) {
    box.innerHTML = '<p class="hint">Pick a field above.</p>';
    return;
  }

  const info = rig.fields.find(f => f.name === chosen);
  box.append(infoRow('kind', info ? info.kind : '?'));

  // A control says what it is for as `field.role`, so its own name is the
  // prefix to look for.
  const mine = controls.filter(c => c.comments.some(t => t.startsWith(chosen + '.')));

  for (const c of mine) {
    const role = c.comments.filter(t => t.startsWith(chosen + '.'))
                           .map(t => t.slice(chosen.length + 1)).join(', ');
    box.append(infoRow(`${c.kind} ${c.number}`, `${role} \u00b7 ${c.value}`));
  }

  if (!mine.length) box.append(infoRow('driven by', 'nothing on the box'));

  const used = usedBy(chosen);
  box.append(infoRow('used by', used.join(', ') || 'nothing'));
}

// ---- Configuration -------------------------------------------------------

async function drawConfigPage() {
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
  } else if (section === 'midi') {
    for (const c of controls) {
      const what = (c.comments.join(' \u00b7 ') || 'unnamed') + (c.hidden ? ' \u00b7 hidden' : '');
      box.append(infoRow(`${c.kind} ${c.number}`, `${what} \u2014 ${c.value}`));
    }
  } else {
    box.append(infoRow('bank size', rig.size));
    box.append(infoRow('playing', rig.selected === null ? '\u2014' : `preset ${rig.selected}`));
    box.append(infoRow('written', rig.presets.join(', ') || 'none'));
    views = await get('/presets');
    const edited = Object.keys(views).filter(n => isDirty(views[n]));
    box.append(infoRow('unsaved edits', edited.join(', ') || 'none'));
  }
}

async function drawStats() {
  const s = await get('/stats');
  document.getElementById('fps').textContent = `${s.fps.toFixed(0)} fps`;
}

function drawChip() {
  const chip = document.getElementById('preset-chip');
  const n = rig.selected;

  chip.textContent = n === null ? 'preset —' : `preset ${n}`;
  chip.className = (n === null ? 'none' : '') + (dirty ? ' dirty' : '');

  // Saving and reverting act on whatever is playing, so they live up here
  // rather than once per row.
  for (const [id, verb] of [['save-chip', 'commit'], ['revert-chip', 'revert']]) {
    const b = document.getElementById(id);
    b.disabled = !dirty;
    b.title = dirty ? `${verb} preset ${n}` : `nothing to ${verb}`;
  }
}

for (const [id, path] of [['save-chip', 'commit'], ['revert-chip', 'revert']]) {
  document.getElementById(id).onclick = () => {
    if (rig.selected !== null) act(`/presets/${rig.selected}/${path}`);
  };
}
document.getElementById('modal-close').onclick = closePicker;
document.getElementById('preset-chip').onclick = () => {
  if (presetsUp) { closePicker(); return; }
  openPresets();
  document.getElementById('modal').hidden = false;
};

load(); drawStats();
setInterval(async () => {
  drawStats();

  // The preset can change from the controller - a step button or a program
  // change - so the chip follows it rather than showing what it was at load.
  if (rig !== null) {
    const fresh = await get('/rig');
    const moved = fresh.selected !== rig.selected;
    rig = fresh;
    drawChip();
    if (moved && presetsUp) openPresets();   // the marker moves with it
  }

  if (open === null && picking === null && !presetsUp) {
    const view = await get(`/presets/${rig.selected}`);
    ({live: patch, stored} = view);
    dirty = isDirty(view);
    if (tab !== 'effects') controls = await get('/controls');
    drawPage();
  }
}, 1000);


// --- the knob that moved last -------------------------------------------
// Polled faster than the rest: it is only up for two seconds, so a one-second
// poll would catch some of them late and miss others entirely.
const CC_SHOWN = 2000;              // ms a move stays on screen
const CC_POLL = 200;

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

let ccHide = null;

function drawKnob(k) {
  const frac = Math.max(0, Math.min(1, k.value / 127));
  const a = DIAL_FROM + DIAL_SWEEP * frac;

  // An arc of zero length still draws a cap, so leave it out entirely.
  dialValue.setAttribute('d', frac > 0.002 ? arc(DIAL_FROM, a) : '');

  const [x1, y1] = dialAt(5, a), [x2, y2] = dialAt(13, a);
  dialPin.setAttribute('x1', x1.toFixed(2));
  dialPin.setAttribute('y1', y1.toFixed(2));
  dialPin.setAttribute('x2', x2.toFixed(2));
  dialPin.setAttribute('y2', y2.toFixed(2));

  ccNum.textContent = `cc ${k.cc}`;
  ccVal.textContent = k.value;
  ccComments.textContent = k.comments.length ? k.comments.join(' · ') : 'not named';
  ccComments.className = k.comments.length ? '' : 'none';
  ccbar.hidden = false;
}

async function pollKnob() {
  let k;
  try { k = await get('/knobinfo'); } catch (e) { return; }

  if (!k) return;                           // nothing has ever moved

  const left = CC_SHOWN - k.age_ms;
  if (left <= 0) return;                    // that was a while ago

  drawKnob(k);
  clearTimeout(ccHide);
  ccHide = setTimeout(() => { ccbar.hidden = true; }, left);
}

setInterval(pollKnob, CC_POLL);
pollKnob();
