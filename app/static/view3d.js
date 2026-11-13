// 3D evidence viewer: the model in quiet grey, evidence elements lit up one by one.
// Storey focus clips everything above the storey so interior elements (rooms, inner walls) are visible.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

let renderer, scene, camera, controls, host, model = null, hl = null, offMesh = null, hotMesh = null, anim = null;
let positions = null, elements = [], byGuid = new Map(), storeys = [], allIdx = null;
let clip = new THREE.Plane(new THREE.Vector3(0, -1, 0), 1e9);
let cbs = {};
const ray = new THREE.Raycaster();
// not drawn as context: spaces (would hide the interior) and site / terrain (a big box around everything)
const CONTEXT_SKIP = new Set(['IfcSpace', 'IfcSite', 'IfcGeographicElement']);

function b64(s, Type) {
  const bin = atob(s), u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return new Type(u8.buffer);
}

export function init(el, callbacks = {}) {
  host = el; cbs = callbacks;
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
  renderer.localClippingEnabled = true;
  el.appendChild(renderer.domElement);
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0xf3f5f8);
  camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 2.2));
  const d = new THREE.DirectionalLight(0xffffff, 1.6); d.position.set(50, 120, 80); scene.add(d);
  new ResizeObserver(resize).observe(el);
  resize();
  // click (not drag) -> pick the element under the pointer
  let down = null;
  renderer.domElement.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener('pointerup', e => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
    const g = pick(e); if (g && cbs.onPick) cbs.onPick(g);
  });
  renderer.domElement.addEventListener('pointermove', e => {
    if (e.buttons || !cbs.onHover) return;
    cbs.onHover(pick(e));
  });
  (function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();
}

function resize() {
  if (!host) return;
  const w = host.clientWidth, h = host.clientHeight;
  renderer.setSize(w, h); camera.aspect = w / Math.max(1, h); camera.updateProjectionMatrix();
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
  return m;
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

export async function load(path, onStatus) {
  clear();
  if (model) { scene.remove(model); model.geometry.dispose(); model = null; }
  onStatus && onStatus('loading', 'Tessellating the IFC model… (first time can take a while for big models)');
  let r;
  try { r = await fetch('/api/mesh?path=' + encodeURIComponent(path)); } catch (e) { r = null; }
  if (!r || !r.ok) { onStatus && onStatus('error', 'No 3D model could be built for this drawing.'); return null; }
  onStatus && onStatus('loading', 'Building the scene…');
  const d = await r.json();
  positions = new THREE.BufferAttribute(b64(d.positions, Float32Array), 3);
  allIdx = b64(d.indices, Uint32Array);
  elements = d.elements;
  storeys = d.storeys || [];
  byGuid = new Map(elements.map(e => [e.guid, e]));
  model = subMesh(elements.filter(e => !CONTEXT_SKIP.has(e.type)), new THREE.MeshLambertMaterial({
    color: 0xc9d1dc, transparent: true, opacity: 0.35, side: THREE.DoubleSide, depthWrite: false, clippingPlanes: [clip] }));
  scene.add(model);
  setClip(null);
  frame(model.geometry);
  onStatus && onStatus('', '');
  return { storeys, n: elements.length };
}

function frame(geom, steep = false) {
  geom.computeBoundingBox();
  const b = geom.boundingBox.clone();
  if (clip.constant < 1e8) b.max.y = Math.min(b.max.y, clip.constant);
  const c = b.getCenter(new THREE.Vector3()), s = b.getSize(new THREE.Vector3());
  const r = Math.max(s.x, s.y, s.z) * 0.5 + 0.5;
  const dist = r / Math.sin((camera.fov * Math.PI / 180) / 2) * 1.15;
  const dir = (steep ? new THREE.Vector3(0.7, 1.8, 1.0) : new THREE.Vector3(1, 0.9, 1.2)).normalize();
  camera.position.copy(c.clone().add(dir.multiplyScalar(dist)));
  camera.near = dist / 200; camera.far = dist * 20; camera.updateProjectionMatrix();
  controls.target.copy(c); controls.update();
}

export function clear() {
  if (anim) { clearInterval(anim); anim = null; }
  for (const m of [hl, offMesh, hotMesh]) if (m) { scene.remove(m); m.geometry.dispose(); }
  hl = offMesh = hotMesh = null;
}

// storey index -> clip just under the next storey's floor; null = no clipping
function setClip(si) {
  if (si == null || si < 0 || si >= storeys.length - 1) clip.constant = 1e9;
  else clip.constant = storeys[si + 1].z - 0.25;
}
export function getStoreys() { return storeys; }
export function focusStorey(si, reframe = true) {
  setClip(si);
  if (reframe && model) frame(hl ? hl.geometry : model.geometry, si != null && si >= 0);
}
export function setCut(y) { clip.constant = y; }

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

// items: [{guids, on}] in evidence order. Elements light up one item at a time.
export function highlight(items, animate = true, onStep = null, reframe = true, onDone = null) {
  clear();
  if (!model) return;
  const on = [], off = [], ends = [];
  let n = 0;
  items.forEach(it => {
    const list = it.on ? on : off;
    for (const gid of it.guids || []) { const e = byGuid.get(gid); if (e) { list.push(e); if (it.on) n += e.count; } }
    ends.push(n);
  });
  if (off.length) {
    offMesh = subMesh(off, new THREE.MeshLambertMaterial({ color: 0x8a94a3, transparent: true, opacity: 0.55,
      side: THREE.DoubleSide, clippingPlanes: [clip] }));
    scene.add(offMesh);
  }
  if (!on.length) return;
  // rooms are volumes: draw them see-through so what's inside (and the rooms behind) stays visible
  const volumes = on.filter(e => e.type === 'IfcSpace').length > on.length / 2;
  hl = subMesh(on, new THREE.MeshLambertMaterial({ color: 0xff3b6b, emissive: 0x5a0010,
    side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1, clippingPlanes: [clip],
    transparent: volumes, opacity: volumes ? 0.42 : 1, depthWrite: !volumes }));
  hl.renderOrder = 2;
  scene.add(hl);
  if (reframe) frame(hl.geometry, clip.constant < 1e8);
  if (!animate) return;
  let i = 0;
  hl.geometry.setDrawRange(0, 0);
  const step = Math.max(20, Math.min(120, 1800 / Math.max(1, items.length)));
  anim = setInterval(() => {
    hl.geometry.setDrawRange(0, ends[i]); onStep && onStep(i + 1); i++;
    if (i >= ends.length) { clearInterval(anim); anim = null; hl.geometry.setDrawRange(0, Infinity); onDone && onDone(); }
  }, step);
}

// hover glow for one evidence item
export function hot(guids) {
  if (hotMesh) { scene.remove(hotMesh); hotMesh.geometry.dispose(); hotMesh = null; }
  const list = (guids || []).map(g => byGuid.get(g)).filter(Boolean);
  if (!list.length || !model) return;
  hotMesh = subMesh(list, new THREE.MeshLambertMaterial({ color: 0xffc400, emissive: 0x664400, side: THREE.DoubleSide,
    polygonOffset: true, polygonOffsetFactor: -2, clippingPlanes: [clip], depthTest: false, transparent: true, opacity: 0.9 }));
  hotMesh.renderOrder = 3;
  scene.add(hotMesh);
}

export function hasModel() { return !!model; }
export function elementInfo(guid) { return byGuid.get(guid); }
