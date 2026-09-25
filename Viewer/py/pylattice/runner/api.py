"""A REST server and a page to drive it, both reading one Console.

    serve(console)      # starts uvicorn on its own thread, returns it

Everything structured is a dataclass - FastAPI serialises those directly, so
there are no dictionaries crossing the wire by hand.
"""
import threading

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from pylattice.runner.console import Console, ControlState, PatchState, Stats
from pylattice.runner.preset import Preset

PAGE = """<!doctype html>
<title>lattice</title>
<style>
 * { box-sizing: border-box; }
 body { font: 14px/1.5 system-ui, sans-serif; margin: 0; color: #222; }
 header { display: flex; align-items: baseline; gap: 1rem;
          padding: .6rem 1rem; border-bottom: 1px solid #ddd; }
 header h1 { font-size: 1rem; margin: 0; }
 .stats { color: #666; font-variant-numeric: tabular-nums; font-size: .85rem; }
 .layout { display: flex; align-items: stretch; min-height: calc(100vh - 3rem); }

 /* left bar: one tab per effect, presets underneath */
 .side { width: 12rem; flex: none; border-right: 1px solid #ddd; padding: .6rem; }
 .tab { display: block; width: 100%; text-align: left; border: 0; background: none;
        font: inherit; padding: .35rem .5rem; border-radius: .3rem; cursor: pointer; }
 .tab:hover { background: #f2f2f2; }
 .tab.on { background: #e8eeff; font-weight: 600; }
 .tab small { display: block; color: #888; font-weight: 400; font-size: .75rem; }
 .side h2 { font-size: .75rem; text-transform: uppercase; letter-spacing: .04em;
            color: #888; margin: 1.2rem 0 .4rem .5rem; }
 .presets { display: grid; grid-template-columns: repeat(4, 1fr); gap: .25rem; }
 .preset { border: 1px solid #ddd; border-radius: .3rem; padding: .2rem; text-align: center;
           font-size: .75rem; cursor: pointer; background: #fff; }
 .preset.saved { background: #eef; }
 .preset.on { border-color: #556; font-weight: 700; }
 .preset:hover { border-color: #99a; }

 /* tiles, flowing left to right */
 .main { flex: 1; padding: .8rem 1rem; }
 .tiles { display: flex; flex-wrap: wrap; gap: .5rem; align-items: flex-start; }
 .tile { border: 1px solid #ccd; border-radius: .4rem; background: #fff; }
 .tile.shut { writing-mode: vertical-rl; text-orientation: mixed; padding: .6rem .35rem;
              cursor: pointer; color: #445; min-height: 8rem; }
 .tile.shut:hover { background: #f6f7ff; }
 .tile.shut .who { color: #99a; font-size: .8rem; }
 .tile.shut.empty { border-style: dashed; border-color: #c88; }
 .tile.open { min-width: 15rem; padding: .5rem .6rem .6rem; }
 .tile .head { display: flex; justify-content: space-between; align-items: baseline;
               cursor: pointer; }
 .tile .head b { font-size: .9rem; }
 .tile .head span { color: #999; font-size: .75rem; }

 /* the expression tree inside an open tile */
 .node { margin-top: .35rem; }
 .node .row { display: flex; gap: .25rem; align-items: center; }
 .kids { margin-left: .6rem; padding-left: .5rem; border-left: 2px solid #dde; }
 .op { font-size: .7rem; color: #667; letter-spacing: .08em; text-transform: uppercase; }
 select, input[type=number] { font: inherit; font-size: .85rem; padding: .1rem; }
 input[type=number] { width: 5rem; }
 .ops button { font: inherit; font-size: .75rem; width: 1.6rem; padding: .05rem;
               border: 1px solid #ccd; background: #fafaff; border-radius: .25rem; cursor: pointer; }
 .ops button:hover { background: #e8eeff; }
 .drop { border: 0; background: none; color: #a55; cursor: pointer; font-size: .8rem; }

 /* controls strip */
 .controls { display: flex; flex-wrap: wrap; gap: .25rem; margin-top: 1.2rem; }
 .cc { border: 1px solid #ddd; border-radius: .25rem; padding: .1rem .4rem; min-width: 4.2rem;
       font-size: .75rem; font-variant-numeric: tabular-nums; }
 .cc.step { border-color: #99c; background: #f4f4ff; }
 .cc .bar { display: block; height: 3px; background: #69c; margin-top: 2px; }
</style>

<header>
  <h1>lattice</h1>
  <span class="stats" id="stats"></span>
</header>

<div class="layout">
  <div class="side">
    <div id="tabs"></div>
    <h2>presets</h2>
    <div class="presets" id="presets"></div>
    <div style="font-size:.7rem;color:#999;margin-top:.4rem">click loads · shift-click stores</div>
  </div>
  <div class="main">
    <div class="tiles" id="tiles"></div>
    <h2 style="font-size:.75rem;text-transform:uppercase;color:#888;margin:1.5rem 0 .3rem">controls</h2>
    <div class="controls" id="controls"></div>
  </div>
</div>

<script>
const OPS = {add: '+', sub: '−', mul: '×'};
const STEP_CC = [20, 55];

const get = (p) => fetch(p).then(r => r.json());
const post = (p, body) => fetch(p, {method: 'POST', headers: {'Content-Type': 'application/json'},
                                    body: body === undefined ? null : JSON.stringify(body)});

let patch = null;
let active = null;              // effect name whose tab is open
let open = new Set();           // "effect.slot" of expanded tiles
let edits = {};                 // "effect.slot" -> tree being edited

// ---- the expression tree -------------------------------------------------

const isLeaf = (n) => n === null || typeof n === 'string' || typeof n === 'number';
const complete = (n) => n === null ? false : isLeaf(n) ? true : complete(n.a) && complete(n.b);

function leafEditor(node, onChange) {
  const row = document.createElement('div');
  row.className = 'row';

  const sel = document.createElement('select');
  sel.append(new Option(node === null ? '— pick a field —' : '— none —', '__none__'));
  for (const f of patch.fields) sel.append(new Option(f, f));
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

  // Operators only once something is in the slot: clicking one wraps what is
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

function tile(effect, slot) {
  const key = `${effect.name}.${slot.name}`;
  const tree = key in edits ? edits[key] : slot.driver;
  const el = document.createElement('div');

  if (!open.has(key)) {
    el.className = 'tile shut' + (slot.driver === null ? ' empty' : '');
    el.innerHTML = `<b>${slot.name}</b> <span class="who">${describe(slot.driver)}</span>`;
    el.onclick = () => { open.add(key); draw(); };
    return el;
  }

  el.className = 'tile open';
  const head = document.createElement('div');
  head.className = 'head';
  head.innerHTML = `<b>${slot.name}</b><span>close</span>`;
  head.onclick = () => { open.delete(key); delete edits[key]; draw(); };
  el.append(head);

  el.append(nodeEditor(tree, (v) => {
    edits[key] = v;
    if (complete(v)) send(key, v); else draw();
  }));
  return el;
}

async function send(key, tree) {
  const r = await post('/current', {ccs: {}, slots: {[key]: tree}});
  if (!r.ok) alert((await r.json()).detail);
  delete edits[key];
  draw();
}

// ---- page ----------------------------------------------------------------

async function draw() {
  patch = await get('/patch');
  if (!patch.effects.some(e => e.name === active)) active = patch.effects[0]?.name ?? null;

  const tabs = document.getElementById('tabs');
  tabs.innerHTML = '';
  for (const e of patch.effects) {
    const b = document.createElement('button');
    b.className = 'tab' + (e.name === active ? ' on' : '');
    b.innerHTML = `${e.name}<small>${e.effect} · ${e.slots.length} slots</small>`;
    b.onclick = () => { active = e.name; draw(); };
    tabs.append(b);
  }

  const box = document.getElementById('presets');
  box.innerHTML = '';
  for (let n = 0; n < patch.size; n++) {
    const saved = patch.presets.includes(n);
    const d = document.createElement('div');
    d.className = 'preset' + (saved ? ' saved' : '') + (n === patch.selected ? ' on' : '');
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
  const effect = patch.effects.find(e => e.name === active);
  if (effect) for (const s of effect.slots) tiles.append(tile(effect, s));
}

async function drawStats() {
  const s = await get('/stats');
  document.getElementById('stats').textContent =
    `${s.fps.toFixed(1)} fps · render ${s.render_ms.toFixed(2)}ms · gc ${s.gc_ms.toFixed(2)}ms`;
}

async function drawControls() {
  const controls = await get('/controls');
  const box = document.getElementById('controls');
  box.innerHTML = '';
  for (const c of controls) {
    const step = c.cc >= STEP_CC[0] && c.cc <= STEP_CC[1];
    const d = document.createElement('div');
    d.className = 'cc' + (step ? ' step' : '');
    d.innerHTML = `${c.cc}: <b>${c.value}</b>` +
                  `<span class="bar" style="width:${(c.value / 127 * 100).toFixed(0)}%"></span>`;
    box.append(d);
  }
}

draw(); drawStats(); drawControls();
setInterval(() => { drawStats(); drawControls(); }, 1000);
</script>
"""


def make_app(console: Console) -> FastAPI:
    app = FastAPI(title="lattice")

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return PAGE

    @app.get("/stats")
    def stats() -> Stats:
        return console.get_stats()

    @app.get("/controls")
    def controls() -> list[ControlState]:
        return console.read_controls()

    @app.get("/patch")
    def patch() -> PatchState:
        return console.describe()

    @app.get("/current")
    def current() -> Preset:
        return console.read_settings()

    @app.post("/current")
    def write_current(preset: Preset) -> Preset:
        try:
            console.write_settings(preset)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        return console.read_settings()

    @app.get("/presets/{number}")
    def read_preset(number: int) -> Preset:
        try:
            return console.read_preset(number)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

    @app.post("/presets/{number}/store")
    def store_preset(number: int) -> Preset:
        try:
            console.store_current_to(number)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        return console.read_preset(number)

    @app.post("/presets/{number}/load")
    def load_preset(number: int) -> Preset:
        try:
            console.load_current_from(number)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        return console.read_settings()

    return app


def serve(console: Console, host: str = "127.0.0.1", port: int = 8800) -> threading.Thread:
    """Run the API on its own daemon thread, so the render loop keeps the main one."""
    config = uvicorn.Config(make_app(console), host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, name="lattice-api", daemon=True)
    thread.start()
    print(f"api on http://{host}:{port}")
    return thread
