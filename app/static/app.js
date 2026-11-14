// Blueprints that talk: pick or upload a drawing, ask, watch the answer get counted out on the drawing.
'use strict';
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const SRC = {swiss_dwellings: 'Swiss apartments', cubicasa5k: 'Finnish plans', ifc_models: 'IFC / BIM models', ifc_bench: 'IFC text Q&A',
             opening_design: 'US drawing sets', upload: 'Your uploads'};
const ROUTE = {swiss: 'CAD layers (DXF twin)', ifc: 'IFC model query', cubicasa: 'plan symbol detector', generic: 'generic drawing reader', ifctext: 'IFC fact sheet', normalize: 'question normaliser (small LLM)'};
const NS = 'http://www.w3.org/2000/svg';

let tab = 'swiss_dwellings', cur = null, res = null, items = [], marks = [], adding = false, primary = '2d';
let session = {n: 0, ours: 0, base: 0};
let listOffset = 0, listQuery = '';
let uploads = JSON.parse(localStorage.getItem('bp_uploads') || '[]');
let askSeq = 0, animating = false;

// ------------------------------------------------------------ pan / zoom (mouse, wheel, touch pinch)
let view = {s: 1, x: 0, y: 0};
const stage = $('#stage'), viewer = $('#viewer'), img = $('#img'), ov = $('#ov');
function apply() { stage.style.transform = `translate(${view.x}px,${view.y}px) scale(${view.s})`; ov.style.setProperty('--u', (1 / view.s) + 'px'); }
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
  if (!window.V3 || !V3.hasModel() || loaded3d !== cur.path) {  // model still loading: show the final number now
    if (animate) { animating = false; renderAnswer(null); }
    return;
  }
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
  for (const d of r.items) box.appendChild(itemEl(d, `${d.n} questions · ${d.split === 'test' ? 'test drawing, never trained on' : 'development drawing'}`));
  listOffset += r.items.length;
  $('#more').hidden = listOffset >= r.total;
  $('#more').textContent = `show more (${r.total - listOffset} left)`;
  if (!cur && r.items[0]) select(r.items[0], 'replace');
  if (!append) revealSelected();
}
// a drawing opened by the tour or a shared link: scroll the file list (only the list, never the page) to it
function revealSelected() {
  const el = $('#items .item.on'); if (!el) return;
  let box = el.parentElement;
  while (box && box !== document.body && !(box.scrollHeight > box.clientHeight + 1 && /auto|scroll/.test(getComputedStyle(box).overflowY))) box = box.parentElement;
  if (!box || box === document.body) return;
  const top = el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
  if (top < box.scrollTop || top + el.offsetHeight > box.scrollTop + box.clientHeight) box.scrollTop = Math.max(0, top - box.clientHeight / 3);
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
  revealSelected();
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
  if (d.path.startsWith('uploads/') && !uploads.some(u => u.path === d.path)) {  // opened from a shared link
    uploads = [{path: d.path, kind: info.kind, ext: d.path.split('.').pop(), source: 'upload', split: 'upload'}, ...uploads].slice(0, 30);
    localStorage.setItem('bp_uploads', JSON.stringify(uploads)); if (tab === 'upload') loadList();
  }
  Object.assign(cur, info); has3d = info.has3d; loaded3d = null; loading(''); if (window.V3) V3.clear();
  cur.page = 0; cur.pin = null; uploadPanel(info);
  $('#modes').classList.toggle('show', has3d);  // a model without a plan sheet still shows "3D model", with Plan disabled
  $('#m2d').disabled = !info.view; $('#m2d').title = info.view ? '' : 'no plan sheet for this model';
  $('#credit').textContent = !info.credit ? '' : d.path.startsWith('uploads/') ? info.credit : '© ' + info.credit;  // an upload is not licensed to us
  showImage(info.view);
  if (!info.view && !has3d) { $('#empty').hidden = false; $('#empty').textContent = 'No preview for this file type, but you can still ask about it.'; }
  const chips = $('#chips'); chips.innerHTML = '';
  $('#qstitle').textContent = d.source === 'upload' || d.split === 'upload' ? 'Try asking' : `Dataset questions for this drawing (${info.questions.length})`;
  for (const q of info.questions) {
    const c = document.createElement('button'); c.className = 'chip';
    c.innerHTML = `<span class="ty">${esc(q.type)}</span>${esc(q.question)}`;
    c.onclick = () => { $('#q').value = q.question; ask(); }; chips.appendChild(c);
  }
  // chips first: a big model can take a while to tessellate and the questions should not wait for it
  if (cur.path === d.path) await setMode(info.view ? '2d' : (has3d ? '3d' : '2d'));
}
function showImage(view, page = 0) {
  cur.shown = view || null; cur.page = page || 0; syncPageBar();
  if (!view) { img.removeAttribute('src'); return; }
  loadWords(view, page || 0);
  const src = '/api/render?path=' + encodeURIComponent(view) + (page ? '&page=' + page : '');
  if (img.getAttribute('src') !== src) { loading('Rendering the drawing…'); img.onload = () => loading(''); img.onerror = () => { loading(''); hint('Could not render this drawing'); }; img.src = src; }
}

// ------------------------------------------------------------ upload
$('#file').accept = '.pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp,.gif,.svg,.dxf,.ifc';
// what the server did to an upload (rectified photo, turned scan, ...), a not-a-drawing warning, and a page picker
function uploadPanel(info) {
  let box = $('#upnote');
  if (!box) { box = document.createElement('div'); box.id = 'upnote'; box.style.cssText = 'font-size:12px;color:var(--mut);margin:0 0 10px;line-height:1.45'; $('#chips').parentElement.before(box); }
  const up = cur.path.startsWith('uploads/');
  const notes = (up ? info.notes || [] : []).map(n => `<div>· ${esc(n)}</div>`).join('');
  const orig = up && info.original ? `<div><a href="/api/file?path=${encodeURIComponent(info.original)}" target="_blank" rel="noopener">see your original file</a></div>` : '';
  const warn = up && info.not_drawing ? `<div style="color:#b45309"><b>This doesn't look like a construction drawing</b> (it looks like: ${esc(info.not_drawing)}). Questions about it are declined: nothing is counted or read off a file that is not a drawing.</div>` : '';
  box.innerHTML = `${warn}${notes ? '<b>We prepared your file:</b>' + notes : ''}${orig}`;
  box.hidden = !box.innerHTML;
  let bar = $('#pagebar');
  if (!bar) {
    bar = document.createElement('div'); bar.id = 'pagebar';
    bar.style.cssText = 'position:absolute;top:12px;left:50%;transform:translateX(-50%);z-index:6;display:flex;gap:4px;align-items:center;background:var(--panel);border:1px solid var(--line2);border-radius:var(--r1);padding:3px 6px;font-size:12px;max-width:70%';
    bar.innerHTML = '<button id="pgprev" aria-label="Previous page">‹</button><select id="pgsel" aria-label="Page to ask about" style="max-width:340px"></select><button id="pgnext" aria-label="Next page">›</button>';
    $('#viewer').appendChild(bar);
    const go = p => { if (!cur || p < 0 || p >= (cur.pages || 1)) return; cur.pin = p; showImage(cur.view, p); };
    $('#pgsel').onchange = e => { const v = e.target.value; if (v === 'auto') { cur.pin = null; syncPageBar(); } else go(+v); };
    $('#pgprev').onclick = () => go((cur.page || 0) - 1); $('#pgnext').onclick = () => go((cur.page || 0) + 1);
  }
  const n = info.pages || 1, titles = info.page_titles || {};
  bar.hidden = !(cur.path.startsWith('uploads/') && n > 1 && info.view);
  if (!bar.hidden) {
    $('#pgsel').innerHTML = '<option value="auto">Any page: find the right one</option>' +
      Array.from({length: n}, (_, i) => `<option value="${i}">Page ${i + 1} of ${n}${titles[i] ? ' · ' + esc(titles[i]).slice(0, 60) : ''}</option>`).join('');
  }
  syncPageBar();
}
function syncPageBar() {
  const sel = $('#pgsel'); if (!sel || !cur || $('#pagebar').hidden) return;
  sel.value = cur.pin != null ? String(cur.pin) : 'auto';
  const o = sel.querySelector('option[value="auto"]');
  if (o) o.textContent = cur.pin != null ? 'Any page: find the right one' : `Any page (showing ${(cur.page || 0) + 1} of ${cur.pages || 1})`;
}
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
    const body = {path: cur.path, question}; if (cur.pin != null) body.page = cur.pin;
    const resp = await fetch('/api/ask', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    r = await resp.json();
    if (!resp.ok) r = {answer: null, confidence: 0, evidence: [], explanation: r.detail || `server error ${resp.status}`, method: 'error'};
  } catch (err) {
    r = {answer: null, confidence: 0, evidence: [], explanation: 'could not reach the server: ' + err.message, method: 'error'};
  }
  if (seq !== askSeq) return;
  res = r; res._seq = seq; res.question = question; showSecond = false;
  recordTakeoff(res);
  syncURL('replace');
  // a declined question (or a file that is not a drawing) would not have gone to a frontier model either: no estimate
  session.n++; session.ours += res.cost_usd || 0; if (res.answer != null && !cur.not_drawing) session.base += res.baseline_cost_usd || 0;
  updateMeter();
  a.classList.add('pop');
  setupEvidence();
  renderAnswer(items.length && typeof res.answer === 'number' ? 0 : null);
  if (primary === 'ifc' && has3d) { await setMode('3d'); highlight3d(true); }
  else {
    if (mode === '3d' && cur.shown) await setMode('2d');  // no plan sheet (IFC-only): stay in 3D
    const go = () => { zoomToEvidence(); draw(true); };
    if (cur.shown && img.complete && img.naturalWidth && img.getAttribute('src') === '/api/render?path=' + encodeURIComponent(cur.shown) + (cur.page ? '&page=' + cur.page : '')) go();
    else pendingDraw = go;
  }
  renderEvidence();
  if (!PHONE.matches && seq === askSeq) {  // bring the answer card up under the question box (desktop side panel)
    const side = $('#side');
    side.scrollTo({top: Math.max(0, a.getBoundingClientRect().top - side.getBoundingClientRect().top + side.scrollTop - $('.ask').offsetHeight - 16), behavior: 'smooth'});
  }
}
$('#go').onclick = ask; $('#q').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.isComposing) ask(); });

function setupEvidence() {
  const ev = res.evidence || [];
  const flat = ev.filter(e => e.kind === 'box' || e.kind === 'polygon' || e.kind === 'text');
  // which file and page do the 2D items refer to? (multi-page PDFs: the page the answer was read on)
  const files = {}; for (const e of flat) if (e.file) files[e.file] = (files[e.file] || 0) + 1;
  const evFile = Object.keys(files).sort((x, y) => files[y] - files[x])[0];
  const pages = {}; for (const e of flat) if (!e.file || !evFile || e.file === evFile) pages[e.page || 0] = (pages[e.page || 0] || 0) + 1;
  const top = Object.keys(pages).sort((x, y) => pages[y] - pages[x])[0];
  const evPage = top != null ? +top : (cur.pin ?? res.page ?? cur.page ?? 0);
  const two = ev.filter(e => (e.kind === 'box' || e.kind === 'polygon') && (e.page || 0) === evPage);
  const txt = ev.filter(e => e.kind === 'text' && (e.page || 0) === evPage);
  const three = ev.filter(e => e.kind === 'ifc');
  primary = three.length && has3d ? 'ifc' : '2d';
  if (((evFile && evFile !== cur.shown) || evPage !== (cur.page || 0)) && /\.(pdf|png|jpe?g)$/i.test(evFile || cur.shown || '')) showImage(evFile || cur.shown, evPage);
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

function zoomToEvidence(only, maxK = 3) {  // cap: keep enough of the plan around one or two small items for context
  const all = (only || [...items, ...marks]).filter(e => e.kind !== 'ifc' && (e.points || e.bbox));
  if (!all.length || !img.naturalWidth) { fit(); return; }
  let x0 = 1, y0 = 1, x1 = 0, y1 = 0;
  for (const e of all) {
    const pts = e.points || [[e.bbox[0], e.bbox[1]], [e.bbox[2], e.bbox[3]]];
    for (const [x, y] of pts) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
  }
  const W = viewer.clientWidth, H = viewer.clientHeight - 20, w = img.naturalWidth, h = img.naturalHeight;
  const pad = only ? 0.12 : 0.04; x0 = Math.max(0, x0 - pad); y0 = Math.max(0, y0 - pad); x1 = Math.min(1, x1 + pad); y1 = Math.min(1, y1 + pad);
  const fitS = Math.min(W / w, H / h) * 0.97;
  const s = Math.min(W / ((x1 - x0) * w), H / ((y1 - y0) * h));
  view.s = Math.max(fitS, Math.min(s, fitS * maxK)); view.x = W / 2 - (x0 + x1) / 2 * w * view.s; view.y = H / 2 - (y0 + y1) / 2 * h * view.s;
  stage.style.transition = 'transform .6s cubic-bezier(.2,.8,.2,1)'; apply(); setTimeout(() => stage.style.transition = '', 620);
}

// round half away from zero with a small epsilon, so 24.575 (stored as 24.57499…) and a sum that lands on 24.5750001
// both show 24.58: the headline and the evidence total must never differ by a rounding artefact
const round2 = v => { const x = +v, k = Math.round((Math.abs(x) + 1e-9) * 100) / 100; return (x < 0 ? -k : k).toFixed(2); };
const fmt = (v, t) => v == null ? '—' : (t === 'count' ? Math.round(v) : round2(v));
const unitOf = t => ({area: 'm²', length: 'm', volume: 'm³', count: ''}[t] || '');
const latency = s => s == null ? '' : s < 0.001 ? '&lt; 1 ms' : s < 1 ? (s * 1000).toFixed(0) + ' ms' : s.toFixed(1) + ' s';
const money = v => v === 0 ? '$0' : v < 0.001 ? '$' + v.toFixed(5) : v < 1 ? '$' + v.toFixed(3) : '$' + v.toFixed(2);

// how was this answer made? one badge + one line, so a judge knows what to trust and how to check it
function howOf(r) {
  const m = String(r.method || ''), paid = (r.cost_usd || 0) > 0;
  if (r.answer == null && /does not look like a construction drawing/.test(String(r.explanation || ''))) return {cls: 'none', t: 'Not a drawing', how: 'the file was checked before any counting and declined; nothing was guessed'};
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

// ------------------------------------------------------------ honest confidence, "why" trace, frontier side-by-side
const nf = n => Number(n).toLocaleString('en-US');
function pctOf(right, n) {  // never round up to 100 % unless every one was right
  if (right === n) return '100';
  const p = Math.floor(1000 * right / n) / 10;
  return p >= 99.9 ? (Math.floor(10000 * right / n) / 100).toFixed(2) : p.toFixed(1);
}
function calibHTML(r) {
  if (r.answer == null) {
    const m = String(r.method || ''), e = String(r.explanation || '');
    const nd = e.match(/[^|]*does not look like a construction drawing[^|]*/);
    if (nd) return `<div class="calib none"><b>Why no answer</b><span>${esc(nd[0].trim().replace(/^./, c => c.toUpperCase()))}. Upload a plan, section or elevation (PDF, image, DXF or IFC) to ask about it.</span></div>`;
    const why = r.budget_exhausted ? 'the daily budget for paid model calls is used up'
      : m === 'timeout' ? 'the solver ran out of time; it stops rather than guess'
      : /error/.test(m) ? 'the solver failed on this input; it reports that rather than a number'
      : /not understood|not recognised|no room label|not found/.test(e) ? 'the question is outside what the solver can check on this drawing'
      : /-na$|-none$/.test(m) || /no .* values|not in the/.test(e) ? 'the file does not contain what the question asks for'
      : 'the evidence was not good enough';
    return `<div class="calib none"><b>Why no answer</b><span>${esc(why)}. A wrong number on a drawing costs more than an honest “not sure”, so we abstain.</span></div>`;
  }
  const c = r.calibration;
  if (!c) return '';
  const conf = Math.round(100 * (r.confidence ?? 0));
  if (!c.measured) {
    // deterministic routes (IFC / CAD geometry, the trained detector) compute rather than guess: say what the method did
    // on our test files, and that this file is new to us, instead of calling the confidence "the model's own guess"
    const d = r.calibration_dataset, m = String(r.method || '');
    const fixed = /^(swiss|ifc(?!text)|cubicasa|dxf|cad)/.test(m) || howOf(r).cls === 'geo';
    if (d && d.family_n && (fixed || /^cubicasa/.test(m))) {
      const what = /^ifc/.test(m) ? 'test IFC models' : /^cubicasa/.test(m) ? 'held-out test plans' : 'held-out test drawings';
      return `<div class="calib unk"><b>New file: no track record on it yet</b><span>this method (${esc(d.label)}) was ${nf(d.family_right)}/${nf(d.family_n)} right on our ${what}; your file is new to us, so check the evidence before relying on it.</span></div>`;
    }
    if (fixed) return `<div class="calib unk"><b>New file: no track record on it yet</b><span>this answer is computed from the file's own geometry by fixed rules (no AI guess), but files like yours were not part of our test: check the listed items before relying on it.</span></div>`;
    return `<div class="calib unk"><b>No track record yet</b><span>answers made this way were not part of our test, so the ${conf} % is the model's own guess: check the evidence before relying on it.</span></div>`;
  }
  const p = c.right / c.n, cls = p >= 0.95 ? 'hi' : p >= 0.85 ? 'mid' : p >= 0.6 ? 'lo' : 'bad';
  const word = p >= 0.95 ? 'Very likely right' : p >= 0.85 ? 'Usually right' : p >= 0.6 ? 'Often right: check the evidence' : 'Uncertain: check the evidence';
  const band = c.scope === 'bin' ? `, confidence ${Math.round(c.lo * 100)}–${Math.round(c.hi * 100)} %` : '';
  const tally = c.right === c.n ? `all ${nf(c.n)}` : `${nf(c.right)} of ${nf(c.n)}`;
  return `<div class="calib ${cls}" title="Track record on the full held-out test split: ${esc(c.label)}${band}; this answer's own confidence: ${conf} %. ${nf(c.family_n)} questions were answered this way, ${pctOf(c.family_right, c.family_n)} % right overall.">
    <div class="cbar"><i style="width:${(100 * p).toFixed(1)}%"></i></div>
    <b>${word} · ${pctOf(c.right, c.n)} %</b>
    <span>${tally} similar answers were right on test drawings we never trained on</span></div>`;
}
let traceOpen = false;
function traceHTML(r) {
  const t = r.trace; if (!t) return '';
  const u = unitOf(r.type);
  const sec = (h, body) => body ? `<div class="tsec"><h4>${h}</h4>${body}</div>` : '';
  const route = (t.route || []).map(x => `<div><span class="pill">${esc(ROUTE[x.solver] || x.solver)}</span> ${esc(x.why)}</div>`).join('');
  const read = (t.read || []).map(x => `<li>${esc(x)}</li>`).join('');
  const a = t.arith;
  const corrected = typeof r.answer === 'number' && items.some(e => !e.on || e.added);
  const cv = corrected ? items.filter(e => e.on).reduce((s, e) => s + (e.value ?? 1), 0) : null;
  const arith = a ? `${corrected ? '<div class="mut">before your correction:</div>' : ''}<div class="mono">${esc(a.expr)} = <b>${fmt(a.total, r.type)}${u ? ' ' + u : ''}</b></div>
    <div class="${a.matches ? 'okt' : 'mut'}">${a.matches ? `✓ the ${a.n} items listed under Evidence add up to the answer exactly` : 'the answer is not a plain sum of the listed items (it also weighs how likely each count is)'}</div>`
    + (corrected ? `<div class="mono">after your correction: ${items.filter(e => e.on).length} item${items.filter(e => e.on).length === 1 ? '' : 's'} = <b>${fmt(cv, r.type)}${u ? ' ' + u : ''}</b></div>` : '') : '';
  const ex = String(r.explanation || '').replace(/^(read as: [^|]*\| ?)+/, '').trim();  // "read as" is shown under the question
  const note = ex && !(t.read || []).some(x => String(x).includes(ex)) ? `<div>${esc(ex)}</div>` : '';
  const cost = `<div>${money(r.cost_usd || 0)} · ${latency(r.latency_s)} · ${esc(t.model_call)}${t.method ? ` · <code>${esc(t.method)}</code>` : ''}</div>`;
  return `<details class="trace" ${traceOpen ? 'open' : ''}><summary>Why this answer</summary>
    ${sec('1 · Route', route)}${sec('2 · What it read', read ? `<ul>${read}</ul>${r.answer == null ? note : ''}` : note)}${sec('3 · Arithmetic', arith)}${sec('4 · Cost and time', cost)}</details>`;
}
function predTxt(f, t) {
  if (f.pred == null || f.pred === '') return '<i>no answer</i>';
  const n = Number(f.pred);
  if (t !== 'text' && Number.isFinite(n)) return fmt(n, t);
  const s = String(f.pred); return esc(s.length > 40 ? s.slice(0, 38) + '…' : s);
}
function frontierHTML(r, oursOk) {
  const fr = r.frontier || []; if (!fr.length || r.answer == null) return '';
  const mark = ok => ok === true ? '<span class="okt">✓</span>' : ok === false ? '<span class="badt">✗</span>' : '<span class="mut" title="free-text answer not judged">?</span>';
  const ours = typeof r.answer === 'number' ? fmt(r.answer, r.type) : esc(String(r.answer).slice(0, 38));
  const text = typeof r.answer !== 'number';
  const ansCell = f => text ? '' : `<td class="num">${predTxt(f, r.type)}</td>`;
  const sub = f => text ? `<small class="said">${f.pred == null || f.pred === '' ? '<i>no answer</i>' : '“' + esc(String(f.pred).replace(/\s+/g, ' ').slice(0, 90)) + (String(f.pred).length > 90 ? '…' : '') + '”'}</small>` : '';
  const rows = fr.map(f => `<tr><td>${esc(f.model)}<small>${esc(f.setting)}</small>${sub(f)}</td>${ansCell(f)}<td>${mark(f.correct)}</td><td class="num">${money(f.cost_usd || 0)}</td><td class="num">${f.latency_s ? f.latency_s.toFixed(1) + ' s' : ''}</td></tr>`).join('');
  const wrong = fr.filter(f => f.correct === false).length;
  return `<div class="vs"><div class="vshead">Same question, asked to frontier models${wrong ? ` · <span class="badt">${wrong} of ${fr.length} wrong</span>` : ''}</div>
    <table><tr class="us"><td>Blueprints that talk<small>${text ? 'answer above, with the facts it cites' : 'evidence on the drawing'}</small></td>${text ? '' : `<td class="num"><b>${ours}</b></td>`}<td>${mark(oursOk)}</td><td class="num"><b>${money(r.cost_usd || 0)}</b></td><td class="num">${latency(r.latency_s)}</td></tr>${rows}</table>
    <div class="vsnote">From our baseline run on a 400-question sample of the same held-out test split${text ? '; free-text answers were scored by an LLM judge against the reference' : `; the gold answer is ${fmt(r.gold, r.type)}${r.type !== 'count' ? ' ' + unitOf(r.type) : ''}`}.</div></div>`;
}

// ghost comparison: our number against what each frontier model answered on the same drawing, on one 0-based scale,
// with the dataset answer as a rule across it; during the X-ray count our marker slides up past the ghosts
const shortModel = f => String(f.model || '').replace(/^Claude /, '').split(' ').slice(0, 3).join(' ').replace(/ Super\b.*$/, '')
  + (/files|CAD|IFC/i.test(f.setting || '') ? ' + files' : '');
function ghostHTML(r, val, counting) {
  const fr = (r.frontier || []).map(f => ({...f, v: f.pred == null || f.pred === '' ? NaN : Number(f.pred)}));
  if (!fr.some(f => Number.isFinite(f.v))) return '';
  const t = r.type, ref = typeof r.gold === 'number' ? r.gold : r.answer;
  const vals = [ref, r.answer, ...fr.filter(f => Number.isFinite(f.v)).map(f => f.v)];
  const span = Math.max(...vals) - Math.min(...vals), pad = Math.max(span * 0.12, t === 'count' ? 1 : 0.5);
  const lo = Math.max(0, Math.min(...vals) - pad), hi = Math.max(...vals) + pad;  // zoomed to the answers: the gaps are the story
  const x = v => Math.max(0, Math.min(100, 100 * (v - lo) / (hi - lo))).toFixed(2) + '%';
  const delta = v => {
    const d = v - ref, ok = t === 'count' ? Math.round(v) === Math.round(ref) : Math.abs(d) <= 0.02 * Math.abs(ref);
    return ok ? '<span class="okt">✓ right</span>' : `${d < 0 ? '−' : '+'}${fmt(Math.abs(d), t)} ${d < 0 ? 'short' : 'over'}`;
  };
  const row = (name, v, cls, tip) => {
    const ok = Number.isFinite(v), a = ok ? Math.min(v, ref) : 0, b = ok ? Math.max(v, ref) : 0;
    return `<div class="gr ${cls}" title="${esc(tip)}"><span class="gn">${esc(name)}</span><span class="gt"><i class="gref" style="left:${x(ref)}"></i>`
      + (ok ? `<i class="gl ${v < ref ? 'short' : 'over'}" style="left:${x(a)};width:calc(${x(b)} - ${x(a)})"></i><i class="gd" style="left:${x(v)}"></i>` : '')
      + `</span><span class="gv">${ok ? `<b>${fmt(v, t)}</b> ${cls === 'us' && counting ? '' : delta(v)}` : '<i>no answer</i>'}</span></div>`;
  };
  const us = row('Ours', val, 'us', 'Blueprints that talk: counted out on the drawing');
  const rows = fr.map(f => row(shortModel(f), f.v, 'ghost', `${f.model} · ${f.setting}: answered ${f.pred ?? 'nothing'}`)).join('');
  return `<div class="ghostcmp" data-lo="${lo}" data-hi="${hi}" data-ref="${ref}">
    <div class="gh"><span>Frontier models, same drawing</span><span class="gref">${typeof r.gold === 'number' ? 'dataset answer' : 'our answer'} <b>${fmt(ref, t)}${t === 'count' ? '' : ' ' + unitOf(t)}</b></span></div>
    <div class="gbody">${us}${rows}</div></div>`;
}
function ghostMove(a, val) {  // mid-count: slide our marker and its gap to the dataset answer
  const g = a.querySelector('.ghostcmp'); if (!g) return;
  const lo = +g.dataset.lo, hi = +g.dataset.hi, ref = +g.dataset.ref, x = v => Math.max(0, Math.min(100, 100 * (v - lo) / (hi - lo))).toFixed(2) + '%';
  const r = g.querySelector('.gr.us'); if (!r) return;
  const gt = r.querySelector('.gt'), a0 = Math.min(val, ref), up = Math.max(val, ref);
  gt.innerHTML = `<i class="gref" style="left:${x(ref)}"></i><i class="gl ${val < ref ? 'short' : 'over'}" style="left:${x(a0)};width:calc(${x(up)} - ${x(a0)})"></i><i class="gd" style="left:${x(val)}"></i>`;
  r.querySelector('.gv').innerHTML = `<b>${fmt(val, res.type)}</b>`;
}

function renderAnswer(shownSoFar) {
  if (!res) return;
  const a = $('#answer'); const t = res.type;
  const counting = shownSoFar !== null && items.length && typeof res.answer === 'number';
  let val = res.answer;
  if (counting) val = items.slice(0, shownSoFar).reduce((s, e) => s + (e.value ?? 1), 0);
  // a correction (items dropped / added) changes the headline number too; the line under it keeps the solver's value
  else if (typeof val === 'number' && items.some(e => !e.on || e.added)) val = items.filter(e => e.on).reduce((s, e) => s + (e.value ?? 1), 0);
  if (counting && a.dataset.xseq === String(res._seq) && a.querySelector('.big.counting .bn')) {  // mid-count: only the number moves
    a.querySelector('.big.counting .bn').textContent = fmt(val, t);
    ghostMove(a, val);
    return;
  }
  if (counting) a.dataset.xseq = res._seq; else delete a.dataset.xseq;
  const conf = res.confidence ?? 0;
  const confCls = conf >= 0.8 ? 'ok' : conf >= 0.5 ? 'warn' : 'bad';
  let gold = '', oursOk = null;
  if (res.gold != null && res.answer != null && typeof res.gold === 'number') {
    const g = +res.gold, p = +res.answer;
    oursOk = t === 'count' ? Math.round(p) === Math.round(g) : Math.abs(p - g) <= 0.02 * Math.abs(g);
    // after a correction the headline is the user's number, not the solver's: say plainly what the badge compares
    const corrected = items.some(e => !e.on || e.added);
    if (!counting) gold = corrected ? `<span class="pill">dataset answer: ${fmt(g, t)} (${oursOk ? 'matches' : 'differs from'} the solver's answer)</span>`
      : `<span class="pill ${oursOk ? 'ok' : 'bad'}">${oursOk ? '✓ matches' : '✗ differs from'} the dataset answer ${fmt(g, t)}</span>`;
  }
  const hasVs = (res.frontier || []).length && res.answer != null;
  const abst = res.answer == null;
  const num = typeof res.answer === 'number';
  const baseS = res.baseline_latency_s || 8;
  a.innerHTML = `
    <div class="qecho">${esc(res.question)}</div>
    ${res.normalized_question && res.normalized_question !== res.question ? `<div class="readas" style="order:1;font-size:12px;color:var(--mut);margin:-2px 0 6px">read as: <i>${esc(res.normalized_question)}</i></div>` : ''}
    ${typeof res.answer === 'string' ? '' : `<div class="big ${abst ? 'abstain' : ''} ${counting ? 'counting' : ''}">${abst ? 'Not sure, so no guess' : num ? `<span class="bn">${fmt(val, t)}</span>` : ''} <small>${abst ? '' : unitOf(t)}</small></div>`}
    ${typeof res.answer === 'string' ? `<div class="textans">${esc(res.answer.trim().split('\n').map(l => l.replace(/^\s{1,4}(?=\S)/, '')).join('\n'))}</div>` : ''}
    ${(() => { const h = howOf(res); if (num && res.answer === 0 && !items.length && h.cls !== 'geo') h.how = 'it found nothing to box, so there is nothing to check on the drawing: look at the plan yourself before relying on 0'; return `<div class="how ${h.cls}"><b>${h.cls === 'geo' ? '✓ ' : ''}${esc(h.t)}</b><span>${esc(h.how)}</span></div>`; })()}
    ${res.rule ? `<div class="rule"><b>Rule</b> ${esc(res.rule)}</div>` : ''}
    ${crossHTML(res)}
    ${calibHTML(res)}
    ${hasVs && num ? ghostHTML(res, val, counting) : ''}
    ${!res.trace ? `<div class="expl">${esc(res.explanation || '')}</div>` : ''}
    <div class="row">${abst || res.calibration ? '' : `<span class="pill ${confCls}">confidence ${(conf * 100).toFixed(0)}%</span>`}
      ${gold}</div>
    <div class="corr" id="corr"></div>
    ${hasVs ? frontierHTML(res, oursOk) : ''}
    ${traceHTML(res)}
    ${abst ? '' : signHTML(res)}
    <div class="costcmp" ${hasVs || (abst && cur.not_drawing) ? 'hidden' : ''}>
      <span class="lab">this answer</span><span><span class="mbar" style="display:block"><i style="width:${Math.max(0.5, 100 * (res.cost_usd || 0) / Math.max(res.baseline_cost_usd || 1e-9, res.cost_usd || 0))}%"></i></span></span>
      <span class="v"><b>${money(res.cost_usd || 0)}</b> · ${latency(res.latency_s)}</span>
      <span class="lab">frontier model</span><span><span class="mbar" style="display:block"><i class="base" style="width:100%"></i></span></span>
      <span class="v">~${money(res.baseline_cost_usd || 0)} · ~${baseS.toFixed(0)} s</span>
    </div>`;
  const d = a.querySelector('details.trace'); if (d) d.ontoggle = () => { traceOpen = d.open; };
  wireAnswerActions(a);
  if (!counting) recompute();
}

// ------------------------------------------------------------ cross-check (a second, independent method), when the router sends one
let showSecond = false;
function crossHTML(r) {
  const c = r.crosscheck; if (!c || !c.status || c.status === 'single' || r.answer == null) return '';
  const sec = c.second || {}, t = r.type;
  const n2 = (sec.evidence || []).filter(e => e.bbox || e.points).length;
  const btn = n2 ? `<button class="linkish" data-act="second">${showSecond ? 'hide' : 'show'} its ${n2} mark${n2 === 1 ? '' : 's'}</button>` : '';
  const val = v => typeof v === 'number' ? fmt(v, t) : esc(String(v ?? '—'));
  // plain-language name of the second method, and what agreement has meant on held-out test questions
  // (runs/crosscheck_vlm_test.summary.md, runs/crosscheck_test.summary.md)
  const m = String(sec.method || '');
  const [name, track] = /VLM/i.test(m) ? ['Our fine-tuned vision model', 'When both agree, answers were right 94.6 % of the time (12,153 held-out raster questions).']
    : /swiss|pdf/i.test(m) ? ['Reading the PDF itself (not the CAD file)', 'When both agree, answers were right 99.97 % of the time on held-out Swiss plans (7,750 of 7,752).']
    : /svg|sheet|ifc/i.test(m) ? ['The rendered plan sheet', 'When both agree, answers were right on all 432 held-out IFC questions.']
    : /yolo|cubicasa/i.test(m) ? ['A second, separately trained detector', '']
    : [esc(ROUTE[m.split('-')[0]] || m || 'A second method'), ''];
  const tip = c.note ? ` title="${esc(c.note)}"` : '';
  if (c.status === 'agree') return `<div class="xcheck agree"${tip}><b>✓ Two independent methods agree</b><span>${name} also says ${val(sec.answer)}. ${track} ${btn}</span></div>`;
  return `<div class="xcheck conflict"${tip}><b>⚠ Conflict: ${val(r.answer)} vs ${val(sec.answer)}</b><span>${name} disagrees, so confidence is halved: check the evidence before using this number. ${btn}</span></div>`;
}
function secondMarks() {
  const ev = (showSecond && res && res.crosscheck && res.crosscheck.second && res.crosscheck.second.evidence) || [];
  return ev.filter(e => (e.bbox || e.points) && (!e.file || e.file === cur.shown)).map(e => ({...e, mark: true, second: true}));
}

// ------------------------------------------------------------ sign-off and takeoff export
// every answered question this session is a takeoff row; a reviewer can mark it checked (initials + time).
const TAKEOFF_KEY = 'bp_takeoff';
let takeoff = JSON.parse(localStorage.getItem(TAKEOFF_KEY) || '[]');
const rowKey = (path, q) => path + '\u0000' + q;
function saveTakeoff() { localStorage.setItem(TAKEOFF_KEY, JSON.stringify(takeoff.slice(-500))); }
function takeoffRow(r) { return takeoff.find(x => x.key === rowKey(cur.path, r.question)); }
function recordTakeoff(r) {
  if (!cur || r.answer == null) return;
  const key = rowKey(cur.path, r.question);
  let row = takeoff.find(x => x.key === key);
  if (!row) { row = {key}; takeoff.push(row); }
  Object.assign(row, {drawing: cur.path, question: r.question, answer: r.answer, unit: unitOf(r.type), type: r.type,
    method: r.method, confidence: r.confidence, track_record: r.calibration && r.calibration.measured ? +(100 * r.calibration.right / r.calibration.n).toFixed(2) : '',
    rule: r.rule || '', credit: $('#credit').textContent.replace(/^© /, ''), cost_usd: r.cost_usd || 0, asked_at: new Date().toISOString()});
  saveTakeoff();
}
function signHTML(r) {
  const row = takeoffRow(r), n = takeoff.length;
  const signed = row && row.signed_by ? `<span class="signed">✓ checked by ${esc(row.signed_by)} · ${new Date(row.signed_at).toLocaleString([], {dateStyle: 'short', timeStyle: 'short'})}</span>
    <button class="linkish" data-act="unsign">undo</button>` : `<button class="btn ghost" data-act="sign">✓ Mark as checked</button>`;
  return `<div class="signrow">${signed}<span class="grow"></span>
    <button class="btn ghost" data-act="csv" title="Download every answer of this session as a CSV takeoff">⬇ Takeoff CSV${n ? ` (${n})` : ''}</button></div>`;
}
function wireAnswerActions(a) {
  a.querySelectorAll('[data-act]').forEach(b => b.onclick = ev => { ev.stopPropagation(); answerAction(b.dataset.act, b); });
}
async function answerAction(act, b) {
  if (act === 'second') { showSecond = !showSecond; draw(false); renderAnswer(null); return; }
  if (act === 'csv') { exportTakeoff(); return; }
  const row = takeoffRow(res); if (!row) return;
  if (act === 'unsign') { delete row.signed_by; delete row.signed_at; saveTakeoff(); renderAnswer(null); return; }
  if (act === 'sign') {  // inline initials field instead of a prompt() box
    const wrap = b.parentElement;
    wrap.innerHTML = `<input class="initials" maxlength="40" placeholder="your initials" value="${esc(localStorage.getItem('bp_initials') || '')}" aria-label="Your initials">
      <button class="btn" data-act="signok">Sign</button><button class="linkish" data-act="signcancel">cancel</button>`;
    wireAnswerActions(wrap);
    const inp = wrap.querySelector('input'); inp.focus(); inp.select();
    inp.onkeydown = e => { e.stopPropagation(); if (e.key === 'Enter') answerAction('signok'); if (e.key === 'Escape') renderAnswer(null); };
    return;
  }
  if (act === 'signcancel') { renderAnswer(null); return; }
  if (act === 'signok') {
    const who = ($('#answer .initials')?.value || '').trim().slice(0, 40); if (!who) return;
    localStorage.setItem('bp_initials', who);
    const corr = currentCorrection();
    Object.assign(row, {signed_by: who, signed_at: new Date().toISOString(), corrected: corr == null ? '' : corr});
    saveTakeoff(); renderAnswer(null);
    fetch('/api/signoff', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
      path: cur.path, question: res.question, question_id: res.question_id ?? null, answer: res.answer, corrected_answer: corr,
      method: res.method, confidence: res.confidence, initials: who, session: FB_SESSION})}).catch(() => {});
  }
}
function currentCorrection() {
  if (!res || typeof res.answer !== 'number' || !items.some(e => !e.on || e.added)) return null;
  return +items.filter(e => e.on).reduce((s, e) => s + (e.value ?? 1), 0).toFixed(3);
}
function exportTakeoff() {
  const cols = ['drawing', 'question', 'answer', 'unit', 'corrected', 'method', 'confidence', 'track_record', 'rule', 'cost_usd', 'signed_by', 'signed_at', 'asked_at', 'credit'];
  const head = ['drawing', 'question', 'answer', 'unit', 'corrected value', 'method', 'confidence %', 'track record % (held-out test)', 'counting rule', 'cost USD', 'checked by', 'checked at', 'asked at', 'drawing credit'];
  const cell = v => { const t = String(v ?? ''); return /[",\n;]/.test(t) ? '"' + t.replace(/"/g, '""') + '"' : t; };
  const show = (r, c) => {  // an upload is named by its file name, not its server folder; confidence as % like the track record
    if (c === 'drawing' && String(r.drawing || '').startsWith('uploads/')) return String(r.drawing).split('/').pop();
    if (c === 'confidence' && typeof r.confidence === 'number') return +(100 * r.confidence).toFixed(1);
    return typeof r[c] === 'string' ? r[c].replace(/\s+/g, ' ') : r[c];
  };
  const csv = [head.join(','), ...takeoff.map(r => cols.map(c => cell(show(r, c))).join(','))].join('\r\n');
  const url = URL.createObjectURL(new Blob(['\ufeff' + csv], {type: 'text/csv;charset=utf-8'}));
  const link = document.createElement('a'); link.href = url; link.download = `takeoff-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, '')}.csv`;
  document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function updateMeter() {
  const mx = Math.max(session.base, session.ours, 1e-9);
  $('#m-ours').textContent = money(session.ours); $('#m-base').textContent = money(session.base);
  $('#bar-ours').style.width = (100 * session.ours / mx) + '%'; $('#bar-base').style.width = (100 * session.base / mx) + '%';
  const saved = session.base > 0 ? 100 * (1 - session.ours / session.base) : 0;
  $('#m-sum').innerHTML = `<span class="only-desk">${session.n} question${session.n === 1 ? '' : 's'} · </span>` + (saved >= 0
    ? (session.ours > 0 ? `<b>${saved >= 99.95 ? '>99.9' : saved.toFixed(1)}% cheaper</b> (${(session.base / session.ours).toFixed(0)}×)`
      : '<b>no model cost</b>')
    : `${(-saved).toFixed(0)}% dearer`);
  $('#meter').dataset.n = session.n;
  $('#meter').dataset.short = `this session: ours ${money(session.ours)} vs frontier ${money(session.base)}`;
}

// ------------------------------------------------------------ evidence overlay
const PHONE = matchMedia('(max-width: 860px)');
const pgLabelY = (cy, by, fs) => Math.max(cy + fs * 2.4, by - fs * 0.9);
const pgBadgeY = (cy, ty, fs) => Math.max(ty + fs * 1.1, cy - fs * 2.4);
function labelSize() { return (PHONE.matches ? 11 : 14) / view.s; }
// where the drawing's own printed text sits (PDF words, normalised boxes): numbers and m² labels keep off it
let words = {key: '', boxes: []};
function loadWords(file, page) {
  const key = file + '#' + page; if (words.key === key) return;
  words = {key, boxes: []};
  if (!/\.pdf$/i.test(file)) return;
  fetch('/api/words?path=' + encodeURIComponent(file) + '&page=' + page).then(r => r.ok ? r.json() : null)
    .then(d => { if (d && words.key === key && d.boxes?.length) { words.boxes = d.boxes; rescaleLabels(); } }).catch(() => {});
}
// Place every number badge and m² label (in image pixels, for the current zoom): each one tries a few spots
// around what it marks and takes the one that covers the least of the other badges, the printed text and the
// other evidence; a badge pushed away from its box gets a thin leader line back to it.
let lay = new Map();
const ovl = (a, b) => Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
function layoutLabels(W, H, fs) {
  const out = new Map(), placed = [];
  const px = b => [b[0] * W, b[1] * H, b[2] * W, b[3] * H];
  const text = [...words.boxes.map(px), ...marks.filter(m => m.kind === 'text' && m.bbox).map(m => px(m.bbox))];
  const boxes = items.map(e => e.kind === 'box' && e.bbox ? px(e.bbox) : null);
  const pick = (cands, hw, hh, own, i) => {
    const reach = 2 * (hw + hh) + 6 * fs, ox = (own[0] + own[2]) / 2, oy = (own[1] + own[3]) / 2;
    const zone = [own[0] - reach, own[1] - reach, own[2] + reach, own[3] + reach];
    const near = text.filter(t => ovl(t, zone) > 0), nearBx = boxes.filter((b, j) => b && j !== i && ovl(b, zone) > 0);
    const nearPl = placed.filter(p => ovl(p, zone) > 0);
    let best = null;
    cands.forEach((c, k) => {
      const R = [c.x - hw, c.y - hh, c.x + hw, c.y + hh], A = 4 * hw * hh;
      let cost = (c.ring || 0) * 0.45 + k * 0.01 + (c.extra || 0);
      for (const p of nearPl) cost += 8 * ovl(R, p) / A;
      for (const t of near) cost += 2.5 * ovl(R, t) / A;
      for (const b of nearBx) cost += 0.6 * ovl(R, b) / A;
      if (c.ring != null) cost += ovl(R, own) / A;  // a box's number sits beside it, not on what it marks
      cost += 4 * (1 - ovl(R, [0, 0, W, H]) / A);
      if (!best || cost < best.cost - 1e-9) best = {...c, cost};
    });
    placed.push([best.x - hw, best.y - hh, best.x + hw, best.y + hh]);
    return best;
  };
  items.forEach((e, i) => {
    if (e.kind === 'ifc' || (!e.bbox && !e.points)) return;
    if (e.kind === 'polygon') {
      const xs = e.points.map(p => p[0] * W), ys = e.points.map(p => p[1] * H);
      const x0 = Math.min(...xs), x1 = Math.max(...xs), ty = Math.min(...ys), by = Math.max(...ys), cx = (x0 + x1) / 2, cy = (ty + by) / 2;
      const own = [x0, ty, x1, by];
      if (numbered(e)) {  // a room's printed name and number sit at its centre: its number badge goes above them, inside
        const r = fs * 0.85, q = (x1 - x0) / 4;
        const c = [pgBadgeY(cy, ty, fs), ty + fs * 1.1, cy - fs * 1.2, by - fs * 1.1].flatMap(y => [cx, cx - q, cx + q].map((x, j) => ({x, y, extra: j ? 0.1 : 0})));
        out.set(i, {...pick(c, r, r, own, i), lead: null});
      } else if (e.on && e.value != null && res.type !== 'count') {  // the m²: near the room's bottom edge, off its printed name
        const hw = (round2(e.value) + ' m²').length * fs * 0.3 + fs * 0.15, hh = fs * 0.55, sh = fs * 0.33;  // sh: baseline to centre
        const yl = [pgLabelY(cy, by, fs), by - fs * 0.9, ty + fs * 1.6, cy + fs * 1.4, cy - fs * 1.6];
        const xl = [cx, x0 + hw + fs * 0.4, x1 - hw - fs * 0.4];
        const c = yl.flatMap(y => xl.map((x, j) => ({x, y: y - sh, extra: j ? 0.1 : 0})));
        c.push({x: cx, y: by + fs * 0.9 - sh, extra: 1.2}, {x: cx, y: ty - fs * 0.4 - sh, extra: 1.2});  // just outside: a last resort
        const b = pick(c, hw, hh, own, i); out.set(i, {x: b.x, y: b.y + sh});
      }
      return;
    }
    if (!numbered(e)) return;
    const [x0, y0, x1, y1] = px(e.bbox), mx = (x0 + x1) / 2, my = (y0 + y1) / 2, r = fs * 0.8, d = r * 0.78;
    // spots around the box: its corners and edge midpoints, touching it (ring 0), then further out (with a leader)
    const dirs = [[x0, y0, -1, -1], [x1, y0, 1, -1], [x0, y1, -1, 1], [x1, y1, 1, 1], [mx, y0, 0, -1], [mx, y1, 0, 1], [x0, my, -1, 0], [x1, my, 1, 0]];
    if (y1 - y0 < fs * 2.2) dirs.unshift(dirs.splice(6, 1)[0]);  // a thin box (a wall, a door in plan): its left end first
    const c = [];
    for (const ring of [0, 1, 2, 3]) for (const [ax, ay, dx, dy] of dirs) {
      const k = (dx && dy ? d : r * 1.05) + ring * r * 1.9;
      c.push({x: ax + dx * k, y: ay + dy * k, ring});
    }
    const b = pick(c, r * 0.95, r * 0.95, [x0, y0, x1, y1], i);
    out.set(i, {x: b.x, y: b.y, lead: b.ring ? [Math.min(x1, Math.max(x0, b.x)), Math.min(y1, Math.max(y0, b.y))] : null});
  });
  return out;
}
function placeLabels(g, p, fs) {
  if (!p) return;
  const bg = g.querySelector('.badgebg'), t = g.querySelector('text.badge'), pl = g.querySelector('text.pglabel'), ln = ov.querySelector(`line.leader[data-i="${g.dataset.i}"]`);
  if (bg) {
    if (bg.tagName === 'circle') { bg.setAttribute('cx', p.x); bg.setAttribute('cy', p.y); bg.setAttribute('r', fs * 0.78); }
    else { const h = fs * 0.72; bg.setAttribute('x', p.x - h); bg.setAttribute('y', p.y - h); bg.setAttribute('width', 2 * h); bg.setAttribute('height', 2 * h); bg.setAttribute('rx', h * 0.15); }
  }
  if (t) { t.setAttribute('x', p.x); t.setAttribute('y', p.y); t.style.fontSize = (t.textContent.length > 2 ? fs * 0.62 : fs * 0.82) + 'px'; }
  if (pl) { pl.setAttribute('x', p.x); pl.setAttribute('y', p.y); pl.style.fontSize = fs + 'px'; }
  if (ln) {
    ln.style.display = p.lead ? '' : 'none';
    if (p.lead) { ln.setAttribute('x1', p.x); ln.setAttribute('y1', p.y); ln.setAttribute('x2', p.lead[0]); ln.setAttribute('y2', p.lead[1]); }
  }
}
// the stage is a will-change layer: Chrome keeps the raster it made at the old scale, so the numbers would blur
// to specks when zoomed in. Once the zoom settles, drop the hint for a frame so the layer is redrawn at the new scale.
let reraster = 0;
function sharpen() {
  clearTimeout(reraster);
  reraster = setTimeout(() => { stage.style.willChange = 'auto'; requestAnimationFrame(() => requestAnimationFrame(() => { stage.style.willChange = ''; })); }, 160);
}
function rescaleLabels() {
  sharpen();
  if (mode === '3d' || !img.naturalWidth || !items.length) return;
  const fs = labelSize(); lay = layoutLabels(img.naturalWidth, img.naturalHeight, fs);
  ov.querySelectorAll('g[data-i]').forEach(g => { if (+g.dataset.i >= 0) placeLabels(g, lay.get(+g.dataset.i), fs); });
}
// X-ray count: the drawing greys back and every item lights up in turn while the big number ticks up to the answer
// (areas: the running sum). ~60–120 ms an item, never more than 2.5 s; a click or a key skips to the end; instant
// under prefers-reduced-motion.
const RMOTION = matchMedia('(prefers-reduced-motion: reduce)');
let xr = null;
const xhud = document.createElement('div'); xhud.className = 'xhud'; xhud.hidden = true; viewer.appendChild(xhud);
function xrayStop() {  // a new draw / answer: drop a running count without finishing it
  if (!xr) return;
  clearTimeout(xr.t); xr = null; animating = false; viewer.classList.remove('xray'); xhud.hidden = true;
}
let xrSkipT = 0;
function xraySkip() { if (xr) { xrSkipT = performance.now(); xr.skip(); } }
function xrayHud(k, n, val) {
  const t = res && res.type, noun = t === 'count' ? 'counting' : 'adding up';
  xhud.innerHTML = `<div class="xl"><span>X-ray · ${noun}</span><b>${k} / ${n}</b></div><div class="xbar"><i style="width:${(100 * k / Math.max(1, n)).toFixed(1)}%"></i></div>`
    + `<div class="xs">${t && t !== 'count' ? `<b>${fmt(val, t)} ${unitOf(t)}</b> · ` : ''}click or press a key to skip</div>`;
}
function draw(animate) {
  xrayStop();
  ov.innerHTML = '';
  if (mode === '3d' || !img.naturalWidth) return;
  if (RMOTION.matches) animate = false;
  const W = img.naturalWidth, H = img.naturalHeight;
  ov.setAttribute('viewBox', `0 0 ${W} ${H}`);
  lay = layoutLabels(W, H, labelSize());
  const leaders = document.createElementNS(NS, 'g'); leaders.setAttribute('class', 'leaders'); ov.appendChild(leaders);  // under every shape and number
  for (const m of [...marks, ...secondMarks()]) ov.appendChild(shapeFor(m, -1, W, H));
  const list2d = items.map((e, i) => [e, i]).filter(([e]) => e.kind !== 'ifc');
  const done = () => { animating = false; renderAnswer(null); recompute(); };
  if (!animate || !list2d.length) { list2d.forEach(([e, i]) => ov.appendChild(shapeFor(e, i, W, H))); done(); return; }
  const step = Math.min(120, 2500 / list2d.length), r0 = res, n = list2d.length;
  const pings = document.createElementNS(NS, 'g'); pings.setAttribute('class', 'pings'); ov.appendChild(pings);
  let k = 0, sum = 0;
  const show = quiet => {
    const [e, i] = list2d[k++]; sum += e.value ?? 1;
    const g = shapeFor(e, i, W, H); pings.before(g);
    if (!quiet) {
      const p = g.firstElementChild.cloneNode(false); p.setAttribute('class', 'ping' + (modelRead(e) ? ' model' : ''));
      pings.appendChild(p); setTimeout(() => p.remove(), 700);
    }
  };
  const finish = () => { xr = null; viewer.classList.remove('xray'); xhud.hidden = true; pings.remove(); done(); };
  const tick = () => {
    if (res !== r0) { xrayStop(); return; }
    show(false); renderAnswer(k); xrayHud(k, n, sum);
    if (k < n) xr.t = setTimeout(tick, step); else xr.t = setTimeout(finish, 160);
  };
  xr = {t: 0, skip: () => { clearTimeout(xr.t); while (k < n) show(true); finish(); }};
  animating = true; viewer.classList.add('xray'); xhud.hidden = false; xrayHud(0, n, 0);
  xr.t = setTimeout(tick, 120);
}
viewer.addEventListener('pointerdown', e => { if (xr && !e.target.closest('.caption')) { xraySkip(); e.stopPropagation(); } }, true);
$('#answer').addEventListener('pointerdown', () => xraySkip(), true);
function shapeFor(e, i, W, H) {
  const g = document.createElementNS(NS, 'g'); g.dataset.i = i;
  const fs = labelSize();
  let shape;
  if (e.kind === 'polygon') {
    shape = document.createElementNS(NS, 'polygon');
    shape.setAttribute('points', e.points.map(p => (p[0] * W) + ',' + (p[1] * H)).join(' '));
    shape.setAttribute('class', 'pg appear' + (e.on ? '' : ' off'));
  } else {
    const [x0, y0, x1, y1] = e.bbox;
    shape = document.createElementNS(NS, 'rect');
    shape.setAttribute('x', x0 * W); shape.setAttribute('y', y0 * H);
    shape.setAttribute('width', Math.max(2, (x1 - x0) * W)); shape.setAttribute('height', Math.max(2, (y1 - y0) * H));
    shape.setAttribute('rx', 2);
    const cls = e.second ? 'bx second' : e.mark ? (e.kind === 'text' ? 'bx txt' : 'bx mark') : 'bx appear' + (e.on ? '' : ' off') + (e.added ? ' added' : '') + (modelRead(e) ? ' model' : '');
    shape.setAttribute('class', cls);
  }
  const tip = document.createElementNS(NS, 'title'); tip.textContent = (e.label || '') + (e.value != null && res.type !== 'count' ? ` = ${fmt(e.value, res.type)} ${unitOf(res.type)}` : '');
  shape.appendChild(tip);
  g.appendChild(shape);  // the shape stays the group's first rect / polygon: hover and flash look it up that way
  if (i >= 0) {
    shape.addEventListener('click', ev => { if (adding) return; ev.stopPropagation(); if (moved || performance.now() - xrSkipT < 500) return; e.on = !e.on; redraw(); flashRow(i); });
    shape.addEventListener('mouseenter', () => rowHot(i, true, true));
    shape.addEventListener('mouseleave', () => rowHot(i, false));
  } else if (e.guids) {
    shape.addEventListener('mouseenter', () => { const j = guidItem().get(e.guids[0]); if (j != null) rowHot(j, true, true); });
  }
  const p = i >= 0 ? lay.get(i) : null;
  if (p && numbered(e)) {  // numbers stay put after a correction: a dropped item keeps its number, faint, to click back
    const n = items.slice(0, i + 1).filter(numbered).length;
    if (e.kind === 'box') {
      const ln = document.createElementNS(NS, 'line'); ln.dataset.i = i; ln.setAttribute('class', 'leader' + (modelRead(e) ? ' model' : '') + (e.on ? '' : ' off'));
      (ov.querySelector('g.leaders') || g).appendChild(ln);
    }
    // shape carries the meaning without colour: circle = measured from CAD / IFC geometry, square = found by a model
    const c = document.createElementNS(NS, modelRead(e) ? 'rect' : 'circle');
    c.setAttribute('class', 'badgebg' + (e.added ? ' added' : '') + (modelRead(e) ? ' model' : '') + (e.on ? '' : ' off')); g.appendChild(c);
    const t = document.createElementNS(NS, 'text');
    t.setAttribute('text-anchor', 'middle');
    t.setAttribute('dominant-baseline', 'central'); t.setAttribute('class', 'badge' + (e.on ? '' : ' off'));
    t.textContent = n; g.appendChild(t);
  } else if (p) {
    const t = document.createElementNS(NS, 'text');
    t.setAttribute('text-anchor', 'middle'); t.setAttribute('class', 'pglabel');
    t.textContent = round2(e.value) + ' m²'; g.appendChild(t);
  }
  placeLabels(g, p, fs);
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
    ? 'Each row is an IFC element. Hover or click a row to find it in 3D; untick it (or click the element) to drop it from the answer.'
    : primary === 'paired' ? 'Each row is an IFC element, numbered on the plan: click a row to zoom to it, untick it to drop it. Switch to 3D to see the same elements in the model.'
    : 'Click a row to zoom to it; untick it (or click its shape) to drop it. Missed one? Add it.'
      + (items.some(modelRead) ? ' Dashed amber = found by a model, with its score: please check.' : ' Solid = measured from the CAD / IFC geometry.');
  let k = 0;
  items.forEach((e, i) => {
    const d = document.createElement('div'); d.className = (e.on ? '' : 'off') + (e.added ? ' added' : ''); d.dataset.i = i;
    if (numbered(e)) k++;
    const name = e.kind === 'box' ? (e.label || 'item').replace(/ \d+$/, '') : (e.label || (e.kind === 'polygon' ? 'region' : 'item'));
    const lead = numbered(e) ? `<span class="n">#${k}</span>` : `<span class="n">${i + 1}</span>`;
    const val = e.value != null && t !== 'count' ? fmt(e.value, t) + ' ' + unitOf(t) : '';
    const read = modelRead(e) && e.score != null ? `<span class="rd" title="found by a model with score ${Math.round(100 * e.score)} %: please check">${Math.round(100 * e.score)}%</span>` : '';
    d.innerHTML = `<button class="tg" title="${e.on ? 'drop this item from the answer' : 'put it back'}" aria-label="include">${e.on ? '✓' : ''}</button>${lead}<span class="nm" title="${esc(name)}">${esc(name)}${read}</span><span class="vl">${val}</span>`;
    d.onmouseenter = () => hotItem(i, true); d.onmouseleave = () => hotItem(i, false);
    d.querySelector('.tg').onclick = ev => { ev.stopPropagation(); e.on = !e.on; redraw(); };
    d.onclick = () => focusItem(i);
    ev.appendChild(d);
  });
  if (num) {
    const tot = document.createElement('div'); tot.className = 'tot';
    const v = items.filter(e => e.on).reduce((s, e) => s + (e.value ?? 1), 0);
    tot.innerHTML = `<span>${t === 'count' ? 'count' : 'sum'} of checked items</span><span>${fmt(v, t)} ${unitOf(t)}</span>`;
    ev.appendChild(tot);
  }
}
// read by a model (detector / LLM / vision) rather than measured from CAD or IFC geometry: drawn dashed amber
// (a vision / language model's boxes carry no detector score, but they are model-read all the same)
const modelRead = e => !e.added && (e.score != null || (e.kind === 'box' && !!res && howOf(res).cls !== 'geo'));
function focusItem(i) {
  const e = items[i]; if (!e) return;
  if (mode === '3d' || e.kind === 'ifc') { hotItem(i, true); setTimeout(() => hotItem(i, false), 1200); return; }
  zoomToEvidence([e], 3); flashRow(i);
  const s = ov.querySelector(`g[data-i="${i}"] rect, g[data-i="${i}"] polygon`);
  if (s) { s.classList.add('flash'); setTimeout(() => s.classList.remove('flash'), 1300); }
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
  el.innerHTML = changed ? `✎ corrected by you: <b>${fmt(v, res.type)} ${unitOf(res.type)}</b> (the solver said ${fmt(res.answer, res.type)})`
    + `<span class="fbnote" id="fbnote">${fb.res === res && fb.state ? fbText(fb.state) : ''}</span>` : '';
  queueFeedback(changed, v);
  const row = takeoffRow(res); if (row) { const c = changed ? +v.toFixed(3) : ''; if (row.corrected !== c) { row.corrected = c; saveTakeoff(); } }
}

// ------------------------------------------------------------ corrections become training data
// every correction (items dropped / added) is sent once it settles; the server appends it to a JSONL file the
// next training run reviews. Undoing all changes sends a revert, so the last line per answer is the truth.
const FB_SESSION = Math.random().toString(36).slice(2, 12);
const fb = {timer: null, sent: '', res: null, state: ''};
const fbText = st => st === 'saved' ? '✓ saved as feedback for the next training run' : st === 'sending' ? 'saving as feedback…' : st === 'error' ? 'feedback not saved' : '';
function setFb(st) { fb.state = st; const n = $('#fbnote'); if (n) n.textContent = fbText(st); }
function queueFeedback(changed, v) {
  if (!res || res.answer == null) return;
  if (fb.res !== res) { fb.res = res; fb.sent = ''; fb.state = ''; }
  const removed = items.filter(e => !e.on && !e.added), added = items.filter(e => e.on && e.added);
  const sig = JSON.stringify([removed.map(e => items.indexOf(e)), added.map(e => e.bbox)]);
  if (!changed && !fb.sent) return;  // nothing changed and nothing to revert
  if (sig === fb.sent) return;
  clearTimeout(fb.timer);
  const r = res;
  fb.timer = setTimeout(async () => {
    if (r !== res) return;
    setFb('sending');
    const strip = e => ({kind: e.kind, label: e.label, value: e.value, score: e.score, page: e.page, bbox: e.bbox, points: e.points, guids: e.guids});
    try {
      const resp = await fetch('/api/feedback', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        path: cur.path, question: r.question, question_id: r.question_id ?? null, type: r.type, method: r.method,
        original_answer: r.answer, corrected_answer: changed ? v : r.answer,
        removed: removed.map(strip), added: added.map(strip), session: FB_SESSION, tour: !!tour})});
      if (r !== res) return;
      fb.sent = sig; setFb(resp.ok ? (changed ? 'saved' : '') : 'error');
    } catch { if (r === res) setFb('error'); }
  }, 1200);
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
  capFit();
  $('#tnext').textContent = tourI === tour.length - 1 ? 'finish ✓' : 'next ›';
  $('#tprev').disabled = tourI === 0;
  const myI = tourI;
  if (s.path && (!cur || cur.path !== s.path)) {
    tab = s.source || tab;
    await select({path: s.path, source: s.source, split: s.split || ''}, 'replace');
    loadList();
  }
  if (s.question) {
    traceOpen = false;
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
    // on a phone the evidence list sits below the drawing: bring the row up so the change is seen
    if (PHONE.matches) { const row = $(`#ev div[data-i="${i}"]`); if (row) { row.scrollIntoView({behavior: 'smooth', block: 'center'}); await sleep(600); } }
    hotItem(i, true); await sleep(700); items[i].on = !items[i].on; redraw(); hotItem(i, false); flashRow(i); await sleep(900);
  } else if (k === 'add') {
    const [u, v] = arg.split(',').map(Number); const r = img.getBoundingClientRect();
    setAdding(true); await sleep(500); addAt(r.left + u * r.width, r.top + v * r.height); await sleep(600); setAdding(false);
  } else if (k === 'mode') await setMode(arg);
  else if (k === 'storey') { storeyFocus = arg; $('#storey').value = arg; applyStorey(true); await sleep(600); }
  else if (k === 'trace') {
    traceOpen = arg !== 'close'; const d = $('#answer details.trace'); if (!d) return;
    d.open = traceOpen;
    if (PHONE.matches) d.scrollIntoView({behavior: 'smooth', block: 'start'});
    else {  // bring the trace up, but never past the top of the answer card (the big number stays visible)
      const side = $('#side'), a = $('#answer'), top = el => el.getBoundingClientRect().top - side.getBoundingClientRect().top + side.scrollTop;
      const card = top(a) - $('.ask').offsetHeight - 16, want = top(d) + d.offsetHeight - side.clientHeight + 16;
      side.scrollTo({top: Math.max(0, Math.min(card, Math.max(side.scrollTop, want))), behavior: 'smooth'});
    }
    await sleep(900);
  }
  else if (k === 'scroll') {  // bring one part of the answer card into view (e.g. the frontier table)
    const el = $('#answer ' + arg); if (!el) return;
    if (PHONE.matches) el.scrollIntoView({behavior: 'smooth', block: 'start'});
    else {
      const side = $('#side'), top = el.getBoundingClientRect().top - side.getBoundingClientRect().top + side.scrollTop;
      side.scrollTo({top: Math.max(0, top - $('.ask').offsetHeight - 24), behavior: 'smooth'});
    }
    await sleep(900);
  }
  else if (k === 'hover') { const i = +arg; hotItem(i, true); rowHot(i, true, true); await sleep(1400); hotItem(i, false); rowHot(i, false); }
}
function endTour() { tour = null; $('#caption').hidden = true; document.body.classList.remove('touring'); capFit(); }
// phone: the caption is a compact bottom sheet; the text shows two lines and opens on a tap ("more")
const capMore = document.createElement('button');
capMore.className = 'capmore'; capMore.textContent = 'more'; capMore.hidden = true;
$('#captext').after(capMore);
const capToggle = () => { $('#caption').classList.toggle('open'); capFit(); };
capMore.onclick = capToggle;
$('#captext').onclick = () => { if (PHONE.matches) capToggle(); };
function capFit() {  // after the text or the layout changed: show "more" only if the text is cut, pad the side panel by the sheet
  requestAnimationFrame(() => {
    const t = $('#captext'), c = $('#caption');
    capMore.hidden = c.classList.contains('open') || t.scrollHeight <= t.clientHeight + 1;
    document.body.style.setProperty('--caph', c.offsetHeight + 'px');
    const vh = $('#viewer').clientHeight;  // the drawing is shorter while touring on a phone: refit it once
    if (vh !== capVH) { capVH = vh; if (mode === '2d') fit(); }
  });
}
let capVH = 0;
PHONE.addEventListener('change', capFit);
$('#tourbtn').onclick = () => startTour(false);
$('#ctatour').onclick = () => startTour(false);
$('#tnext').onclick = () => { if (!tour) return; if (tourI < tour.length - 1) { tourI++; runStep(); } else { endTour(); if (!PHONE.matches) { $('#q').focus(); $('#q').select(); } } };
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
  if (xr && !typing && !['Shift', 'Control', 'Alt', 'Meta'].includes(e.key)) xraySkip();
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
