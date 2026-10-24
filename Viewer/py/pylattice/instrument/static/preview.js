// The visual cheatsheet: a popup that plays one part of a formula out on a small
// 3D rig, colouring every end from red (0) to blue (1) through purple.
//
// The values come from the server (/ws/preview), which runs the real fields on a
// set of its own. This file only draws them: a frame is one byte saying whether
// the pads are down, then a byte per end, 0-255 for 0-1.
//
// The rig is a cut-down version of Viewer/index.html: the same six edges to a
// segment (A-F, see module-edges.svg), the same hinge geometry, but plain
// prisms instead of the glTF model. Two layouts, as in index.html's presets:
// "Hex 60" (a ring of six segments, a 60 degree hinge between each) and "Flat"
// (the same six in a straight row).
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';

const COLS = 6, ROWS = 2;                 // tiles: the rig the fields are made for
const PITCH = 0.9924;                     // m, hinge to hinge (MEASUREMENTS.md)
const STACK = 1.32;                       // m a level up
const LEVEL_H = Math.sqrt(3);             // a tile's height, in graph units
const R = 1 / Math.sqrt(3);               // a tile's hex radius
const X_SCALE = PITCH;                    // graph x -> m (a tile is one pitch wide)
const H_SCALE = STACK / LEVEL_H;          // graph y -> m
const THICK = 0.035;                      // m, half the width of an edge's prism

const MODES = {
  hex:  {label: 'Hex 60°', joint: 60},
  flat: {label: 'Flat', joint: 0},
};

// Each edge as (u, h) at its top end and its bottom end, where u runs along the
// segment from its centre and h up from the tile's hex centre - the vertices
// graph.py puts at the same names.
const EDGES = [
  [[0, R],         [-0.5, R / 2]],        // A
  [[0, R],         [0.5, R / 2]],         // B
  [[-0.5, R / 2],  [-0.5, -R / 2]],       // C
  [[-0.5, -R / 2], [0, -R]],              // D
  [[0.5, -R / 2],  [0, -R]],              // E
  [[0, -R],        [0, R - LEVEL_H]],     // F: down to the ABF of the tile below
];

// Red at 0 to blue at 1, the long way round through purple.
export function colourOf(v, out = new THREE.Color()) {
  const t = Math.max(0, Math.min(1, v));
  return out.setHSL((360 - 120 * t) / 360, 1, 0.5, THREE.SRGBColorSpace);
}

// Where each segment sits: the centre of segment k and which way it faces, with
// a hinge of `joint` degrees between each and the next.
function chain(joint) {
  const out = [];
  let x = 0, z = 0, a = 0;
  for (let k = 0; k < COLS; k++) {
    if (k > 0) {
      // From the last centre to the shared pin, then on to this centre.
      x += Math.cos(a) * PITCH / 2; z += Math.sin(a) * PITCH / 2;
      a += joint * Math.PI / 180;
      x += Math.cos(a) * PITCH / 2; z += Math.sin(a) * PITCH / 2;
    }
    out.push({x, z, a});
  }
  const cx = out.reduce((s, p) => s + p.x, 0) / COLS;
  const cz = out.reduce((s, p) => s + p.z, 0) / COLS;
  return out.map(p => ({...p, x: p.x - cx, z: p.z - cz}));
}

// Which byte of a frame is this end: modules of two tiles side by side, stacked
// in rows; twelve edges to a module, six from each tile; a top end then a bottom.
const slot = (x, y, edge, top) => (((x >> 1) * ROWS + y) * 12 + edge + 6 * (x & 1)) * 2 + (top ? 0 : 1);

// One prism along every edge of every tile, with two rings of vertices, so a
// colour at each end runs smoothly along it.
function buildRig(mode) {
  const segs = chain(MODES[mode].joint);
  const pos = [], index = [], ends = [];       // ends[v] = frame slot of vertex v's ring
  const centre = new THREE.Vector3();

  for (let y = 0; y < ROWS; y++) for (let x = 0; x < COLS; x++) for (let e = 0; e < 6; e++) {
    const s = segs[x];
    const dir = new THREE.Vector3(Math.cos(s.a), 0, Math.sin(s.a));
    const point = ([u, h]) =>
      new THREE.Vector3(s.x, y * STACK, s.z).addScaledVector(dir, u * X_SCALE).add(new THREE.Vector3(0, h * H_SCALE, 0));
    const p0 = point(EDGES[e][0]), p1 = point(EDGES[e][1]);

    // A square section: the edge's own direction decides which way is "out".
    const along = p1.clone().sub(p0).normalize();
    const side = new THREE.Vector3().crossVectors(along, new THREE.Vector3(0, 0, 1)).normalize();
    if (side.lengthSq() < 0.5) side.set(1, 0, 0);
    const up = new THREE.Vector3().crossVectors(along, side).normalize();

    const base = pos.length / 3;
    for (const [p, top] of [[p0, true], [p1, false]])
      for (const [a, b] of [[1, 1], [1, -1], [-1, -1], [-1, 1]]) {
        pos.push(...p.clone().addScaledVector(side, a * THICK).addScaledVector(up, b * THICK).toArray());
        ends.push(slot(x, y, e, top));
      }
    for (let i = 0; i < 4; i++) {
      const j = (i + 1) % 4;
      index.push(base + i, base + j, base + 4 + j, base + i, base + 4 + j, base + 4 + i);
    }
    centre.add(p0).add(p1);
  }
  centre.divideScalar(pos.length / 3 / 4);

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(new Float32Array(pos.length).fill(0.15), 3));
  geometry.setIndex(index);
  geometry.computeBoundingSphere();
  return {geometry, ends, centre, radius: geometry.boundingSphere.radius};
}

const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};

let open = null;        // the closer of the popup that is up

// Open the popup on `tree`, a formula as a slot holds it. `title` is how it
// reads in words.
export function openPreview(tree, title) {
  if (open) open();

  let mode = 'hex';
  try { mode = localStorage.getItem('v3.previewMode') === 'flat' ? 'flat' : 'hex'; } catch {}

  const box = el('div', 'preview');
  const head = el('div', 'preview-head');
  const heading = el('span', 'preview-title', title);
  heading.title = title;
  const toggle = el('span', 'seg small');
  const close = el('button', 'preview-close', '×');
  close.title = 'close';
  head.append(heading, toggle, close);

  const stage = el('div', 'preview-stage');
  const note = el('div', 'preview-note dim', 'connecting…');
  const legend = el('div', 'preview-legend');
  legend.append(el('span', 'dim', '0'), el('div', 'preview-bar'), el('span', 'dim', '1'));
  const pad = el('span', 'preview-pad dim');
  box.append(head, stage, legend, el('div', 'preview-foot'));
  box.lastChild.append(note, pad);
  document.body.append(box);

  // -- the 3D side --
  const renderer = new THREE.WebGLRenderer({antialias: true});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  stage.append(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0e1014);
  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  let mesh = null, rig = null;
  const colour = new THREE.Color();
  let latest = null;                            // the last frame, as bytes

  function paint() {
    if (!rig) return;
    const attr = rig.geometry.getAttribute('color');
    for (let v = 0; v < rig.ends.length; v++) {
      if (latest) colourOf(latest[1 + rig.ends[v]] / 255, colour); else colour.setRGB(0.15, 0.15, 0.15);
      attr.setXYZ(v, colour.r, colour.g, colour.b);
    }
    attr.needsUpdate = true;
  }

  function show(next) {
    mode = next;
    try { localStorage.setItem('v3.previewMode', mode); } catch {}
    if (mesh) { scene.remove(mesh); mesh.geometry.dispose(); }
    rig = buildRig(mode);
    mesh = new THREE.Mesh(rig.geometry, new THREE.MeshBasicMaterial({vertexColors: true}));
    scene.add(mesh);
    controls.target.copy(rig.centre);
    // Looking in from a corner, a little above, far enough to take in all of it.
    // A flat row is best met head on; a ring from a corner.
    const d = rig.radius * (mode === 'flat' ? 2.4 : 2.6);
    const from = mode === 'flat' ? new THREE.Vector3(0.1, 0.1, 1) : new THREE.Vector3(0.6, 0.35, 0.8);
    camera.position.copy(rig.centre).addScaledVector(from, d);
    controls.update();
    paint();
    for (const b of toggle.children) b.className = b.dataset.id === mode ? 'on' : '';
  }

  for (const [id, {label}] of Object.entries(MODES)) {
    const b = el('button', '', label);
    b.dataset.id = id;
    b.onclick = () => show(id);
    toggle.append(b);
  }
  show(mode);

  function resize() {
    const {clientWidth: w, clientHeight: h} = stage;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  const observer = new ResizeObserver(resize);
  observer.observe(stage);

  let frame = 0;
  const loop = () => {
    frame = requestAnimationFrame(loop);
    controls.update();
    renderer.render(scene, camera);
  };
  loop();

  // -- the values --
  const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/preview`;
  const ws = new WebSocket(url);
  ws.binaryType = 'arraybuffer';
  let usesPad = false;
  ws.onopen = () => ws.send(JSON.stringify({tree}));
  ws.onmessage = (ev) => {
    if (typeof ev.data === 'string') {
      const msg = JSON.parse(ev.data);
      if (msg.error) { note.textContent = msg.error; note.classList.add('bad'); return; }
      usesPad = msg.pad;
      note.textContent = usesPad ? 'knobs at 0.5; pads held 1s, let go 1s' : 'knobs at 0.5';
      return;
    }
    latest = new Uint8Array(ev.data);
    pad.textContent = usesPad ? (latest[0] ? 'pad pressed' : 'pad released') : '';
    paint();
  };
  // A socket that never gave a frame or an error of its own: most likely a server
  // started before the preview existed.
  ws.onclose = () => {
    if (latest || note.classList.contains('bad')) return;
    note.textContent = 'no preview from the server - is it running the latest code? restart it';
    note.classList.add('bad');
  };

  function closer() {
    cancelAnimationFrame(frame);
    observer.disconnect();
    ws.onclose = null;
    ws.close();
    controls.dispose();
    if (mesh) mesh.geometry.dispose();
    renderer.dispose();
    box.remove();
    document.removeEventListener('keydown', onKey);
    if (open === closer) open = null;
  }
  const onKey = (e) => { if (e.key === 'Escape') closer(); };
  document.addEventListener('keydown', onKey);
  close.onclick = closer;
  open = closer;
}
