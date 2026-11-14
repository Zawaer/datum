// "See it in 3D" for the Swiss CAD plans and the CubiCasa raster plans: the drawing itself lies on the floor (the
// same page the 2D view shows, registered to the CAD twin, or the raster itself), and the plan's walls rise out of it
// as a low cut-away model ("dollhouse": 1.2 m, no ceilings, the plan readable through the open top). A raster plan's
// walls are read from its pixels (the thick dark strokes), and the gaps in them become doors (a beige leaf) or windows
// (glass) by what is drawn inside. Opening it tilts the 2D view up into 3D in one move. The answer is painted on the
// floor with soft edges: measured rooms on one sequential blue by m², counted symbols in the accent with a round pin,
// runs as dashed lines, and one legend bar. A compass (click: north up) and zoom sit top right. Read-only, on demand.
// Self-contained: it reads app.js's state (cur / res / items are global bindings of that classic script), watches the
// DOM for changes, and never calls anything in app.js except rowHot() for hover linking.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const WALL_H = 1.2, SILL = 0.75, PIN_H = 1.9;  // cut-away heights (the DXF is 2D): said so in the legend
const RISE_MS = 1100;
const HEAT = ['#e3eef7', '#bcd7ec', '#8bbadc', '#4f95c6', '#1a6fa6'];  // the 2D heat-map's sequential blue, light = small
const COL = {
  paper: 0xe3e6ea, wall: 0xffffff, cap: 0xd5d9de, cut: 0x2b3036, edge: 0x2f3640,
  glass: 0x9fd0ee, frame: 0xf4f5f6, door: 0xe3cfae, fixture: 0xffffff, ev: 0x0072b2, off: 0x9aa2ad, offTint: 0xe9ebee,
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
const isRaster = c => !!c && !!c.path && !c.path.startsWith('uploads/') && c.path.includes('cubicasa5k/') && /\.(png|jpe?g)$/i.test(c.path);
const has3D = c => isSwiss(c) || isRaster(c);

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
.p3l { position: absolute; left: 0; top: 0; will-change: transform; opacity: 0; transition: opacity .25s ease; white-space: nowrap;
  pointer-events: auto; cursor: pointer; }
.p3l.in { opacity: 1; }
.p3n { position: relative; display: grid; place-items: center; min-width: 26px; height: 26px; padding: 0 6px; border-radius: 13px;
  background: var(--ev); color: #fff; font: 600 12px/1 var(--font); font-feature-settings: "tnum" 1; border: 2px solid #fff;
  box-shadow: 0 1px 3px rgba(22,25,29,.35); margin-bottom: 7px; }
.p3n::after, .p3a::after { content: ''; position: absolute; left: 50%; bottom: -6px; width: 8px; height: 8px; margin-left: -5px;
  background: inherit; border: inherit; border-width: 0 2px 2px 0; transform: rotate(45deg); border-radius: 0 0 2px 0; }
.p3a { position: relative; display: flex; flex-direction: column; align-items: center; background: #fff; border: 1.5px solid var(--ev); border-radius: 6px;
  padding: 2px 7px 3px; box-shadow: 0 1px 3px rgba(22,25,29,.22); line-height: 1.2; margin-bottom: 6px; }
.p3a::after { border-width: 0 1.5px 1.5px 0; width: 7px; height: 7px; margin-left: -4.5px; bottom: -5px; }
.p3a b { font: 600 12px/1.2 var(--font); color: var(--ev-ink); font-feature-settings: "tnum" 1; }
.p3a small { font: 400 11px/1.2 var(--font); color: var(--mut); max-width: 120px; overflow: hidden; text-overflow: ellipsis; }
.p3l.off .p3n { background: #fff; color: #6b7584; border-color: #9aa2ad; text-decoration: line-through; box-shadow: 0 1px 2px rgba(22,25,29,.15); }
.p3l.off .p3a { border-color: var(--faint); } .p3l.off .p3a b { color: var(--faint); text-decoration: line-through; }
.p3l.hot .p3n, .p3l.hot .p3a { background: var(--hl); color: var(--ink); border-color: var(--ink); }
.p3l.hot .p3a b { color: var(--ink); } .p3l.hot { z-index: 2; }
#viewer.p3on #p3modes { box-shadow: 0 1px 3px rgba(22,25,29,.12); }
.p3ctl { position: absolute; right: 12px; top: 64px; z-index: 5; display: flex; flex-direction: column; gap: 8px; align-items: center; }
.p3ctl > * { background: var(--panel); border: 1px solid var(--line2); border-radius: 8px; box-shadow: 0 1px 3px rgba(22,25,29,.12); }
.p3ctl button { display: grid; place-items: center; width: 34px; height: 34px; border: 0; background: transparent; color: var(--text);
  cursor: pointer; padding: 0; font: 500 18px/1 var(--font); }
.p3ctl button:hover { color: var(--ev-ink); background: var(--panel2); }
.p3ctl .zm { display: flex; flex-direction: column; overflow: hidden; } .p3ctl .zm button + button { border-top: 1px solid var(--line); }
.p3ctl .cmp { border-radius: 50%; overflow: hidden; } .p3ctl .cmp button { width: 38px; height: 38px; }
.p3ctl .cmp svg { width: 26px; height: 26px; transition: none; }
.p3ctl svg text { font: 600 7px var(--font); fill: var(--mut); }
.p3leg { position: absolute; left: 12px; bottom: 30px; z-index: 4; background: var(--panel); border: 1px solid var(--line2); border-radius: 8px;
  padding: 5px 9px; font-size: 11px; color: var(--mut); display: flex; gap: 12px; align-items: center; pointer-events: none;
  max-width: calc(100% - 24px); box-shadow: 0 1px 3px rgba(22,25,29,.08); }
.p3leg i { display: inline-block; width: 10px; height: 10px; border-radius: 3px; vertical-align: -1px; margin-right: 4px; }
.p3leg .sc { display: inline-flex; flex-direction: column; gap: 1px; }
.p3leg .sc span { display: grid; grid-template-columns: repeat(5, 22px); gap: 1px; } .p3leg .sc span i { width: 22px; height: 8px; margin: 0; border-radius: 0; }
.p3leg .sc em { display: grid; grid-template-columns: repeat(5, 22px); gap: 1px; font: 400 9px/1 var(--font); font-style: normal; color: var(--mut); font-feature-settings: "tnum" 1; }
.p3leg .sc em b { font-weight: 400; transform: translateX(-50%); } .p3leg .sc em b:first-child { transform: none; }
.p3leg .pin { display: inline-grid; place-items: center; width: 14px; height: 14px; border-radius: 7px; background: var(--ev); color: #fff;
  font: 600 8px/1 var(--font); margin-right: 6px; vertical-align: -2px; border: 1px solid #fff; box-shadow: 0 0 0 1px var(--ev); }
.p3load { position: absolute; inset: 0; display: grid; place-items: center; font-size: 13px; color: var(--mut); pointer-events: none; }
@media (max-width: 860px) { .p3leg .p3wide { display: none; } .p3leg { bottom: 26px; } }
`;
document.head.appendChild(css);

const box = document.createElement('div'); box.id = 'p3';
box.innerHTML = '<div class="p3labs"></div><div class="p3leg"></div><div class="p3load" hidden>Building the model…</div>' +
  '<div class="p3ctl"><div class="cmp"><button type="button" class="north" title="North up" aria-label="Turn the view north up">' +
  '<svg viewBox="0 0 26 26" aria-hidden="true"><g class="ndl"><path d="M13 3.5 16 13h-6z" fill="#0072b2"/><path d="M13 22.5 10 13h6z" fill="#c9ced5"/></g></svg></button></div>' +
  '<div class="zm"><button type="button" class="zin" title="Zoom in" aria-label="Zoom in">+</button><button type="button" class="zout" title="Zoom out" aria-label="Zoom out">−</button></div></div>';
viewer.appendChild(box);
const labs = box.querySelector('.p3labs'), leg = box.querySelector('.p3leg'), loadEl = box.querySelector('.p3load');
const needle = box.querySelector('.ndl');
box.querySelector('.north').onclick = () => turnTo(0);
box.querySelector('.zin').onclick = () => zoomBy(0.72);
box.querySelector('.zout').onclick = () => zoomBy(1 / 0.72);
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
  // a sky / ground hemisphere and one low sun from the south-west: with flat shading every wall orientation gets its
  // own tone (as in a physical model), the tops stay lightest after the cap tint
  scene.add(new THREE.HemisphereLight(0xffffff, 0xbcc3cc, 2.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.3); sun.name = 'sun';
  scene.add(sun); scene.add(sun.target);
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
    select(pick(e), {x: e.clientX, y: e.clientY});
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
    placeLabels(); placeCompass();
  });
}
// the compass shows where plan north is; a click turns the view north up, the zoom buttons dolly in / out (eased)
let lastAz = null;
function placeCompass() {
  const o = camera.position.clone().sub(controls.target), az = Math.atan2(o.x, o.z);
  if (lastAz !== null && Math.abs(az - lastAz) < 1e-4) return;
  lastAz = az; needle.setAttribute('transform', `rotate(${(az * 180 / Math.PI).toFixed(2)} 13 13)`);
}
function orbitTween(fn) {
  const t = controls.target.clone(), o = camera.position.clone().sub(t), d0 = o.length();
  const p0 = Math.acos(Math.min(1, Math.max(-1, o.y / d0))), a0 = Math.atan2(o.x, o.z);
  tween(380, k => { const e = ease(k), [d, p, a] = fn(e, d0, p0, a0); place(t, d, p, a); });
}
function turnTo(az) {
  if (!opened) return;
  orbitTween((e, d0, p0, a0) => { let da = az - a0; while (da > Math.PI) da -= 2 * Math.PI; while (da < -Math.PI) da += 2 * Math.PI; return [d0, p0, a0 + da * e]; });
}
function zoomBy(f) {
  if (!opened) return;
  orbitTween((e, d0, p0, a0) => { const d1 = Math.min(controls.maxDistance, Math.max(controls.minDistance, d0 * f)); return [d0 + (d1 - d0) * e, p0, a0]; });
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
// thin dark outlines (1 px) on every crease, so each wall reads as a clean block
const edgeMats = new Map();
function edgeMat(opacity) {
  if (!edgeMats.has(opacity)) edgeMats.set(opacity, new THREE.LineBasicMaterial({color: COL.edge, transparent: true, opacity}));
  return edgeMats.get(opacity);
}
function edges(g, opacity = 0.5) { return new THREE.LineSegments(new THREE.EdgesGeometry(g, 28), edgeMat(opacity)); }
const centroid = pts => { let x = 0, y = 0; for (const p of pts) { x += p[0]; y += p[1]; } return [x / pts.length, y / pts.length]; };

// soft contact shading baked into one texture: blurred wall footprints darken the floor along every wall, which reads
// as ambient occlusion at no per-frame cost. Transparent where there is no shade, so it lies over the drawing.
function bakeAO(walls, x0, y0, w, h) {
  const S = Math.min(2048, Math.ceil(Math.max(w, h) * 48)), k = S / Math.max(w, h), OFF = 4 * S;
  const c = document.createElement('canvas'); c.width = Math.ceil(w * k); c.height = Math.ceil(h * k);
  const g = c.getContext('2d');
  const pass = (blur, alpha) => {
    g.save(); g.shadowColor = `rgba(30,38,50,${alpha})`; g.shadowBlur = blur * k; g.shadowOffsetX = -OFF; g.fillStyle = '#000';
    g.beginPath();
    for (const p of walls) for (const r of [p.outer, ...p.holes]) {
      r.forEach(([x, y], i) => { const X = (x - x0) * k + OFF, Y = (y0 + h - y) * k; i ? g.lineTo(X, Y) : g.moveTo(X, Y); }); g.closePath();
    }
    g.fill('evenodd'); g.restore();
  };
  pass(0.6, 0.26); pass(0.18, 0.3); pass(0.05, 0.2);  // a wide soft shade and a tight dark line at the wall foot
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
  // shape uv = (x - cx, y - cy): map that onto the canvas (v up = +y)
  t.repeat.set(1 / w, 1 / h); t.offset.set(-(x0 - center[0]) / w, -(y0 - center[1]) / h);
  t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
  return t;
}

// the page as plan metres: to_page maps x, y (m) to normalised page u, v (v down), so its inverse places the sheet
function pageRect(d) {
  const [ax, bx, ay, by] = d.to_page, xs = [(0 - bx) / ax, (1 - bx) / ax], ys = [(0 - by) / ay, (1 - by) / ay];
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}
// the drawing as a texture over shape uv (x - cx, y - cy): u = ax x + bx, and v flipped (texture v runs up)
function pageTexture(d, im) {
  const t = new THREE.Texture(im); t.needsUpdate = true; t.colorSpace = THREE.SRGBColorSpace; t.generateMipmaps = true;
  t.minFilter = THREE.LinearMipmapLinearFilter; t.magFilter = THREE.LinearFilter;
  t.anisotropy = renderer.capabilities.getMaxAnisotropy(); t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
  const [ax, bx, ay, by] = d.to_page;
  t.repeat.set(ax, -ay); t.offset.set(ax * center[0] + bx, 1 - (ay * center[1] + by));
  return t;
}

// a sharper copy of the part of the page the plan is on (/api/crop), laid over the full page: the same uv mapping as
// pageTexture, scaled to the crop box [u0, v0, u1, v1]
function cropTexture(d, im, [u0, v0, u1, v1]) {
  const t = pageTexture(d, im), [ax, bx, ay, by] = d.to_page, du = u1 - u0, dv = v1 - v0;
  t.repeat.set(ax / du, -ay / dv); t.offset.set((ax * center[0] + bx - u0) / du, 1 - (ay * center[1] + by - v0) / dv);
  return t;
}

// one paint layer on the floor for the answer: every room / symbol filled with a feathered edge (a heat-map look) and
// every run as a dashed line, drawn into a canvas over the plan's extent and repainted on hover
let paintC = null, paintTex = null, paintBox = null;
function paintLayer(x0, y0, w, h) {
  const S = Math.min(2048, renderer.capabilities.maxTextureSize), k = Math.min(S / Math.max(w, h), 96);
  paintC = document.createElement('canvas'); paintC.width = Math.ceil(w * k); paintC.height = Math.ceil(h * k);
  paintBox = {x0, y0, w, h, k};
  paintTex && paintTex.dispose();
  paintTex = new THREE.CanvasTexture(paintC); paintTex.colorSpace = THREE.SRGBColorSpace;
  paintTex.anisotropy = renderer.capabilities.getMaxAnisotropy();
  paintTex.repeat.set(1 / w, 1 / h); paintTex.offset.set(-(x0 - center[0]) / w, -(y0 - center[1]) / h);
  const g = new THREE.ShapeGeometry(shape([[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]]));
  g.rotateX(-Math.PI / 2); g.translate(0, 0.02, 0);
  const m = mesh(g, new THREE.MeshBasicMaterial({map: paintTex, transparent: true, depthWrite: false, polygonOffset: true,
    polygonOffsetFactor: -4, polygonOffsetUnits: -8}), false, false);
  m.renderOrder = 1; m.raycast = () => {};
  return m;
}

let pageTex = null, sharpTex = null;
function build(d) {
  built = d;
  if (root) { scene.remove(root); root.traverse(o => { o.geometry && o.geometry.dispose(); }); }
  root = new THREE.Group(); scene.add(root);
  const [bx0, by0, bx1, by1] = d.bounds; center = [(bx0 + bx1) / 2, (by0 + by1) / 2];
  radius = Math.hypot(bx1 - bx0, by1 - by0) / 2;
  const m = 1.2, x0 = bx0 - m, y0 = by0 - m, w = bx1 - bx0 + 2 * m, h = by1 - by0 + 2 * m;
  aoTex && aoTex.dispose(); aoTex = bakeAO(d.walls, x0, y0, w, h);
  pageTex && pageTex.dispose(); pageTex = d.img ? pageTexture(d, d.img) : null;
  sharpTex && sharpTex.dispose(); sharpTex = d.sharp ? cropTexture(d, d.sharp.im, d.sharp.box) : null;

  // the sheet: the drawing itself, unlit so it reads exactly as in 2D, on a thin board; then the contact shade over it
  const [px0, py0, px1, py1] = d.img ? pageRect(d) : [x0, y0, x0 + w, y0 + h];
  const sheet = new THREE.MeshBasicMaterial({color: 0xffffff, map: pageTex});
  const sideMat = new THREE.MeshLambertMaterial({color: 0xd6dade});
  const rect = (a, b, c, e) => [[a, b], [c, b], [c, e], [a, e]];
  const base = mesh(prism([shape(rect(px0, py0, px1, py1))], -0.08, 0), [sheet, sideMat], false, true); root.add(base);
  if (sharpTex) {  // the sharp crop over the part of the page the plan is on
    const [u0, v0, u1, v1] = d.sharp.box, a = toPlanD(d, u0, v0), b = toPlanD(d, u1, v1);
    const sg = new THREE.ShapeGeometry(shape(rect(Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1]))));
    sg.rotateX(-Math.PI / 2); sg.translate(0, 0.001, 0);
    root.add(mesh(sg, new THREE.MeshBasicMaterial({map: sharpTex, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -2}), false, false));
  }
  const ag = new THREE.ShapeGeometry(shape(rect(x0, y0, x0 + w, y0 + h))); ag.rotateX(-Math.PI / 2); ag.translate(0, 0.004, 0);
  root.add(mesh(ag, new THREE.MeshBasicMaterial({map: aoTex, transparent: true, depthWrite: false}), false, false));
  root.add(paintLayer(x0, y0, w, h));
  rise = new THREE.Group(); root.add(rise);
  // white walls, flat-shaded so each orientation reads in its own tone, a slightly darker cap and thin dark outlines;
  // doors are open with a beige leaf, windows keep a sill with light-blue glass above it, set into the wall
  const wallMat = [new THREE.MeshLambertMaterial({color: COL.cap, flatShading: true}), new THREE.MeshLambertMaterial({color: COL.wall, flatShading: true})];
  const wg = prism(d.walls.map(p => shape(p.outer, p.holes)), 0, WALL_H);
  rise.add(mesh(wg, wallMat));
  if (d.wallEdges) {  // a raster's walls are many small blocks: outline their union (from the pixel mask), not each block
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(d.wallEdges(center, WALL_H), 3));
    rise.add(new THREE.LineSegments(g, edgeMat(0.55)));
  } else rise.add(edges(wg, 0.55));
  const glassMat = new THREE.MeshLambertMaterial({color: COL.glass, transparent: true, opacity: 0.8, flatShading: true});
  const doorMat = new THREE.MeshLambertMaterial({color: COL.door, flatShading: true});
  const doorFloor = new THREE.MeshBasicMaterial({color: COL.door, transparent: true, opacity: 0.45, depthWrite: false,
    polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -4});
  const fixMat = new THREE.MeshLambertMaterial({color: COL.fixture, flatShading: true});
  d.symbols.forEach((s, k) => {
    const sh = [shape(s.pts)];
    s.c = centroid(s.pts); s.k = k;
    if (s.kind === 'window') {
      if (!s.pane) s.pane = paneOf(s.pts, 0.34);
      const g = prism(sh, 0, SILL); rise.add(mesh(g, wallMat)); rise.add(edges(g, 0.45));
      const gg = prism([shape(s.pane || s.pts)], SILL, WALL_H - 0.02);
      const gl = mesh(gg, glassMat, false, false); gl.userData.sym = k; gl.renderOrder = 2; rise.add(gl); rise.add(edges(gg, 0.35)); s.glass = gl;
    } else if (s.kind === 'door' && s.leaf) {  // a raster's door: a beige leaf standing in the opening
      const g = prism([shape(s.leaf)], 0, WALL_H * 0.86); rise.add(mesh(g, doorMat)); rise.add(edges(g, 0.4));
    } else if (s.kind === 'door') {  // a CAD door: its swing painted beige on the floor, the opening left open
      const g = new THREE.ShapeGeometry(sh); g.rotateX(-Math.PI / 2); g.translate(0, 0.012, 0);
      const f = mesh(g, doorFloor, false, false); f.renderOrder = 1; f.raycast = () => {}; root.add(f);
    } else if (s.h) {
      const g = prism(sh, 0, s.h); const f = mesh(g, fixMat); rise.add(f); rise.add(edges(g, 0.4)); s.mesh = f;
    }
  });
  evGroup = new THREE.Group(); root.add(evGroup);

  const sun = scene.getObjectByName('sun');
  sun.position.set(-radius * 0.9, radius * 1.4, radius * 0.6); sun.target.position.set(0, 0, 0);
  controls.minDistance = 2; controls.maxDistance = radius * 6;
}
// a window's glass: its footprint narrowed across the wall to a thin pane in the middle (the pts are a rectangle)
function paneOf(pts, f) {
  if (pts.length !== 4) return pts;
  const [a, b, c] = pts, l1 = Math.hypot(b[0] - a[0], b[1] - a[1]), l2 = Math.hypot(c[0] - b[0], c[1] - b[1]);
  const mid = (p, q, t) => [p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t], t0 = (1 - f) / 2, t1 = 1 - t0;
  const [p0, p1, p2, p3] = pts;
  return l1 < l2 ? [mid(p0, p1, t0), mid(p0, p1, t1), mid(p3, p2, t1), mid(p3, p2, t0)]
    : [mid(p0, p3, t0), mid(p1, p2, t0), mid(p1, p2, t1), mid(p0, p3, t1)];
}
const toPlanD = (d, u, v) => { const [ax, bx, ay, by] = d.to_page; return [(u - bx) / ax, (v - by) / ay]; };

// camera on a sphere around the plan: polar 0 = straight down (the 2D view), azimuth 0 = plan north up
const fitDist = (k = 1) => {
  const fov = camera.fov * Math.PI / 180, aspect = Math.max(0.4, camera.aspect);
  return k * radius / Math.sin(fov / 2) / Math.min(1, aspect) * 1.02;
};
function place(t, dist, polar, az) {
  camera.position.set(t.x + dist * Math.sin(polar) * Math.sin(az), t.y + dist * Math.cos(polar), t.z + dist * Math.sin(polar) * Math.cos(az));
  camera.up.set(0, 1, 0); controls.target.copy(t); camera.lookAt(t);
}
// where the 2D view has the drawing right now, as a camera straight above the floor: the same point in the middle of
// the viewer and the same metres per pixel, so the first 3D frame is the 2D frame (null when the 2D view shows another page)
function cameraOver2D(d) {
  const im = $('#img'), c = app.cur();
  if (!im || !im.naturalWidth || !c || !(im.getAttribute('src') || '').includes(encodeURIComponent(c.path))) return null;
  const ir = im.getBoundingClientRect(), vr = viewer.getBoundingClientRect();
  if (!ir.width || !ir.height || !vr.height) return null;
  const [ax, bx, ay, by] = d.to_page;
  const u = (vr.left + vr.width / 2 - ir.left) / ir.width, v = (vr.top + vr.height / 2 - ir.top) / ir.height;
  const x = (u - bx) / ax, y = (v - by) / ay, pxm = Math.abs(ay) * ir.height;  // screen px per plan metre
  const dist = (vr.height / pxm) / 2 / Math.tan(camera.fov * Math.PI / 360);
  if (!isFinite(dist) || dist <= 0) return null;
  return {t: new THREE.Vector3(x - center[0], 0, -(y - center[1])), dist};
}

// ------------------------------------------------------------ evidence in 3D
const fill = (color, opacity) => new THREE.MeshBasicMaterial({color, transparent: true, opacity, depthWrite: false,
  polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -8});
const mats = {
  // lit evidence that stands up (a fixture, a window's glass); what lies on the floor is painted (paintLayer)
  solid: new THREE.MeshLambertMaterial({color: COL.ev, emissive: COL.ev, emissiveIntensity: 0.35, transparent: true, opacity: 0.85, depthWrite: false}),
  solidOff: new THREE.MeshLambertMaterial({color: COL.off, transparent: true, opacity: 0.3, depthWrite: false}),
  // hover / selection: a light accent tint, never a saturated solid colour
  hot: fill(0x8dbde0, 0.9),
};
const fmtA = v => (Math.round(v * 100) / 100).toFixed(2);
// the 2D heat-map's breaks (four round steps, five classes), over the measured values of this answer
function breaks(vals) {
  const mx = Math.max(1, ...vals);
  const nice = [2, 2.5, 4, 5, 6, 8, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100, 150, 200].find(x => x * 5 >= mx) || Math.ceil(mx / 5);
  return [1, 2, 3, 4].map(k => k * nice);
}
const heatClass = (a, br) => { const i = br.findIndex(b => a < b); return i < 0 ? 4 : i; };

function toPlan(u, v) { const [ax, bx, ay, by] = data.to_page; return [(u - bx) / ax, (v - by) / ay]; }

function signature() {
  const r = app.res(), it = app.items();
  return (r ? r._seq : '-') + '|' + it.map(e => `${e.kind}${e.on ? 1 : 0}${(e.bbox || []).join()}${e.points ? e.points.length : ''}${e.value ?? ''}`).join(';');
}

// the paint layer: fills feathered by a canvas shadow (drawn off-canvas, its blurred shadow lands in place), runs dashed
const hex = c => '#' + new THREE.Color(c).getHexString();
function rgba(c, a) { const h = hex(c), n = parseInt(h.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; }  // sRGB, as written
function paintItem(it, isHot) {
  if (!paintC) return;
  const g = paintC.getContext('2d'), {x0, y0, h, k} = paintBox, OFF = paintC.width + 400;
  const X = x => (x - x0) * k, Y = y => (y0 + h - y) * k;
  for (const p of it.paint) {
    const col = isHot ? '#5fa6d6' : p.color, a = isHot ? 0.75 : p.alpha;
    g.save();
    if (p.line) {
      g.strokeStyle = rgba(col, Math.min(1, a + 0.2)); g.lineWidth = Math.max(2, 0.09 * k); g.lineCap = 'round';
      g.setLineDash([0.32 * k, 0.2 * k]); g.beginPath();
      p.rings[0].forEach(([x, y], j) => j ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y))); g.stroke();
    } else {
      g.shadowColor = rgba(col, a); g.shadowBlur = Math.max(3, (p.feather || 0.22) * k); g.shadowOffsetX = -OFF; g.fillStyle = '#000';
      g.beginPath();
      for (const r of p.rings) { r.forEach(([x, y], j) => j ? g.lineTo(X(x) + OFF, Y(y)) : g.moveTo(X(x) + OFF, Y(y))); g.closePath(); }
      g.fill('evenodd');
      if (isHot) {  // the hovered one also gets a crisp dark outline
        g.shadowColor = 'transparent'; g.strokeStyle = rgba(COL.cut, 0.85); g.lineWidth = Math.max(1.5, 0.035 * k); g.beginPath();
        for (const r of p.rings) { r.forEach(([x, y], j) => j ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y))); g.closePath(); }
        g.stroke();
      }
    }
    g.restore();
  }
  paintTex.needsUpdate = true;
}
function repaint() {
  if (!paintC) return;
  paintC.getContext('2d').clearRect(0, 0, paintC.width, paintC.height);
  for (const it of ev) if (it.shown && it !== hot) paintItem(it, false);
  if (hot && hot.shown) paintItem(hot, true);
  paintTex.needsUpdate = true; requestRender();
}

function clearEvidence() {
  if (!evGroup) return;
  for (const o of [...evGroup.children]) { evGroup.remove(o); o.traverse(x => x.geometry && x.geometry.dispose()); }
  for (const s of data ? data.symbols : []) { if (s.glass) s.glass.visible = true; if (s.mesh) s.mesh.visible = true; }
  labs.innerHTML = ''; ev = []; hot = null; selI = null; br = null;
  if (paintC) { paintC.getContext('2d').clearRect(0, 0, paintC.width, paintC.height); paintTex.needsUpdate = true; }
}

const W3 = (x, y, h) => new THREE.Vector3(x - center[0], h, -(y - center[1]));
// an invisible floor patch: what a pointer picks for a painted room or symbol (raycasts ignore visibility)
function flat(ring, h, holes = []) {
  const g = new THREE.ShapeGeometry(shape(ring, holes)); g.rotateX(-Math.PI / 2); g.translate(0, h, 0);
  const m = mesh(g, mats.hot, false, false); m.visible = false; m.userData.pickOnly = true; return m;
}
const grow = (ring, d) => { const [cx, cy] = centroid(ring); return ring.map(([x, y]) => { const l = Math.hypot(x - cx, y - cy) || 1; return [x + (x - cx) / l * d, y + (y - cy) / l * d]; }); };

let br = null;  // the m² class breaks of the answer on show (null: a count)
function applyEvidence(animate, at) {  // at(i): when item i is painted, in ms (the 2D replay's timeline, app.js rpRun)
  if (!data || !evGroup) return;
  const keep = evSig.split('|')[0] === signature().split('|')[0] ? selI : null;  // same answer: the selection stays
  evSig = signature();
  clearEvidence();
  const r = app.res(), list = app.items(), type = r && r.type;
  const vals = list.filter(e => e.kind === 'polygon' && e.value != null && type !== 'count').map(e => +e.value);
  br = vals.length ? breaks(vals) : null;
  let k = 0;
  list.forEach((e, i) => {
    const numbered = e.kind === 'box' || (e.kind === 'polygon' && type === 'count');
    if (numbered) k++;
    if (e.kind !== 'box' && e.kind !== 'polygon' && e.kind !== 'polyline') return;
    const it = {i, e, on: !!e.on, meshes: [], paint: [], anchor: null, el: null, n: numbered ? k : null, shown: false};
    const add = m => { m.userData.i = i; evGroup.add(m); it.meshes.push(m); };
    let foot = 0.03, px, py;
    if (e.kind === 'polyline') {
      // a run: a dashed line on the floor, no pin
      const pts = (e.points || []).map(([u, v]) => toPlan(u, v));
      if (pts.length < 2) return;
      it.paint.push({line: true, rings: [pts], color: it.on ? hex(COL.ev) : hex(COL.off), alpha: 0.8});
      ev.push(it); return;
    }
    if (e.kind === 'box') {
      // a counted symbol: its footprint painted in the accent on the floor, a pin above it with its number
      const [u0, v0, u1, v1] = e.bbox, a = toPlan(u0, v0), b = toPlan(u1, v1);
      const pad = data.raster ? 0 : 0.1, rx0 = Math.min(a[0], b[0]) + pad, rx1 = Math.max(a[0], b[0]) - pad, ry0 = Math.min(a[1], b[1]) + pad, ry1 = Math.max(a[1], b[1]) - pad;
      const cx = (rx0 + rx1) / 2, cy = (ry0 + ry1) / 2;
      let best = null, bd = 0.35;
      for (const s of data.symbols) { const d = Math.hypot(s.c[0] - cx, s.c[1] - cy); if (d < bd) { bd = d; best = s; } }
      if (best && data.raster && best.kind === 'door') best = null;  // a raster's detected door box is the evidence itself
      const ring = best ? grow(best.pts, 0.08) : [[rx0, ry0], [rx1, ry0], [rx1, ry1], [rx0, ry1]];
      add(flat(ring, 0.02));
      it.paint.push({rings: [ring], color: it.on ? hex(COL.ev) : hex(COL.off), alpha: it.on ? 0.72 : 0.4, feather: 0.07});
      if (best && best.kind === 'window') {
        const g = prism([shape(best.pane || best.pts)], SILL, WALL_H + 0.01), m = mesh(g, it.on ? mats.solid : mats.solidOff, false, false);
        m.userData.mat = m.material; m.renderOrder = 2; add(m); best.glass.visible = false; foot = WALL_H;
      } else if (best && best.h && best.kind !== 'door') {
        const g = prism([shape(best.pts)], 0, best.h + 0.02), m = mesh(g, it.on ? mats.solid : mats.solidOff, false, false);
        m.userData.mat = m.material; m.renderOrder = 2; add(m); foot = best.h;
        if (best.mesh) best.mesh.visible = false;  // same footprint as the highlight: hide it, or the two faces flicker
      }
      [px, py] = best ? best.c : [cx, cy];
      it.anchor = W3(px, py, foot + 0.02); it.name = best ? best.kind : (e.label || '');
    } else {
      // a room: filled on the floor, by its m² (the 2D heat-map's blue) or in the accent when it is counted
      const pts = e.points.map(([u, v]) => toPlan(u, v));
      const num = (e.label || '').split(' ')[0];
      const room = (data.rooms || []).find(q => q.number && q.number === num);
      const ring = room ? room.pts : pts;
      // a room wrapped around others (a corridor) carries them as holes: they stay unpainted, and pickable on their own
      const holes = (e.holes || []).filter(r => r && r.length > 2).map(r => r.map(([u, v]) => toPlan(u, v)));
      const color = !it.on ? hex(COL.offTint) : br && e.value != null ? HEAT[heatClass(+e.value, br)] : hex(COL.ev);
      add(flat(ring, 0.03, holes));
      it.paint.push({rings: [ring, ...holes], color, alpha: !it.on ? 0.8 : br && e.value != null ? 0.82 : 0.55});
      [px, py] = room && room.label ? room.label : centroid(ring);
      it.anchor = W3(px, py, 0.05);
      it.name = room ? room.name : (e.label || '');
    }
    const el = document.createElement('div'); el.className = 'p3l' + (it.on ? '' : ' off'); el.dataset.i = i;
    if (it.n != null) el.innerHTML = `<span class="p3n">${it.n}</span>`;
    else el.innerHTML = `<span class="p3a"><b>${e.value != null ? fmtA(e.value) + ' m²' : ''}</b>${it.name ? `<small>${esc(it.name)}</small>` : ''}</span>`;
    el.addEventListener('pointerenter', () => hover(i)); el.addEventListener('pointerleave', () => hover(null));
    el.addEventListener('click', ev2 => { ev2.stopPropagation(); const r = el.getBoundingClientRect(); select(i, {x: r.left + r.width / 2, y: r.top}); });
    labs.appendChild(el); it.el = el;
    ev.push(it);
  });
  legend();
  if (keep != null && ev.some(x => x.i === keep)) { selI = keep; setHot(keep); }
  // paint them one after the other (the 2D view counts them out the same way): each spreads up from the floor
  const step = Math.max(25, Math.min(90, 900 / Math.max(1, ev.length)));
  ev.forEach((it, j) => {
    const show = () => { it.shown = true; it.el && it.el.classList.add('in'); paintItem(it, it === hot); requestRender(); };
    if (!animate || reduced) { show(); return; }
    for (const m of it.meshes) if (!m.userData.pickOnly) m.visible = false;
    setTimeout(() => {
      if (!ev.includes(it)) return;
      const fades = it.meshes.filter(m => !m.userData.pickOnly).map(m => { m.visible = true; const c = m.userData.mat.clone(); m.material = c; return [m, c]; });
      const base = fades.map(([, c]) => c.opacity);
      if (fades.length) tween(320, k2 => fades.forEach(([, c], q) => { c.opacity = base[q] * ease(k2); }), () => {
        for (const [m, c] of fades) { m.material = hot === it ? mats.hot : m.userData.mat; c.dispose(); }
        requestRender();
      });
      show();
    }, at ? Math.max(0, at(it.i) || 0) : j * step);
  });
  requestRender();
}
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

// one compact bar, bottom left: what the colours on the floor mean
function legend() {
  const r = app.res(), n = ev.filter(x => x.on).length, off = ev.length - n;
  let what;
  if (!ev.length) what = '<span>Ask a question to paint its evidence on the floor</span>';
  else if (br) {
    what = `<span class="sc"><span>${HEAT.map(c => `<i style="background:${c}"></i>`).join('')}</span>` +
      `<em><b>0</b>${br.map(b => `<b>${b}</b>`).join('')}</em></span><span>m² per room · ${n} measured</span>`;
  } else what = `<span><i class="pin"></i>${n} counted</span>`;
  if (ev.length && off) what += `<span><i style="background:#e9ebee;border:1px solid #9aa2ad"></i>${off} dropped</span>`;
  const src = data && data.raster ? 'walls read from the drawing\'s thick lines, cut away' : `walls from the CAD layers, cut at ${WALL_H} m`;
  leg.innerHTML = `${what}<span class="p3wide">Floor: the drawing · ${src}</span>`;
}

// numbers and m² labels follow their anchors on every rendered frame; a label that would sit on an earlier one
// is nudged up so the numbers stay readable
const _v = new THREE.Vector3();
function placeLabels() {
  if (!ev.length) return;
  const w = box.clientWidth, h = box.clientHeight, placed = [];
  const order = ev.filter(x => x.el).sort((a, b) => (b === hot) - (a === hot) || (b.on - a.on) || a.i - b.i);
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
// a click on an element or its pin selects it: its row flashes, and the app's card opens beside it (what it is, its
// value, drop / put back). A click on nothing closes the card.
function select(i, pt) {
  selI = i ?? null; setHot(selI);
  try { if (typeof window.pinCardAt === 'function') window.pinCardAt(selI, pt); } catch (e) { /* app changed */ }
  if (selI == null) return;
  const w = $('#evwrap'); if (w && !w.open) w.open = true;
  try { if (typeof window.flashRow === 'function') window.flashRow(selI); else app.rowHot(selI, true); } catch (e) { /* app changed */ }
}
function setHot(i) {
  const it = i == null ? null : ev.find(x => x.i === i) || null;
  if (it === hot) return;
  for (const x of [hot, it]) {
    if (!x) continue;
    const on = x === it;
    for (const m of x.meshes) if (!m.userData.pickOnly) m.material = on ? mats.hot : m.userData.mat;
    x.el && x.el.classList.toggle('hot', on);
  }
  hot = it; repaint();
}
// pointing at a row of the evidence list lights its element in 3D
const evList = $('#ev');
if (evList) {
  evList.addEventListener('mouseover', e => { if (!opened) return; const d = e.target.closest('div[data-i]'); setHot(d ? +d.dataset.i : null); });
  evList.addEventListener('mouseleave', () => { if (opened) setHot(null); });
}

// ------------------------------------------------------------ open / close / follow the app
const loadImg = src => new Promise(ok => {
  const im = new Image(); im.decoding = 'async';
  im.onload = () => ok(im); im.onerror = () => ok(null); im.src = src;
});
async function load(p) {
  if (dataPath === p && data) return data;
  if (isRaster({path: p})) {
    const im = await loadImg('/api/render?path=' + encodeURIComponent(p));
    if (!im) throw new Error('no drawing');
    const d = rasterPlan(im);
    if (!d.walls.length) throw new Error('no walls on this drawing');
    d.img = im;
    return d;
  }
  const r = await fetch('/api/plan3d?path=' + encodeURIComponent(p));
  if (!r.ok) throw new Error('no 3D for this drawing');
  const d = await r.json();
  if (!d.walls || !d.walls.length) throw new Error('no walls on this drawing');
  // the page the 2D view shows, to lie on the floor (a model without it still opens, on a plain board), and a sharp
  // crop of the part the plan is on, about 18 px per 10 cm of plan, so the drawing stays crisp when the camera comes close
  const [bx0, by0, bx1, by1] = d.bounds, m = 1.5, [ax, bx, ay, by] = d.to_page;
  const us = [(bx0 - m) * ax + bx, (bx1 + m) * ax + bx], vs = [(by0 - m) * ay + by, (by1 + m) * ay + by];
  const box = [Math.max(0, Math.min(...us)), Math.max(0, Math.min(...vs)), Math.min(1, Math.max(...us)), Math.min(1, Math.max(...vs))];
  const cw = Math.min(4096, Math.round((bx1 - bx0 + 2 * m) * 180 / 32) * 32);
  const q = `path=${encodeURIComponent(p)}`;
  const [img, sharp] = await Promise.all([loadImg('/api/render?dpi=220&' + q),
    loadImg(`/api/crop?${q}&x0=${box[0].toFixed(5)}&y0=${box[1].toFixed(5)}&x1=${box[2].toFixed(5)}&y1=${box[3].toFixed(5)}&w=${cw}`)]);
  d.img = img;
  if (sharp && sharp.naturalWidth > (img ? img.naturalWidth * (box[2] - box[0]) * 1.2 : 0)) d.sharp = {im: sharp, box};
  return d;
}

// ------------------------------------------------------------ a raster plan's walls, read from its pixels
// The thick dark strokes are the walls: threshold, then an opening (erode, dilate) removes text, hatching and the thin
// lines of furniture and door swings. The mask is cut into row-run rectangles (extruded as blocks; their union's outline
// is drawn from the mask, not per block). The wall thickness (the median stroke width) sets the scale: 0.2 m. A gap
// between two collinear wall blocks of the same thickness is an opening: a window when lines are drawn inside it (glazing),
// else a door. Plan metres: x right, y up; to_page maps them onto the page as for the CAD plans.
function rasterPlan(im) {
  const A = Math.min(1600, im.naturalWidth), sc = A / im.naturalWidth, W = A, H = Math.round(im.naturalHeight * sc);
  const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
  const g = cv.getContext('2d', {willReadFrequently: true}); g.fillStyle = '#fff'; g.fillRect(0, 0, W, H); g.drawImage(im, 0, 0, W, H);
  const px = g.getImageData(0, 0, W, H).data, N = W * H, lum = new Uint8Array(N);
  for (let i = 0; i < N; i++) lum[i] = (px[4 * i] * 0.3 + px[4 * i + 1] * 0.59 + px[4 * i + 2] * 0.11) | 0;
  let M = new Uint8Array(N); for (let i = 0; i < N; i++) M[i] = lum[i] < 120 ? 1 : 0;
  const r = Math.max(2, Math.round(W / 500));
  // separable square min / max filters of radius r (running counts)
  const pass = (src, horiz, isMin) => {
    const out = new Uint8Array(N), L = horiz ? W : H, S = horiz ? H : W;
    for (let s = 0; s < S; s++) {
      let cnt = 0; const at = t => horiz ? s * W + t : t * W + s;
      for (let t = 0; t < Math.min(L, r); t++) cnt += src[at(t)];
      for (let t = 0; t < L; t++) {
        if (t + r < L) cnt += src[at(t + r)];
        if (t - r - 1 >= 0) cnt -= src[at(t - r - 1)];
        const n = Math.min(L - 1, t + r) - Math.max(0, t - r) + 1;
        out[at(t)] = isMin ? (cnt === n ? 1 : 0) : (cnt > 0 ? 1 : 0);
      }
    }
    return out;
  };
  M = pass(pass(M, true, true), false, true); M = pass(pass(M, true, false), false, false);
  // row-run rectangles: a run continues a rectangle when the row above had the very same run
  const rects = []; let open = new Map();
  for (let y = 0; y <= H; y++) {
    const next = new Map();
    if (y < H) for (let x = 0; x < W;) {
      if (!M[y * W + x]) { x++; continue; }
      let e = x; while (e < W && M[y * W + e]) e++;
      const key = x * 65536 + e, o = open.get(key);
      if (o) { o.y1 = y + 1; next.set(key, o); open.delete(key); } else next.set(key, {x0: x, x1: e, y0: y, y1: y + 1});
      x = e;
    }
    for (const o of open.values()) rects.push(o);
    open = next;
  }
  const big = rects.filter(q => (q.x1 - q.x0) * (q.y1 - q.y0) >= 4 * r * r);
  // the wall thickness: the median length of the mask's runs, across rows and columns (a wall of length L gives L runs
  // of its thickness across it, and only a few long ones along it)
  const runs = [];
  for (let y = 0; y < H; y += 2) for (let x = 0; x < W;) { if (!M[y * W + x]) { x++; continue; } let e = x; while (e < W && M[y * W + e]) e++; runs.push(e - x); x = e; }
  for (let x = 0; x < W; x += 2) for (let y = 0; y < H;) { if (!M[y * W + x]) { y++; continue; } let e = y; while (e < H && M[e * W + x]) e++; runs.push(e - y); y = e; }
  runs.sort((a, b) => a - b);
  const T = Math.max(2 * r + 1, runs.length ? runs[runs.length >> 1] : 2 * r + 2);
  const ppm = T / 0.2, Wm = W / ppm, Hm = H / ppm;
  const P2 = (x, y) => [x / ppm, (H - y) / ppm];
  const rr = (x0, y0, x1, y1) => [P2(x0, y1), P2(x1, y1), P2(x1, y0), P2(x0, y0)];
  const walls = rects.filter(q => (q.x1 - q.x0) * (q.y1 - q.y0) >= 3).map(q => ({outer: rr(q.x0, q.y0, q.x1, q.y1), holes: []}));
  // openings: runs of floor between two wall pixels on one row (or column), 0.55 to 2.6 m long, grouped into connected
  // regions; a region as thick as a wall (not a corridor) is an opening in that wall
  const symbols = [];
  const darkIn = (x0, y0, x1, y1) => { let n = 0, d = 0; for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) { n++; if (lum[y * W + x] < 170) d++; } return n ? d / n : 0; };
  const lo = Math.round(0.55 * ppm), hi = Math.round(3.6 * ppm);
  for (const horiz of [true, false]) {
    const C = new Uint8Array(N), L = horiz ? W : H, S = horiz ? H : W, at = (s2, t) => horiz ? s2 * W + t : t * W + s2;
    for (let s2 = 0; s2 < S; s2++) {
      let last = -1;
      for (let t = 0; t < L; t++) if (M[at(s2, t)]) {
        if (last >= 0 && t - last - 1 >= lo && t - last - 1 <= hi) for (let u = last + 1; u < t; u++) C[at(s2, u)] = 1;
        last = t;
      }
    }
    const stack = [];
    for (let i = 0; i < N; i++) {
      if (C[i] !== 1) continue;
      let x0 = W, y0 = H, x1 = 0, y1 = 0, n = 0; C[i] = 2; stack.push(i);
      while (stack.length) {
        const j = stack.pop(), x = j % W, y = (j - x) / W; n++;
        if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
        for (const k2 of [x > 0 ? j - 1 : -1, x < W - 1 ? j + 1 : -1, y > 0 ? j - W : -1, y < H - 1 ? j + W : -1]) if (k2 >= 0 && C[k2] === 1) { C[k2] = 2; stack.push(k2); }
      }
      x1++; y1++;
      const thick = horiz ? y1 - y0 : x1 - x0, len = horiz ? x1 - x0 : y1 - y0;
      if (thick < 0.4 * T || thick > 3 * T || len < lo || len > hi || n < 0.5 * thick * len) continue;
      const dk = darkIn(x0, y0, x1, y1), pts = rr(x0, y0, x1, y1);
      const m = horiz ? (y0 + y1) / 2 : (x0 + x1) / 2;
      const band = t => horiz ? rr(x0, m - t, x1, m + t) : rr(m - t, y0, m + t, y1);
      if (dk > 0.14) symbols.push({kind: 'window', pts, pane: band(Math.max(1, T * 0.16))});  // glazing lines inside: a window
      else if (len <= 1.3 * ppm) symbols.push({kind: 'door', pts, leaf: band(Math.max(1, T * 0.18))});
    }
  }
  // the outline of the wall mask: boundary runs between wall and floor pixels, at the top and the foot, and an upright
  // at every run end (the corners)
  const segs = [];
  for (let y = 0; y <= H; y++) for (let x = 0; x < W;) {
    const d = q => (y < H && M[y * W + q] ? 1 : 0) !== (y > 0 && M[(y - 1) * W + q] ? 1 : 0);
    if (!d(x)) { x++; continue; } let e = x; while (e < W && d(e)) e++; segs.push([x, y, e, y]); x = e;
  }
  for (let x = 0; x <= W; x++) for (let y = 0; y < H;) {
    const d = q => (x < W && M[q * W + x] ? 1 : 0) !== (x > 0 && M[q * W + x - 1] ? 1 : 0);
    if (!d(y)) { y++; continue; } let e = y; while (e < H && d(e)) e++; segs.push([x, y, x, e]); y = e;
  }
  const wallEdges = (c, top) => {
    const corners = new Set(), out = [];
    const push = (x, y, h) => { const [a, b] = P2(x, y); out.push(a - c[0], h, -(b - c[1])); };
    const ends = [new Set(), new Set()];
    for (const [xa, ya, xb, yb] of segs) {
      const len = Math.abs(xb - xa) + Math.abs(yb - ya);
      for (const h of [top, 0.004]) { push(xa, ya, h); push(xb, yb, h); }
      if (len >= 4) for (const k2 of [xa * 65536 + ya, xb * 65536 + yb]) ends[ya === yb ? 0 : 1].add(k2);
    }
    for (const k2 of ends[0]) if (ends[1].has(k2)) corners.add(k2);  // an upright where a long run meets a long run
    for (const k2 of corners) { const x = Math.floor(k2 / 65536), y = k2 % 65536; push(x, y, 0); push(x, y, top); }
    return new Float32Array(out);
  };
  return {raster: true, T, nRects: big.length, walls, symbols, rooms: [], wallEdges, to_page: [1 / Wm, 0, -1 / Hm, 1], bounds: [0, 0, Wm, Hm]};
}

async function open() {
  const c = app.cur(); if (!has3D(c) || opened) return;
  opened = true; path = c.path;
  try { if (typeof window.pinCardAt === 'function') window.pinCardAt(null); } catch (e) { /* app changed */ }  // a 2D card stays in 2D
  initGL();
  box.classList.add('on'); viewer.classList.add('p3on');
  tog.querySelector('#p3plan').classList.remove('on'); tog.querySelector('#p3go').classList.add('on');
  tog.querySelector('#p3plan').setAttribute('aria-pressed', 'false'); tog.querySelector('#p3go').setAttribute('aria-pressed', 'true');
  resize();
  let d;
  loadEl.hidden = false;
  try { d = await load(path); } catch (err) { loadEl.hidden = true; close(); hintMsg('No 3D model could be built from this plan'); return; }
  loadEl.hidden = true;
  if (!opened || path !== (app.cur() || {}).path) return;
  data = d; dataPath = path;
  if (built !== d) build(d);
  applyEvidence(false);
  for (const it of ev) { for (const m of it.meshes) if (!m.userData.pickOnly) m.visible = false; it.shown = false; it.el && it.el.classList.remove('in'); }
  repaint();
  // the tilt: the camera starts where the 2D view is (straight down, same scale), then swings to a three-quarter view
  // while the walls rise out of the drawing
  camera.aspect = box.clientWidth / Math.max(1, box.clientHeight); camera.updateProjectionMatrix();
  const from = cameraOver2D(d) || {t: new THREE.Vector3(0, 0, 0), dist: fitDist(1)};  // the 2D view keeps its layout, hidden
  const T1 = new THREE.Vector3(0, 0.3, 0), D1 = fitDist(0.86), P1 = 0.78, A1 = -0.42, t = new THREE.Vector3();
  rise.scale.y = 0.001; place(from.t, from.dist, 0.0001, 0);
  tween(window.__p3riseMs || RISE_MS, k => {
    const e = ease(k), e2 = ease(Math.max(0, (k - 0.15) / 0.85));
    rise.scale.y = Math.max(0.001, e2);
    t.lerpVectors(from.t, T1, e);
    place(t, from.dist + (D1 - from.dist) * e, 0.0001 + (P1 - 0.0001) * e, A1 * e);
  }, () => { if (opened) applyEvidence(true); });
}

function close() {
  if (!opened) return;
  opened = false; tweens.clear(); hover(null);
  if (selI != null) select(null);
  box.classList.remove('on'); viewer.classList.remove('p3on');
  tog.querySelector('#p3plan').classList.add('on'); tog.querySelector('#p3go').classList.remove('on');
  tog.querySelector('#p3plan').setAttribute('aria-pressed', 'true'); tog.querySelector('#p3go').setAttribute('aria-pressed', 'false');
}

function hintMsg(msg) {
  const h = $('#hint'); if (!h) return;
  h.hidden = false; h.textContent = msg; setTimeout(() => { if (h.textContent === msg) h.hidden = true; }, 2500);
}

function sync() {
  const c = app.cur(), swiss = has3D(c);
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
// Esc closes an open card first (the app does that), then the 3D view
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || !opened || e.defaultPrevented || e.target.closest('input, textarea')) return;
  const card = document.querySelector('.tip3d'); if (card && !card.hidden) return;
  close();
});
q();

// the 2D replay paints the floor on its own timeline (null: everything at once, a skipped replay)
function replay(at) { if (!opened || !data || !evGroup) return false; applyEvidence(!!at, at); return true; }
window.__p3 = {open, close, replay, get opened() { return opened; }, get ready() { return opened && !!data && !tweens.size; }, get _three() { return {scene, renderer, camera, requestRender}; }, get data() { return data; }};
