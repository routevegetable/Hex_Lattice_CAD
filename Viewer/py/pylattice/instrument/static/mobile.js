// Touch UI: stats, a bar of effects, that effect's slots stacked below, and a
// modal that covers the slots (never the effects bar) for choosing a field.
const OPS = {add: '+', sub: '−', mul: '×', div: '÷', avg: '≈'};

const get = (p) => fetch(p).then(r => r.json());
const post = (p, body) => fetch(p, {method: 'POST', headers: {'Content-Type': 'application/json'},
                                    body: body === undefined ? null : JSON.stringify(body)});

let rig = null;
let patch = null;
let active = null;          // effect showing its slots
let open = null;            // "effect.slot" of the expanded slot, one at a time
let picking = null;         // {key, path} while the modal is up

const effectOf = (key) => key.split('.')[0];
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

async function write(key, tree) {
  const r = await post('/current', {ccs: {}, slots: {[key]: tree}});
  if (!r.ok) alert((await r.json()).detail);
  await load();
}

// ---- the slot list -------------------------------------------------------

function leaf(key, tree, path) {
  const node = at(tree, path);
  const wrap = document.createElement('div');
  wrap.className = 'row-wrap';

  const b = document.createElement('button');
  b.className = 'leaf' + (node === null ? ' unset' : '');
  b.textContent = node === null ? 'choose…' : describe(node);
  b.onclick = () => openPicker(key, path);
  wrap.append(b);

  if (node !== null) {
    const ops = document.createElement('div');
    ops.className = 'ops';
    for (const [name, glyph] of Object.entries(OPS)) {
      const o = document.createElement('button');
      o.textContent = glyph;
      o.onclick = () => redrawSlot(key, replace(tree, path, {op: name, a: node, b: null}));
      ops.append(o);
    }
    wrap.append(ops);
  }
  return wrap;
}

function nodeView(key, tree, path) {
  const node = at(tree, path);
  if (isLeaf(node)) return leaf(key, tree, path);

  const box = document.createElement('div');
  box.className = 'node';

  const head = document.createElement('div');
  head.className = 'row-wrap';
  const label = document.createElement('span');
  label.className = 'op-label';
  label.textContent = node.op;
  const un = document.createElement('button');
  un.className = 'unwrap';
  un.textContent = '⨯';
  un.title = 'drop this operator';
  un.onclick = () => redrawSlot(key, replace(tree, path, node.a));
  head.append(label, un);

  const kids = document.createElement('div');
  kids.className = 'kids';
  kids.append(nodeView(key, tree, [...path, 'a']), nodeView(key, tree, [...path, 'b']));

  box.append(head, kids);
  return box;
}

// Local edits live here until every operand is filled, then they are sent.
let editing = {};

function redrawSlot(key, tree) {
  editing[key] = tree;
  const done = (function whole(n) {
    return n === null ? false : isLeaf(n) ? true : whole(n.a) && whole(n.b);
  })(tree);
  if (done) { delete editing[key]; write(key, tree); }
  else drawSlots();
}

function drawSlots() {
  const box = document.getElementById('slots');
  box.innerHTML = '';
  for (const key of rig.slots.filter(k => effectOf(k) === active)) {
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
  showClasses();
  document.getElementById('modal').hidden = false;
}

function closePicker() {
  picking = null;
  document.getElementById('modal').hidden = true;
}

function showClasses() {
  const picker = document.getElementById('picker');
  document.getElementById('modal-title').textContent = 'what kind of field?';
  document.getElementById('modal-back').style.visibility = 'hidden';
  picker.innerHTML = '';

  const byKind = {};
  for (const f of rig.fields) (byKind[f.kind] ??= []).push(f);

  for (const [kind, fields] of Object.entries(byKind).sort()) {
    const b = document.createElement('button');
    b.innerHTML = `<b>${kind}</b><small>${fields.length} field${fields.length > 1 ? 's' : ''}</small>`;
    b.onclick = () => showFields(kind, fields);
    picker.append(b);
  }

  const num = document.createElement('button');
  num.innerHTML = '<b>a number</b><small>constant value</small>';
  num.onclick = showNumber;
  picker.append(num);
}

function showFields(kind, fields) {
  const picker = document.getElementById('picker');
  document.getElementById('modal-title').textContent = kind;
  document.getElementById('modal-back').style.visibility = 'visible';
  picker.innerHTML = '';

  for (const f of fields) {
    const b = document.createElement('button');
    b.innerHTML = `<b>${f.name}</b>`;
    b.onclick = () => choose(f.name);
    picker.append(b);
  }
}

function showNumber() {
  const picker = document.getElementById('picker');
  document.getElementById('modal-title').textContent = 'a number';
  document.getElementById('modal-back').style.visibility = 'visible';
  picker.innerHTML = '';

  const input = document.createElement('input');
  input.type = 'number'; input.step = '0.05'; input.value = '0.5';
  const ok = document.createElement('button');
  ok.innerHTML = '<b>use it</b>';
  ok.onclick = () => choose(parseFloat(input.value) || 0);
  picker.append(input, ok);
}

function choose(value) {
  const {key, path} = picking;
  const tree = key in editing ? editing[key] : (patch.slots[key] ?? null);
  closePicker();
  redrawSlot(key, replace(tree, path, value));
}

// ---- page ----------------------------------------------------------------

async function load() {
  [rig, patch] = await Promise.all([get('/rig'), get('/current')]);
  const effects = [...new Set(rig.slots.map(effectOf))];
  if (!effects.includes(active)) active = effects[0] ?? null;

  const bar = document.getElementById('effects');
  bar.innerHTML = '';
  for (const name of effects) {
    const slots = rig.slots.filter(k => effectOf(k) === name);
    const unset = slots.filter(k => (patch.slots[k] ?? null) === null).length;
    const b = document.createElement('button');
    b.className = name === active ? 'on' : '';
    b.innerHTML = `${name}<small>${slots.length} slots${unset ? ` · ${unset} free` : ''}</small>`;
    b.dataset.effect = name;
    b.onclick = () => { active = name; open = null; closePicker(); drawSlots(); redrawTabs(); };
    bar.append(b);
  }
  drawSlots();
}

function redrawTabs() {
  for (const b of document.getElementById('effects').children)
    b.className = b.dataset.effect === active ? 'on' : '';
}

async function drawStats() {
  const s = await get('/stats');
  document.getElementById('stats').textContent =
    `${s.fps.toFixed(0)} fps · render ${s.render_ms.toFixed(1)}ms · gc ${s.gc_ms.toFixed(1)}ms`;
}

document.getElementById('modal-close').onclick = closePicker;
document.getElementById('modal-back').onclick = showClasses;

load(); drawStats();
setInterval(async () => {
  drawStats();
  if (open === null && picking === null) { patch = await get('/current'); drawSlots(); }
}, 1000);
