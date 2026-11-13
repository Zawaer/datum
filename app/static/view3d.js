// 3D evidence viewer: the whole model in quiet grey, evidence elements lit up one by one.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

let renderer, scene, camera, controls, host, model = null, hl = null, spacesHl = null, anim = null;
let positions = null, elements = [], byGuid = new Map();

function b64(s, Type) {
  const bin = atob(s), u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return new Type(u8.buffer);
}

export function init(el) {
  host = el;
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
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
  (function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();
}

function resize() {
  if (!host) return;
  const w = host.clientWidth, h = host.clientHeight;
  renderer.setSize(w, h); camera.aspect = w / Math.max(1, h); camera.updateProjectionMatrix();
}

export async function load(path, onStatus) {
  clear();
  if (model) { scene.remove(model); model.geometry.dispose(); model = null; }
  onStatus && onStatus('tessellating the model…');
  const r = await fetch('/api/mesh?path=' + encodeURIComponent(path));
  if (!r.ok) { onStatus && onStatus('no 3D model'); return false; }
  const d = await r.json();
  positions = new THREE.BufferAttribute(b64(d.positions, Float32Array), 3);
  const allIdx = b64(d.indices, Uint32Array);
  elements = d.elements;
  byGuid = new Map(elements.map(e => [e.guid, e]));
  // the context model: everything except spaces, flat grey, slightly transparent
  const keep = [];
  for (const e of elements) if (e.type !== 'IfcSpace') keep.push(allIdx.subarray(e.start, e.start + e.count));
  const idx = new Uint32Array(keep.reduce((n, a) => n + a.length, 0));
  let o = 0; for (const a of keep) { idx.set(a, o); o += a.length; }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', positions); g.setIndex(new THREE.BufferAttribute(idx, 1));
  g.computeVertexNormals();
  model = new THREE.Mesh(g, new THREE.MeshLambertMaterial({ color: 0xc9d1dc, transparent: true, opacity: 0.35,
    side: THREE.DoubleSide, depthWrite: false }));
  model.userData.allIdx = allIdx;
  scene.add(model);
  frame(g);
  onStatus && onStatus('');
  return true;
}

function frame(geom) {
  geom.computeBoundingBox();
  const b = geom.boundingBox, c = b.getCenter(new THREE.Vector3()), s = b.getSize(new THREE.Vector3());
  const r = Math.max(s.x, s.y, s.z) * 0.5 + 0.5;
  const dist = r / Math.sin((camera.fov * Math.PI / 180) / 2) * 1.2;
  const dir = new THREE.Vector3(1, 0.9, 1.2).normalize();
  camera.position.copy(c.clone().add(dir.multiplyScalar(dist)));
  camera.near = dist / 200; camera.far = dist * 20; camera.updateProjectionMatrix();
  controls.target.copy(c); controls.update();
}

export function clear() {
  if (anim) { clearInterval(anim); anim = null; }
  for (const m of [hl, spacesHl]) if (m) { scene.remove(m); m.geometry.dispose(); }
  hl = spacesHl = null;
}

// items: [{guids, on}] in evidence order. Elements light up one item at a time.
export function highlight(items, animate = true, onStep = null) {
  clear();
  if (!model) return;
  const allIdx = model.userData.allIdx;
  const parts = [], ends = [];
  let n = 0;
  items.forEach(it => {
    if (!it.on) { ends.push(n); return; }
    for (const gid of it.guids || []) {
      const e = byGuid.get(gid); if (!e) continue;
      parts.push(allIdx.subarray(e.start, e.start + e.count)); n += e.count;
    }
    ends.push(n);
  });
  if (!n) return;
  const idx = new Uint32Array(n); let o = 0; for (const a of parts) { idx.set(a, o); o += a.length; }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', positions); g.setIndex(new THREE.BufferAttribute(idx, 1));
  g.computeVertexNormals();
  hl = new THREE.Mesh(g, new THREE.MeshLambertMaterial({ color: 0xff3b6b, emissive: 0x5a0010,
    side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1 }));
  hl.renderOrder = 2;
  scene.add(hl);
  // frame the evidence (with the building still in view around it)
  frame(g);
  if (!animate) return;
  let i = 0;
  g.setDrawRange(0, 0);
  const step = Math.max(20, Math.min(120, 1800 / Math.max(1, items.length)));
  anim = setInterval(() => {
    g.setDrawRange(0, ends[i]); onStep && onStep(i + 1); i++;
    if (i >= ends.length) { clearInterval(anim); anim = null; g.setDrawRange(0, Infinity); }
  }, step);
}

export function hasModel() { return !!model; }
