const OPS = {add: '+', sub: '−', mul: '×', div: '÷', avg: '≈'};
const STEP_CC = [20, 55];

const get = (p) => fetch(p).then(r => r.json());
const post = (p, body) => fetch(p, {method: 'POST', headers: {'Content-Type': 'application/json'},
                                    body: body === undefined ? null : JSON.stringify(body)});

// The two things the page holds: what can be patched, and what is patched.
let rig = null;
let patch = null;
let active = null;              // effect whose tab is open
let open = new Set();           // "effect.slot" of expanded tiles
let edits = {};                 // "effect.slot" -> tree mid-edit

const effectOf = (key) => key.split('.')[0];
const slotOf = (key) => key.split('.').slice(1).join('.');
const driverOf = (key) => key in edits ? edits[key] : (patch.slots[key] ?? null);

// ---- the expression tree -------------------------------------------------

const isLeaf = (n) => n === null || typeof n === 'string' || typeof n === 'number';
const complete = (n) => n === null ? false : isLeaf(n) ? true : complete(n.a) && complete(n.b);

function leafEditor(node, onChange) {
  const row = document.createElement('div');
  row.className = 'row';

  const sel = document.createElement('select');
  sel.append(new Option(node === null ? '— pick a field —' : '— none —', '__none__'));
  for (const f of rig.fields) sel.append(new Option(f, f));
  sel.append(new Option('number…', '__num__'));
  sel.value = typeof node === 'string' ? node : (typeof node === 'number' ? '__num__' : '__none__');
  sel.onchange = () => {
    if (sel.value === '__none__') onChange(null);
    else if (sel.value === '__num__') onChange(typeof node === 'number' ? node : 0);
    else onChange(sel.value);
  };
  row.append(sel);

  if (typeof node === 'number') {
    const num = document.createElement('input');
    num.type = 'number'; num.step = '0.05'; num.value = node;
    num.onchange = () => onChange(parseFloat(num.value));
    row.append(num);
  }

  // Operators appear once something is in the slot: clicking one wraps what is
  // here inside that operator and opens a fresh slot beside it.
  if (node !== null) {
    const ops = document.createElement('span');
    ops.className = 'ops';
    for (const [name, glyph] of Object.entries(OPS)) {
      const b = document.createElement('button');
      b.textContent = glyph; b.title = name;
      b.onclick = () => onChange({op: name, a: node, b: null});
      ops.append(b);
    }
    row.append(ops);
  }
  return row;
}

function nodeEditor(node, onChange) {
  if (isLeaf(node)) return leafEditor(node, onChange);

  const box = document.createElement('div');
  box.className = 'node';

  const head = document.createElement('div');
  head.className = 'row';
  const label = document.createElement('span');
  label.className = 'op'; label.textContent = node.op;
  const drop = document.createElement('button');
  drop.className = 'drop'; drop.textContent = 'unwrap'; drop.title = 'keep only the first operand';
  drop.onclick = () => onChange(node.a);
  head.append(label, drop);

  const kids = document.createElement('div');
  kids.className = 'kids';
  kids.append(nodeEditor(node.a, (v) => onChange({...node, a: v})),
              nodeEditor(node.b, (v) => onChange({...node, b: v})));

  box.append(head, kids);
  return box;
}

// ---- tiles ---------------------------------------------------------------

function describe(node) {
  if (node === null) return 'unset';
  if (typeof node === 'number') return String(node);
  if (typeof node === 'string') return node;
  return `${describe(node.a)} ${OPS[node.op]} ${describe(node.b)}`;
}

function tile(key) {
  const driver = driverOf(key);
  const el = document.createElement('div');

  if (!open.has(key)) {
    el.className = 'tile shut' + (driver === null ? ' empty' : '');
    el.innerHTML = `<b>${slotOf(key)}</b> <span class="who">${describe(driver)}</span>`;
    el.onclick = () => { open.add(key); draw(); };
    return el;
  }

  el.className = 'tile open';
  const head = document.createElement('div');
  head.className = 'head';
  head.innerHTML = `<b>${slotOf(key)}</b><span>close</span>`;
  head.onclick = () => { open.delete(key); delete edits[key]; draw(); };
  el.append(head);

  el.append(nodeEditor(driver, (v) => {
    edits[key] = v;
    if (complete(v)) send(key, v); else draw();
  }));
  return el;
}

// Send a Patch carrying just this slot - no ccs, so live knobs are untouched.
async function send(key, tree) {
  const r = await post('/current', {ccs: {}, slots: {[key]: tree}});
  if (!r.ok) alert((await r.json()).detail);
  delete edits[key];
  draw();
}

// ---- page ----------------------------------------------------------------

async function draw() {
  [rig, patch] = await Promise.all([get('/rig'), get('/current')]);

  const effects = [...new Set(rig.slots.map(effectOf))];
  if (!effects.includes(active)) active = effects[0] ?? null;

  const tabs = document.getElementById('tabs');
  tabs.innerHTML = '';
  for (const name of effects) {
    const slots = rig.slots.filter(k => effectOf(k) === name);
    const unset = slots.filter(k => driverOf(k) === null).length;
    const b = document.createElement('button');
    b.className = 'tab' + (name === active ? ' on' : '');
    b.innerHTML = `${name}<small>${slots.length} slots${unset ? ` · ${unset} unset` : ''}</small>`;
    b.onclick = () => { active = name; draw(); };
    tabs.append(b);
  }

  const box = document.getElementById('presets');
  box.innerHTML = '';
  for (let n = 0; n < rig.size; n++) {
    const saved = rig.presets.includes(n);
    const d = document.createElement('div');
    d.className = 'preset' + (saved ? ' saved' : '') + (n === rig.selected ? ' on' : '');
    d.textContent = n;
    d.title = saved ? 'click to load, shift-click to overwrite' : 'shift-click to store';
    d.onclick = async (ev) => {
      if (ev.shiftKey) await post(`/presets/${n}/store`);
      else if (saved) { const r = await post(`/presets/${n}/load`);
                        if (!r.ok) alert((await r.json()).detail); }
      draw();
    };
    box.append(d);
  }

  const tiles = document.getElementById('tiles');
  tiles.innerHTML = '';
  for (const key of rig.slots.filter(k => effectOf(k) === active)) tiles.append(tile(key));

  drawControls();
}

// The knob values are part of the Patch, so they come from the same fetch.
function drawControls() {
  const box = document.getElementById('controls');
  box.innerHTML = '';
  for (const cc of Object.keys(patch.ccs).map(Number).sort((x, y) => x - y)) {
    const value = patch.ccs[cc];
    const step = cc >= STEP_CC[0] && cc <= STEP_CC[1];
    const d = document.createElement('div');
    d.className = 'cc' + (step ? ' step' : '');
    d.innerHTML = `${cc}: <b>${value}</b>` +
                  `<span class="bar" style="width:${(value / 127 * 100).toFixed(0)}%"></span>`;
    box.append(d);
  }
}

async function drawStats() {
  const s = await get('/stats');
  document.getElementById('stats').textContent =
    `${s.fps.toFixed(1)} fps · render ${s.render_ms.toFixed(2)}ms · gc ${s.gc_ms.toFixed(2)}ms`;
}

// Knobs move under us, so refresh the Patch too - but not while a tile is open,
// which would pull the tree out from under the edit.
async function poll() {
  drawStats();
  if (open.size === 0) { patch = await get('/current'); drawControls(); }
}

draw(); drawStats();
setInterval(poll, 1000);
