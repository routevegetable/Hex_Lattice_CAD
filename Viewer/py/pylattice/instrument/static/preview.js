// The visual cheatsheet: a popup that plays one part of a formula out on the
// real rig, and colours every end from red (0) to blue (1) through purple.
//
// The values come from the server (/ws/preview), which runs the real fields on a
// set of its own. This file only draws them: a frame is one byte saying whether
// the pads are down, then a byte per end, 0-255 for 0-1.
//
// What is drawn is Viewer/index.html's rig, without the room or the sidebars:
// the same Hinge Hexagon segments, hinged the same way, with the same glowing
// filaments, bloom and reflections. Two layouts, as in index.html's presets:
// "Hex 60" (a ring of six segments, a 60 degree hinge between each) and "Flat"
// (the same six in a straight row). The pieces below are ported from there, so
// they carry its names; MEASUREMENTS.md has the numbers.
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {mergeGeometries} from 'three/addons/utils/BufferGeometryUtils.js';
import {EffectComposer} from 'three/addons/postprocessing/EffectComposer.js';
import {RenderPass} from 'three/addons/postprocessing/RenderPass.js';
import {UnrealBloomPass} from 'three/addons/postprocessing/UnrealBloomPass.js';
import {OutputPass} from 'three/addons/postprocessing/OutputPass.js';

const SEGMENTS = 6, LEVELS = 2;           // tiles across and up: the rig the fields are made for
const STACK = 1.32;                       // a level up (index.html: 1320 mm at 1 unit per m)
const MODES = {
  hex:  {label: 'Hex 60°', angles: Array(SEGMENTS - 1).fill(60)},
  flat: {label: 'Flat',         angles: Array(SEGMENTS - 1).fill(0)},
};

// Red at 0 to blue at 1, the long way round through purple - but most of the
// range stays red-ish or blue-ish, and purple is only a thin band in the middle,
// so values either side of it can be told apart. Pure red up to 0.10 and pure
// blue from 0.90. [value, hue in degrees]:
const HUES = [[0.10, 360], [0.42, 338], [0.58, 262], [0.90, 240]];
const hueOf = (v) => {
  if (v <= HUES[0][0]) return HUES[0][1];
  for (let i = 1; i < HUES.length; i++) {
    const [v1, h1] = HUES[i], [v0, h0] = HUES[i - 1];
    if (v <= v1) return h0 + (h1 - h0) * (v - v0) / (v1 - v0);
  }
  return HUES[HUES.length - 1][1];
};
export function colourOf(v, out = new THREE.Color()) {
  return out.setHSL(hueOf(v) / 360, 1, 0.5, THREE.SRGBColorSpace);
}

// ---- the segment, loaded once ---------------------------------------------
// Everything read off the glTF that does not depend on the layout.
let segmentPromise = null;
const loadSegment = () => segmentPromise ||= new Promise((resolve, reject) => {
  new GLTFLoader().setPath('/hinge/').load('Hinge Hexagon.gltf', (gltf) => {
    try { resolve(prepareSegment(gltf.scene)); } catch (e) { reject(e); }
  }, undefined, () => reject(new Error('the rig model did not load')));
}).catch((e) => { segmentPromise = null; throw e; });

// The glTF is modelled leg-up. Flip it about its own centre so the F tube
// points down, before anything is read from it.
function flipSegmentVertically(obj) {
  obj.updateMatrixWorld(true);
  const c = new THREE.Box3().setFromObject(obj).getCenter(new THREE.Vector3());
  obj.applyMatrix4(new THREE.Matrix4().makeTranslation(c.x, c.y, c.z)
    .multiply(new THREE.Matrix4().makeRotationX(Math.PI))
    .multiply(new THREE.Matrix4().makeTranslation(-c.x, -c.y, -c.z)));
  obj.updateMatrixWorld(true);
}

// Axis endpoints and a perpendicular frame for one tube (PCA of its vertices).
function extractTube(meshes) {
  const pts = [], c = new THREE.Vector3(), v = new THREE.Vector3();
  for (const mesh of meshes) {
    const p = mesh.geometry.attributes.position, M = mesh.matrixWorld;
    for (let i = 0; i < p.count; i++) { v.fromBufferAttribute(p, i).applyMatrix4(M); pts.push(v.clone()); c.add(v); }
  }
  c.multiplyScalar(1 / pts.length);
  let xx = 0, xy = 0, xz = 0, yy = 0, yz = 0, zz = 0;
  for (const q of pts) {
    const dx = q.x - c.x, dy = q.y - c.y, dz = q.z - c.z;
    xx += dx * dx; xy += dx * dy; xz += dx * dz; yy += dy * dy; yz += dy * dz; zz += dz * dz;
  }
  const w = new THREE.Vector3(0, 0, 1);           // power-iterate the top eigenvector
  for (let it = 0; it < 40; it++) {
    const nx = xx * w.x + xy * w.y + xz * w.z, ny = xy * w.x + yy * w.y + yz * w.z, nz = xz * w.x + yz * w.y + zz * w.z;
    w.set(nx, ny, nz);
    if (w.lengthSq() < 1e-12) { w.set(0, 0, 1); break; }
    w.normalize();
  }
  let tmin = Infinity, tmax = -Infinity;
  for (const q of pts) { const t = q.clone().sub(c).dot(w); if (t < tmin) tmin = t; if (t > tmax) tmax = t; }
  const ref = Math.abs(w.z) < 0.9 ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(1, 0, 0);
  const u = ref.clone().cross(w).normalize();
  return {end0: c.clone().addScaledVector(w, tmin), end1: c.clone().addScaledVector(w, tmax),
          u, v: w.clone().cross(u).normalize()};
}

function prepareSegment(obj) {
  flipSegmentVertically(obj);
  obj.updateMatrixWorld(true);

  // Hinge pins and the apex centre, from the geometry. glTF keeps vertices in
  // each part's own frame, so every one goes through its matrixWorld.
  const v = new THREE.Vector3();
  const eachVertex = (cb) => obj.traverse(o => {
    const p = o.geometry?.attributes?.position;
    if (!p) return;
    for (let i = 0; i < p.count; i++) { v.fromBufferAttribute(p, i).applyMatrix4(o.matrixWorld); cb(v); }
  });
  let maxZ = -Infinity, minZ = Infinity;
  eachVertex(pt => { if (pt.z > maxZ) maxZ = pt.z; if (pt.z < minZ) minZ = pt.z; });
  let sx = 0, n = 0;
  eachVertex(pt => { if (pt.z >= maxZ - 0.002) { sx += pt.x; n++; } });
  const centreX = sx / n;

  // The leftmost compact tube is the left hinge; the right is its mirror.
  let hinge = null;
  obj.traverse(o => {
    if (!o.isMesh || !/tube/i.test(o.name)) return;
    const box = new THREE.Box3().setFromObject(o);
    if (box.getSize(new THREE.Vector3()).x > 0.1) return;
    const c = box.getCenter(new THREE.Vector3());
    if (!hinge || c.x < hinge.x) hinge = c;
  });
  const pins = hinge ? {left: hinge.x, right: 2 * centreX - hinge.x, y: hinge.y}
                     : {left: centreX - 0.381, right: centreX + 0.381, y: 0};

  // The six tubes: outermost tube-named nodes, with the grey material made
  // translucent so the filaments show through.
  const roots = [];
  obj.traverse(o => {
    if (!/tube/i.test(o.name)) return;
    for (let p = o.parent; p; p = p.parent) if (/tube/i.test(p.name)) return;
    roots.push(o);
  });
  let tubeMat = null;
  for (const r of roots) r.traverse(o => { if (o.isMesh && !tubeMat) tubeMat = o.material; });
  if (tubeMat) { tubeMat.transparent = true; tubeMat.opacity = 0.2; tubeMat.depthWrite = false; }

  const tubes = [];
  for (const r of roots) {
    const meshes = [];
    r.traverse(o => { if (o.isMesh) meshes.push(o); });
    if (meshes.length) tubes.push({frame: extractTube(meshes), meshes});
  }
  // Classify into A..F (module-edges.svg): the two verticals are C (left) and F
  // (the leg); the four diagonals split upper/lower, then left/right, into A/B
  // (top) and D/E (bottom).
  const info = tubes.map(t => ({t, xcen: (t.frame.end0.x + t.frame.end1.x) / 2,
                                zcen: (t.frame.end0.z + t.frame.end1.z) / 2,
                                vertical: Math.abs(t.frame.end1.z - t.frame.end0.z) > 2 * Math.abs(t.frame.end1.x - t.frame.end0.x)}));
  const verticals = info.filter(i => i.vertical).sort((a, b) => a.xcen - b.xcen);
  const diagonals = info.filter(i => !i.vertical).sort((a, b) => b.zcen - a.zcen);
  if (verticals.length !== 2 || diagonals.length !== 4) throw new Error('the rig model has unexpected tubes');
  const upper = diagonals.slice(0, 2).sort((a, b) => a.xcen - b.xcen);
  const lower = diagonals.slice(2, 4).sort((a, b) => a.xcen - b.xcen);
  const ordered = [upper[0].t, upper[1].t, verticals[0].t, lower[0].t, lower[1].t, verticals[1].t];   // A..F

  // end0 is the top end.
  for (const o of ordered) {
    const f = o.frame;
    if (f.end0.z < f.end1.z) [f.end0, f.end1] = [f.end1, f.end0];
  }
  const legMeshes = new Set(ordered[5].meshes);        // F: hidden on the bottom ring

  // One baked geometry per material, so each is one InstancedMesh. The leg is
  // its own part, left off the bottom ring.
  const byMat = new Map(), legGeoms = [];
  let legMat = null;
  obj.traverse(o => {
    if (!o.isMesh) return;
    let g = o.geometry.clone();
    g.applyMatrix4(o.matrixWorld);
    for (const name of Object.keys(g.attributes)) if (name !== 'position' && name !== 'normal') g.deleteAttribute(name);
    if (g.index) g = g.toNonIndexed();
    if (!g.attributes.normal) g.computeVertexNormals();
    if (legMeshes.has(o)) { legGeoms.push(g); legMat = o.material; return; }
    if (!byMat.has(o.material.uuid)) byMat.set(o.material.uuid, {material: o.material, geoms: []});
    byMat.get(o.material.uuid).geoms.push(g);
  });
  const parts = [...byMat.values()].map(({material, geoms}) => ({geometry: mergeGeometries(geoms, false), material, legOnly: false}));
  if (legGeoms.length) parts.push({geometry: mergeGeometries(legGeoms, false), material: legMat, legOnly: true});

  return {pins, tubes: ordered.map(o => o.frame), parts, zRange: [minZ, maxZ]};
}

// ---- one layout -------------------------------------------------------------
const FIL_HALF = 0.005;                   // filaments sit in a 10 mm square
const FIL_OFFSETS = [[+1, +1], [+1, -1], [-1, +1], [-1, -1]];
const FIL_SEGMENTS = 10, FIL_RADIAL = 5, FIL_RADIUS = 0.0045;
const VPF = (FIL_SEGMENTS + 1) * (FIL_RADIAL + 1);       // vertices per filament
const EMISSIVE_GAIN = 2.4, ALPHA_GAIN = 6;               // push past 1 so bloom lights them
const VERT_T = Float32Array.from({length: VPF}, (_, i) => Math.floor(i / (FIL_RADIAL + 1)) / FIL_SEGMENTS);

// Where each segment sits: each is the last one turned about the shared pin.
function segmentMatrices(seg, anglesDeg) {
  const step = (theta) => new THREE.Matrix4().makeTranslation(seg.pins.right, seg.pins.y, 0)
    .multiply(new THREE.Matrix4().makeRotationZ(theta))
    .multiply(new THREE.Matrix4().makeTranslation(-seg.pins.left, -seg.pins.y, 0));
  const mats = [new THREE.Matrix4()];
  for (const a of anglesDeg) mats.push(mats[mats.length - 1].clone().multiply(step(a * Math.PI / 180)));
  return mats;
}

// Which byte of a frame is this end: modules of two segments side by side,
// stacked in rows; twelve edges to a module; a top end then a bottom.
const slotOf = (lateral, level, edge, top) => ((lateral * LEVELS + level) * 12 + edge) * 2 + (top ? 0 : 1);

function buildRig(seg, mode) {
  const mats = segmentMatrices(seg, MODES[mode].angles);
  const placements = [];
  for (let k = 0; k < LEVELS; k++) {
    const lift = new THREE.Matrix4().makeTranslation(0, 0, STACK * k);
    for (const base of mats) placements.push(new THREE.Matrix4().multiplyMatrices(lift, base));
  }

  const lattice = new THREE.Group();
  for (const part of seg.parts) {
    const list = part.legOnly ? placements.slice(SEGMENTS) : placements;
    const inst = new THREE.InstancedMesh(part.geometry, part.material, list.length);
    list.forEach((m, j) => inst.setMatrixAt(j, m));
    inst.instanceMatrix.needsUpdate = true;
    inst.frustumCulled = false;
    lattice.add(inst);
  }

  // Modules: pairs of lateral neighbours within a level.
  const modules = [];
  for (let k = 0; k < LEVELS; k++)
    for (let i = 0, lateral = 0; i + 1 < SEGMENTS; i += 2, lateral++)
      modules.push({pair: [placements[k * SEGMENTS + i], placements[k * SEGMENTS + i + 1]], lateral, level: k});

  // Every filament as a thin tube, merged into one mesh, remembering which
  // frame byte colours each end of it.
  const geoms = [], ends = [];             // ends[fi] = [slot of top end, slot of bottom end]
  const path = Array.from({length: FIL_SEGMENTS + 1}, () => new THREE.Vector3());
  for (const {pair, lateral, level} of modules) {
    for (let e = 0; e < 12; e++) {
      if (level === 0 && e % 6 === 5) continue;                // the leg dangles on the bottom ring
      const tube = seg.tubes[e % 6], at = pair[e < 6 ? 0 : 1];
      for (const [oa, ob] of FIL_OFFSETS) {
        const cu = [], cv = [];                                // a smooth wander, 0 at both ends
        for (let k = 1; k <= 4; k++) { const amp = 0.006 / k; cu.push((Math.random() * 2 - 1) * amp); cv.push((Math.random() * 2 - 1) * amp); }
        for (let i = 0; i <= FIL_SEGMENTS; i++) {
          const t = i / FIL_SEGMENTS, out = path[i];
          out.copy(tube.end0).lerp(tube.end1, t);
          let du = oa * FIL_HALF, dv = ob * FIL_HALF;
          for (let k = 1; k <= 4; k++) { const s = Math.sin(k * Math.PI * t); du += cu[k - 1] * s; dv += cv[k - 1] * s; }
          out.addScaledVector(tube.u, du).addScaledVector(tube.v, dv).applyMatrix4(at);
        }
        const tg = new THREE.TubeGeometry(new THREE.CatmullRomCurve3(path.map(p => p.clone())), FIL_SEGMENTS, FIL_RADIUS, FIL_RADIAL, false);
        tg.deleteAttribute('uv');
        geoms.push(tg);
        ends.push([slotOf(lateral, level, e, true), slotOf(lateral, level, e, false)]);
      }
    }
  }
  const merged = mergeGeometries(geoms, false);
  geoms.forEach(g => g.dispose());
  const colours = new Float32Array(merged.attributes.position.count * 4);
  merged.setAttribute('color', new THREE.BufferAttribute(colours, 4));
  // Transparent, so a strand with no light fades out instead of showing as a dark tube.
  const material = new THREE.MeshBasicMaterial({vertexColors: true, transparent: true, depthWrite: false});
  material.toneMapped = false;
  const filaments = new THREE.Mesh(merged, material);
  filaments.frustumCulled = false;

  // Where to look: the middle of the rig, and how far it reaches.
  const spots = placements.map(m => new THREE.Vector3().setFromMatrixPosition(m));
  const centre = new THREE.Vector3();
  spots.forEach(p => centre.add(p));
  centre.divideScalar(spots.length);
  centre.z = (seg.zRange[0] + seg.zRange[1]) / 2 + STACK * (LEVELS - 1) / 2;
  const reach = Math.max(...spots.map(p => Math.hypot(p.x - centre.x, p.y - centre.y)));

  return {lattice, filaments, ends, colours, geometry: merged, centre, reach};
}

// ---- the popup ----------------------------------------------------------------
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
  const bar = el('div', 'preview-bar');
  // The same curve as the rig, so the bar is the key to what is drawn.
  bar.style.background = `linear-gradient(to right, ${
    Array.from({length: 21}, (_, i) => `hsl(${hueOf(i / 20).toFixed(1)} 100% 50%) ${i * 5}%`).join(', ')})`;
  legend.append(el('span', 'dim', '0'), bar, el('span', 'dim', '1'));
  const pad = el('span', 'preview-pad dim');
  const foot = el('div', 'preview-foot');
  foot.append(note, pad);
  box.append(head, stage, legend, foot);
  document.body.append(box);

  // -- the scene, as index.html sets it up --
  const renderer = new THREE.WebGLRenderer({antialias: true});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  stage.append(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0b0e);
  const camera = new THREE.PerspectiveCamera(40, 1, 0.02, 200);
  camera.up.set(0, 0, 1);                                      // Z is up, as in the model
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  // index.html is lit by a dim plum fill and a whole room to reflect. Here there
  // is no room, so the fill is stronger and a pair of lights give the panels form.
  const hemi = new THREE.HemisphereLight(new THREE.Color().setHSL(308 / 360, 0.35, 0.55), 0x10131a, 0.8);
  scene.add(hemi);
  const key = new THREE.DirectionalLight(0xffffff, 1.1);
  key.position.set(-3, -5, 6);
  const rim = new THREE.DirectionalLight(0x9db4ff, 0.9);
  rim.position.set(4, 5, 2);
  scene.add(key, rim);

  // Glossy parts reflect the glowing filaments, from a probe in the middle.
  const cubeRT = new THREE.WebGLCubeRenderTarget(256, {type: THREE.HalfFloatType});
  const cubeCam = new THREE.CubeCamera(0.1, 100, cubeRT);
  scene.add(cubeCam);
  scene.environment = cubeRT.texture;
  let envTick = 0;

  // Bloom, through a multisampled target so edges stay smooth.
  const composer = new EffectComposer(renderer, new THREE.WebGLRenderTarget(1, 1, {type: THREE.HalfFloatType, samples: 4}));
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.45, 0.4, 0.75);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());

  let seg = null, rig = null, latest = null, dirty = false, gone = false;
  const colour = new THREE.Color();

  // Paint every filament from the latest frame: its top colour to its bottom.
  function paint() {
    if (!rig) return;
    const lit = new Float32Array(3 * rig.slots);
    for (let s = 0; s < rig.slots; s++) {
      colourOf(latest ? latest[1 + s] / 255 : 0, colour);
      lit[3 * s] = colour.r; lit[3 * s + 1] = colour.g; lit[3 * s + 2] = colour.b;
    }
    const out = rig.colours;
    rig.ends.forEach(([top, bottom], fi) => {
      for (let vv = 0; vv < VPF; vv++) {
        const t = VERT_T[vv], j = (fi * VPF + vv) * 4;
        const r = lit[3 * top] + (lit[3 * bottom] - lit[3 * top]) * t;
        const g = lit[3 * top + 1] + (lit[3 * bottom + 1] - lit[3 * top + 1]) * t;
        const b = lit[3 * top + 2] + (lit[3 * bottom + 2] - lit[3 * top + 2]) * t;
        out[j] = r * EMISSIVE_GAIN; out[j + 1] = g * EMISSIVE_GAIN; out[j + 2] = b * EMISSIVE_GAIN;
        out[j + 3] = Math.min(1, Math.max(r, g, b) * ALPHA_GAIN);
      }
    });
    rig.geometry.getAttribute('color').needsUpdate = true;
  }

  function show(next) {
    mode = next;
    try { localStorage.setItem('v3.previewMode', mode); } catch {}
    for (const b of toggle.children) b.className = b.dataset.id === mode ? 'on' : '';
    if (!seg) return;
    if (rig) { scene.remove(rig.lattice, rig.filaments); rig.geometry.dispose(); rig.lattice.children.forEach(m => m.dispose()); }
    rig = buildRig(seg, mode);
    rig.slots = LEVELS * (SEGMENTS / 2) * 12 * 2;
    scene.add(rig.lattice, rig.filaments);
    cubeCam.position.copy(rig.centre);

    // Looking in from the front and a little above, far enough to take in all of it.
    const span = rig.reach * 2 + 1.8;
    const from = mode === 'flat' ? new THREE.Vector3(0.12, -1, 0.3) : new THREE.Vector3(0.5, -1, 0.42);
    camera.position.copy(rig.centre).addScaledVector(from.normalize(), span * (mode === 'flat' ? 1.0 : 1.12));
    controls.target.copy(rig.centre);
    controls.update();
    dirty = true;
  }

  for (const [id, {label}] of Object.entries(MODES)) {
    const b = el('button', '', label);
    b.dataset.id = id;
    b.onclick = () => show(id);
    toggle.append(b);
  }
  show(mode);

  loadSegment().then((loaded) => {
    if (gone) return;
    seg = loaded;
    show(mode);
  }, (e) => {
    note.textContent = e.message;
    note.classList.add('bad');
  });

  function resize() {
    const {clientWidth: w, clientHeight: h} = stage;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    composer.setSize(w, h);
    bloom.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  const observer = new ResizeObserver(resize);
  observer.observe(stage);

  let frame = 0;
  const loop = () => {
    frame = requestAnimationFrame(loop);
    if (dirty) { paint(); dirty = false; }
    controls.update();
    if (rig && (envTick++ % 12) === 0) {
      cubeCam.update(renderer, scene);
      cubeRT.texture.needsPMREMUpdate = true;
    }
    composer.render();
  };
  loop();

  // -- the values --
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/preview`);
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
    dirty = true;
  };
  // A socket that never gave a frame or an error of its own: most likely a server
  // started before the preview existed.
  ws.onclose = () => {
    if (latest || note.classList.contains('bad')) return;
    note.textContent = 'no preview from the server - is it running the latest code? restart it';
    note.classList.add('bad');
  };

  function closer() {
    gone = true;
    cancelAnimationFrame(frame);
    observer.disconnect();
    ws.onclose = null;
    ws.close();
    controls.dispose();
    if (rig) { rig.geometry.dispose(); rig.lattice.children.forEach(m => m.dispose()); }
    cubeRT.dispose();
    composer.dispose();
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
