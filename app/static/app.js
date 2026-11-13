// Blueprints that talk: pick or upload a drawing, ask, watch the answer get counted out on the drawing.
'use strict';
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const SRC = {swiss_dwellings: 'Swiss apartments', cubicasa5k: 'Finnish plans', ifc_models: 'IFC models', ifc_bench: 'IFC bench',
             opening_design: 'US drawing sets', upload: 'Your uploads'};
const ROUTE = {swiss: 'CAD layers (DXF twin)', ifc: 'IFC model query', cubicasa: 'plan symbol detector', generic: 'generic drawing reader'};
const NS = 'http://www.w3.org/2000/svg';

let tab = 'swiss_dwellings', cur = null, res = null, items = [], marks = [], adding = false, primary = '2d';
let session = {n: 0, ours: 0, base: 0};
let listOffset = 0, listQuery = '';
let uploads = JSON.parse(localStorage.getItem('bp_uploads') || '[]');
let askSeq = 0, animating = false;

// ------------------------------------------------------------ pan / zoom (mouse, wheel, touch pinch)
let view = {s: 1, x: 0, y: 0};
const stage = $('#stage'), viewer = $('#viewer'), img = $('#img'), ov = $('#ov');
function apply() { stage.style.transform = `translate(${view.x}px,${view.y}px) scale(${view.s})`; }
function fit() {
  const W = viewer.clientWidth, H = viewer.clientHeight, w = img.naturalWidth, h = img.naturalHeight;
  if (!w) return;
  view.s = Math.min(W / w, (H - 24) / h) * 0.97; view.x = (W - w * view.s) / 2; view.y = (H - 20 - h * view.s) / 2; apply();
  rescaleLabels();
}
function zoomAt(mx, my, k) {
  const s2 = Math.min(30, Math.max(0.03, view.s * k));
  view.x = mx - (mx - view.x) * s2 / view.s; view.y = my - (my - view.y) * s2 / view.s; view.s = s2; apply();
  rescaleLabels();
}
viewer.addEventListener('wheel', e => {
  if (mode === '3d') return;
  e.preventDefault();
  const r = viewer.getBoundingClientRect();
  zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.0015));
}, {passive: false});
const ptrs = new Map(); let gesture = null, moved = false;
viewer.addEventListener('pointerdown', e => {
  if (mode === '3d' || e.target.closest('button, select, input, .caption, .tools3d')) return;
  ptrs.set(e.pointerId, [e.clientX, e.clientY]); moved = false;
  startGesture();
});
function startGesture() {
  const p = [...ptrs.values()];
  if (p.length === 1) gesture = {kind: 'pan', x: p[0][0] - view.x, y: p[0][1] - view.y, sx: p[0][0], sy: p[0][1]};
  else if (p.length >= 2) {
    const r = viewer.getBoundingClientRect();
    gesture = {kind: 'pinch', d: Math.hypot(p[0][0] - p[1][0], p[0][1] - p[1][1]), s: view.s, vx: view.x, vy: view.y,
               cx: (p[0][0] + p[1][0]) / 2 - r.left, cy: (p[0][1] + p[1][1]) / 2 - r.top};
  }
}
window.addEventListener('pointermove', e => {
  if (!ptrs.has(e.pointerId) || !gesture) return;
  ptrs.set(e.pointerId, [e.clientX, e.clientY]);
  const p = [...ptrs.values()];
  if (gesture.kind === 'pan' && p.length === 1) {
    if (Math.hypot(e.clientX - gesture.sx, e.clientY - gesture.sy) > 4) moved = true;
    if (moved) { view.x = e.clientX - gesture.x; view.y = e.clientY - gesture.y; apply(); viewer.classList.add('dragging'); }
  } else if (gesture.kind === 'pinch' && p.length >= 2) {
    moved = true;
    const d = Math.hypot(p[0][0] - p[1][0], p[0][1] - p[1][1]);
    const s2 = Math.min(30, Math.max(0.03, gesture.s * d / gesture.d));
    view.x = gesture.cx - (gesture.cx - gesture.vx) * s2 / gesture.s; view.y = gesture.cy - (gesture.cy - gesture.vy) * s2 / gesture.s;
    view.s = s2; apply();
  }
});
function endPtr(e) {
  if (!ptrs.has(e.pointerId)) return;
  ptrs.delete(e.pointerId); viewer.classList.remove('dragging');
  if (ptrs.size) startGesture(); else { gesture = null; rescaleLabels(); }
}
window.addEventListener('pointerup', endPtr); window.addEventListener('pointercancel', endPtr);
img.addEventListener('load', () => { fit(); if (pendingDraw) { const a = pendingDraw; pendingDraw = null; a(); } });
window.addEventListener('resize', () => { if (mode === '2d') fit(); });
$('#zin').onclick = () => zoomAt(viewer.clientWidth / 2, viewer.clientHeight / 2, 1.4);
$('#zout').onclick = () => zoomAt(viewer.clientWidth / 2, viewer.clientHeight / 2, 1 / 1.4);
$('#zfit').onclick = fit;

// ------------------------------------------------------------ adding missed items
function setAdding(on) {
  adding = on; viewer.classList.toggle('adding', adding);
  $('#addbtn').textContent = adding ? '✓ done adding' : '+ add missed item'; $('#addbtn').classList.toggle('on', adding);
  hint(adding ? 'Click each item the solver missed' : '');
}
$('#addbtn').onclick = () => setAdding(!adding);
viewer.addEventListener('click', e => {
  if (!adding || !res || moved || mode === '3d' || e.target.closest('button, .caption')) return;
  addAt(e.clientX, e.clientY);
});
function addAt(cx, cy) {
  const r = img.getBoundingClientRect();
  const u = (cx - r.left) / r.width, v = (cy - r.top) / r.height, d = 0.012;
  items.push({kind: 'box', bbox: [u - d, v - d, u + d, v + d], label: 'added by you', value: 1, on: true, added: true});
  draw(false); renderEvidence(); recompute();
}
function hint(msg) { $('#hint').hidden = !msg; $('#hint').textContent = msg || ''; }
let loadT = null;
function loading(msg) {  // overlay with a running clock, so a slow first load never looks frozen
  clearInterval(loadT); $('#loading').hidden = !msg; $('#loadmsg').textContent = msg || '';
  if (!msg) return;
  const t0 = performance.now();
  loadT = setInterval(() => { const s = (performance.now() - t0) / 1000; if (s > 2.5) $('#loadmsg').textContent = `${msg} ${s.toFixed(0)} s`; }, 500);
}

// ------------------------------------------------------------ 2D / 3D
let mode = '2d', loaded3d = null, has3d = false, storeyFocus = 'auto';
async function setMode(m) {
  mode = m; viewer.classList.toggle('mode3d', m === '3d');
  $('#m2d').classList.toggle('on', m === '2d'); $('#m3d').classList.toggle('on', m === '3d');
  if (m === '3d') { const fresh = loaded3d !== cur.path; if (await ensure3d() && !fresh) highlight3d(false); }
  else if (img.naturalWidth && res) draw(false);
  if (res) renderEvidence();
}
async function ensure3d() {
  if (!window.V3) await new Promise(r => window.addEventListener('v3ready', r, {once: true}));
  if (loaded3d === cur.path) return true;
  const path = cur.path; loaded3d = path;
  const info = await V3.load(path, (state, msg) => { if (cur.path === path) loading(state === 'loading' ? msg : ''); });
  if (cur.path !== path) return false;
  if (!info) { loaded3d = null; hint('No 3D model could be built for this drawing'); return false; }
  const sel = $('#storey'); sel.innerHTML = '';
  for (const [v, t] of [['auto', 'auto (follow evidence)'], ['all', 'whole building'], ...info.storeys.map((s, i) => [i, s.name])]) {
    const o = document.createElement('option'); o.value = v; o.textContent = t; sel.appendChild(o);
  }
  sel.value = storeyFocus === 'auto' || storeyFocus === 'all' ? storeyFocus : 'auto';
  $('#tools3d').classList.toggle('show', info.storeys.length > 1);
  highlight3d(false);
  return true;
}
$('#m2d').onclick = () => setMode('2d'); $('#m3d').onclick = () => setMode('3d');
$('#storey').onchange = e => { storeyFocus = e.target.value; applyStorey(true); };
$('#cut').oninput = e => {
  const st = V3.getStoreys(); if (!st.length) return;
  const lo = st[0].z, hi = st[st.length - 1].z + 4, y = lo + (hi - lo) * e.target.value / 1000;
  V3.setCut(e.target.value >= 1000 ? 1e9 : y);
};
function ifcItems() { return items.filter(e => e.guids && e.guids.length); }
function applyStorey(reframe) {
  let si = null;
  if (storeyFocus === 'auto') si = V3.autoStorey(ifcItems().filter(e => e.on));
  else if (storeyFocus !== 'all') si = +storeyFocus;
  V3.focusStorey(si, reframe);
  $('#cut').value = 1000;
  return si;
}
function highlight3d(animate) {
  if (!window.V3 || !V3.hasModel() || loaded3d !== cur.path) return;
  const it = ifcItems();
  applyStorey(false);
  if (!it.length) { V3.clear(); V3.focusStorey(null, false); return; }
  if (animate) animating = true;
  V3.highlight(it, animate, animate ? (k => renderAnswer(k)) : null, true, animate ? () => { animating = false; renderAnswer(null); recompute(); } : null);
}
const guidItem = () => { const m = new Map(); items.forEach((e, i) => (e.guids || []).forEach(g => m.set(g, i))); return m; };
window.onPick3d = g => {
  const i = guidItem().get(g);
  if (i != null) { items[i].on = !items[i].on; redraw(); flashRow(i); return; }
  const info = V3.elementInfo(g);
  if (info && res && primary === 'ifc') hint(`${info.type} '${info.name}' is not part of this answer`);
};
let lastHover = null;
window.onHover3d = g => {
  const i = g == null ? null : guidItem().get(g);
  if (i === lastHover) return;
  if (lastHover != null) rowHot(lastHover, false);
  lastHover = i ?? null;
  if (i != null) { rowHot(i, true, true); V3.hot(items[i].guids); } else V3.hot(null);
};

// ------------------------------------------------------------ drawing list
async function loadList(append = false) {
  if (!append) listOffset = 0;
  const tabs = $('#tabs'), box = $('#items');
  if (tab === 'upload') {
    const r = await (await fetch('/api/drawings?limit=0')).json(); renderTabs(r.counts);
    box.innerHTML = ''; $('#more').hidden = true;
    for (const d of uploads) box.appendChild(itemEl(d, `${d.kind || d.ext} · uploaded`));
    if (!uploads.length) box.innerHTML = '<div class="item"><small>Nothing uploaded yet: use the box above.</small></div>';
    return;
  }
  const r = await (await fetch(`/api/drawings?source=${tab}&q=${encodeURIComponent(listQuery)}&offset=${listOffset}&limit=80`)).json();
  renderTabs(r.counts);
  if (!append) box.innerHTML = '';
  for (const d of r.items) box.appendChild(itemEl(d, `${d.n} questions · ${d.split === 'test' ? 'held-out test' : 'dev'}`));
  listOffset += r.items.length;
  $('#more').hidden = listOffset >= r.total;
  $('#more').textContent = `show more (${r.total - listOffset} left)`;
  if (!cur && r.items[0]) select(r.items[0], 'replace');
}
function renderTabs(counts) {
  const tabs = $('#tabs'); tabs.innerHTML = '';
  const all = {...counts}; if (uploads.length) all.upload = uploads.length;
  for (const s of Object.keys(SRC)) {
    if (!all[s]) continue;
    const b = document.createElement('button'); b.className = 'tab' + (s === tab ? ' on' : '');
    b.innerHTML = `${SRC[s]} <small>${all[s]}</small>`;
    b.onclick = () => { tab = s; loadList(); }; tabs.appendChild(b);
  }
}
function itemEl(d, sub) {
  const el = document.createElement('div'); el.className = 'item' + (cur && cur.path === d.path ? ' on' : '');
  el.dataset.path = d.path;
  el.innerHTML = `${esc(d.path.split('/').pop())}<br><small>${esc(sub)}</small>`;
  el.onclick = () => { select(d); document.body.classList.remove('drawer'); };
  return el;
}
$('#more').onclick = () => loadList(true);
let searchT; $('#search').oninput = e => { clearTimeout(searchT); searchT = setTimeout(() => { listQuery = e.target.value; loadList(); }, 200); };
$('#drawerbtn').onclick = () => document.body.classList.toggle('drawer');

let pendingDraw = null;
async function select(d, how = 'push') {
  cur = {...d}; res = null; items = []; marks = []; ov.innerHTML = ''; setAdding(false); askSeq++;
  $('#answer').hidden = true; $('#evwrap').hidden = true; hint(''); $('#empty').hidden = true; $('#intro').hidden = false;
  syncURL(how);
  document.querySelectorAll('.item').forEach(e => e.classList.toggle('on', e.dataset.path === d.path));
  const r = await fetch('/api/questions?path=' + encodeURIComponent(d.path));
  if (!r.ok) {
    if (cur.path !== d.path) return;
    img.removeAttribute('src'); cur.shown = null; $('#chips').innerHTML = ''; $('#modes').classList.remove('show'); $('#credit').textContent = '';
    $('#empty').hidden = false;
    $('#empty').textContent = d.path.startsWith('uploads/') ? 'This upload is no longer on the server (uploads are cleared when it is rebuilt). Upload it again to ask about it.'
      : 'This drawing is not available. Pick another one from the list.';
    return;
  }
  const info = await r.json();
  if (cur.path !== d.path) return;
  Object.assign(cur, info); has3d = info.has3d; loaded3d = null; loading(''); if (window.V3) V3.clear();
  $('#modes').classList.toggle('show', has3d && !!info.view);
  $('#credit').textContent = info.credit ? '© ' + info.credit : '';
  showImage(info.view);
  if (!info.view && !has3d) { $('#empty').hidden = false; $('#empty').textContent = 'No preview for this file type, but you can still ask about it.'; }
  await setMode(info.view ? '2d' : (has3d ? '3d' : '2d'));
  const chips = $('#chips'); chips.innerHTML = '';
  $('#qstitle').textContent = d.source === 'upload' || d.split === 'upload' ? 'Try asking' : `Dataset questions for this drawing (${info.questions.length})`;
  for (const q of info.questions) {
    const c = document.createElement('button'); c.className = 'chip';
    c.innerHTML = `<span class="ty">${esc(q.type)}</span>${esc(q.question)}`;
    c.onclick = () => { $('#q').value = q.question; ask(); }; chips.appendChild(c);
  }
}
function showImage(view) {
  cur.shown = view || null;
  if (!view) { img.removeAttribute('src'); return; }
  const src = '/api/render?path=' + encodeURIComponent(view);
  if (img.getAttribute('src') !== src) { loading('Rendering the drawing…'); img.onload = () => loading(''); img.onerror = () => { loading(''); hint('Could not render this drawing'); }; img.src = src; }
}

// ------------------------------------------------------------ upload
$('#file').onchange = e => { if (e.target.files[0]) upload(e.target.files[0]); e.target.value = ''; };
let dragDepth = 0;
window.addEventListener('dragenter', e => { if (e.dataTransfer?.types?.includes('Files')) { dragDepth++; $('#dropzone').hidden = false; } });
window.addEventListener('dragleave', () => { if (--dragDepth <= 0) { dragDepth = 0; $('#dropzone').hidden = true; } });
window.addEventListener('dragover', e => e.preventDefault());
window.addEventListener('drop', e => {
  e.preventDefault(); dragDepth = 0; $('#dropzone').hidden = true;
  const f = e.dataTransfer?.files?.[0]; if (f) upload(f);
});
async function upload(f) {
  loading(`Uploading ${f.name} (${(f.size / 1e6).toFixed(1)} MB)…`);
  try {
    const r = await fetch('/api/upload?name=' + encodeURIComponent(f.name), {method: 'POST', body: f});
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || r.statusText);
    uploads = [d, ...uploads.filter(u => u.path !== d.path)].slice(0, 30);
    localStorage.setItem('bp_uploads', JSON.stringify(uploads));
    tab = 'upload'; loading(''); await loadList(); await select(d);
    $('#q').focus();
  } catch (err) { loading(''); hint('Upload failed: ' + err.message); }
}

// ------------------------------------------------------------ ask
const THINK = {swiss_dwellings: ['reading the CAD layers of the DXF twin', 'measuring room polygons'],
  cubicasa5k: ['looking for door, window and room symbols', 'counting detections'],
  ifc_models: ['querying the IFC model', 'summing element quantities'], ifc_bench: ['querying the IFC model'],
  upload: ['classifying your file', 'reading the drawing']};
async function ask() {
  const question = $('#q').value.trim(); if (!question || !cur) return;
  const seq = ++askSeq;
  setAdding(false);
  const a = $('#answer'); a.hidden = false; a.classList.remove('pop'); $('#intro').hidden = true;
  if (PHONE.matches) $('#q').blur();  // drop the phone keyboard so the answer is visible
  const steps = THINK[cur.source || cur.split] || THINK[cur.path.startsWith('uploads/') ? 'upload' : ''] || ['reading the drawing'];
  const t0 = performance.now();
  const tick = () => {
    if (seq !== askSeq || res?._seq === seq) return;
    const s = (performance.now() - t0) / 1000;
    a.innerHTML = `<div class="qecho">${esc(question)}</div><div class="thinking"><div><span class="spin"></span> ${esc(steps[Math.min(steps.length - 1, Math.floor(s / 1.5))])}…</div>
      <small>${s.toFixed(1)} s${s > 6 ? ' · big models load slowly the first time, then answers come from cache' : ''}</small></div>`;
    setTimeout(tick, 100);
  };
  res = null; tick();
  $('#evwrap').hidden = true; ov.innerHTML = '';
  let r;
  try {
    const resp = await fetch('/api/ask', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({path: cur.path, question})});
    r = await resp.json();
    if (!resp.ok) r = {answer: null, confidence: 0, evidence: [], explanation: r.detail || `server error ${resp.status}`, method: 'error'};
  } catch (err) {
    r = {answer: null, confidence: 0, evidence: [], explanation: 'could not reach the server: ' + err.message, method: 'error'};
  }
  if (seq !== askSeq) return;
  res = r; res._seq = seq; res.question = question;
  syncURL('replace');
  session.n++; session.ours += res.cost_usd || 0; session.base += res.baseline_cost_usd || 0;
  updateMeter();
  a.classList.add('pop');
  setupEvidence();
  renderAnswer(items.length && typeof res.answer === 'number' ? 0 : null);
  if (primary === 'ifc' && has3d) { await setMode('3d'); highlight3d(true); }
  else {
    if (mode === '3d') await setMode('2d');
    const go = () => { zoomToEvidence(); draw(true); };
    if (cur.shown && img.complete && img.naturalWidth && img.getAttribute('src')?.includes(encodeURIComponent(cur.shown))) go();
    else pendingDraw = go;
  }
  renderEvidence();
}
$('#go').onclick = ask; $('#q').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.isComposing) ask(); });

function setupEvidence() {
  const ev = res.evidence || [];
  const two = ev.filter(e => (e.kind === 'box' || e.kind === 'polygon') && (e.page || 0) === 0);
  const txt = ev.filter(e => e.kind === 'text');
  const three = ev.filter(e => e.kind === 'ifc');
  primary = three.length && has3d ? 'ifc' : '2d';
  // which page image do the 2D items refer to? switch to it if it isn't the one on screen
  const files = {}; for (const e of [...two, ...txt]) if (e.file) files[e.file] = (files[e.file] || 0) + 1;
  const evFile = Object.keys(files).sort((x, y) => files[y] - files[x])[0];
  if (evFile && evFile !== cur.shown && /\.(pdf|png|jpe?g)$/i.test(evFile)) showImage(evFile);
  const onShown = e => !e.file || e.file === (evFile || cur.shown);
  const plan2d = two.filter(onShown);
  if (three.length && plan2d.length === three.length) {
    // the plan items are the IFC elements, in the same order: count on the drawing, light up the same ones in 3D
    primary = 'paired';
    items = plan2d.map((e, i) => ({...e, label: (e.label || '').replace(/^\d+\.\s*/, ''), value: e.value ?? three[i].value,
                                   guids: [...(e.guids || []), ...(three[i].guids || [])], on: true}));
    marks = txt.filter(onShown).map(e => ({...e, mark: true}));
  } else if (primary === 'ifc') {
    items = three.map(e => ({...e, on: true}));
    marks = [...two, ...txt].filter(onShown).map(e => ({...e, mark: true}));
  } else {
    items = (two.length ? plan2d : three).map(e => ({...e, on: true}));
    marks = txt.filter(onShown).map(e => ({...e, mark: true}));
  }
}

function zoomToEvidence() {
  const all = [...items, ...marks].filter(e => e.kind !== 'ifc');
  if (!all.length || !img.naturalWidth) { fit(); return; }
  let x0 = 1, y0 = 1, x1 = 0, y1 = 0;
  for (const e of all) {
    const pts = e.points || [[e.bbox[0], e.bbox[1]], [e.bbox[2], e.bbox[3]]];
    for (const [x, y] of pts) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
  }
  const W = viewer.clientWidth, H = viewer.clientHeight - 20, w = img.naturalWidth, h = img.naturalHeight;
  const pad = 0.04; x0 = Math.max(0, x0 - pad); y0 = Math.max(0, y0 - pad); x1 = Math.min(1, x1 + pad); y1 = Math.min(1, y1 + pad);
  const fitS = Math.min(W / w, H / h) * 0.97;
  const s = Math.min(W / ((x1 - x0) * w), H / ((y1 - y0) * h));
  view.s = Math.max(fitS, Math.min(s, fitS * 6)); view.x = W / 2 - (x0 + x1) / 2 * w * view.s; view.y = H / 2 - (y0 + y1) / 2 * h * view.s;
  stage.style.transition = 'transform .6s cubic-bezier(.2,.8,.2,1)'; apply(); setTimeout(() => stage.style.transition = '', 620);
}

const fmt = (v, t) => v == null ? '—' : (t === 'count' ? Math.round(v) : (+v).toFixed(2));
const unitOf = t => ({area: 'm²', length: 'm', volume: 'm³', count: ''}[t] || '');
const latency = s => s == null ? '' : s < 0.001 ? '&lt; 1 ms' : s < 1 ? (s * 1000).toFixed(0) + ' ms' : s.toFixed(1) + ' s';
const money = v => v === 0 ? '$0' : v < 0.001 ? '$' + v.toFixed(5) : v < 1 ? '$' + v.toFixed(3) : '$' + v.toFixed(2);

// how was this answer made? one badge + one line, so a judge knows what to trust and how to check it
function howOf(r) {
  const m = String(r.method || ''), paid = (r.cost_usd || 0) > 0;
  if (r.answer == null) return r.budget_exhausted ? {cls: 'none', t: 'Paused: daily budget used', how: 'the $0 solvers for Swiss, CubiCasa and IFC drawings still answer'}
    : {cls: 'none', t: 'Abstained', how: 'when the evidence is not good enough we say so instead of guessing'};
  if (/-na$|-none$/.test(m)) return {cls: 'none', t: 'Not in the model', how: 'nothing in the file states this, so we say so rather than guess'};
  if (/^swiss/.test(m)) return {cls: 'geo', t: 'Verified by geometry', how: 'counted and measured on the CAD layers of the drawing; no AI model involved'};
  if (/^ifc-text/.test(m)) return {cls: 'geo', t: 'Looked up in the BIM model', how: 'read from the IFC model by a fixed rule; no AI model involved'};
  if (/^ifc/.test(m) && !/^ifctext/.test(m)) return {cls: 'geo', t: 'Verified by geometry', how: 'queried from the IFC model: every element and quantity that adds up to it is listed'};
  if (/^cubicasa/.test(m)) return {cls: 'vis', t: 'Detected by vision', how: 'a small detector we trained found each symbol; every box it counted is on the plan'};
  if (/ground|^vlm/.test(m)) return {cls: 'vis', t: 'Detected by vision', how: 'a vision model boxed every instance it counted; check the boxes on the drawing'};
  if (/generic-text/.test(m)) return {cls: 'llm', t: 'Answered by an LLM', how: 'a language model read the drawing\'s text; the text it used is boxed on the drawing'};
  if (/^ifctext/.test(m)) return {cls: 'llm', t: 'Answered by an LLM', how: 'a language model answered from facts extracted from the IFC model' + (paid ? '' : ' (no paid call)')};
  return {cls: 'llm', t: 'Answered by an AI model', how: 'a model read the drawing; treat it as a lead and check the evidence'};
}

function renderAnswer(shownSoFar) {
  if (!res) return;
  const a = $('#answer'); const t = res.type;
  const counting = shownSoFar !== null && items.length && typeof res.answer === 'number';
  let val = res.answer;
  if (counting) val = items.slice(0, shownSoFar).reduce((s, e) => s + (e.value ?? 1), 0);
  const conf = res.confidence ?? 0;
  const confCls = conf >= 0.8 ? 'ok' : conf >= 0.5 ? 'warn' : 'bad';
  let gold = '';
  if (res.gold != null && res.answer != null && !counting && typeof res.gold === 'number') {
    const g = +res.gold, p = +res.answer;
    const ok = t === 'count' ? Math.round(p) === Math.round(g) : Math.abs(p - g) <= 0.02 * Math.abs(g);
    gold = `<span class="pill ${ok ? 'ok' : 'bad'}">${ok ? '✓ matches' : '✗ differs from'} the dataset answer ${fmt(g, t)}</span>`;
  }
  const abst = res.answer == null;
  const num = typeof res.answer === 'number';
  const route = res.route && res.route !== '-' ? `<span class="pill">${esc(res.route.split(' -> ').filter(x => x !== '-').map(x => ROUTE[x] || x).join(' → '))}</span>` : '';
  const baseS = res.baseline_latency_s || 8;
  a.innerHTML = `
    <div class="qecho">${esc(res.question)}</div>
    <div class="big ${abst ? 'abstain' : ''} ${counting ? 'counting' : ''}">${abst ? 'Not sure, so no guess' : num ? fmt(val, t) : ''} <small>${abst ? '' : unitOf(t)}</small></div>
    ${typeof res.answer === 'string' ? `<div class="textans">${esc(res.answer)}</div>` : ''}
    ${(() => { const h = howOf(res); return `<div class="how ${h.cls}"><b>${h.cls === 'geo' ? '✓' : h.cls === 'vis' ? '◎' : h.cls === 'llm' ? '✦' : '–'} ${esc(h.t)}</b><span>${esc(h.how)}</span></div>`; })()}
    <div class="expl">${esc(res.explanation || '')}</div>
    <div class="row" style="margin-top:10px">${abst ? '' : `<span class="pill ${confCls}">confidence ${(conf * 100).toFixed(0)}%</span>`}
      ${route}${gold}</div>
    <div class="corr" id="corr"></div>
    <div class="costcmp">
      <span class="lab">this answer</span><span><span class="mbar" style="display:block"><i style="width:${Math.max(0.5, 100 * (res.cost_usd || 0) / Math.max(res.baseline_cost_usd || 1e-9, res.cost_usd || 0))}%"></i></span></span>
      <span class="v"><b>${money(res.cost_usd || 0)}</b> · ${latency(res.latency_s)}</span>
      <span class="lab">frontier VLM</span><span><span class="mbar" style="display:block"><i class="base" style="width:100%"></i></span></span>
      <span class="v">~${money(res.baseline_cost_usd || 0)} · ~${baseS.toFixed(0)} s</span>
    </div>`;
  if (!counting) recompute();
}

function updateMeter() {
  const mx = Math.max(session.base, session.ours, 1e-9);
  $('#m-ours').textContent = money(session.ours); $('#m-base').textContent = money(session.base);
  $('#bar-ours').style.width = (100 * session.ours / mx) + '%'; $('#bar-base').style.width = (100 * session.base / mx) + '%';
  const saved = session.base > 0 ? 100 * (1 - session.ours / session.base) : 0;
  $('#m-sum').innerHTML = `<span class="only-desk">${session.n} question${session.n === 1 ? '' : 's'} · </span>` + (saved >= 0
    ? `<b>${saved >= 99.95 ? '100' : saved.toFixed(1)}% cheaper</b>` + (session.ours > 0 ? ` (${(session.base / session.ours).toFixed(0)}×)` : '<span class="only-desk"> · no model calls</span>')
    : `${(-saved).toFixed(0)}% dearer`);
  $('#meter').dataset.short = `ours ${money(session.ours)} vs frontier ${money(session.base)}`;
}

// ------------------------------------------------------------ evidence overlay
const PHONE = matchMedia('(max-width: 860px)');
function labelSize() { return (PHONE.matches ? 11 : 14) / view.s; }
function rescaleLabels() {
  const fs = labelSize();
  ov.querySelectorAll('circle.badgebg').forEach(c => c.setAttribute('r', fs * 0.78));
  ov.querySelectorAll('text.badge').forEach(t => t.style.fontSize = (t.textContent.length > 2 ? fs * 0.62 : fs * 0.82) + 'px');
  ov.querySelectorAll('text.pglabel').forEach(t => { t.style.fontSize = fs + 'px'; t.setAttribute('y', +t.dataset.y + fs * 1.5); });
}
function draw(animate) {
  ov.innerHTML = '';
  if (mode === '3d' || !img.naturalWidth) return;
  const W = img.naturalWidth, H = img.naturalHeight;
  ov.setAttribute('viewBox', `0 0 ${W} ${H}`);
  for (const m of marks) ov.appendChild(shapeFor(m, -1, W, H));
  const list2d = items.map((e, i) => [e, i]).filter(([e]) => e.kind !== 'ifc');
  const step = animate ? Math.max(25, Math.min(110, 1800 / Math.max(1, list2d.length))) : 0;
  list2d.forEach(([e, i], k) => {
    const show = () => { ov.appendChild(shapeFor(e, i, W, H)); if (animate) renderAnswer(k + 1); };
    if (animate) setTimeout(() => { if (res && items[i] === e) show(); }, k * step); else show();
  });
  const done = () => { animating = false; renderAnswer(null); recompute(); };
  if (animate) { animating = true; setTimeout(done, list2d.length * step + 60); } else done();
}
function shapeFor(e, i, W, H) {
  const g = document.createElementNS(NS, 'g'); g.dataset.i = i;
  const fs = labelSize();
  let shape, lx, ly;
  if (e.kind === 'polygon') {
    shape = document.createElementNS(NS, 'polygon');
    shape.setAttribute('points', e.points.map(p => (p[0] * W) + ',' + (p[1] * H)).join(' '));
    shape.setAttribute('class', 'pg appear' + (e.on ? '' : ' off'));
    const xs = e.points.map(p => p[0] * W), ys = e.points.map(p => p[1] * H);
    lx = (Math.min(...xs) + Math.max(...xs)) / 2; ly = (Math.min(...ys) + Math.max(...ys)) / 2;
  } else {
    const [x0, y0, x1, y1] = e.bbox;
    shape = document.createElementNS(NS, 'rect');
    shape.setAttribute('x', x0 * W); shape.setAttribute('y', y0 * H);
    shape.setAttribute('width', Math.max(2, (x1 - x0) * W)); shape.setAttribute('height', Math.max(2, (y1 - y0) * H));
    shape.setAttribute('rx', 2);
    const cls = e.mark ? (e.kind === 'text' ? 'bx txt' : 'bx mark') : 'bx appear' + (e.on ? '' : ' off') + (e.added ? ' added' : '');
    shape.setAttribute('class', cls); lx = x0 * W; ly = y0 * H;
  }
  const tip = document.createElementNS(NS, 'title'); tip.textContent = (e.label || '') + (e.value != null && res.type !== 'count' ? ` = ${fmt(e.value, res.type)} ${unitOf(res.type)}` : '');
  shape.appendChild(tip);
  g.appendChild(shape);
  if (i >= 0) {
    shape.addEventListener('click', ev => { if (adding) return; ev.stopPropagation(); if (moved) return; e.on = !e.on; redraw(); flashRow(i); });
    shape.addEventListener('mouseenter', () => rowHot(i, true, true));
    shape.addEventListener('mouseleave', () => rowHot(i, false));
  } else if (e.guids) {
    shape.addEventListener('mouseenter', () => { const j = guidItem().get(e.guids[0]); if (j != null) rowHot(j, true, true); });
  }
  if (i >= 0 && numbered(e) && e.on) {
    const n = items.slice(0, i + 1).filter(x => x.on && numbered(x)).length;
    const c = document.createElementNS(NS, 'circle');
    c.setAttribute('cx', lx); c.setAttribute('cy', ly); c.setAttribute('r', fs * 0.78);
    c.setAttribute('class', 'badgebg' + (e.added ? ' added' : '')); g.appendChild(c);
    const t = document.createElementNS(NS, 'text');
    t.setAttribute('x', lx); t.setAttribute('y', ly); t.setAttribute('text-anchor', 'middle');
    t.setAttribute('dominant-baseline', 'central'); t.setAttribute('class', 'badge');
    t.textContent = n; t.style.fontSize = (String(n).length > 2 ? fs * 0.62 : fs * 0.82) + 'px'; g.appendChild(t);
  } else if (i >= 0 && e.kind === 'polygon' && e.on && e.value != null && res.type !== 'count') {
    const t = document.createElementNS(NS, 'text');
    t.setAttribute('x', lx); t.dataset.y = ly; t.setAttribute('y', ly + fs * 1.5); t.setAttribute('text-anchor', 'middle');
    t.setAttribute('class', 'pglabel'); t.style.fontSize = fs + 'px';
    t.textContent = (+e.value).toFixed(2) + ' m²'; g.appendChild(t);
  }
  return g;
}

// boxes, and room polygons in a count question, carry a running number on the drawing and in the list
function numbered(e) { return e.kind === 'box' || (e.kind === 'polygon' && res && res.type === 'count'); }

// ------------------------------------------------------------ evidence list
function renderEvidence() {
  $('#evwrap').hidden = !items.length;
  if (!items.length) return;
  const ev = $('#ev'); ev.innerHTML = '';
  const t = res.type, num = typeof res.answer === 'number';
  const on = items.filter(e => e.on).length;
  $('#evtitle').textContent = `Evidence · ${on} of ${items.length}`;
  $('#addbtn').hidden = primary === 'ifc' || mode === '3d' || !num;
  $('#evhelp').textContent = primary === 'ifc'
    ? 'Each row is an IFC element. Hover to find it in 3D; click a row or the element itself to drop it from the answer.'
    : primary === 'paired' ? 'Each row is an IFC element, numbered on the plan. Switch to 3D to see the same elements in the model; click to drop one.'
    : 'Hover a row to find it on the drawing; click a row or a shape to drop it. Missed one? Add it.';
  let k = 0;
  items.forEach((e, i) => {
    const d = document.createElement('div'); d.className = (e.on ? '' : 'off') + (e.added ? ' added' : ''); d.dataset.i = i;
    if (numbered(e) && e.on) k++;
    const name = e.kind === 'box' ? (e.label || 'item').replace(/ \d+$/, '') : (e.label || (e.kind === 'polygon' ? 'region' : 'item'));
    const lead = numbered(e) ? `<span class="n">${e.on ? '#' + k : '–'}</span>` : `<span class="n">${i + 1}</span>`;
    const val = e.value != null && t !== 'count' ? fmt(e.value, t) + ' ' + unitOf(t) : '';
    d.innerHTML = `${lead}<span class="nm" title="${esc(name)}">${esc(name)}</span><span class="vl">${val}</span>`;
    d.onmouseenter = () => hotItem(i, true); d.onmouseleave = () => hotItem(i, false);
    d.onclick = () => { e.on = !e.on; redraw(); };
    ev.appendChild(d);
  });
  if (num) {
    const tot = document.createElement('div'); tot.className = 'tot';
    const v = items.filter(e => e.on).reduce((s, e) => s + (e.value ?? 1), 0);
    tot.innerHTML = `<span>${t === 'count' ? 'count' : 'sum'} of checked items</span><span>${fmt(v, t)} ${unitOf(t)}</span>`;
    ev.appendChild(tot);
  }
}
function redraw() {
  if (mode === '3d') { highlight3d(false); renderAnswer(null); }
  else draw(false);
  renderEvidence(); recompute();
}
function hotItem(i, on) {
  const s = ov.querySelector(`g[data-i="${i}"] rect, g[data-i="${i}"] polygon`); if (s) s.classList.toggle('hot', on);
  if (mode === '3d' && window.V3) V3.hot(on ? items[i]?.guids : null);
  if (mode === '2d' && items[i]?.guids) {  // plan marks that belong to this IFC element
    ov.querySelectorAll('g[data-i="-1"] rect').forEach((r, k) => { const m = marks[k]; if (m && m.guids && m.guids.some(g => items[i].guids.includes(g))) r.classList.toggle('hot', on); });
  }
}
function rowHot(i, on, scroll) {
  const r = $(`#ev div[data-i="${i}"]`); if (!r) return;
  r.classList.toggle('hot', on);
  if (on && scroll) {  // scroll the list only, never the page (on a phone the page scroll would hide the drawing)
    const box = $('#ev'), top = r.offsetTop, bot = top + r.offsetHeight;
    if (top < box.scrollTop) box.scrollTop = top; else if (bot > box.scrollTop + box.clientHeight) box.scrollTop = bot - box.clientHeight + 30;
  }
  const s = ov.querySelector(`g[data-i="${i}"] rect, g[data-i="${i}"] polygon`); if (s) s.classList.toggle('hot', on);
}
function flashRow(i) { rowHot(i, true, true); setTimeout(() => rowHot(i, false), 700); }

function recompute() {
  if (!res || typeof res.answer !== 'number') return;
  const changed = items.some(e => !e.on || e.added);
  const v = items.filter(e => e.on).reduce((s, e) => s + (e.value ?? 1), 0);
  const el = $('#corr'); if (!el) return;
  el.innerHTML = changed ? `✎ corrected by you: <b>${fmt(v, res.type)} ${unitOf(res.type)}</b> (the solver said ${fmt(res.answer, res.type)})` : '';
}

// ------------------------------------------------------------ demo tour
let tour = null, tourI = 0, tourAuto = false;
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function startTour(auto = false) {
  tour = await (await fetch('/api/tour')).json(); tourAuto = auto;
  if (!tour.length) { hint('No tour steps available on this dataset'); return; }
  tourI = 0; await runStep();
}
async function typeQuestion(text) {
  const q = $('#q'); q.value = '';
  const dt = Math.max(12, Math.min(40, 1400 / text.length));
  for (const ch of text) { q.value += ch; await sleep(dt); }
}
async function runStep() {
  const s = tour[tourI];
  $('#caption').hidden = false; document.body.classList.add('touring');
  $('#capstep').textContent = `Demo tour · ${tourI + 1} / ${tour.length}`;
  $('#captitle').textContent = s.title; $('#captext').textContent = s.caption || '';
  $('#tnext').textContent = tourI === tour.length - 1 ? 'finish ✓' : 'next ›';
  $('#tprev').disabled = tourI === 0;
  const myI = tourI;
  if (s.path && (!cur || cur.path !== s.path)) {
    tab = s.source || tab;
    await select({path: s.path, source: s.source, split: s.split || ''}, 'replace');
    loadList();
  }
  if (s.question) {
    await sleep(400); await typeQuestion(s.question); await sleep(250);
    if (myI !== tourI) return;
    await ask();
    for (let t = 0; t < 12000 && animating; t += 100) await sleep(100);  // let the count finish, however slow the GPU
    await sleep(1200);
  }
  for (const act of s.actions || []) {
    if (myI !== tourI) return;
    await doAction(act);
  }
  window.__tourStepDone = myI;
}
async function doAction(act) {
  const [k, arg] = act.split(':');
  if (k === 'wait') await sleep(+arg);
  else if (k === 'toggle') {
    const i = +arg; if (!items[i]) return;
    hotItem(i, true); await sleep(700); items[i].on = !items[i].on; redraw(); hotItem(i, false); flashRow(i); await sleep(900);
  } else if (k === 'add') {
    const [u, v] = arg.split(',').map(Number); const r = img.getBoundingClientRect();
    setAdding(true); await sleep(500); addAt(r.left + u * r.width, r.top + v * r.height); await sleep(600); setAdding(false);
  } else if (k === 'mode') await setMode(arg);
  else if (k === 'storey') { storeyFocus = arg; $('#storey').value = arg; applyStorey(true); await sleep(600); }
  else if (k === 'hover') { const i = +arg; hotItem(i, true); rowHot(i, true, true); await sleep(1400); hotItem(i, false); rowHot(i, false); }
}
function endTour() { tour = null; $('#caption').hidden = true; document.body.classList.remove('touring'); }
$('#tourbtn').onclick = () => startTour(false);
$('#tnext').onclick = () => { if (!tour) return; if (tourI < tour.length - 1) { tourI++; runStep(); } else endTour(); };
$('#tprev').onclick = () => { if (tour && tourI > 0) { tourI--; runStep(); } };
$('#texit').onclick = endTour;
window.bpTour = {start: startTour, next: () => $('#tnext').click(), get step() { return tourI; }, get steps() { return tour; }};

// ------------------------------------------------------------ start
// ------------------------------------------------------------ URL state (reload / share / back / forward)
function syncURL(how) {
  if (!cur || how === 'none') return;
  const p = new URLSearchParams();
  p.set('tab', tab); p.set('path', cur.path); if (res && res.question) p.set('q', res.question);
  const u = location.pathname + '?' + p.toString();
  if (u === location.pathname + location.search) return;
  history[how === 'push' ? 'pushState' : 'replaceState'](null, '', u);
}
async function restore(first) {
  const p = new URLSearchParams(location.search);
  const t = p.get('tab'), path = p.get('path'), q = p.get('q');
  const tabChanged = t && t !== tab && (SRC[t]);
  if (tabChanged) tab = t;
  if (path && (!cur || cur.path !== path)) await select({path, source: tab, split: tab === 'upload' ? 'upload' : ''}, 'none');
  if (first || tabChanged) await loadList();
  if (q && (!res || res.question !== q)) { $('#q').value = q; await ask(); }
  else if (!q && res) { askSeq++; res = null; items = []; marks = []; ov.innerHTML = ''; $('#answer').hidden = true; $('#evwrap').hidden = true; $('#intro').hidden = false; $('#q').value = ''; fit(); }
}
window.addEventListener('popstate', () => { if (tour) endTour(); restore(false); });

// ------------------------------------------------------------ keyboard
document.addEventListener('keydown', e => {
  const typing = e.target.matches('input, textarea, select');
  if (e.key === 'Escape') {
    if (tour) endTour();
    else if (adding) setAdding(false);
    else if (document.body.classList.contains('drawer')) document.body.classList.remove('drawer');
    else if (typing) e.target.blur();
    return;
  }
  if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === '/') { e.preventDefault(); $('#q').focus(); $('#q').select(); }
  else if (tour && e.key === 'ArrowRight') $('#tnext').click();
  else if (tour && e.key === 'ArrowLeft') $('#tprev').click();
  else if (e.key === 'f' && mode === '2d') fit();
  else if ((e.key === '+' || e.key === '=') && mode === '2d') $('#zin').click();
  else if (e.key === '-' && mode === '2d') $('#zout').click();
});
$('#credit').onclick = () => $('#credit').classList.toggle('open');
$('#scrim').onclick = () => document.body.classList.remove('drawer');

// ------------------------------------------------------------ start
(async () => {
  await restore(true);
  const p = new URLSearchParams(location.search);
  if (p.has('tour')) startTour(p.get('tour') === 'auto');
})();
