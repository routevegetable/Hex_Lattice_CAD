// Touch UI: stats, a bar of effects, that effect's slots stacked below, and a
// modal that covers the slots (never the effects bar) for choosing a field.
const OPS = {add: '+', sub: '−', mul: '×', div: '÷', avg: '≈'};

const get = (p) => fetch(p).then(r => r.json());
const send = (method, p, body) => fetch(p, {method, headers: {'Content-Type': 'application/json'},
                                           body: body === undefined ? null : JSON.stringify(body)});
const post = (p, body) => send('POST', p, body);
const put = (p, body) => send('PUT', p, body);

// Three tabs up top; the bar under them is whatever that tab needs.
const TABS = [['effects', 'Effects'], ['controls', 'Controls'], ['config', 'Configuration']];
const SECTIONS = [['stats', 'Stats'], ['midi', 'MIDI'], ['presets', 'Presets'],
                  ['surface', 'Surface']];

let rig = null;
let patch = null;           // what is playing, bar the knobs - see heldPatch
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
let addingUp = false;       // so does the list of effects to add
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
  const r = await put(`/presets/${rig.selected}`,
                      {...patch, ccs: liveCCs(), active: names});
  if (!r.ok) { alert((await r.json()).detail); return; }
  await load();
}

// Every field named anywhere in an expression, however deep.
function fieldsIn(node) {
  if (typeof node === 'string') return [node];
  if (node && typeof node === 'object') return [...fieldsIn(node.a), ...fieldsIn(node.b)];
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

// The effects in the chain that took knobs of their own. They earn a place on
// the controls screen for the same reason a field does - something on the desk
// moves them - so they are listed beside the fields rather than only being
// reachable through the effect they belong to.
const effectsWithControls = () => activeEffects()
    .filter(name => controlsOwnedBy(name).length)
    .sort((a, b) => a.localeCompare(b));

// The knobs behind an expression: every control belonging to a field it names.
// It grows as fields are added, because it is read off the tree being edited.
function controlsFor(tree) {
  const names = fieldsIn(tree);
  return controls.filter(c => c.kind === 'cc' &&
      c.comments.some(t => names.some(n => t.startsWith(n + '.'))));
}

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

// The knobs as they stand, in the shape a patch records them. Read off the
// store the socket keeps rather than carried along from the last GET, so a
// knob turned while a slot was open is written as it is now and not as it was
// when the slot was opened.
//
// Only the ones something is listening to: every stray the box has ever sent
// is in the store too, and a preset is a set of settings rather than a log of
// what came down the wire.
const liveCCs = () => Object.fromEntries(
    Object.entries(knobs).filter(([, k]) => k.comments.length)
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
                                          comments: c.comments,
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

  // Knobs the effect itself owns, as against the ones behind whatever is
  // patched into its slots. They belong to the effect rather than to any
  // expression, so they are on show the whole time it is.
  const own = controlsOwnedBy(active);
  if (own.length) box.append(controlList(own));

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

    host.replaceChild(makeDial(knob.value), el);

    const now = host.querySelector('.now');
    if (now) now.textContent = knob.value;
  }
}

function controlList(found) {
  const box = document.createElement('div');
  box.className = 'ctrls';

  for (const c of found) {
    const name = c.comments[0] ?? `cc ${c.number}`;
    const waiting = mapping === name;

    const row = document.createElement('button');
    row.className = 'ctrl' + (waiting ? ' waiting' : '');
    row.dataset.cc = c.number;
    row.title = waiting ? 'turn the knob you want'
                        : `drag to turn, tap to put ${name} on another knob`;

    // Drag it like a knob; a tap that went nowhere is the assign gesture.
    let from = null;

    row.onpointerdown = (e) => {
      from = {y: e.clientY, value: liveValue(c), turned: false};
      row.setPointerCapture(e.pointerId);
    };

    row.onpointermove = (e) => {
      if (from === null) return;

      const want = clamp(Math.round(from.value + (from.y - e.clientY) * DRAG_PER_PX));
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

    row.append(makeDial(liveValue(c)));

    const label = document.createElement('b');
    label.textContent = name;

    const where = document.createElement('span');
    where.className = 'at';
    where.textContent = waiting ? 'turn a knob\u2026'
                                : `cc ${c.number}${c.number === c.default ? '' : ' \u00b7 moved'}`;

    const val = document.createElement('span');
    val.className = 'now';
    val.textContent = liveValue(c);

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

  for (let n = 0; n < rig.controller_presets; n++) {
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
        const r = await put(`/presets/${to}`, {...patch, ccs: liveCCs()});
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

      box.append(pick, kill);
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

function drawFieldPage() {
  const box = document.getElementById('page');
  box.innerHTML = '';
  box.append(knobDiagram());

  if (chosen === null) {
    box.insertAdjacentHTML('beforeend',
        '<p class="hint">Pick a field or an effect above to see which knobs it '
        + 'listens to.</p>');
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
    box.append(infoRow('controller presets', rig.controller_presets));
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

  // The preset can change from the controller - a program change - so the
  // chip follows it rather than showing what it was at load.
  if (rig !== null) {
    const fresh = await get('/rig');
    const moved = fresh.selected !== rig.selected;
    rig = fresh;
    drawChip();
    if (moved && presetsUp) openPresets();   // the marker moves with it
  }

  if (open === null && picking === null && !presetsUp && !addingUp) {
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
function makeDial(value) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 40 40');
  svg.setAttribute('class', 'dial');

  const frac = Math.max(0, Math.min(1, value / 127));
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
  if (frac > 0.002) svg.append(path(arc(DIAL_FROM, a), '#6a8fd0'));

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
  ccComments.textContent = k.comments.length ? k.comments.join(' · ') : 'not mapped';
  ccComments.className = k.comments.length ? '' : 'none';
  ccbar.hidden = false;
}

// Controls the instrument treats as plumbing. The stream says what moved and
// leaves the judgement here, so this is where anything declared hidden gets
// ignored.
const isPlumbing = (cc) =>
    controls.some(c => c.kind === 'cc' && c.number === cc && c.hidden);

async function applyMapping(name, number) {
  mapping = null;
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
