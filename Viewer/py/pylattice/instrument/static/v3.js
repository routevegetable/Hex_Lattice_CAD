// v3: effects down the left, whatever they hold on the right.

const get = (p) => fetch(p).then(r => r.json());
const post = (p) => fetch(p, {method: 'POST'});

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

function drawPresets() {
  if (cells.length !== rig.size) buildPresets();

  cells.forEach((b, n) => {
    b.className = 'pcell' + (rig.presets.includes(n) ? ' saved' : '') +
                  (isDirty(views[n]) ? ' dirty' : '') +
                  (n === rig.selected ? ' on' : '');
  });

  const n = rig.selected;
  const dirty = n !== null && isDirty(views[n]);
  for (const b of [save, revert]) {
    b.disabled = !dirty;
    b.title = dirty ? `${b.dataset.verb} preset ${n}` : `nothing to ${b.dataset.verb}`;
  }
}

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

function drawEffects() {
  list.innerHTML = '';
  const view = views[rig.selected];
  if (!view) return;

  const names = chain(view.live);
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
    card.className = 'effect';
    card.dataset.effect = name;

    const head = document.createElement('div');
    head.className = 'effect-head';
    const title = document.createElement('b');
    title.textContent = name;
    const count = document.createElement('span');
    count.className = 'dim';
    count.textContent = `${wired}/${keys.length}`;
    head.append(title, count);

    card.append(head);
    list.append(card);
  }
}

// ---- keeping up ----------------------------------------------------------

async function refresh() {
  [rig, views] = await Promise.all([get('/rig'), get('/presets')]);
  drawPresets();
  drawEffects();
}

async function drawStats() {
  const s = await get('/stats');
  document.getElementById('fps').textContent = `${s.fps.toFixed(0)} fps`;
}

refresh(); drawStats();

// The preset can change from the controller - a program change - so the bar
// follows it rather than showing what it was at load.
setInterval(() => { refresh(); drawStats(); }, 1000);
