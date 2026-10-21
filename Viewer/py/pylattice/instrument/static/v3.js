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
    card.className = 'effect' + (isMuted(name) ? ' off' : '');
    card.dataset.effect = name;

    const head = document.createElement('div');
    head.className = 'effect-head';
    const title = document.createElement('b');
    title.textContent = name;
    const count = document.createElement('span');
    count.className = 'dim';
    count.textContent = `${wired}/${keys.length}`;
    const sw = document.createElement('button');
    sw.className = 'switch' + (isMuted(name) ? '' : ' on');
    sw.title = isMuted(name) ? `unmute ${name}` : `mute ${name}`;
    sw.onclick = () => setMuted(isMuted(name) ? rig.muted.filter(n => n !== name)
                                              : [...rig.muted, name]);

    head.append(title, count, sw);

    card.append(head);
    list.append(card);
  }
}

// ---- keeping up ----------------------------------------------------------

async function refresh() {
  [rig, views] = await Promise.all([get('/rig'), get('/presets')]);
  drawPresets();
  if (!adding) drawEffects();
}

async function drawStats() {
  const s = await get('/stats');
  document.getElementById('fps').textContent = `${s.fps.toFixed(0)} fps`;
}

refresh(); drawStats();

// The preset can change from the controller - a program change - so the bar
// follows it rather than showing what it was at load.
setInterval(() => { refresh(); drawStats(); }, 1000);
