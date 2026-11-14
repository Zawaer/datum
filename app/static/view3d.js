// 3D evidence viewer: the model as a quiet line drawing, evidence elements lit up one by one.
// Storey focus clips everything above the storey so interior elements (rooms, inner walls) are visible.
// Two view controls live in the viewer itself: "Explode storeys" lifts the floors apart (each one labelled), and
// "X-ray" turns everything that is not evidence into faint glass with its outlines kept, so the counted items stand out.
// The answer is also painted where it applies: the floor area of every room (IfcSpace) in the evidence is filled on its
// slab (one sequential blue by m², or the accent when rooms are counted), counted elements get a pin (a pole and a
// number chip) above them, and one legend bar (bottom left) says what the colours mean.
// Rendering is on demand: frames are drawn only while something moves, never while the view is idle.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';

let renderer, scene, camera, controls, host, model = null, hl = null, offMesh = null, hotMesh = null, anim = null, animDone = null;
let ctxEdges = null, hlEdges = null, offEdges = null, pulse = null, grid = null;
let positions = null, elements = [], byGuid = new Map(), storeys = [], allIdx = null;
let edgeIdx = null;  // per-element outline segments (vertex index pairs into the shared position buffer)
let clip = new THREE.Plane(new THREE.Vector3(0, -1, 0), 1e9), clipWanted = 1e9;
let cbs = {}, revealListener = null;
const ray = new THREE.Raycaster();
// not drawn as context: spaces (would hide the interior) and site / terrain (a big box around everything)
const CONTEXT_SKIP = new Set(['IfcSpace', 'IfcSite', 'IfcGeographicElement']);
const RM = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
const ease = t => t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;  // cubic in-out

// the context model, its outlines and the evidence: one material each, retuned when x-ray is switched
const ctxMat = new THREE.MeshLambertMaterial({ color: 0xd9dee5, side: THREE.DoubleSide, polygonOffset: true,
  polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
const ctxLine = new THREE.LineBasicMaterial({ color: 0x5b6470, transparent: true, opacity: 0.3, depthWrite: false });
const hlLine = new THREE.LineBasicMaterial({ color: 0x003a5c, transparent: true, opacity: 0.85 });
const pulseMat = new THREE.MeshBasicMaterial({ color: 0x56b4e9, transparent: true, opacity: 0, side: THREE.DoubleSide,
  depthTest: false, depthWrite: false });
// dropped (unticked) evidence: a faint grey veil with its outlines, so it can still be found and put back
const offMat = new THREE.MeshLambertMaterial({ color: 0x8a94a3, transparent: true, opacity: 0.1, side: THREE.DoubleSide,
  depthWrite: false });
const offLine = new THREE.LineBasicMaterial({ color: 0x5b6470, transparent: true, opacity: 0.6, depthWrite: false });
// hover and selection: a light accent tint over the element and a 2 px outline, never a solid block of colour
const markTint = new THREE.MeshBasicMaterial({ color: 0x0072b2, transparent: true, opacity: 0.25, side: THREE.FrontSide,
  depthTest: false, depthWrite: false });
const markLine = new LineMaterial({ color: 0x00324f, linewidth: 2, transparent: true, opacity: 0.95, depthTest: false, depthWrite: false });
// rooms painted on their floor: flat, unlit, one colour per evidence item (vertex colours), over the slab
const footMat = new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.85, side: THREE.DoubleSide,
  depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
for (const m of [ctxMat, ctxLine, hlLine, pulseMat, offMat, offLine, markTint, markLine, footMat]) m.clippingPlanes = [clip];
const HEAT = ['#e3eef7', '#bcd7ec', '#8bbadc', '#4f95c6', '#1a6fa6'];  // the 2D heat-map's sequential blue, light = small
const EV = '#0072b2', OFF = '#c9ced6', WHITE = new THREE.Color(1, 1, 1);
// the answer on show, read from the app (a classic script: its top-level bindings are visible here); absent = none
const appRes = () => { try { return res; } catch (e) { return null; } };  // eslint-disable-line no-undef
const appNumber = it => {  // the item's number on the plan and in the list (null when it has none)
  try { if (!numbered(it)) return null; const i = items.indexOf(it); return i < 0 ? null : items.slice(0, i + 1).filter(numbered).length; }  // eslint-disable-line no-undef
  catch (e) { return null; }
};
function breaks(vals) {  // the 2D heat-map's breaks: four round steps, five classes
  const mx = Math.max(1, ...vals);
  const nice = [2, 2.5, 4, 5, 6, 8, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100, 150, 200].find(x => x * 5 >= mx) || Math.ceil(mx / 5);
  return [1, 2, 3, 4].map(k => k * nice);
}
const heatClass = (a, br) => { const i = br.findIndex(b => a < b); return i < 0 ? 4 : i; };

function b64(s, Type) {
  const bin = atob(s), u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return new Type(u8.buffer);
}

// ------------------------------------------------------------ in-viewer controls and storey labels (DOM owned here)
let bar, btnExplode, btnXray, labLayer, labels = [], floorEl = null, pinLayer = null, legEl = null;
let focusSi = null, homeSi = null;  // the storey on show (null = whole building), and the one the evidence is on
const CSS = `
.v3bar { position: absolute; left: 12px; top: 12px; display: flex; gap: 0; z-index: 4; font: 500 13px var(--font, system-ui); }
.v3bar button { border: 1px solid var(--line2, #c3c8cf); background: var(--panel, #fff); color: var(--text, #16191d);
  padding: 5px 10px; cursor: pointer; font: inherit; display: inline-flex; align-items: center; gap: 6px; min-height: 30px; }
.v3bar button + button { border-left: 0; }
.v3bar button:first-child { border-radius: var(--r1, 4px) 0 0 var(--r1, 4px); }
.v3bar button:last-child { border-radius: 0 var(--r1, 4px) var(--r1, 4px) 0; }
.v3bar button:only-child { border-radius: var(--r1, 4px); }
.v3bar button[aria-pressed=true] { background: var(--ink, #16191d); color: #fff; border-color: var(--ink, #16191d); }
.v3bar button[hidden] { display: none; }
.v3bar svg { width: 14px; height: 14px; flex: none; }
.v3labs { position: absolute; inset: 0; pointer-events: none; z-index: 3; overflow: hidden; }
.v3lab { position: absolute; left: 0; top: 0; display: flex; align-items: center; white-space: nowrap; will-change: transform;
  font: 500 11px var(--font, system-ui); letter-spacing: .06em; text-transform: uppercase; color: var(--mut, #5b6470); }
.v3lab b { font-weight: 600; color: var(--text, #16191d); background: var(--panel, #fff); border: 1px solid var(--line2, #c3c8cf);
  border-radius: var(--r1, 4px); padding: 2px 6px; }
.v3lab i { font-style: normal; font-feature-settings: "tnum"; color: var(--mut, #5b6470); margin-left: 6px; letter-spacing: 0; text-transform: none; }
.v3lab.ev b { border-color: var(--ev, #0072b2); box-shadow: inset 3px 0 0 var(--ev, #0072b2); padding-left: 8px; }
.v3lab.ev i { color: var(--ev-ink, #005f94); font-weight: 600; }
.v3lab s { display: block; width: 18px; height: 1px; background: var(--faint, #8a929d); text-decoration: none; }
.v3lab.ev s { background: var(--ev, #0072b2); }
.v3labs.n .v3lab i { display: none; }
.v3floor { position: absolute; left: 14px; top: 60px; z-index: 4; display: flex; align-items: center; gap: 8px;
  font: 13px var(--font, system-ui); color: var(--mut, #5b6470); background: var(--panel, #fff); border: 1px solid var(--line2, #c3c8cf);
  border-radius: var(--r1, 4px); padding: 4px 4px 4px 10px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.v3floor[hidden] { display: none; }
.v3floor b { color: var(--text, #16191d); font-weight: 600; }
.v3floor button { border: 1px solid var(--line2, #c3c8cf); background: var(--panel2, #f5f6f8); color: var(--text, #16191d);
  border-radius: var(--r1, 4px); padding: 3px 9px; font: 500 12px var(--font, system-ui); cursor: pointer; min-height: 26px; }
.v3floor button:hover { border-color: var(--ev, #0072b2); color: var(--ev-ink, #005f94); }
.v3pins { position: absolute; inset: 0; pointer-events: none; z-index: 3; overflow: hidden; }
.v3pin { position: absolute; left: 0; top: 0; display: flex; flex-direction: column; align-items: center; will-change: transform;
  pointer-events: auto; cursor: pointer; }
.v3pin span { display: grid; place-items: center; min-width: 20px; height: 20px; padding: 0 5px; border-radius: 10px; background: var(--ev, #0072b2);
  color: #fff; font: 600 11px/1 var(--font, system-ui); border: 1.5px solid #fff; box-shadow: 0 1px 2px rgba(22,25,29,.25); font-feature-settings: "tnum"; }
.v3pin i { display: block; width: 1.5px; height: 16px; background: #3c4450; }
.v3pin.off span { background: #fff; color: #6b7584; border-color: #7a8594; text-decoration: line-through; box-shadow: none; } .v3pin.off i { background: #9aa2ad; }
.v3pin.hot span { background: var(--hl, #f0e442); color: var(--ink, #16191d); border-color: var(--ink, #16191d); } .v3pin.hot { z-index: 2; }
.v3leg { position: absolute; left: 12px; bottom: 30px; z-index: 4; background: var(--panel, #fff); border: 1px solid var(--line2, #c3c8cf);
  border-radius: var(--r1, 4px); padding: 5px 9px; font: 11px var(--font, system-ui); color: var(--mut, #5b6470); display: flex; gap: 12px;
  align-items: center; pointer-events: none; max-width: calc(100% - 24px); box-shadow: 0 1px 3px rgba(22,25,29,.08); }
.v3leg[hidden] { display: none; }
.v3leg i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; vertical-align: -1px; margin-right: 4px; }
.v3leg .sc { display: inline-flex; flex-direction: column; gap: 1px; }
.v3leg .sc span, .v3leg .sc em { display: grid; grid-template-columns: repeat(5, 22px); gap: 1px; }
.v3leg .sc span i { width: 22px; height: 8px; margin: 0; border-radius: 0; }
.v3leg .sc em { font: 400 9px/1 var(--font, system-ui); font-style: normal; font-feature-settings: "tnum"; }
.v3leg .sc em b { font-weight: 400; transform: translateX(-50%); } .v3leg .sc em b:first-child { transform: none; }
.v3leg .pin { display: inline-grid; place-items: center; width: 14px; height: 14px; border-radius: 7px; background: var(--ev, #0072b2); color: #fff;
  font: 600 8px/1 var(--font, system-ui); vertical-align: -2px; margin-right: 6px; border: 1px solid #fff; box-shadow: 0 0 0 1px var(--ev, #0072b2); }
@media (max-width: 700px) { .v3leg .v3wide { display: none; } .v3leg { bottom: 26px; } }
.v3lab.r { flex-direction: row-reverse; } .v3lab.r i { margin: 0 6px 0 0; }
@media (max-width: 700px) { .v3floor { left: 8px; top: 52px; font-size: 12px; } .v3floor button { min-height: 32px; }
  .v3bar { left: 8px; top: 8px; font-size: 12px; } .v3bar button { padding: 4px 8px; min-height: 36px; }
  .v3lab b { padding: 1px 5px; } .v3lab s { width: 10px; } }
`;
const ICON_EXPLODE = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M2 4.5 8 2l6 2.5L8 7z"/><path d="M2 11.5 8 9l6 2.5L8 14z"/></svg>';
const ICON_XRAY = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><rect x="2.5" y="2.5" width="11" height="11" rx="1" stroke-dasharray="2 1.6"/><rect x="5.5" y="5.5" width="5" height="5" fill="currentColor" stroke="none"/></svg>';

function buildUI() {
  if (!document.getElementById('v3css')) {
    const st = document.createElement('style'); st.id = 'v3css'; st.textContent = CSS; document.head.appendChild(st);
  }
  labLayer = document.createElement('div'); labLayer.className = 'v3labs'; host.appendChild(labLayer);
  pinLayer = document.createElement('div'); pinLayer.className = 'v3pins'; host.appendChild(pinLayer);
  legEl = document.createElement('div'); legEl.className = 'v3leg'; legEl.hidden = true; host.appendChild(legEl);
  // a pin is the element's handle: hover lights its row, a click selects it (the app opens its card beside the pin)
  pinLayer.addEventListener('pointerdown', e => { if (e.target.closest('.v3pin')) e.stopPropagation(); });
  pinLayer.addEventListener('click', e => {
    const p = e.target.closest('.v3pin'); if (!p) return; e.stopPropagation();
    const r = p.getBoundingClientRect();
    if (cbs.onPick) cbs.onPick(p.dataset.g, { x: r.left + r.width / 2, y: r.top + 10 });
  });
  pinLayer.addEventListener('pointerover', e => { const p = e.target.closest('.v3pin'); if (p && cbs.onHover) cbs.onHover(p.dataset.g); });
  pinLayer.addEventListener('pointerout', e => { const p = e.target.closest('.v3pin'); if (p && cbs.onHover && !p.contains(e.relatedTarget)) cbs.onHover(null); });
  bar = document.createElement('div'); bar.className = 'v3bar'; bar.setAttribute('role', 'group'); bar.setAttribute('aria-label', '3D view');
  btnExplode = document.createElement('button'); btnExplode.type = 'button';
  btnExplode.innerHTML = ICON_EXPLODE + '<span>Explode storeys</span>';
  btnExplode.title = 'Lift the storeys apart so every floor can be seen';
  btnXray = document.createElement('button'); btnXray.type = 'button';
  btnXray.innerHTML = ICON_XRAY + '<span>X-ray</span>';
  btnXray.title = 'Show everything that is not evidence as faint outlines';
  bar.append(btnExplode, btnXray); host.appendChild(bar);
  btnExplode.onclick = () => explode(explodeTo < 0.5);
  btnXray.onclick = () => setXray(!xrayOn());
  // the bar sits on the canvas: keep its clicks away from orbit / pick, and from the 2D pan handler around it
  for (const ev of ['pointerdown', 'pointerup', 'wheel']) bar.addEventListener(ev, e => e.stopPropagation());
  // which part of the building is on show: the storey the question is about, or the whole building (a deliberate step)
  floorEl = document.createElement('div'); floorEl.className = 'v3floor'; floorEl.hidden = true;
  floorEl.innerHTML = '<span></span><button type="button"></button>';
  host.appendChild(floorEl);
  for (const ev of ['pointerdown', 'pointerup', 'wheel']) floorEl.addEventListener(ev, e => e.stopPropagation());
  floorEl.querySelector('button').onclick = () => {
    const to = focusSi != null ? 'all' : homeSi;
    if (to == null) return;
    if (cbs.onStorey) cbs.onStorey(to); else focusStorey(to === 'all' ? null : to, true, homeSi);
  };
  syncUI();
}
function syncUI() {
  if (!bar) return;
  bar.hidden = !model;
  // one floor on show: explode and x-ray belong to the whole building, offered once it is on show
  const floor = focusSi != null && !(explodeTo > 0);
  btnExplode.hidden = storeys.length < 2 || floor;
  btnXray.hidden = floor;
  if (floorEl) {
    const nm = i => (storeys[i] && storeys[i].name) || `Storey ${i + 1}`;
    const show = !!model && storeys.length > 1 && (focusSi != null || homeSi != null) && !(explodeTo > 0);
    floorEl.hidden = !show;
    if (show) {
      const sp = floorEl.querySelector('span'), b = floorEl.querySelector('button');
      if (focusSi != null) { sp.innerHTML = '<b></b> only'; sp.firstChild.textContent = nm(focusSi); b.textContent = 'Show whole building'; b.title = 'Show every storey, the rest of the building as faint glass'; }
      else { sp.innerHTML = '<b>Whole building</b>'; b.textContent = `Only ${nm(homeSi)}`; b.title = 'Back to the storey the question is about'; }
    }
  }
  btnExplode.setAttribute('aria-pressed', String(explodeTo > 0.5));
  btnExplode.querySelector('span').textContent = explodeTo > 0.5 ? 'Collapse storeys' : 'Explode storeys';
  btnXray.setAttribute('aria-pressed', String(xrayOn()));
}

export function init(el, callbacks = {}) {
  host = el; cbs = callbacks;
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
  renderer.localClippingEnabled = true;
  el.appendChild(renderer.domElement);
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0xe3e6ea);
  camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 2.2));
  const d = new THREE.DirectionalLight(0xffffff, 1.6); d.position.set(50, 120, 80); scene.add(d);
  buildUI();
  new ResizeObserver(resize).observe(el);
  resize();
  // a click (pressed and released within 4 px and 300 ms) selects the element under the pointer; anything longer or
  // further is an orbit and selects nothing. A click never changes the answer: dropping an item is done in the list.
  // A press during the count only skips the count.
  let down = null, swallow = false;
  renderer.domElement.addEventListener('pointerdown', e => {
    down = [e.clientX, e.clientY, performance.now()]; swallow = false;
    if (anim) { skipReveal(); swallow = true; }
    cbs.onPress && cbs.onPress();
  });
  renderer.domElement.addEventListener('pointerup', e => {
    if (swallow) { swallow = false; return; }
    const d = down; down = null;
    if (!d || Math.hypot(e.clientX - d[0], e.clientY - d[1]) >= 4 || performance.now() - d[2] > 300) return;
    if (cbs.onPick) cbs.onPick(pick(e), { x: e.clientX, y: e.clientY });
  });
  renderer.domElement.addEventListener('pointermove', e => {
    if (e.buttons || !cbs.onHover) return;
    cbs.onHover(pick(e));
  });
  document.addEventListener('keydown', e => { if (anim && e.key === 'Escape' && host.offsetParent) skipReveal(); });
  controls.addEventListener('change', () => { if (!inFrame) requestRender(); });  // user input; update() in a frame decides itself
  controls.addEventListener('start', () => { held = true; tweens.delete(camTween); camTween = null; });
  controls.addEventListener('end', () => { held = false; released = performance.now(); });
  requestRender();
}

// render on demand: one frame per request, and more frames only while the orbit controls are still damping or a
// tween (explode, camera move, reveal pulse) is running. The damping tail is capped in time: it decays per frame, so
// on a slow (software) renderer it would crawl on for a minute
let pending = false, inFrame = false, held = false, released = -1e9;
const DAMP_MS = 2500;
const tweens = new Set();  // functions(now) -> true while still running
window.__v3renders = 0;  // debug counter (headless tests check that the view idles)
export function requestRender() {
  if (pending || !renderer) return;
  pending = true;
  requestAnimationFrame(() => {
    pending = false;
    const now = performance.now();
    for (const f of [...tweens]) if (!f(now)) tweens.delete(f);
    inFrame = true; const moving = controls.update(); inFrame = false;
    if (tweens.size || (moving && (held || now - released < DAMP_MS))) requestRender();  // still easing out
    renderer.render(scene, camera);
    placeLabels(); placePins();
    window.__v3renders++;
  });
}
function tween(f) { tweens.add(f); requestRender(); return f; }

function resize() {
  if (!host) return;
  const w = host.clientWidth, h = host.clientHeight;
  renderer.setSize(w, h); markLine.resolution.set(w, h); camera.aspect = w / Math.max(1, h); camera.updateProjectionMatrix();
  requestRender();
}

// a mesh over a subset of elements, remembering which faces belong to which element (for picking)
function subMesh(list, material) {
  let n = 0; for (const e of list) n += e.count;
  const idx = new Uint32Array(n), ranges = [];
  let o = 0;
  for (const e of list) { idx.set(allIdx.subarray(e.start, e.start + e.count), o); ranges.push([o, e.guid]); o += e.count; }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', positions); g.setIndex(new THREE.BufferAttribute(idx, 1));
  g.computeVertexNormals();
  const m = new THREE.Mesh(g, material);
  m.userData.ranges = ranges;
  m.frustumCulled = false;  // the shared buffer moves when storeys are exploded; the bounds would go stale
  return m;
}

// the outlines of a subset of elements: crease and boundary edges, as segments over the shared position buffer,
// so they move with the storeys like the faces do. ends[] (optional) gets the running segment count per group
function subEdges(groups, material, ends = null) {
  if (!edgeIdx) return null;
  let n = 0; for (const g of groups) for (const e of g) n += e.ecount;
  const idx = new Uint32Array(n);
  let o = 0;
  for (const g of groups) { for (const e of g) { idx.set(edgeIdx.subarray(e.estart, e.estart + e.ecount), o); o += e.ecount; } if (ends) ends.push(o); }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', positions); geo.setIndex(new THREE.BufferAttribute(idx, 1));
  const l = new THREE.LineSegments(geo, material);
  l.frustumCulled = false;
  return l;
}

// crease (> 20 degrees) and open edges of every element; the IFC tessellation shares vertices within an element
function buildEdges() {
  const pa = positions.array, nv = positions.count, COS = Math.cos(20 * Math.PI / 180);
  let out = new Uint32Array(Math.max(1024, allIdx.length)), len = 0;
  const nrm = (t, r) => {
    const a = allIdx[t] * 3, b = allIdx[t + 1] * 3, c = allIdx[t + 2] * 3;
    const ux = pa[b] - pa[a], uy = pa[b + 1] - pa[a + 1], uz = pa[b + 2] - pa[a + 2];
    const vx = pa[c] - pa[a], vy = pa[c + 1] - pa[a + 1], vz = pa[c + 2] - pa[a + 2];
    let x = uy * vz - uz * vy, y = uz * vx - ux * vz, z = ux * vy - uy * vx;
    const l = Math.hypot(x, y, z) || 1; r[0] = x / l; r[1] = y / l; r[2] = z / l;
  };
  const n1 = [0, 0, 0], n2 = [0, 0, 0], m = new Map();
  for (const e of elements) {
    e.estart = len; m.clear();
    for (let t = e.start, end = e.start + e.count; t < end; t += 3) {
      for (let k = 0; k < 3; k++) {
        const u = allIdx[t + k], v = allIdx[t + (k + 1) % 3];
        const key = u < v ? u * nv + v : v * nv + u;
        const f = m.get(key);
        if (f === undefined) m.set(key, t);
        else if (f >= 0) { nrm(f, n1); nrm(t, n2); m.set(key, Math.abs(n1[0] * n2[0] + n1[1] * n2[1] + n1[2] * n2[2]) > COS ? -1 : -2); }
      }
    }
    for (const [key, f] of m) {
      if (f === -1) continue;
      if (len + 2 > out.length) { const o2 = new Uint32Array(out.length * 2); o2.set(out); out = o2; }
      const a = Math.floor(key / nv); out[len++] = a; out[len++] = key - a * nv;
    }
    e.ecount = len - e.estart;
  }
  edgeIdx = out.subarray(0, len);
}

function guidAt(mesh, faceIndex) {
  const r = mesh.userData.ranges, k = faceIndex * 3;
  let lo = 0, hi = r.length - 1;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (r[mid][0] <= k) lo = mid; else hi = mid - 1; }
  return r[lo] ? r[lo][1] : null;
}

function pick(e) {
  if (!model) return null;
  const rc = renderer.domElement.getBoundingClientRect();
  const p = new THREE.Vector2(((e.clientX - rc.left) / rc.width) * 2 - 1, -((e.clientY - rc.top) / rc.height) * 2 + 1);
  ray.setFromCamera(p, camera);
  const targets = [hl, offMesh, model].filter(Boolean);
  const hits = ray.intersectObjects(targets, false).filter(h => h.point.y <= clip.constant + 1e-6);  // raycasts ignore clipping
  if (!hits.length) return null;
  // prefer evidence (lit or toggled off) over the context model when both are under the pointer
  const ev = hits.find(h => h.object !== model) || hits[0];
  return guidAt(ev.object, ev.faceIndex);
}

function dropModel() {
  for (const m of [model, ctxEdges, grid]) if (m) { scene.remove(m); m.geometry.dispose(); }
  model = ctxEdges = grid = null;
  tweens.clear(); camTween = null;
  explodeT = explodeTo = 0; baseY = vStorey = offsets = null; storeyBox = []; edgeIdx = null;
}

export async function load(path, onStatus) {
  clear();
  dropModel(); syncUI(); clearLabels();
  onStatus && onStatus('loading', 'Tessellating the IFC model… (first time can take a while for big models)');
  let r;
  try { r = await fetch('/api/mesh?path=' + encodeURIComponent(path)); } catch (e) { r = null; }
  if (!r || !r.ok) { onStatus && onStatus('error', 'No 3D model could be built for this drawing.'); return null; }
  onStatus && onStatus('loading', 'Building the scene…');
  const d = await r.json();
  dropModel();  // a second load may have finished first
  positions = new THREE.BufferAttribute(b64(d.positions, Float32Array), 3);
  positions.setUsage(THREE.DynamicDrawUsage);
  allIdx = b64(d.indices, Uint32Array);
  elements = d.elements;
  storeys = d.storeys || [];
  byGuid = new Map(elements.map(e => [e.guid, e]));
  prepareStoreys();
  model = subMesh(elements.filter(e => !CONTEXT_SKIP.has(e.type)), ctxMat);
  scene.add(model);
  try { buildEdges(); } catch (e) { edgeIdx = null; }
  ctxEdges = subEdges([elements.filter(e => !CONTEXT_SKIP.has(e.type))], ctxLine);
  if (ctxEdges) { ctxEdges.renderOrder = 1; scene.add(ctxEdges); }
  addGrid();
  { const b = drawnBox(model, true, FABRIC); footprint = { x0: b.min.x, x1: b.max.x, z0: b.min.z, z1: b.max.z }; }
  applyLook();
  setClip(null); requestRender();
  frame(model);
  syncUI();
  onStatus && onStatus('', '');
  return { storeys, n: elements.length };
}

// a faint ground grid under the building, as in a model space
function addGrid() {
  const b = drawnBox(model, true); if (b.isEmpty()) return;
  const s = b.getSize(new THREE.Vector3()), c = b.getCenter(new THREE.Vector3());
  const span = Math.max(s.x, s.z) * 1.6, step = span > 120 ? 10 : span > 40 ? 5 : 1;
  const size = Math.ceil(span / step) * step;
  grid = new THREE.GridHelper(size, Math.round(size / step), 0xb4bbc4, 0xcdd2d8);
  grid.material.transparent = true; grid.material.opacity = 0.7; grid.material.depthWrite = false;
  grid.position.set(c.x, b.min.y - 0.02, c.z);
  grid.renderOrder = -1;
  scene.add(grid);
}

// the box to frame: only vertices a mesh actually draws (the position buffer is shared with undrawn elements).
// For the whole model, prefer the building shell (walls, slabs, spaces) and trim the 2 % tails per axis, so a stray
// proxy or a far-off site object does not shrink the building to a dot. Evidence is framed in full.
const SHELL = /^Ifc(Wall|Slab|Space|Roof|Column|Beam)/;
const FABRIC = /^Ifc(Wall|Slab|Roof|Column|Curtain)/;  // the built fabric only (spaces can sit far off in some models)
function drawnBox(mesh, robust, types = SHELL) {
  let idx = mesh.geometry.index.array;
  if (robust) {
    const shell = elements.filter(e => types.test(e.type));
    if (shell.length) {
      let n = 0; for (const e of shell) n += e.count;
      const sub = new Uint32Array(n); let o = 0;
      for (const e of shell) { sub.set(allIdx.subarray(e.start, e.start + e.count), o); o += e.count; }
      idx = sub;
    }
  }
  const pa = positions.array, b = new THREE.Box3();
  if (!idx.length) return b;
  const stride = Math.max(1, Math.floor(idx.length / 150000));
  const xs = [], ys = [], zs = [];
  for (let i = 0; i < idx.length; i += stride) { const k = idx[i] * 3; xs.push(pa[k]); ys.push(pa[k + 1]); zs.push(pa[k + 2]); }
  const lim = a => {
    if (!robust || a.length < 50) { let lo = Infinity, hi = -Infinity; for (const v of a) { if (v < lo) lo = v; if (v > hi) hi = v; } return [lo, hi]; }
    const s = Float64Array.from(a).sort();
    return [s[Math.floor(s.length * 0.02)], s[Math.min(s.length - 1, Math.ceil(s.length * 0.98))]];
  };
  const [x0, x1] = lim(xs), [y0, y1] = lim(ys), [z0, z1] = lim(zs);
  b.min.set(x0, y0, z0); b.max.set(x1, y1, z1);
  return b;
}

// where the camera should sit to frame a box; dir = view direction (from the target towards the camera)
function framing(b, dir) {
  const c = b.getCenter(new THREE.Vector3()), s = b.getSize(new THREE.Vector3());
  const r = s.length() * 0.5 + 0.3;  // the bounding sphere, so a tall narrow selection is not cut off
  // fit the narrower of the two view angles (a phone is taller than wide); a hidden viewer has no aspect yet
  const fov = camera.fov * Math.PI / 180, asp = camera.aspect > 0.2 ? camera.aspect : 1;
  const hfov = 2 * Math.atan(Math.tan(fov / 2) * asp);
  const dist = r / Math.sin(Math.min(fov, hfov) / 2) * (asp < 1 ? 1.0 : 1.15);
  return { target: c, pos: c.clone().add(dir.clone().normalize().multiplyScalar(dist)), dist };
}
function frame(mesh, steep = false) {
  const b = drawnBox(mesh, mesh === model);
  if (b.isEmpty()) return;
  if (clip.constant < 1e8) b.max.y = Math.min(b.max.y, clip.constant);
  const f = framing(b, steep ? new THREE.Vector3(0.7, 1.8, 1.0) : new THREE.Vector3(1, 0.9, 1.2));
  tweens.delete(camTween); camTween = null;
  camera.position.copy(f.pos);
  camera.near = f.dist / 200; camera.far = f.dist * 20; camera.updateProjectionMatrix();
  controls.target.copy(f.target); controls.update();
  requestRender();
}
// the same, eased over ms (keeping the current view direction)
let camTween = null;
function glideTo(b, ms) {
  if (b.isEmpty()) return;
  const dir = camera.position.clone().sub(controls.target);
  const f = framing(b, dir);
  const p0 = camera.position.clone(), t0 = controls.target.clone(), n0 = camera.near, far0 = camera.far, s = performance.now();
  tweens.delete(camTween);
  camTween = tween(now => {
    const k = ms ? ease(Math.min(1, (now - s) / ms)) : 1;
    camera.position.lerpVectors(p0, f.pos, k); controls.target.lerpVectors(t0, f.target, k);
    camera.near = n0 + (f.dist / 200 - n0) * k; camera.far = far0 + (f.dist * 20 - far0) * k; camera.updateProjectionMatrix();
    return k < 1;
  });
}

export function clear() {
  if (anim) { clearInterval(anim); anim = null; const d = animDone; animDone = null; if (d) d(); }  // never leave a count half-way
  for (const m of [hl, offMesh, hotMesh, hlEdges, offEdges, pulse]) if (m) { scene.remove(m); m.geometry.dispose(); }
  hl = offMesh = hotMesh = hlEdges = offEdges = pulse = null;
  if (foot) { scene.remove(foot); foot.geometry.dispose(); foot = null; footSrc = null; }
  for (const p of pins) p.el.remove(); pins = [];
  if (legEl) legEl.hidden = true;
  setMark('hot', null); setMark('sel', null); pinSets.hot.clear(); pinSets.sel.clear();
  if (hlMat) { hlMat.dispose(); hlMat = null; }
  evStoreys = new Map();
  applyLook(); updateLabels();
  requestRender();
}

// ------------------------------------------------------------ storeys: clipping and the exploded view
// storey index -> clip just under the next storey's floor; null = no clipping. While exploded nothing is clipped:
// every floor is on show, lifted clear of the one under it.
function setClip(si) {
  if (si == null || si < 0 || si >= storeys.length - 1) clipWanted = 1e9;
  else clipWanted = storeys[si + 1].z - 0.25;
  applyClip();
}
function applyClip() { clip.constant = explodeTo > 0 || explodeT > 0 ? 1e9 : clipWanted; }
export function getStoreys() { return storeys; }
// si: the storey to show on its own (everything above it cut away), or null for the whole building; home: the storey
// the evidence is on (offered as "Only <storey>" while the whole building is on show). Going from one storey to the
// whole building, the cut rises through the building while the camera pulls back.
export function focusStorey(si, reframe = true, home) {
  if (home !== undefined) homeSi = home;
  const valid = si != null && si >= 0 && si < storeys.length;
  const was = clipWanted;
  focusSi = valid ? si : null;
  setClip(valid ? si : null);
  syncUI();
  if (!model) return;
  const ev = hl || offMesh;
  if (reframe && !valid && was < 1e8 && clipWanted >= 1e8 && !(explodeTo > 0) && !RM.matches) {
    const top = drawnBox(model, true).max.y + 0.5, b = drawnBox(model, true), t0 = performance.now(), ms = 900;
    clipWanted = was; applyClip();
    for (const f of tweens) if (f.rise) tweens.delete(f);
    const f = now => {
      if (focusSi != null) return false;  // back to one storey meanwhile
      const k = Math.min(1, (now - t0) / ms);
      clipWanted = k >= 1 ? 1e9 : was + (top - was) * ease(k); applyClip();
      return k < 1;
    };
    f.rise = true; tween(f);
    glideTo(b, ms);
  } else if (reframe) frame(ev || model, valid && !(explodeTo > 0));
  requestRender();
}
export function setCut(y) { for (const f of tweens) if (f.rise) tweens.delete(f); clipWanted = y; applyClip(); requestRender(); }

let footprint = null;  // the building's plan extent (robust): every storey label sits off the same corner of it
let baseY = null, vStorey = null, offsets = null, storeyBox = [], explodeT = 0, explodeTo = 0, evStoreys = new Map();
// which storey each vertex belongs to (elements without one go by their base level), the lift of each storey when
// exploded (a storey height and a half per level, so each floor is seen from above with air under the next), and
// whether a storey draws anything (empty ones get no label)
function prepareStoreys() {
  const nv = positions.count, pa = positions.array;
  baseY = new Float32Array(nv); for (let i = 0; i < nv; i++) baseY[i] = pa[i * 3 + 1];
  vStorey = new Int16Array(nv);
  storeyBox = storeys.map(() => ({ n: 0 }));  // how many context elements each storey draws (empty ones get no label)
  if (storeys.length < 2) return;
  const sOf = e => {
    if (e.storey >= 0 && e.storey < storeys.length) return e.storey;
    let s = 0; for (let i = 0; i < storeys.length; i++) if (storeys[i].z <= (e.zmin ?? 0) + 0.3) s = i;
    return s;
  };
  for (const e of elements) {
    const s = sOf(e), bx = storeyBox[s], ctx = !CONTEXT_SKIP.has(e.type);
    for (let t = e.start, end = e.start + e.count; t < end; t++) vStorey[allIdx[t]] = s;
    if (ctx) bx.n++;
  }
  const h = [];
  for (let i = 1; i < storeys.length; i++) { const d = storeys[i].z - storeys[i - 1].z; if (d > 1.5) h.push(d); }
  h.sort((a, b) => a - b);
  const H = h.length ? h[h.length >> 1] : 3;
  const gap = Math.min(8, Math.max(2.5, H * 1.5));
  offsets = new Float32Array(storeys.length);
  for (let i = 0; i < storeys.length; i++) offsets[i] = i * gap;
}
function applyExplode() {
  const pa = positions.array, nv = positions.count, t = explodeT;
  for (let i = 0; i < nv; i++) pa[i * 3 + 1] = baseY[i] + offsets[vStorey[i]] * t;
  positions.needsUpdate = true;
  if (foot) {  // the painted floors ride with their storey
    const fa = foot.geometry.attributes.position;
    for (let j = 0; j < footSrc.length; j++) fa.array[j * 3 + 1] = pa[footSrc[j] * 3 + 1] + 0.03;
    fa.needsUpdate = true;
  }
  for (const k of ['hot', 'sel']) if (marks[k]) markOutline(marks[k]);  // the 2 px outlines hold copies: follow the lift
}

// lift the storeys apart (true) or set them back (false), eased over ~0.8 s; the camera follows to frame the stack
export function explode(on = true, ms = 800) {
  if (!model || !offsets || storeys.length < 2) return;
  const to = on ? 1 : 0;
  if (to === explodeTo) return;
  explodeTo = to; for (const f of tweens) if (f.rise) tweens.delete(f); applyClip(); syncUI();
  if (RM.matches) ms = 0;
  // frame where things will be at the end: the whole stack when lifting, the evidence (or the focused storey) when
  // setting back. Measured on the end state, then the buffer goes back to where it is now
  const from = explodeT, target = hl && !on ? hl : model;
  explodeT = to; applyExplode();
  const b = drawnBox(target, target === model, on ? FABRIC : SHELL);
  explodeT = from; applyExplode();
  if (on) b.expandByVector(new THREE.Vector3(0, offsets[1] * 0.4, 0));  // air above the roof and under the lowest floor
  if (!on && clipWanted < 1e8 && target === model) b.max.y = Math.min(b.max.y, clipWanted);
  const s = performance.now();
  for (const f of tweens) if (f.explode) tweens.delete(f);
  const f = now => {
    const k = ms ? Math.min(1, (now - s) / ms) : 1;
    explodeT = from + (to - from) * ease(k);
    applyExplode(); fadeLabels();
    if (k >= 1) { explodeT = to; applyClip(); syncUI(); for (const m of [model, hl, offMesh, hotMesh]) if (m) { m.geometry.boundingSphere = null; m.geometry.boundingBox = null; } }
    return k < 1;
  };
  f.explode = true;
  tween(f);
  glideTo(b, ms);
  updateLabels();
}
export function isExploded() { return explodeTo > 0.5; }

// ------------------------------------------------------------ storey labels, drawn beside each lifted floor
function clearLabels() { for (const l of labels) l.el.remove(); labels = []; }
function updateLabels() {
  if (!labLayer) return;
  clearLabels();
  if (!model || storeys.length < 2 || (explodeTo === 0 && explodeT === 0)) return;
  storeys.forEach((s, i) => {
    const bx = storeyBox[i]; if (!bx || !bx.n) return;
    const el = document.createElement('div');
    const ev = evStoreys.get(i) || 0;
    el.className = 'v3lab' + (ev ? ' ev' : '');
    const z = s.z, elev = (z >= 0 ? '+' : '−') + Math.abs(z).toFixed(2);
    el.innerHTML = `<b></b><i></i><s></s>`;
    el.querySelector('b').textContent = s.name || `Storey ${i + 1}`;
    el.querySelector('i').textContent = ev ? `${elev} · evidence` : elev;
    el.title = `${s.name}, level ${elev} m`;
    labLayer.appendChild(el);
    labels.push({ el, i, ev, w: 0, h: 0 });
  });
  fadeLabels();
  requestRender();
}
function fadeLabels() { if (labLayer) labLayer.style.opacity = String(Math.max(0, (explodeT - 0.35) / 0.65)); }
const _v = new THREE.Vector3();
function placeLabels() {
  if (!labels.length || !footprint) return;
  const W = host.clientWidth, H = host.clientHeight, shown = [];
  // on a narrow viewer the labels carry the storey name only
  const narrow = W < 560;
  if (labLayer.classList.contains('n') !== narrow) { labLayer.classList.toggle('n', narrow); for (const l of labels) l.w = 0; }
  // controls floating over the viewer (ours, and the page's storey / mode / tour panels): labels keep clear of them
  const hr = host.getBoundingClientRect();
  for (const o of [bar, ...(host.parentElement ? host.parentElement.querySelectorAll('.tools3d, .modes, .caption') : [])]) {
    const r = o.getBoundingClientRect();
    if (r.width && r.height) shown.push({ x: r.left - hr.left, y: r.top - hr.top, w: r.width, h: r.height, box: true });
  }
  for (const l of labels) {
    if (!l.w) { l.w = l.el.offsetWidth; l.h = l.el.offsetHeight; }
    const bx = footprint, y = storeys[l.i].z + offsets[l.i] * explodeT + 0.2;
    let lo = null, hi = null;
    for (const [x, z] of [[bx.x0, bx.z0], [bx.x0, bx.z1], [bx.x1, bx.z0], [bx.x1, bx.z1]]) {
      _v.set(x, y, z).project(camera);
      if (_v.z > 1) continue;
      const sx = (_v.x + 1) / 2 * W, sy = (1 - _v.y) / 2 * H;
      if (!lo || sx < lo[0]) lo = [sx, sy];
      if (!hi || sx > hi[0]) hi = [sx, sy];
    }
    l.lo = lo; l.hi = hi;
  }
  // all in one column: beside the left edge of the building if they fit there, else beside its right edge
  const vis = labels.filter(l => l.lo), fitL = vis.every(l => l.lo[0] - l.w - 2 >= 4), fitR = vis.every(l => l.hi[0] + l.w + 2 <= W - 4);
  const right = !fitL && (fitR || vis.reduce((a, l) => a + (W - l.hi[0]) - l.lo[0], 0) > 0);
  for (const l of labels) {
    l.pos = !l.lo ? null : right ? [l.hi[0] + l.w + 2, l.hi[1]] : l.lo;
    l.el.classList.toggle('r', right);
  }
  // evidence storeys first, then top to bottom; a label that would overlap one already placed is left out
  const order = [...labels].sort((a, b) => (b.ev > 0) - (a.ev > 0) || b.i - a.i);
  for (const l of order) {
    let ok = !!l.pos;
    if (ok) {
      const x = Math.min(W - l.w - 4, Math.max(4, l.pos[0] - l.w - 2)), y = Math.min(H - l.h - 2, Math.max(4, l.pos[1] - l.h / 2));
      l.x = x; l.y = y;
      ok = !shown.some(o => y < o.y + o.h + 2 && o.y < y + l.h + 2 && x < o.x + o.w + 2 && o.x < x + l.w + 2);
    }
    l.el.style.display = ok ? '' : 'none';
    if (ok) { l.el.style.transform = `translate(${l.x.toFixed(1)}px, ${l.y.toFixed(1)}px)`; shown.push(l); }
  }
}

// ------------------------------------------------------------ x-ray: everything but the evidence as faint glass
let xrayUser = null;  // null = automatic: on while an answer has evidence to show (even all of it dropped), off for the bare model
function xrayOn() { return xrayUser != null ? xrayUser : !!(hl || offMesh); }
export function setXray(on) { xrayUser = on == null ? null : !!on; applyLook(); syncUI(); requestRender(); }
export function isXray() { return xrayOn(); }
function applyLook() {
  const x = xrayOn();
  // solid: a light-grey model with fine dark outlines; x-ray: barely-there glass, the outlines carry the shape
  ctxMat.transparent = x; ctxMat.opacity = x ? 0.08 : 1; ctxMat.depthWrite = !x;
  ctxMat.color.set(x ? 0xc4ccd6 : 0xd9dee5);
  ctxLine.opacity = x ? 0.2 : 0.32;
  ctxMat.needsUpdate = true;
  if (hlMat && !hlMat.userData.volumes) { hlMat.emissive.set(x ? 0x004670 : 0x002a44); }
  syncUI();
}

// ------------------------------------------------------------ evidence
// which storey to focus so the evidence is visible: the highest storey holding evidence, if the evidence sits
// on one or two adjacent storeys; else none
export function autoStorey(items) {
  const s = new Set();
  for (const it of items) for (const g of it.guids || []) { const e = byGuid.get(g); if (e && e.storey >= 0) s.add(e.storey); }
  if (!s.size) return null;
  const a = [...s].sort((x, y) => x - y);
  if (a[a.length - 1] - a[0] > 1) return null;
  return a[a.length - 1];
}

let hlMat = null, revealSkip = null;
// a listener for the count-up: fn(k, total) after each item lights up (k = items lit so far), and fn(total, total)
// when the count is complete or skipped. The highlight() onStep argument does the same for one call.
export function onReveal(fn) { revealListener = fn; }
// finish the running count at once (a click or tap on the model, Esc, or the caller)
export function skipReveal() { if (revealSkip) revealSkip(); }
export function revealing() { return !!anim; }

// items: [{guids, on}] in evidence order. Elements light up one item at a time (each with a short pulse), in at
// most ~1.8 s however many items there are; instant under prefers-reduced-motion.
export function highlight(items, animate = true, onStep = null, reframe = true, onDone = null) {
  clear();
  if (!model) return;
  if (RM.matches) animate = false;
  const on = [], off = [], ends = [], groups = [];
  let n = 0;
  items.forEach(it => {
    const list = it.on ? on : off, grp = [];
    for (const gid of it.guids || []) { const e = byGuid.get(gid); if (e) { list.push(e); if (it.on) { n += e.count; grp.push(e); } } }
    ends.push(n); groups.push(grp);
  });
  // count evidence items (not elements) per storey, for the labels
  evStoreys = new Map();
  for (const g of groups) { const ss = new Set(g.map(e => e.storey >= 0 ? e.storey : vStorey ? vStorey[allIdx[e.start]] : -1)); for (const s of ss) evStoreys.set(s, (evStoreys.get(s) || 0) + 1); }
  if (off.length) {
    offMesh = subMesh(off, offMat); offMesh.renderOrder = 1;
    scene.add(offMesh);
    offEdges = subEdges([off], offLine);
    if (offEdges) { offEdges.renderOrder = 2; scene.add(offEdges); }
  }
  updateLabels();
  requestRender();
  if (!on.length) {  // every item dropped: keep them in view as faint outlines, so they can be found and put back
    paint(items);
    applyLook();
    if (reframe && offMesh && !(explodeTo > 0)) frame(offMesh, clip.constant < 1e8);
    revealListener && revealListener(items.length, items.length);
    onDone && onDone(); return;
  }
  // rooms are volumes: draw them see-through so what's inside (and the rooms behind) stays visible
  const volumes = on.filter(e => e.type === 'IfcSpace').length > on.length / 2;
  // drawn in the transparent pass, after the context: in x-ray the glass in front of it does not veil it, while a
  // solid (depth-writing) context still hides what is behind a wall
  hlMat = new THREE.MeshLambertMaterial({ color: 0x0072b2, emissive: 0x002a44,
    side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1, clippingPlanes: [clip],
    transparent: true, opacity: volumes ? 0.07 : 1, depthWrite: !volumes });
  hlMat.userData.volumes = volumes;
  hl = subMesh(on, hlMat);
  hl.renderOrder = 2;
  scene.add(hl);
  const eEnds = [];
  hlEdges = subEdges(groups, hlLine, eEnds);
  if (hlEdges) { hlEdges.renderOrder = 3; scene.add(hlEdges); }
  // the pulse: the item that has just lit up, flashed light blue and fading into the evidence blue
  paint(items);
  const pg = new THREE.BufferGeometry();
  pg.setAttribute('position', positions); pg.setAttribute('normal', hl.geometry.getAttribute('normal')); pg.setIndex(hl.geometry.index);
  pulse = new THREE.Mesh(pg, pulseMat); pulse.frustumCulled = false; pulse.renderOrder = 5; pg.setDrawRange(0, 0);
  scene.add(pulse);
  applyLook();
  requestRender();
  if (reframe) { if (explodeTo > 0) requestRender(); else frame(hl, clip.constant < 1e8); }
  const total = items.length;
  if (!animate) { revealListener && revealListener(total, total); onDone && onDone(); return; }
  hl.geometry.setDrawRange(0, 0); if (hlEdges) hlEdges.geometry.setDrawRange(0, 0);
  if (foot) foot.geometry.setDrawRange(0, 0); for (const p of pins) p.shown = false;
  requestRender();
  // time-based, so a slow GPU (or a software renderer) skips steps instead of stretching the count out
  const step = Math.max(20, Math.min(120, 1800 / Math.max(1, total))), dur = step * total, t0 = performance.now();
  let i = 0, pulseAt = 0, pulseFrom = 0;
  const myHl = hl;
  tween(now => {
    if (hl !== myHl) return false;
    const a = Math.max(0, 1 - (now - pulseAt) / 380);
    pulseMat.opacity = 0.9 * a * a;
    if (a <= 0) pg.setDrawRange(0, 0);
    return a > 0 || !!anim;
  });
  const finish = () => {
    clearInterval(anim); anim = null; animDone = null; revealSkip = null;
    hl.geometry.setDrawRange(0, Infinity); if (hlEdges) hlEdges.geometry.setDrawRange(0, Infinity);
    if (foot) foot.geometry.setDrawRange(0, Infinity); for (const p of pins) p.shown = true;
    requestRender();
    revealListener && revealListener(total, total);
    onDone && onDone();
  };
  revealSkip = () => { if (!anim) return; i = total; onStep && onStep(i); finish(); };
  animDone = () => { revealSkip = null; hl && hl.geometry.setDrawRange(0, Infinity); if (foot) foot.geometry.setDrawRange(0, Infinity); for (const p of pins) p.shown = true; onDone && onDone(); };
  anim = setInterval(() => {
    const prev = i;
    i = Math.min(total, Math.max(i + 1, Math.floor((performance.now() - t0) / dur * total)));
    hl.geometry.setDrawRange(0, ends[i - 1]); if (hlEdges) hlEdges.geometry.setDrawRange(0, eEnds[i - 1]);
    if (foot) foot.geometry.setDrawRange(0, fEnds[i - 1]);
    pulseFrom = prev > 0 ? ends[prev - 1] : 0; pg.setDrawRange(pulseFrom, ends[i - 1] - pulseFrom); pulseAt = performance.now();
    for (const p of pins) p.shown = p.k < i;
    requestRender(); onStep && onStep(i); revealListener && i < total && revealListener(i, total);
    if (i >= total) finish();
  }, step);
}

// ------------------------------------------------------------ the answer painted on the floor: rooms, pins, legend
let foot = null, footSrc = null, fEnds = [], pins = [];
// items: as highlight(). Each room (IfcSpace) of an item gets its floor faces copied a few cm above the slab, coloured
// by the item: the m² class when rooms are measured, the accent when counted, grey when dropped. Counted items get a pin.
function paint(items) {
  const r = appRes(), count = !!r && r.type === 'count';
  const isSpace = it => (it.guids || []).some(g => (byGuid.get(g) || {}).type === 'IfcSpace');
  const vals = count ? [] : items.filter(it => isSpace(it) && it.value != null).map(it => +it.value);
  const br = vals.length ? breaks(vals) : null;
  const pa = positions.array, P = [], C = [], src = [], col = new THREE.Color();
  fEnds = [];
  for (const it of items) {
    col.set(!it.on ? OFF : br && it.value != null ? HEAT[heatClass(+it.value, br)] : EV);
    if (it.on && !(br && it.value != null)) col.lerp(WHITE, 0.3);  // counted rooms: the accent, a touch lighter so a marked one stands out
    for (const g of it.guids || []) {
      const e = byGuid.get(g); if (!e || e.type !== 'IfcSpace') continue;
      let lo = Infinity; for (let t = e.start, end = e.start + e.count; t < end; t++) lo = Math.min(lo, pa[allIdx[t] * 3 + 1]);
      for (let t = e.start, end = e.start + e.count; t < end; t += 3) {
        const a = allIdx[t] * 3, b = allIdx[t + 1] * 3, c = allIdx[t + 2] * 3;
        if (pa[a + 1] > lo + 0.2 || pa[b + 1] > lo + 0.2 || pa[c + 1] > lo + 0.2) continue;  // the floor face only
        const ux = pa[b] - pa[a], uz = pa[b + 2] - pa[a + 2], vx = pa[c] - pa[a], vz = pa[c + 2] - pa[a + 2];
        if (Math.abs(ux * vz - uz * vx) < 1e-6) continue;  // a wall face seen edge-on
        for (const v of [a, b, c]) { P.push(pa[v], pa[v + 1] + 0.03, pa[v + 2]); C.push(col.r, col.g, col.b); src.push(v / 3); }
      }
    }
    fEnds.push(P.length / 3);
  }
  if (P.length) {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(P), 3).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute('color', new THREE.BufferAttribute(new Float32Array(C), 3));
    foot = new THREE.Mesh(g, footMat); foot.renderOrder = 1; foot.frustumCulled = false; footSrc = Uint32Array.from(src);
    scene.add(foot);
  }
  // pins: one per numbered item (a count), as long as there are few enough to read
  if (pinLayer && count && items.length <= 150) items.forEach((it, k) => {
    const n = appNumber(it), list = (it.guids || []).map(g => byGuid.get(g)).filter(Boolean);
    if (n == null || !list.length) return;
    const el = document.createElement('div'); el.className = 'v3pin' + (it.on ? '' : ' off'); el.dataset.g = list[0].guid;
    el.innerHTML = `<span>${n}</span><i></i>`; el.title = it.label || '';
    pinLayer.appendChild(el);
    pins.push({ el, list, k, shown: true, space: list.every(e => e.type === 'IfcSpace'), w: 0, h: 0 });
  });
  pinMark('hot', [...pinSets.hot]);
  // the legend: what the colours on the floor mean
  if (legEl) {
    const n = items.filter(it => it.on).length, off = items.length - n;
    let h = br ? `<span class="sc"><span>${HEAT.map(c => `<i style="background:${c}"></i>`).join('')}</span><em><b>0</b>${br.map(b => `<b>${b}</b>`).join('')}</em></span><span>m² per room · ${n} measured</span>`
      : count ? `<span><i class="pin"></i>${n} counted</span>` : `<span><i style="background:${EV}"></i>${n} in the total</span>`;
    if (off) h += `<span><i style="background:#e9ebee;border:1px solid #9aa2ad"></i>${off} dropped</span>`;
    h += `<span class="v3wide">${P.length ? 'Rooms painted on their floor · ' : ''}the rest of the model in grey</span>`;
    legEl.innerHTML = h; legEl.hidden = false;
  }
}
const pinSets = { hot: new Set(), sel: new Set() };
function pinMark(kind, guids) {
  pinSets[kind] = new Set(guids || []);
  for (const p of pins) p.el.classList.toggle('hot', p.list.some(e => pinSets.hot.has(e.guid) || pinSets.sel.has(e.guid)));
  requestRender();
}
// a pin stands on top of its element (a room: on its floor), cut at the storey; its pole is drawn in pixels
const _pb = new THREE.Box3(), _pv = new THREE.Vector3();
function placePins() {
  if (!pins.length) return;
  const W = host.clientWidth, H = host.clientHeight, pa = positions.array;
  for (const p of pins) {
    _pb.makeEmpty();
    for (const e of p.list) for (let t = e.start, end = e.start + e.count; t < end; t += 3) { const k = allIdx[t] * 3; _pb.expandByPoint(_pv.set(pa[k], pa[k + 1], pa[k + 2])); }
    const top = Math.min(p.space ? _pb.min.y + 0.1 : _pb.max.y, clip.constant);
    _pv.set((_pb.min.x + _pb.max.x) / 2, top, (_pb.min.z + _pb.max.z) / 2).project(camera);
    const vis = p.shown && _pb.min.y < clip.constant && _pv.z < 1 && Math.abs(_pv.x) < 1.1 && Math.abs(_pv.y) < 1.1;
    p.el.style.display = vis ? '' : 'none';
    if (!vis) continue;
    if (!p.w) { p.w = p.el.offsetWidth; p.h = p.el.offsetHeight; }
    p.el.style.transform = `translate(${((_pv.x + 1) / 2 * W - p.w / 2).toFixed(1)}px, ${((1 - _pv.y) / 2 * H - p.h).toFixed(1)}px)`;
  }
}

// hover ('hot') and selection ('sel'): a light accent tint and a 2 px outline over the element(s)
const marks = { hot: null, sel: null };
function markOutline(m) {
  if (!edgeIdx) return;
  const pa = positions.array; let n = 0;
  for (const e of m.list) n += e.ecount;
  const arr = new Float32Array(n * 3); let o = 0;
  for (const e of m.list) for (let k = e.estart, end = e.estart + e.ecount; k < end; k++) { const v = edgeIdx[k] * 3; arr[o++] = pa[v]; arr[o++] = pa[v + 1]; arr[o++] = pa[v + 2]; }
  if (m.line) { scene.remove(m.line); m.line.geometry.dispose(); }
  const g = new LineSegmentsGeometry(); g.setPositions(arr);
  m.line = new LineSegments2(g, markLine); m.line.renderOrder = 7; m.line.frustumCulled = false;
  scene.add(m.line);
}
function setMark(kind, guids) {
  const old = marks[kind];
  if (old) { scene.remove(old.mesh); old.mesh.geometry.dispose(); if (old.line) { scene.remove(old.line); old.line.geometry.dispose(); } marks[kind] = null; requestRender(); }
  const list = (guids || []).map(g => byGuid.get(g)).filter(Boolean);
  if (!list.length || !model) return;
  const m = { list, mesh: subMesh(list, markTint), line: null };
  m.mesh.renderOrder = 6; scene.add(m.mesh);
  markOutline(m);
  marks[kind] = m; requestRender();
}
export function hot(guids) { setMark('hot', guids); pinMark('hot', guids); }
// the selected element (a click in 3D, or a row of the evidence list): stays marked until something else is selected
export function select(guids) { setMark('sel', guids); pinMark('sel', guids); }
// where an element is on screen (the middle of its box), for a tooltip beside it; null when behind the camera
export function screenPos(guids) {
  const list = (guids || []).map(g => byGuid.get(g)).filter(Boolean); if (!list.length) return null;
  const pa = positions.array, b = new THREE.Box3(), v = new THREE.Vector3();
  for (const e of list) for (let t = e.start, end = e.start + e.count; t < end; t++) { const k = allIdx[t] * 3; b.expandByPoint(v.set(pa[k], Math.min(pa[k + 1], clip.constant), pa[k + 2])); }
  b.getCenter(v).project(camera);
  if (v.z > 1) return null;
  const rc = renderer.domElement.getBoundingClientRect();
  return { x: rc.left + (v.x + 1) / 2 * rc.width, y: rc.top + (1 - v.y) / 2 * rc.height };
}

export function hasModel() { return !!model; }
export function elementInfo(guid) { return byGuid.get(guid); }
