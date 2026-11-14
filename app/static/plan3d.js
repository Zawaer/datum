// "See it in 3D" for the Swiss CAD plans: the plan's DXF twin (walls, doors, windows, fixtures, rooms) rises into a
// small architectural model, and the current answer's evidence is lit inside it (counted doors glow, measured rooms
// are tinted, each with the number or m² it carries on the drawing and in the list). Read-only, render on demand.
// Self-contained: it reads app.js's state (cur / res / items are global bindings of that classic script), watches the
// DOM for changes, and never calls anything in app.js except rowHot() for hover linking.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const WALL_H = 2.6, DOOR_H = 2.1, SILL = 0.9, HEAD = 2.2;  // assumed heights (the DXF is 2D): said so in the legend
const RISE_MS = 1000;
const COL = {
  paper: 0xe3e6ea, base: 0xf3f4f6, floor: 0xffffff, outdoor: 0xe4e8ec, wall: 0xf5f4f1, cut: 0x2b3036, edge: 0x5b6470,
  glass: 0xa9c4d6, fixture: 0xffffff, ev: 0x0072b2, evTint: 0xb3d4ea, off: 0x9aa2ad, offTint: 0xe9ebee, hl: 0xf0e442,
};
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const $ = s => document.querySelector(s);

// ------------------------------------------------------------ app state (read-only)
const app = {
  cur() { try { return cur; } catch (e) { return null; } },          // eslint-disable-line no-undef
  res() { try { return res; } catch (e) { return null; } },          // eslint-disable-line no-undef
  items() { try { return items || []; } catch (e) { return []; } },  // eslint-disable-line no-undef
  rowHot(i, on) { try { if (typeof window.rowHot === 'function') window.rowHot(i, on, on); } catch (e) { /* app changed */ } },
};
const isSwiss = c => !!c && !!c.path && !c.path.startsWith('uploads/') && c.path.includes('swiss_dwellings/');

// ------------------------------------------------------------ DOM: toggle, container, labels, legend
const viewer = $('#viewer');
const css = document.createElement('style');
css.textContent = `
#p3 { position: absolute; inset: 0; z-index: 3; background: var(--paper); display: none; cursor: grab; touch-action: none; }
#p3.on { display: block; } #p3:active { cursor: grabbing; }
#p3 canvas { display: block; width: 100%; height: 100%; outline: none; }
#viewer.p3on .zoom, #viewer.p3on #stage, #viewer.p3on .ptools, #viewer.p3on .hlegend { visibility: hidden; }
#p3modes { z-index: 6; }
.p3labs { position: absolute; inset: 0; pointer-events: none; overflow: hidden; }
.p3l { position: absolute; left: 0; top: 0; will-change: transform; opacity: 0; transition: opacity .25s ease; white-space: nowrap; }
.p3l.in { opacity: 1; }
.p3n { display: grid; place-items: center; min-width: 20px; height: 20px; padding: 0 5px; border-radius: 10px; background: var(--ev);
  color: #fff; font: 600 11px/1 var(--font); border: 1.5px solid #fff; box-shadow: 0 1px 2px rgba(22,25,29,.25); }
.p3a { display: flex; flex-direction: column; align-items: center; background: #fff; border: 1px solid var(--ev); border-radius: var(--r1);
  padding: 2px 6px 3px; box-shadow: 0 1px 3px rgba(22,25,29,.18); line-height: 1.2; }
.p3a b { font: 600 12px/1.2 var(--font); color: var(--ev-ink); font-feature-settings: "tnum" 1; }
.p3a small { font: 400 11px/1.2 var(--font); color: var(--mut); max-width: 120px; overflow: hidden; text-overflow: ellipsis; }
.p3l.off .p3n { background: #fff; color: #6b7584; border-color: #7a8594; text-decoration: line-through; box-shadow: none; }
.p3l.off .p3a { border-color: var(--faint); } .p3l.off .p3a b { color: var(--faint); text-decoration: line-through; }
.p3l.hot .p3n, .p3l.hot .p3a { background: var(--hl); color: var(--ink); border-color: var(--ink); }
.p3l.hot .p3a b { color: var(--ink); } .p3l.hot { z-index: 2; }
.p3leg { position: absolute; left: 12px; bottom: 30px; z-index: 4; background: var(--panel); border: 1px solid var(--line2); border-radius: var(--r1);
  padding: 4px 8px; font-size: 11px; color: var(--mut); display: flex; gap: 10px; align-items: center; pointer-events: none; max-width: calc(100% - 24px); }
.p3leg i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; vertical-align: -1px; margin-right: 4px; }
.p3load { position: absolute; inset: 0; display: grid; place-items: center; font-size: 13px; color: var(--mut); pointer-events: none; }
@media (max-width: 860px) { .p3leg .p3wide { display: none; } .p3leg { bottom: 26px; } }
`;
document.head.appendChild(css);

const box = document.createElement('div'); box.id = 'p3';
box.innerHTML = '<div class="p3labs"></div><div class="p3leg"></div><div class="p3load" hidden>Building the model from the CAD layers…</div>';
viewer.appendChild(box);
const labs = box.querySelector('.p3labs'), leg = box.querySelector('.p3leg'), loadEl = box.querySelector('.p3load');
// the 2D view pans / zooms / adds items on pointer, wheel and click events that bubble to #viewer: keep ours to ourselves
for (const t of ['pointerdown', 'wheel', 'click', 'dblclick']) box.addEventListener(t, e => e.stopPropagation(), {passive: true});

const tog = document.createElement('div'); tog.className = 'modes'; tog.id = 'p3modes';
tog.innerHTML = '<button id="p3plan" class="on" aria-pressed="true">Plan</button><button id="p3go" aria-pressed="false" title="Raise the walls of this plan from its CAD layers and see the evidence in 3D">3D</button>';
($('#vtools') || viewer).prepend(tog);  // beside the app's ⋯ view menu
tog.querySelector('#p3plan').onclick = () => close();
tog.querySelector('#p3go').onclick = () => open();

// ------------------------------------------------------------ three.js scene (created on first open)
let renderer, scene, camera, controls, root, rise, evGroup, aoTex, data = null, dataPath = null, center = [0, 0], radius = 10;
let built = null, opened = false, path = null, evSig = '', hot = null, ev = [];
const tweens = new Set();
window.__p3renders = 0;

function initGL() {
  if (renderer) return;
  renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  box.prepend(renderer.domElement);
  scene = new THREE.Scene(); scene.background = new THREE.Color(COL.paper);
  camera = new THREE.PerspectiveCamera(35, 1, 0.1, 1000);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = 0.12;
  controls.maxPolarAngle = 1.42; controls.screenSpacePanning = true;
  scene.add(new THREE.HemisphereLight(0xffffff, 0xcfd5dc, 1.7));
  const sun = new THREE.DirectionalLight(0xffffff, 1.9); sun.name = 'sun';
  scene.add(sun); scene.add(sun.target);
  const fill = new THREE.DirectionalLight(0xe8eef5, 0.45); fill.position.set(30, 20, 40); scene.add(fill);
  controls.addEventListener('change', () => { if (!inFrame) requestRender(); });
  controls.addEventListener('start', () => { held = true; });
  controls.addEventListener('end', () => { held = false; released = performance.now(); });
  new ResizeObserver(resize).observe(box);
  const cv = renderer.domElement;
  cv.addEventListener('pointermove', e => { if (!e.buttons) hover(pick(e)); });
  cv.addEventListener('pointerleave', () => hover(null));
  // as in the IFC viewer: a click (within 4 px and 300 ms) selects the item and finds its row; a drag orbits and
  // selects nothing. Neither changes the answer: items are dropped in the evidence list.
  let down = null;
  cv.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY, performance.now()]; });
  cv.addEventListener('pointerup', e => {
    const d = down; down = null;
    if (!d || Math.hypot(e.clientX - d[0], e.clientY - d[1]) >= 4 || performance.now() - d[2] > 300) return;
    select(pick(e));
  });
}

// render on demand (as view3d.js): a frame per request, more only while damping (capped) or a tween runs
let pending = false, inFrame = false, held = false, released = -1e9;
function requestRender() {
  if (pending || !renderer || !opened) return;
  pending = true;
  requestAnimationFrame(now => {
    pending = false;
    for (const t of tweens) { const k = Math.min(1, (now - t.t0) / t.ms); t.step(k); if (k >= 1) { tweens.delete(t); t.done && t.done(); } }
    inFrame = true; const moving = controls.update(); inFrame = false;
    if (tweens.size || (moving && (held || performance.now() - released < 2500))) requestRender();
    renderer.render(scene, camera); window.__p3renders++;
    placeLabels();
  });
}
function tween(ms, step, done) { const t = {t0: performance.now(), ms: reduced ? 1 : ms, step, done}; tweens.add(t); requestRender(); return t; }
const ease = k => 1 - Math.pow(1 - k, 3);

function resize() {
  if (!renderer) return;
  const w = box.clientWidth, h = box.clientHeight; if (!w || !h) return;
  renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); requestRender();
}

// ------------------------------------------------------------ geometry
const P = ([x, y]) => new THREE.Vector2(x - center[0], y - center[1]);  // DXF metres -> shape plane (centred)
function shape(outer, holes = []) {
  const s = new THREE.Shape(outer.map(P));
  for (const h of holes) s.holes.push(new THREE.Path(h.map(P)));
  return s;
}
// extrude plan shapes from y0 to y1 (shape x, y -> world x, -z)
function prism(shapes, y0, y1) {
  const g = new THREE.ExtrudeGeometry(shapes, {depth: y1 - y0, bevelEnabled: false, curveSegments: 1});
  g.rotateX(-Math.PI / 2); g.translate(0, y0, 0);
  return g;
}
function mesh(g, mat, cast = true, receive = true) { const m = new THREE.Mesh(g, mat); m.castShadow = cast; m.receiveShadow = receive; return m; }
function edges(g, opacity = 0.32) {
  return new THREE.LineSegments(new THREE.EdgesGeometry(g, 28), new THREE.LineBasicMaterial({color: COL.edge, transparent: true, opacity}));
}
const centroid = pts => { let x = 0, y = 0; for (const p of pts) { x += p[0]; y += p[1]; } return [x / pts.length, y / pts.length]; };

// soft contact shading baked into one texture over the whole base: blurred wall footprints darken the floor along
// every wall, which reads as ambient occlusion at no per-frame cost (shapes and slabs get uv = plan metres)
function bakeAO(walls, x0, y0, w, h) {
  const S = Math.min(2048, Math.ceil(Math.max(w, h) * 48)), k = S / Math.max(w, h), OFF = 4 * S;
  const c = document.createElement('canvas'); c.width = Math.ceil(w * k); c.height = Math.ceil(h * k);
  const g = c.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height);
  const pass = (blur, alpha) => {
    g.save(); g.shadowColor = `rgba(30,38,50,${alpha})`; g.shadowBlur = blur * k; g.shadowOffsetX = -OFF; g.fillStyle = '#000';
    g.beginPath();
    for (const p of walls) for (const r of [p.outer, ...p.holes]) {
      r.forEach(([x, y], i) => { const X = (x - x0) * k + OFF, Y = (y0 + h - y) * k; i ? g.lineTo(X, Y) : g.moveTo(X, Y); }); g.closePath();
    }
    g.fill('evenodd'); g.restore();
  };
  pass(0.7, 0.34); pass(0.18, 0.3);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
  // shape uv = (x - cx, y - cy): map that onto the canvas (v up = +y)
  t.repeat.set(1 / w, 1 / h); t.offset.set(-(x0 - center[0]) / w, -(y0 - center[1]) / h);
  t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
  return t;
}

function build(d) {
  built = d;
  if (root) { scene.remove(root); root.traverse(o => { o.geometry && o.geometry.dispose(); }); }
  root = new THREE.Group(); scene.add(root);
  const [bx0, by0, bx1, by1] = d.bounds; center = [(bx0 + bx1) / 2, (by0 + by1) / 2];
  radius = Math.hypot(bx1 - bx0, by1 - by0) / 2;
  const m = 1.2, x0 = bx0 - m, y0 = by0 - m, w = bx1 - bx0 + 2 * m, h = by1 - by0 + 2 * m;
  aoTex && aoTex.dispose(); aoTex = bakeAO(d.walls, x0, y0, w, h);

  // the base board (model on a plinth), room floors, then everything that rises
  const baseMat = new THREE.MeshStandardMaterial({color: COL.base, map: aoTex, roughness: 0.95});
  const sideMat = new THREE.MeshStandardMaterial({color: 0xdfe2e6, roughness: 1});
  const rect = [[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]];
  const base = mesh(prism([shape(rect)], -0.35, 0), [baseMat, sideMat], false, true); root.add(base); root.add(edges(base.geometry, 0.25));
  const floorMat = new THREE.MeshStandardMaterial({color: COL.floor, map: aoTex, roughness: 0.9});
  const outMat = new THREE.MeshStandardMaterial({color: COL.outdoor, map: aoTex, roughness: 0.95});
  for (const r of d.rooms) {
    const g = new THREE.ShapeGeometry(shape(r.pts)); g.rotateX(-Math.PI / 2); g.translate(0, 0.015, 0);
    root.add(mesh(g, r.outdoor ? outMat : floorMat, false, true));
  }
  rise = new THREE.Group(); root.add(rise);
  const wallMat = [new THREE.MeshStandardMaterial({color: COL.cut, roughness: 0.8}), new THREE.MeshStandardMaterial({color: COL.wall, roughness: 0.85})];
  const wg = prism(d.walls.map(p => shape(p.outer, p.holes)), 0, WALL_H);
  rise.add(mesh(wg, wallMat)); rise.add(edges(wg));
  const glassMat = new THREE.MeshStandardMaterial({color: COL.glass, transparent: true, opacity: 0.45, roughness: 0.15, metalness: 0.1, depthWrite: false});
  const fixMat = new THREE.MeshStandardMaterial({color: COL.fixture, roughness: 0.6});
  d.symbols.forEach((s, k) => {
    const sh = [shape(s.pts)];
    s.c = centroid(s.pts); s.k = k;
    if (s.kind === 'door') {
      const g = prism(sh, DOOR_H, WALL_H); rise.add(mesh(g, wallMat)); rise.add(edges(g));
    } else if (s.kind === 'window') {
      for (const [a, b] of [[0, SILL], [HEAD, WALL_H]]) { const g = prism(sh, a, b); rise.add(mesh(g, wallMat)); rise.add(edges(g)); }
      const gl = mesh(prism(sh, SILL, HEAD), glassMat, false, false); gl.userData.sym = k; rise.add(gl); s.glass = gl;
    } else if (s.h) {
      const g = prism(sh, 0, s.h); const f = mesh(g, fixMat); rise.add(f); rise.add(edges(g, 0.4)); s.mesh = f;
    }
  });
  evGroup = new THREE.Group(); root.add(evGroup);

  const sun = scene.getObjectByName('sun');
  sun.position.set(radius * 0.6, radius * 1.8, radius * 1.0); sun.target.position.set(0, 0, 0);
  controls.minDistance = 2; controls.maxDistance = radius * 6;
}

// camera on a sphere around the plan: polar 0 = straight down (the 2D view), azimuth 0 = plan north up
function frame(polar, az, k = 1) {
  const fov = camera.fov * Math.PI / 180, aspect = Math.max(0.4, camera.aspect);
  const dist = k * radius / Math.sin(fov / 2) / Math.min(1, aspect) * 1.02;
  const t = new THREE.Vector3(0, 0.6, 0);
  camera.position.set(t.x + dist * Math.sin(polar) * Math.sin(az), t.y + dist * Math.cos(polar), t.z + dist * Math.sin(polar) * Math.cos(az));
  camera.up.set(0, 1, 0); controls.target.copy(t); camera.lookAt(t);
}

// ------------------------------------------------------------ evidence in 3D
const mats = {
  door: new THREE.MeshStandardMaterial({color: COL.ev, emissive: COL.ev, emissiveIntensity: 0.5, transparent: true, opacity: 0.72, roughness: 0.4, depthWrite: false}),
  doorOff: new THREE.MeshStandardMaterial({color: COL.off, transparent: true, opacity: 0.3, roughness: 0.8, depthWrite: false}),
  // room tints are flat (unlit), like the 2D overlay: a lit floor facing the sky would wash the tint out to white
  room: new THREE.MeshBasicMaterial({color: COL.evTint}),
  roomOff: new THREE.MeshBasicMaterial({color: COL.offTint}),
  // hover / selection: a light accent tint with a dark outline (lineHot), never a saturated solid colour
  hotRoom: new THREE.MeshBasicMaterial({color: 0x8dbde0}),
  hot: new THREE.MeshStandardMaterial({color: COL.ev, emissive: COL.ev, emissiveIntensity: 0.25, transparent: true, opacity: 0.45, roughness: 0.6, depthWrite: false}),
  line: new THREE.LineBasicMaterial({color: COL.ev}), lineOff: new THREE.LineBasicMaterial({color: COL.off}), lineHot: new THREE.LineBasicMaterial({color: COL.cut}),
};
const fmtA = v => (Math.round(v * 100) / 100).toFixed(2);

function toPlan(u, v) { const [ax, bx, ay, by] = data.to_page; return [(u - bx) / ax, (v - by) / ay]; }

function signature() {
  const r = app.res(), it = app.items();
  return (r ? r._seq : '-') + '|' + it.map(e => `${e.kind}${e.on ? 1 : 0}${(e.bbox || []).join()}${e.points ? e.points.length : ''}${e.value ?? ''}`).join(';');
}

function clearEvidence() {
  if (!evGroup) return;
  for (const o of [...evGroup.children]) { evGroup.remove(o); o.traverse(x => x.geometry && x.geometry.dispose()); }
  for (const s of data ? data.symbols : []) if (s.glass) s.glass.material = s.glass.userData.base || s.glass.material;
  labs.innerHTML = ''; ev = []; hot = null; selI = null;
}

function applyEvidence(animate) {
  if (!data || !evGroup) return;
  evSig = signature();
  clearEvidence();
  const r = app.res(), list = app.items(), type = r && r.type;
  let k = 0;
  list.forEach((e, i) => {
    const numbered = e.kind === 'box' || (e.kind === 'polygon' && type === 'count');
    if (numbered) k++;
    if (e.kind !== 'box' && e.kind !== 'polygon') return;
    const it = {i, e, on: !!e.on, meshes: [], lines: [], anchor: null, el: null, n: numbered ? k : null};
    if (e.kind === 'box') {
      const [u0, v0, u1, v1] = e.bbox, a = toPlan(u0, v0), b = toPlan(u1, v1);
      const pad = 0.1, rx0 = Math.min(a[0], b[0]) + pad, rx1 = Math.max(a[0], b[0]) - pad, ry0 = Math.min(a[1], b[1]) + pad, ry1 = Math.max(a[1], b[1]) - pad;
      const cx = (rx0 + rx1) / 2, cy = (ry0 + ry1) / 2;
      let best = null, bd = 0.35;
      for (const s of data.symbols) { const d = Math.hypot(s.c[0] - cx, s.c[1] - cy); if (d < bd) { bd = d; best = s; } }
      let g, top;
      if (best && best.kind === 'door') { g = prism([shape(best.pts)], 0.01, DOOR_H); top = WALL_H; }
      else if (best && best.kind === 'window') { g = prism([shape(best.pts)], SILL, HEAD); top = WALL_H; best.glass.visible = false; it.hideGlass = best.glass; }
      else if (best && best.h) { g = prism([shape(best.pts)], 0, best.h + 0.02); top = Math.max(best.h, 1.2); }
      else { const rr = [[rx0, ry0], [rx1, ry0], [rx1, ry1], [rx0, ry1]]; g = prism([shape(rr)], 0.01, 0.6); top = 1.4; }
      const m = mesh(g, it.on ? mats.door : mats.doorOff, false, false); m.userData.i = i; m.renderOrder = 2; evGroup.add(m); it.meshes.push(m);
      const ol = new THREE.LineSegments(new THREE.EdgesGeometry(g, 28), it.on ? mats.line : mats.lineOff); m.add(ol); it.lines.push(ol);
      const [px, py] = best ? best.c : [cx, cy];
      it.anchor = new THREE.Vector3(px - center[0], top + 0.55, -(py - center[1]));
      const stem = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(px - center[0], top, -(py - center[1])), it.anchor]);
      const l = new THREE.Line(stem, it.on ? mats.line : mats.lineOff); evGroup.add(l); it.lines.push(l);
    } else {
      const pts = e.points.map(([u, v]) => toPlan(u, v));
      const num = (e.label || '').split(' ')[0];
      const room = data.rooms.find(q => q.number && q.number === num);
      const ring = room ? room.pts : pts;
      const g = new THREE.ShapeGeometry(shape(ring)); g.rotateX(-Math.PI / 2); g.translate(0, 0.035, 0);
      const m = mesh(g, it.on ? mats.room : mats.roomOff, false, true); m.userData.i = i; m.renderOrder = 1; evGroup.add(m); it.meshes.push(m);
      const outline = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(ring.map(([x, y]) => new THREE.Vector3(x - center[0], 0.05, -(y - center[1])))), it.on ? mats.line : mats.lineOff);
      evGroup.add(outline); it.lines.push(outline);
      const [lx, ly] = room && room.label ? room.label : centroid(ring);
      it.anchor = new THREE.Vector3(lx - center[0], 1.5, -(ly - center[1]));
      const stem = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(lx - center[0], 0.05, -(ly - center[1])), it.anchor]);
      const l = new THREE.Line(stem, it.on ? mats.line : mats.lineOff); evGroup.add(l); it.lines.push(l);
      it.name = room ? room.name : (e.label || '');
    }
    const el = document.createElement('div'); el.className = 'p3l' + (it.on ? '' : ' off');
    if (it.n != null) el.innerHTML = `<span class="p3n">${it.n}</span>`;
    else el.innerHTML = `<span class="p3a"><b>${e.value != null ? fmtA(e.value) + ' m²' : ''}</b>${it.name ? `<small>${esc(it.name)}</small>` : ''}</span>`;
    labs.appendChild(el); it.el = el;
    ev.push(it);
  });
  legend();
  // light them up one after the other (the 2D view counts them out the same way)
  const step = Math.max(25, Math.min(90, 900 / Math.max(1, ev.length)));
  ev.forEach((it, j) => {
    const show = () => { it.el.classList.add('in'); };
    if (!animate || reduced) { show(); return; }
    for (const m of it.meshes) m.scale.set(1, 0.001, 1);
    for (const l of it.lines) l.visible = false;
    setTimeout(() => {
      if (!ev.includes(it)) return;
      for (const l of it.lines) l.visible = true;
      tween(320, k2 => { for (const m of it.meshes) m.scale.y = Math.max(0.001, ease(k2)); });
      show();
    }, j * step);
  });
  requestRender();
}
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

function legend() {
  const r = app.res(), n = ev.filter(x => x.on).length;
  const what = !ev.length ? 'Ask a question to light up its evidence'
    : r && r.type === 'count' ? `<span><i style="background:var(--ev)"></i>${n} counted</span>`
    : `<span><i style="background:#bcd9ed;border:1px solid var(--ev)"></i>${n} measured</span>`;
  leg.innerHTML = `${what}<span class="p3wide">Walls, doors and windows from the CAD layers · heights assumed (2.6 m)</span>`;
}

// numbers and m² labels follow their anchors on every rendered frame; a label that would sit on an earlier one
// is nudged up so the numbers stay readable
const _v = new THREE.Vector3();
function placeLabels() {
  if (!ev.length) return;
  const w = box.clientWidth, h = box.clientHeight, placed = [];
  const order = [...ev].sort((a, b) => (b === hot) - (a === hot) || (b.on - a.on) || a.i - b.i);
  for (const it of order) {
    _v.copy(it.anchor).project(camera);
    if (_v.z > 1 || _v.x < -1.2 || _v.x > 1.2 || _v.y < -1.2 || _v.y > 1.2) { it.el.style.visibility = 'hidden'; continue; }
    it.el.style.visibility = '';
    const ew = it.el.offsetWidth || 20, eh = it.el.offsetHeight || 20;
    let x = (_v.x + 1) / 2 * w - ew / 2, y = (1 - _v.y) / 2 * h - eh;
    for (let t = 0; t < 4; t++) {
      const hit = placed.find(p => x < p[0] + p[2] && x + ew > p[0] && y < p[1] + p[3] && y + eh > p[1]);
      if (!hit) break;
      y = hit[1] - eh - 2;
    }
    placed.push([x, y, ew, eh]);
    it.el.style.transform = `translate(${Math.round(x)}px,${Math.round(y)}px)`;
  }
}

// ------------------------------------------------------------ hover: 3D <-> evidence list
const ray = new THREE.Raycaster();
function pick(e) {
  if (!ev.length) return null;
  const rc = renderer.domElement.getBoundingClientRect();
  ray.setFromCamera(new THREE.Vector2(((e.clientX - rc.left) / rc.width) * 2 - 1, -((e.clientY - rc.top) / rc.height) * 2 + 1), camera);
  const hits = ray.intersectObjects(ev.flatMap(x => x.meshes), false);
  return hits.length ? hits[0].object.userData.i : null;
}
let hoverRow = null, selI = null;
function hover(i) {
  if (i === hoverRow) return;
  if (hoverRow != null) app.rowHot(hoverRow, false);
  hoverRow = i; if (i != null) app.rowHot(i, true);
  setHot(i ?? selI);
  renderer.domElement.style.cursor = i != null ? 'pointer' : '';
}
function select(i) {
  selI = i ?? null; setHot(selI);
  if (selI == null) return;
  const w = $('#evwrap'); if (w && !w.open) w.open = true;
  try { if (typeof window.flashRow === 'function') window.flashRow(selI); else app.rowHot(selI, true); } catch (e) { /* app changed */ }
}
function setHot(i) {
  const it = i == null ? null : ev.find(x => x.i === i) || null;
  if (it === hot) return;
  for (const x of [hot, it]) {
    if (!x) continue;
    const on = x === it, room = x.e.kind === 'polygon';
    for (const m of x.meshes) m.material = on ? (room ? mats.hotRoom : mats.hot) : room ? (x.on ? mats.room : mats.roomOff) : (x.on ? mats.door : mats.doorOff);
    for (const l of x.lines) l.material = on ? mats.lineHot : x.on ? mats.line : mats.lineOff;
    x.el.classList.toggle('hot', on);
  }
  hot = it; requestRender();
}
// pointing at a row of the evidence list lights its element in 3D
const evList = $('#ev');
if (evList) {
  evList.addEventListener('mouseover', e => { if (!opened) return; const d = e.target.closest('div[data-i]'); setHot(d ? +d.dataset.i : null); });
  evList.addEventListener('mouseleave', () => { if (opened) setHot(null); });
}

// ------------------------------------------------------------ open / close / follow the app
async function load(p) {
  if (dataPath === p && data) return data;
  const r = await fetch('/api/plan3d?path=' + encodeURIComponent(p));
  if (!r.ok) throw new Error('no 3D for this drawing');
  const d = await r.json();
  if (!d.walls || !d.walls.length) throw new Error('no walls on this drawing');
  return d;
}

async function open() {
  const c = app.cur(); if (!isSwiss(c) || opened) return;
  opened = true; path = c.path;
  box.classList.add('on'); viewer.classList.add('p3on');
  tog.querySelector('#p3plan').classList.remove('on'); tog.querySelector('#p3go').classList.add('on');
  tog.querySelector('#p3plan').setAttribute('aria-pressed', 'false'); tog.querySelector('#p3go').setAttribute('aria-pressed', 'true');
  initGL(); resize();
  let d;
  loadEl.hidden = false;
  try { d = await load(path); } catch (err) { loadEl.hidden = true; close(); hintMsg('No 3D model could be built from this plan'); return; }
  loadEl.hidden = true;
  if (!opened || path !== (app.cur() || {}).path) return;
  data = d; dataPath = path;
  if (built !== d) build(d);
  applyEvidence(false);
  for (const it of ev) { for (const m of it.meshes) m.scale.y = 0.001; for (const l of it.lines) l.visible = false; it.el.classList.remove('in'); }
  // the rise: from the plan seen straight down, walls grow while the camera tilts to a three-quarter view
  rise.scale.y = 0.001; frame(0.0001, 0);
  const P1 = 0.62, A1 = -0.5;
  tween(window.__p3riseMs || RISE_MS, k => {
    const e = ease(k);
    rise.scale.y = Math.max(0.001, e);
    frame(0.0001 + (P1 - 0.0001) * e, A1 * e, 1 + 0.06 * e);
  }, () => { if (opened) applyEvidence(true); });
}

function close() {
  if (!opened) return;
  opened = false; tweens.clear(); hover(null);
  box.classList.remove('on'); viewer.classList.remove('p3on');
  tog.querySelector('#p3plan').classList.add('on'); tog.querySelector('#p3go').classList.remove('on');
  tog.querySelector('#p3plan').setAttribute('aria-pressed', 'true'); tog.querySelector('#p3go').setAttribute('aria-pressed', 'false');
}

function hintMsg(msg) {
  const h = $('#hint'); if (!h) return;
  h.hidden = false; h.textContent = msg; setTimeout(() => { if (h.textContent === msg) h.hidden = true; }, 2500);
}

function sync() {
  const c = app.cur(), swiss = isSwiss(c);
  const modes = $('#modes'), ifc3d = modes && modes.classList.contains('show');
  tog.classList.toggle('show', swiss && !ifc3d);
  if (opened && (!c || c.path !== path || !swiss)) close();
  if (swiss && c.path !== dataPath) {  // fetch the geometry ahead of the click, so the rise starts at once
    const p = c.path;
    load(p).then(d => { if ((app.cur() || {}).path === p && !opened) { data = d; dataPath = p; if (renderer) build(d); } }).catch(() => {});
    dataPath = p; data = null;
  }
  if (opened && data && signature() !== evSig && !tweens.size) applyEvidence(true);
  else if (opened && data && signature() !== evSig) setTimeout(sync, 300);
}
let syncQ = false;
const q = () => { if (!syncQ) { syncQ = true; requestAnimationFrame(() => { syncQ = false; sync(); }); } };
const mo = new MutationObserver(q);
for (const [sel, opts] of [['#ev', {childList: true}], ['#evwrap', {attributes: true}], ['#img', {attributes: true, attributeFilter: ['src']}],
  ['#modes', {attributes: true}], ['#chips', {childList: true}], ['#answer', {attributes: true, attributeFilter: ['hidden']}]]) {
  const el = $(sel); if (el) mo.observe(el, opts);
}
// a tour step drives the 2D view (hovering numbered marks): leave 3D when it moves on
const cap = $('#capstep'); if (cap) new MutationObserver(() => close()).observe(cap, {childList: true, characterData: true, subtree: true});
document.addEventListener('keydown', e => { if (e.key === 'Escape' && opened && !e.target.closest('input, textarea')) close(); });
q();

window.__p3 = {open, close, get opened() { return opened; }, get ready() { return opened && !!data && !tweens.size; }, get _three() { return {scene, renderer, camera, requestRender}; }};
