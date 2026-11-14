// Blueprints that talk: pick or upload a drawing, ask, watch the answer get counted out on the drawing.
'use strict';
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const SRC = {swiss_dwellings: 'Swiss apartments', cubicasa5k: 'Finnish plans', ifc_models: 'BIM models', ifc_bench: 'IFC text Q&A',
             opening_design: 'US drawing sets', upload: 'Your uploads'};
const ROUTE = {swiss: 'CAD layers (DXF twin)', ifc: 'IFC model query', cubicasa: 'plan symbol detector', generic: 'generic drawing reader', ifctext: 'IFC fact sheet', normalize: 'question normaliser (small LLM)'};
const NS = 'http://www.w3.org/2000/svg';

// a drawing's name for people, not its file name: "Swiss apartment plan 9385", "Grundplan · Molio", "A-701 · Restrooms"
const cap1 = s => s.charAt(0).toUpperCase() + s.slice(1);
function friendly(d) {
  const path = String(d.path || ''), file = path.split('/').pop(), stem = file.replace(/\.\w+$/, '');
  let m;
  if (path.startsWith('uploads/')) return {name: d.name || file.replace(/^[0-9a-f]{8,}[-_]/, ''), kind: 'Your upload'};
  if (/swiss_dwellings\//.test(path) && (m = stem.match(/floor(\d+)/))) return {name: `Swiss apartment plan ${m[1]}`, kind: 'Swiss CAD plan'};
  if (/cubicasa5k\//.test(path) && (m = stem.match(/(\d+)$/))) return {name: `Finnish apartment plan ${m[1]}`, kind: 'Finnish raster plan'};
  if (/ifc_models\//.test(path) && (m = stem.match(/^[^_]+_(.+?)_plan-\d+-(.+)$/))) {
    const proj = m[1].replace(/[-_]+/g, ' ').replace(/\b(with uris|example project|ar)\b/gi, '').replace(/\s+/g, ' ').trim();
    return {name: `${cap1(m[2].replace(/[-_]+/g, ' '))} · ${cap1(proj)}`, kind: 'BIM model, plan sheet'};
  }
  if (/ifc_models\/|ifc_bench\//.test(path)) return {name: cap1(stem.replace(/^[^_]+_(?=.*_)/, '').replace(/[-_]+/g, ' ')), kind: 'BIM model'};
  if (/opening_design\//.test(path)) {
    const proj = path.split('/')[2] || '';
    return {name: stem.replace(/\s+-\s+/, ' · ').replace(/\b([A-Z]{3,})\b/g, w => cap1(w.toLowerCase())), kind: `US drawing set${proj ? ' · ' + proj.replace(/_/g, ' ') : ''}`};
  }
  return {name: stem, kind: ''};
}

let tab = 'swiss_dwellings', cur = null, res = null, items = [], marks = [], adding = false, primary = '2d';
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
  $('#addbtn').textContent = adding ? '✓ Done' : '+ Add missed'; $('#addbtn').classList.toggle('on', adding);
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
  $('#m2d').setAttribute('aria-pressed', m === '2d'); $('#m3d').setAttribute('aria-pressed', m === '3d');
  if (m === '3d') { const fresh = loaded3d !== cur.path; if (await ensure3d() && !fresh) highlight3d(false); }
  else if (img.naturalWidth && res) draw(false);
  if (res) renderEvidence();
  plantools();
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
  if (i != null && items[i]) { items[i].on = !items[i].on; redraw(); flashRow(i); return; }
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
    for (const d of uploads) box.appendChild(itemEl(d, `${String(d.kind || d.ext || '').toUpperCase()} · uploaded`));
    if (!uploads.length) box.innerHTML = '<div class="item empty-note"><small>Nothing uploaded yet.</small></div>';
    return;
  }
  const r = await (await fetch(`/api/drawings?source=${tab}&q=${encodeURIComponent(listQuery)}&offset=${listOffset}&limit=80`)).json();
  renderTabs(r.counts);
  if (!append) box.innerHTML = '';
  for (const d of r.items) box.appendChild(itemEl(d, `${d.n} questions${d.split === 'test' ? ' · test set, never trained on' : ''}`));
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
    b.setAttribute('aria-pressed', s === tab);
    b.innerHTML = `${SRC[s]} <small>${all[s]}</small>`;
    b.onclick = () => { tab = s; loadList(); }; tabs.appendChild(b);
  }
}
function itemEl(d, sub) {
  const el = document.createElement('button'); el.type = 'button'; el.className = 'item' + (cur && cur.path === d.path ? ' on' : '');
  el.dataset.path = d.path; el.title = d.path.split('/').pop();
  el.innerHTML = `<b>${esc(friendly(d).name)}</b><small>${esc(sub)}</small>`;
  el.onclick = () => { closePicker(); select(d); };
  return el;
}
$('#more').onclick = () => loadList(true);
let searchT; $('#search').oninput = e => { clearTimeout(searchT); searchT = setTimeout(() => { listQuery = e.target.value; loadList(); }, 200); };

// ------------------------------------------------------------ popovers: the drawing picker, the ⋯ view menu, the keyboard help
// one open at a time; Esc, a click outside or picking something closes it and focus goes back to its button
const POPS = {list: '#drawerbtn', vmenu: '#vmbtn', keys: '#keysbtn'};
let popOpen = null;
function openPop(id) {
  if (popOpen && popOpen !== id) closePop(false);
  popOpen = id; $('#' + id).hidden = false; $(POPS[id]).setAttribute('aria-expanded', 'true');
  if (id === 'list') {
    document.body.classList.add('drawer'); loadList();
    if (!PHONE.matches) setTimeout(() => $('#search').focus(), 0); else $('#uploadbox').focus();
  } else $('#' + id).querySelector('button, select, input')?.focus();
}
function closePop(refocus = true) {
  if (!popOpen) return;
  const id = popOpen; popOpen = null;
  $('#' + id).hidden = true; $(POPS[id]).setAttribute('aria-expanded', 'false');
  document.body.classList.remove('drawer');
  if (refocus && !$(POPS[id]).hidden) $(POPS[id]).focus();
}
function closePicker() { if (popOpen === 'list') closePop(false); }
window.bpOpenPicker = t => { if (t && SRC[t]) tab = t; openPop('list'); };
$('#drawerbtn').onclick = () => popOpen === 'list' ? closePop() : openPop('list');
$('#keysbtn').onclick = () => popOpen === 'keys' ? closePop() : openPop('keys');
$('#vmbtn').onclick = () => { if (popOpen === 'vmenu') closePop(); else { viewMenu(); openPop('vmenu'); } };
document.addEventListener('pointerdown', e => {
  if (!popOpen) return;
  const pop = $('#' + popOpen), btn = $(POPS[popOpen]);
  if (!pop.contains(e.target) && !btn.contains(e.target)) closePop(false);
}, true);
$('#uploadbox').addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('#file').click(); } });
function setPickerLabel(d) {
  const f = friendly(d);
  $('#pkname').textContent = f.name;
  $('#drawerbtn').title = `${f.kind ? f.kind + ': ' : ''}${d.path.split('/').pop()}. Pick another drawing, or upload your own`;
  $('#drawerbtn').setAttribute('aria-label', `Drawing: ${f.name}. Pick another drawing or upload your own`);
}

let pendingDraw = null;
async function select(d, how = 'push') {
  cur = {...d}; res = null; items = []; marks = []; ov.innerHTML = ''; setAdding(false); askSeq++; setHeat(false); closeSheet();
  $('#answer').hidden = true; $('#evwrap').hidden = true; hint(''); $('#empty').hidden = true; setAnswered(false); setPickerLabel(d); viewTools();
  syncURL(how);
  document.querySelectorAll('.item').forEach(e => e.classList.toggle('on', e.dataset.path === d.path));
  revealSelected();
  const r = await fetch('/api/questions?path=' + encodeURIComponent(d.path));
  if (!r.ok) {
    if (cur.path !== d.path) return;
    img.removeAttribute('src'); cur.shown = null; renderChips([]); $('#modes').classList.remove('show'); $('#credit').textContent = '';
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
  renderChips(info.questions || []);
  // chips first: a big model can take a while to tessellate and the questions should not wait for it
  if (cur.path === d.path) await setMode(info.view ? '2d' : (has3d ? '3d' : '2d'));
}
// three example questions, one click each (short, English, different kinds first); the rest folded under "More questions"
function renderChips(qs) {
  const chip = q => {
    const c = document.createElement('button'); c.type = 'button'; c.className = 'chip'; c.title = q.type ? `${q.type} question` : '';
    c.textContent = q.question; c.onclick = () => { $('#q').value = q.question; ask(); }; return c;
  };
  const en = q => /^(how|what|which|is|are|does|do|where|list|name)\b/i.test(q.question);
  const ranked = [...qs].sort((a, b) => (en(b) - en(a)) || (a.question.length - b.question.length));
  const pick = [];
  for (const q of ranked) if (pick.length < 3 && !pick.some(p => p.type === q.type)) pick.push(q);
  for (const q of ranked) if (pick.length < 3 && !pick.includes(q)) pick.push(q);
  $('#chips3').replaceChildren(...pick.map(chip));
  $('#chips').replaceChildren(...qs.map(chip));
  $('#qstitle').textContent = `More questions (${qs.length})`;
  $('#moreqs').open = false;
}
// landing (hero, tour button, three examples) vs answering (question box, answer card, more questions)
function setAnswered(on) { $('#side').classList.toggle('answered', on); }
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
  if (!box) { box = document.createElement('div'); box.id = 'upnote'; $('#qs').before(box); }
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
  setAdding(false); if (heat.on) setHeat(false);
  const a = $('#answer'); a.hidden = false; a.classList.remove('pop'); setAnswered(true); $('#atail').innerHTML = '';
  if (PHONE.matches) $('#q').blur();  // drop the phone keyboard so the answer is visible
  const steps = THINK[cur.source || cur.split] || THINK[cur.path.startsWith('uploads/') ? 'upload' : ''] || ['reading the drawing'];
  const t0 = performance.now();
  const tick = () => {
    if (seq !== askSeq || res?._seq === seq) return;
    const s = (performance.now() - t0) / 1000;
    $('#ahead').innerHTML = `<div class="qecho">${esc(question)}</div><div class="thinking"><div><span class="spin"></span> ${esc(cap1(steps[Math.min(steps.length - 1, Math.floor(s / 1.5))]))}…</div>
      <small>${s.toFixed(1)} s${s > 6 ? ' · the first load of a big model is slow' : ''}</small></div>`;
    setTimeout(tick, 100);
  };
  res = null; tick();
  $('#evwrap').hidden = true; ov.innerHTML = '';
  let r;
  try {
    const body = {path: cur.path, question}; if (cur.pin != null) body.page = cur.pin;
    const resp = await fetch('/api/ask', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    r = await resp.json();
    if (resp.status === 429) {  // the public demo's per-visitor limit: not an abstention, say when to come back
      const m = String(r.detail || '').match(/per (\d+) minutes?/);
      r = {answer: null, confidence: 0, evidence: [], explanation: r.detail || 'too many questions', method: 'rate-limit', limited: m ? +m[1] : 0};
    } else if (!resp.ok) r = {answer: null, confidence: 0, evidence: [], explanation: r.detail || `server error ${resp.status}`, method: 'error'};
  } catch (err) {
    r = {answer: null, confidence: 0, evidence: [], explanation: 'could not reach the server: ' + err.message, method: 'error'};
  }
  if (seq !== askSeq) return;
  res = r; res._seq = seq; res.question = question; showSecond = false;
  recordTakeoff(res);
  syncURL('replace');
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
  if (!PHONE.matches && seq === askSeq) $('#side').scrollTo({top: 0, behavior: smooth()});  // the question box and the answer card
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
// why there is no number, short (the trust line) and long (How it was worked out)
function whyNone(r) {
  const m = String(r.method || ''), e = String(r.explanation || '');
  const nd = e.match(/[^|]*does not look like a construction drawing[^|]*/);
  if (nd) return {short: 'This file does not look like a construction drawing',
    long: cap1(nd[0].trim()) + '. Upload a plan, section or elevation (PDF, image, DXF or IFC) to ask about it.'};
  const why = r.budget_exhausted ? 'the daily budget for paid model calls is used up'
    : m === 'timeout' ? 'the solver ran out of time; it stops rather than guess'
    : /error/.test(m) ? 'the solver failed on this input; it reports that rather than a number'
    : /not understood|not recognised|no room label|not found/.test(e) ? 'the question is outside what the solver can check on this drawing'
    : /-na$|-none$/.test(m) || /no .* values|not in the/.test(e) ? 'the file does not contain what the question asks for'
    : 'the evidence was not good enough';
  return {short: cap1(why.split(';')[0]), long: `${cap1(why)}. A wrong number on a drawing costs more than an honest “not sure”, so we abstain.`};
}
const isCompare = r => /-compare$/.test(String(r.method || '')) || !!r.comparison;
function calibHTML(r) {
  if (r.answer == null) return `<div class="calib none"><b>Why no answer</b><span>${esc(whyNone(r).long)}</span></div>`;
  const c = r.calibration;
  if (!c) return '';
  const conf = Math.round(100 * (r.confidence ?? 0));
  if (!c.measured && isCompare(r)) return `<div class="calib unk"><b>No track record for this question type yet</b><span>comparison questions are new: we have no measured track record for them, so check the listed items before relying on the answer.</span></div>`;
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
const secOpen = {vs: false, how: false};  // the answer card's folded sections stay as the reader left them
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
  return `<div class="trace">${sec('Route', route)}${sec('What it read', read ? `<ul>${read}</ul>${r.answer == null ? note : ''}` : note)}${sec('Arithmetic', arith)}${sec('Cost and time', cost)}</div>`;
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
  return `<div class="vs"><table><tr class="us"><td>Blueprints that talk<small>${text ? 'answer above, with the facts it cites' : 'evidence on the drawing'}</small></td>${text ? '' : `<td class="num"><b>${ours}</b></td>`}<td>${mark(oursOk)}</td><td class="num"><b>${money(r.cost_usd || 0)}</b></td><td class="num">${latency(r.latency_s)}</td></tr>${rows}</table>
    </div>`;
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

// the trust line under the number: how it was found (a badge, its explanation as a tooltip) and its track record in words
function trustHTML(r, h) {
  const badge = `<span class="tbadge ${h.cls}" title="${esc(cap1(h.how))}">${h.cls === 'geo' ? '✓ ' : ''}${esc(h.t)}</span>`;
  if (r.answer == null) return `<div class="trust">${badge}<span>${esc(whyNone(r).short)}</span></div>`;
  const c = r.calibration;
  let tr = '';
  if (c && c.measured) {
    const p = c.right / c.n, cls = p >= 0.95 ? 'hi' : p >= 0.85 ? 'mid' : p >= 0.6 ? 'lo' : 'bad';
    tr = `<span class="tr ${cls}" title="${c.right === c.n ? 'all ' + nf(c.n) : nf(c.right) + ' of ' + nf(c.n)} similar answers were right on held-out test drawings we never trained on">Right <b>${pctOf(c.right, c.n)} %</b> of the time on similar test drawings</span>`;
  } else if (c && isCompare(r)) tr = `<span class="tr warn" title="Comparison questions are new: no measured track record for this question type">New question type: <b>check the evidence</b></span>`;
  else if (c) tr = `<span class="tr warn" title="No track record on files like this one yet">New kind of file: <b>check the evidence</b></span>`;
  else if (r.confidence != null) tr = `<span class="tr ${r.confidence >= 0.8 ? '' : 'warn'}">Model confidence <b>${Math.round(100 * r.confidence)} %</b></span>`;
  return `<div class="trust">${badge}${tr}</div>`;
}
// the second opinion in one line: a check mark when it agrees, a warning when it does not
function secondHTML(r) {
  const c = r.crosscheck; if (!c || !c.status || c.status === 'single' || r.answer == null) return '';
  const sec = c.second || {}, n2 = (sec.evidence || []).filter(e => e.bbox || e.points).length;
  const v = typeof sec.answer === 'number' ? fmt(sec.answer, r.type) : esc(String(sec.answer ?? '—'));
  const btn = n2 ? ` <button class="linkish" data-act="second">${showSecond ? 'hide' : 'show'} its marks</button>` : '';
  if (c.status === 'agree') return `<div class="second" title="${esc(c.note || 'A second, independent method gave the same answer')}">✓ A second, independent method agrees${btn}</div>`;
  return `<div class="second conflict" title="${esc(c.note || '')}">⚠ A second method says ${v}: check the evidence${btn}</div>`;
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
  const h = howOf(res);
  if (num && res.answer === 0 && !items.length && h.cls !== 'geo') h.how = 'it found nothing to box, so there is nothing to check on the drawing: look at the plan yourself before relying on 0';
  const qrow = `<div class="qrow"><div class="qecho" title="${esc(res.question)}">${esc(res.question)}</div><span class="qtools" id="qtools"></span></div>`;
  if (res.method === 'rate-limit') {  // the demo's per-visitor limit: no abstain card, no comparison, no cost
    $('#ahead').innerHTML = `${qrow}<div class="big limit">Demo limit reached</div>
      <div class="trust"><span>Try again in ${res.limited ? `${res.limited} min` : 'a few minutes'}. Every visitor gets a fixed number of questions.</span></div>`;
    $('#atail').innerHTML = '';
    wireAnswerActions(a); return;
  }
  // head: the question, the number, one trust line, the second opinion in one line, a correction if any
  $('#ahead').innerHTML = `${qrow}
    ${res.normalized_question && res.normalized_question !== res.question ? `<div class="readas">read as: <i>${esc(res.normalized_question)}</i></div>` : ''}
    ${typeof res.answer === 'string' ? `<div class="textans">${esc(res.answer.trim().split('\n').map(l => l.replace(/^\s{1,4}(?=\S)/, '')).join('\n'))}</div>`
      : `<div class="big ${abst ? 'abstain' : ''} ${counting ? 'counting' : ''}">${abst ? 'Not sure, so no guess' : num ? `<span class="bn">${fmt(val, t)}</span>` : ''}${abst || !unitOf(t) ? '' : ` <small>${unitOf(t)}</small>`}</div>`}
    ${trustHTML(res, h)}
    ${secondHTML(res)}
    <div class="corr" id="corr"></div>`;
  // the rest folds: compared with frontier models, and how it was worked out (method, track record, rule, arithmetic, cost)
  const fr = res.frontier || [], wrong = fr.filter(f => f.correct === false).length;
  const vsSum = wrong ? `<span class="badt">${wrong} of ${fr.length} wrong</span>` : fr.length && fr.every(f => f.correct === true) ? `all ${fr.length} right` : `${fr.length} models`;
  const vs = hasVs ? `<details class="sec" data-sec="vs" ${secOpen.vs ? 'open' : ''}><summary><span>Frontier models</span><span class="sv">${vsSum}</span></summary><div class="secbody">
      ${(num && ghostHTML(res, val, counting)) || frontierHTML(res, oursOk)}
      <div class="vsnote">Same drawing and question, from our baseline run on held-out test questions.</div></div></details>` : '';
  const how = `<details class="sec" data-sec="how" ${secOpen.how ? 'open' : ''}><summary><span>How it was worked out</span><span class="sv">${abst && cur.not_drawing ? '' : `${money(res.cost_usd || 0)} · ${latency(res.latency_s)}`}</span></summary><div class="secbody">
      <div class="how ${h.cls}"><b>${h.cls === 'geo' ? '✓ ' : ''}${esc(h.t)}</b><span>${esc(h.how)}</span></div>
      ${calibHTML(res)}
      ${crossHTML(res)}
      ${res.rule ? `<div class="rule"><b>Rule</b> ${esc(res.rule)}</div>` : ''}
      ${!res.trace ? `<div class="expl">${esc(res.explanation || '')}</div>` : ''}
      <div class="row">${abst || res.calibration ? '' : `<span class="pill ${confCls}">confidence ${(conf * 100).toFixed(0)}%</span>`}${gold}</div>
      ${traceHTML(res)}
      <div class="costcmp" ${abst && cur.not_drawing ? 'hidden' : ''}>
        <span class="lab">this answer</span><span><span class="mbar" style="display:block"><i style="width:${Math.max(0.5, 100 * (res.cost_usd || 0) / Math.max(res.baseline_cost_usd || 1e-9, res.cost_usd || 0))}%"></i></span></span>
        <span class="v"><b>${money(res.cost_usd || 0)}</b> · ${latency(res.latency_s)}</span>
        <span class="lab">frontier model</span><span><span class="mbar" style="display:block"><i class="base" style="width:100%"></i></span></span>
        <span class="v">~${money(res.baseline_cost_usd || 0)} · ~${baseS.toFixed(0)} s</span>
      </div></div></details>`;
  $('#atail').innerHTML = vs + how + (abst ? '' : signHTML(res));
  a.querySelectorAll('#atail details.sec').forEach(d => d.ontoggle = () => { secOpen[d.dataset.sec] = d.open; });
  wireAnswerActions(a);
  speakTools(counting);  // spoken answers: the read-aloud button (block "spoken answers" below)
  if (!counting) { recompute(); announce(); }
}
// screen readers hear each answer once, when its count has finished (the card itself is not a live region:
// the X-ray count and corrections re-render it many times)
let announcedSeq = null;
function announce() {
  if (!res || announcedSeq === res._seq) return;
  announcedSeq = res._seq;
  const t = res.type, h = howOf(res);
  const ans = res.answer == null ? 'not sure, so no guess'
    : typeof res.answer === 'number' ? `${fmt(res.answer, t)} ${unitOf(t)}`.trim()
    : String(res.answer).trim().slice(0, 300);
  const sr = $('#sr-status'); if (sr) sr.textContent = `${res.question}: ${ans}. ${h.t}.`;
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
  // (runs/crosscheck_vlm_test_v7.summary.md, runs/crosscheck_test.summary.md)
  const m = String(sec.method || '');
  const [name, track] = /VLM/i.test(m) ? ['Our fine-tuned vision model', 'When both agree, answers were right 94.9 % of the time (12,178 held-out raster questions).']
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
function signHTML(r) {  // the card's footer: sign-off, the session's takeoff CSV, and what the answer cost
  const row = takeoffRow(r), n = takeoff.length;
  const signed = row && row.signed_by ? `<span class="signed">✓ Checked by ${esc(row.signed_by)} · ${new Date(row.signed_at).toLocaleString([], {dateStyle: 'short', timeStyle: 'short'})}</span>
    <button class="act" data-act="unsign">undo</button>` : `<button class="act" data-act="sign" title="Sign this answer off with your initials">Mark as checked</button>`;
  return `<div class="afoot signrow">${signed}
    <button class="act" data-act="csv" title="Download every answer of this session as a CSV takeoff">Export CSV${n > 1 ? ` (${n})` : ''}</button>
    <span class="grow"></span><span class="cost" title="What this answer cost us">${(r.cost_usd || 0) === 0 ? '<b>$0</b>' : money(r.cost_usd)} · ${latency(r.latency_s)}</span></div>`;
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
      <button class="btn" data-act="signok">Sign</button><button class="act" data-act="signcancel">cancel</button>`;
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
  const show = (r, c) => {  // an upload is named by its file name, not its server folder; confidence as % like the track record
    if (c === 'drawing' && String(r.drawing || '').startsWith('uploads/')) return String(r.drawing).split('/').pop();
    if (c === 'confidence' && typeof r.confidence === 'number') return +(100 * r.confidence).toFixed(1);
    return typeof r[c] === 'string' ? r[c].replace(/\s+/g, ' ') : r[c];
  };
  downloadCSV([head, ...takeoff.map(r => cols.map(c => show(r, c)))], `takeoff-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, '')}.csv`);
}
function downloadCSV(rows, filename) {  // UTF-8 with a BOM, so Excel opens the m² and umlauts right
  const cell = v => { const t = String(v ?? ''); return /[",\n;]/.test(t) ? '"' + t.replace(/"/g, '""') + '"' : t; };
  const csv = rows.map(r => r.map(cell).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob(['\ufeff' + csv], {type: 'text/csv;charset=utf-8'}));
  const link = document.createElement('a'); link.href = url; link.download = filename;
  document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000);
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
  sharpen(); if (typeof rescaleHeat === 'function') rescaleHeat();
  if (mode === '3d' || !img.naturalWidth || !items.length) return;
  const fs = labelSize(); lay = layoutLabels(img.naturalWidth, img.naturalHeight, fs);
  ov.querySelectorAll('g[data-i]').forEach(g => { if (+g.dataset.i >= 0) placeLabels(g, lay.get(+g.dataset.i), fs); });
}
// X-ray count: the drawing greys back and every item lights up in turn while the big number ticks up to the answer
// (areas: the running sum). ~60–120 ms an item, never more than 2.5 s; a click or a key skips to the end; instant
// under prefers-reduced-motion.
const RMOTION = matchMedia('(prefers-reduced-motion: reduce)');
function smooth() { return RMOTION.matches ? 'auto' : 'smooth'; }  // scrolls jump instead of glide under reduced motion
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
  $('#evtitle').textContent = on === items.length ? `${items.length} item${items.length === 1 ? '' : 's'}` : `${on} of ${items.length}`;
  $('#addbtn').hidden = primary === 'ifc' || mode === '3d' || !num;
  $('#evhelp').textContent = primary === 'ifc' ? 'Untick a row, or click it in 3D, to drop it.' : 'Untick a row, or click its mark, to drop it.';
  $('#evhelp').title = primary === 'ifc'
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
    const leadTxt = numbered(e) ? `#${k}` : String(i + 1);
    d.innerHTML = `<button class="tg" role="checkbox" aria-checked="${e.on}" title="${e.on ? 'drop this item from the answer' : 'put it back'}" aria-label="Include ${esc(name)} ${leadTxt}">${e.on ? '✓' : ''}</button>${lead}<span class="nm" title="${esc(name)}">${esc(name)}${read}</span><span class="vl">${val}</span>`;
    d.onmouseenter = () => hotItem(i, true); d.onmouseleave = () => hotItem(i, false);
    d.querySelector('.tg').onclick = ev => {
      ev.stopPropagation(); e.on = !e.on;
      const kb = document.activeElement === ev.currentTarget; redraw();
      if (kb) $(`#ev div[data-i="${i}"] .tg`)?.focus();  // the list is rebuilt: keep keyboard focus on this row's toggle
    };
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
  if (tour) return;  // the tour's scripted correction is not a visitor's feedback
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

// ------------------------------------------------------------ room heat-map and takeoff sheet (Swiss CAD plans)
// /api/rooms reads every numbered room off the plan's CAD twin (apartment, net m², outline): the heat-map shades each
// room by its net area on one sequential blue (light = small), and the takeoff sheet lists them by apartment, with
// the door / window / fixture counts and the drawing credit, ready to print or save as CSV. No model call: $0.
const HEAT = ['#e3eef7', '#bcd7ec', '#8bbadc', '#4f95c6', '#1a6fa6'];  // one hue, light to dark (sequential)
const SYM = [['door', 'Doors'], ['window', 'Windows'], ['toilet', 'Toilets (WC)'], ['washbasin', 'Washbasins'], ['bathtub', 'Bathtubs'],
             ['shower', 'Showers'], ['stove', 'Stoves'], ['stairs', 'Stair flights']];
const heat = {on: false, data: null, path: null};
const isSwiss = () => !!cur && !cur.path.startsWith('uploads/') && /swiss_dwellings\//.test(cur.path) && !!cur.shown;
const heatSvg = document.createElementNS(NS, 'svg'); heatSvg.id = 'heat'; heatSvg.setAttribute('viewBox', '0 0 1 1'); stage.insertBefore(heatSvg, ov);
const legend = document.createElement('div'); legend.className = 'hlegend'; legend.hidden = true; viewer.appendChild(legend);
async function roomData() {
  if (heat.path === cur.path && heat.data) return heat.data;
  const path = cur.path, r = await fetch('/api/rooms?path=' + encodeURIComponent(path));
  if (!r.ok || cur.path !== path) return null;
  heat.data = await r.json(); heat.path = path; return heat.data;
}
// the ⋯ view menu on the drawing: heat-map and takeoff sheet (Swiss CAD plans); explode, x-ray, storey and section (3D models).
// The 3D viewer keeps its own buttons (hidden by CSS); the menu offers them by name and clicks them.
function viewTools() {  // after a drawing is shown or the mode changes: is there anything to offer?
  const swiss2d = isSwiss() && mode === '2d';
  if (!swiss2d && heat && heat.on) setHeat(false);
  const v3 = mode === '3d' && [...document.querySelectorAll('#three .v3bar button')].some(b => !b.hidden);
  const t3 = mode === '3d' && $('#tools3d').classList.contains('show');
  $('#vmbtn').hidden = !(swiss2d || v3 || t3);
  if ($('#vmbtn').hidden && popOpen === 'vmenu') closePop(false);
}
function plantools() { viewTools(); }
function viewMenu() {  // the items, built as the menu opens
  const box = $('#vmitems'); box.innerHTML = '';
  const add = (label, pressed, fn, title) => {
    const b = document.createElement('button'); b.type = 'button';
    b.innerHTML = `${esc(label)}${pressed != null ? `<small>${pressed ? 'On' : ''}</small>` : ''}`;
    if (pressed != null) b.setAttribute('aria-pressed', String(pressed));
    if (title) b.title = title;
    b.onclick = () => { closePop(); fn(); }; box.appendChild(b);
  };
  if (isSwiss() && mode === '2d') {
    add('Room heat-map', heat.on, () => setHeat(!heat.on), 'Shade every room by its net area (from the CAD layers)');
    add('Takeoff sheet', null, () => openSheet(), 'A printable room schedule with areas per apartment and symbol counts');
  }
  if (mode === '3d') for (const b of document.querySelectorAll('#three .v3bar button')) {
    if (!b.hidden) add(b.textContent.trim(), b.getAttribute('aria-pressed') === 'true', () => b.click(), b.title);
  }
}
const inLiving = r => !r.outdoor && !r.shaft && !r.common;  // the dataset's "net living area" of an apartment
function heatBreaks(rooms) {
  const mx = Math.max(...rooms.filter(r => !r.outdoor).map(r => r.area), 1);
  const nice = [2, 2.5, 4, 5, 6, 8, 10, 15, 20, 25].find(s => s * 5 >= mx) || Math.ceil(mx / 5);
  return [1, 2, 3, 4].map(k => k * nice);
}
const heatClass = (a, br) => br.findIndex(b => a < b) < 0 ? 4 : br.findIndex(b => a < b);
async function setHeat(on) {
  heat.on = on;
  viewer.classList.toggle('heaton', on); heatSvg.innerHTML = ''; legend.hidden = true;
  if (!on) return;
  const d = await roomData();
  if (!heat.on) return;
  if (!d || !d.rooms.length) { hint('No room outlines on this plan'); setHeat(false); return; }
  drawHeat(d);
  zoomToEvidence(d.rooms.map(r => ({kind: 'polygon', points: r.points})), 3);
  setTimeout(rescaleHeat, 650);
}
function drawHeat(d) {
  const W = img.naturalWidth, H = img.naturalHeight; if (!W) return;
  heatSvg.setAttribute('viewBox', `0 0 ${W} ${H}`); heatSvg.innerHTML = '';
  const br = heatBreaks(d.rooms), fs = labelSize();
  const defs = document.createElementNS(NS, 'defs');
  defs.innerHTML = `<pattern id="hatch" patternUnits="userSpaceOnUse" width="8" height="8" patternTransform="rotate(45)"><rect width="8" height="8" fill="#f3f4f6"/><line x1="0" y1="0" x2="0" y2="8" stroke="#a7aeb8" stroke-width="2"/></pattern>`;
  heatSvg.appendChild(defs);
  const labels = [];
  d.rooms.forEach((r, k) => {
    const p = document.createElementNS(NS, 'polygon');
    p.setAttribute('points', r.points.map(q => q[0] * W + ',' + q[1] * H).join(' '));
    const cls = r.outdoor ? 'out' : r.shaft || r.common ? 'common' : 'c' + heatClass(r.area, br);
    p.setAttribute('class', 'hr ' + cls);
    if (!r.outdoor && !r.shaft && !r.common) p.style.fill = HEAT[heatClass(r.area, br)];
    p.style.animationDelay = RMOTION.matches ? '0s' : (k * 0.03).toFixed(2) + 's';
    const tip = document.createElementNS(NS, 'title');
    tip.textContent = `${r.number} ${r.name}${r.unit ? ' · apartment ' + r.unit : ''}: ${round2(r.area)} m²${r.outdoor ? ' (outdoor, not in the net living area)' : r.common ? ' (common area)' : ''}`;
    p.appendChild(tip); heatSvg.appendChild(p);
    labels.push(r);
  });
  for (const r of labels) {  // the room's m², just under its printed name and number (area-weighted centre)
    let A = 0, cx = 0, cy = 0; const P = r.points.map(q => [q[0] * W, q[1] * H]);
    for (let i = 0; i < P.length - 1; i++) { const c = P[i][0] * P[i + 1][1] - P[i + 1][0] * P[i][1]; A += c; cx += (P[i][0] + P[i + 1][0]) * c; cy += (P[i][1] + P[i + 1][1]) * c; }
    if (Math.abs(A) < 1e-6) continue; cx /= 3 * A; cy /= 3 * A;
    const t = document.createElementNS(NS, 'text'); t.setAttribute('class', 'hlab' + (heatClass(r.area, br) >= 3 && inLiving(r) ? ' dark' : ''));
    const xs = P.map(q => q[0]), ys = P.map(q => q[1]);
    t.setAttribute('x', cx); t.setAttribute('y', cy); t.dataset.dy = 2.1;
    t.dataset.w = Math.max(...xs) - Math.min(...xs); t.dataset.h = Math.max(...ys) - Math.min(...ys);
    t.textContent = round2(r.area) + ' m²'; heatSvg.appendChild(t);
  }
  rescaleHeat();
  const units = [...new Set(d.rooms.map(r => r.unit).filter(Boolean))].sort();
  legend.innerHTML = `<div class="lt">Net area per room</div><div class="lscale">${HEAT.map((c, i) => `<i style="background:${c}"></i>`).join('')}</div>
    <div class="lticks">${[0, ...br].map((b, k) => `<span style="left:${k * 20}%">${b}</span>`).join('')}<span class="u">m²</span></div>
    <div class="lkeys"><span class="sw"><i class="hatch"></i>outdoor</span><span class="sw"><i class="com"></i>common / stairs</span></div>
    <div class="ltot">${units.map(u => `<span>Apt ${esc(u)} <b>${round2(d.rooms.filter(r => r.unit === u && inLiving(r)).reduce((s, r) => s + r.area, 0))} m²</b></span>`).join('')}</div>`;
  legend.hidden = false;
}
function rescaleHeat() {
  if (!heat.on) return;
  const fs = labelSize();
  const f = fs * 0.85;  // a label that would not fit inside its room is left out (hover the room for its tooltip)
  heatSvg.querySelectorAll('text.hlab').forEach(t => {
    t.style.fontSize = f + 'px'; t.setAttribute('dy', f * +t.dataset.dy);
    t.style.display = +t.dataset.w > t.textContent.length * f * 0.62 && +t.dataset.h > f * 5 ? '' : 'none';
  });
}

// the takeoff sheet: a white A4 page over the app (print: only the page is printed)
const sheetWrap = document.createElement('div'); sheetWrap.id = 'sheetwrap'; sheetWrap.hidden = true; document.body.appendChild(sheetWrap);
async function openSheet() {
  const d = await roomData(); if (!d) { hint('No room schedule for this drawing'); return; }
  const W = img.naturalWidth, H = img.naturalHeight, name = cur.path.split('/').pop().replace(/\.\w+$/, '');
  const br = heatBreaks(d.rooms);
  let x0 = 1, y0 = 1, x1 = 0, y1 = 0;
  for (const r of d.rooms) for (const [u, v] of r.points) { x0 = Math.min(x0, u); y0 = Math.min(y0, v); x1 = Math.max(x1, u); y1 = Math.max(y1, v); }
  const pd = 0.02; x0 = Math.max(0, x0 - pd); y0 = Math.max(0, y0 - pd); x1 = Math.min(1, x1 + pd); y1 = Math.min(1, y1 + pd);
  const fs = Math.max((x1 - x0) * W, (y1 - y0) * H) / 70;
  const polys = d.rooms.map(r => {
    const fill = r.outdoor ? 'url(#shatch)' : r.shaft || r.common ? '#eceef1' : HEAT[heatClass(r.area, br)];
    const P = r.points.map(q => [q[0] * W, q[1] * H]); let A = 0, cx = 0, cy = 0;
    for (let i = 0; i < P.length - 1; i++) { const c = P[i][0] * P[i + 1][1] - P[i + 1][0] * P[i][1]; A += c; cx += (P[i][0] + P[i + 1][0]) * c; cy += (P[i][1] + P[i + 1][1]) * c; }
    const lab = Math.abs(A) > 1e-6 ? `<text x="${cx / (3 * A)}" y="${cy / (3 * A)}" font-size="${fs}" dominant-baseline="central" class="snum">${esc(r.number)}</text>` : '';
    return `<polygon points="${P.map(p => p.join(',')).join(' ')}" fill="${fill}" fill-opacity=".72" stroke="#16191d" stroke-width="${fs / 8}"/>${lab}`;
  }).join('');
  const groups = [...new Set(d.rooms.map(r => r.unit || ''))].sort((a, b) => (a === '') - (b === '') || a.localeCompare(b));
  const tbl = groups.map(u => {
    const rs = d.rooms.filter(r => (r.unit || '') === u), liv = rs.filter(inLiving), net = liv.reduce((s, r) => s + r.area, 0);
    const rows = rs.map(r => `<tr class="${r.outdoor || r.shaft ? 'ex' : r.common ? 'cm' : ''}"><td class="no">${esc(r.number)}</td><td>${esc(r.name || 'unnamed')}${r.outdoor ? ' <small>outdoor</small>' : r.shaft ? ' <small>shaft / void</small>' : r.common ? ' <small>common</small>' : ''}</td><td class="q">${round2(r.area)} m²</td></tr>`).join('');
    const foot = u ? `<tr class="sub"><td></td><td>Net living area, apartment ${esc(u)} <small>(${liv.length} rooms, outdoor excluded)</small></td><td class="q">${round2(net)} m²</td></tr>` : '';
    return `<tbody><tr class="gh"><th colspan="3">${u ? 'Apartment ' + esc(u) : 'Common areas and unassigned rooms'}</th></tr>${rows}${foot}</tbody>`;
  }).join('');
  const indoor = d.rooms.filter(r => !r.outdoor && !r.shaft), outdoor = d.rooms.filter(r => r.outdoor);
  const sum = rs => round2(rs.reduce((s, r) => s + r.area, 0));
  const counts = SYM.filter(([k]) => d.counts[k]).map(([k, n]) => `<tr><td>${n}</td><td class="q">${d.counts[k]}</td></tr>`).join('');
  sheetWrap.innerHTML = `<div class="sheettools"><span>Takeoff sheet · ${esc(name)}</span><span class="grow"></span>
      <button class="btn ghost" id="sheetcsv">⬇ CSV</button><button class="btn" id="sheetprint">Print / PDF</button><button class="btn ghost" id="sheetclose" aria-label="Close">Close</button></div>
    <article class="sheet">
      <header class="sh"><div><div class="sk">Room schedule and symbol takeoff</div><h1>${esc(name)}</h1></div>
        <div class="sm">Measured from the CAD layers of the drawing (DXF twin)<br>no AI model involved · $0 · ${new Date().toLocaleDateString('en-GB', {day: 'numeric', month: 'short', year: 'numeric'})}</div></header>
      <div class="splan"><svg viewBox="${x0 * W} ${y0 * H} ${(x1 - x0) * W} ${(y1 - y0) * H}"><defs><pattern id="shatch" patternUnits="userSpaceOnUse" width="${fs * .8}" height="${fs * .8}" patternTransform="rotate(45)"><rect width="${fs * .8}" height="${fs * .8}" fill="#f3f4f6"/><line x1="0" y1="0" x2="0" y2="${fs * .8}" stroke="#a7aeb8" stroke-width="${fs / 5}"/></pattern></defs>
        <image href="${img.src}" x="0" y="0" width="${W}" height="${H}"/>${polys}</svg>
        <div class="slegend"><span>Net area per room</span>${HEAT.map((c, i) => `<span class="sw"><i style="background:${c}"></i>${i ? (i < 4 ? br[i - 1] + '–' + br[i] : '≥ ' + br[3]) : '< ' + br[0]} m²</span>`).join('')}<span class="sw"><i class="hatch"></i>outdoor</span></div></div>
      <div class="scols">
        <table class="st"><thead><tr><th>No.</th><th>Room</th><th class="q">Net area</th></tr></thead>${tbl}
          <tbody class="tot"><tr><td></td><td>All numbered indoor rooms <small>(${indoor.length})</small></td><td class="q">${sum(indoor)} m²</td></tr>
          <tr><td></td><td>Outdoor spaces <small>(${outdoor.length}, not in net area)</small></td><td class="q">${sum(outdoor)} m²</td></tr></tbody></table>
        <div><table class="st cnt"><thead><tr><th>Symbol counts</th><th class="q">Count</th></tr></thead><tbody>${counts}</tbody></table>
          <p class="snote">Each count is one symbol on its CAD layer (DOOR, WINDOW, sanitary fixtures). Areas are net: the printed room area where the plan has one, else the outline less any shafts inside it.</p></div>
      </div>
      <footer class="scredit">© ${esc(d.credit || '')}</footer>
    </article>`;
  sheetWrap.hidden = false; document.body.classList.add('sheeton');
  $('#sheetclose').onclick = closeSheet; $('#sheetprint').onclick = () => window.print();
  $('#sheetcsv').onclick = () => {
    const rows = [['section', 'apartment', 'room no.', 'room', 'net area m²', 'in net living area'],
      ...d.rooms.map(r => ['room', r.unit || '', r.number, r.name, round2(r.area), inLiving(r) ? 'yes' : 'no']),
      ...groups.filter(Boolean).map(u => ['apartment total', u, '', 'net living area', round2(d.rooms.filter(r => r.unit === u && inLiving(r)).reduce((s, r) => s + r.area, 0)), '']),
      ['floor total', '', '', 'all numbered indoor rooms', sum(indoor), ''],
      ...SYM.filter(([k]) => d.counts[k]).map(([k, n]) => ['count', '', '', n, d.counts[k], '']),
      ['credit', '', '', d.credit || '', '', '']];
    downloadCSV(rows, `rooms-${name}.csv`);
  };
  sheetWrap.scrollTop = 0; $('#sheetprint').focus();
}
function closeSheet() { sheetWrap.hidden = true; document.body.classList.remove('sheeton'); }

// ------------------------------------------------------------ ask by voice
// The mic sits in the ask box; while it listens, a strip under the box shows what is happening and the language it
// listens for. Two engines, picked once at load:
//  - server (when /api/transcribe says it is available): the browser records the question (MediaRecorder), a level
//    meter and timer show it is listening, it stops on a click, after ~1.5 s of silence or at 20 s, and the audio
//    goes to our server, which has ElevenLabs Scribe turn it into text. Works in every browser with a microphone,
//    Firefox included.
//  - browser (fallback): the Web Speech API (Chrome, Edge, Safari), words appear as they are heard.
// Either way the text is asked straight away. With neither, the mic is not shown.
const VOICE_LANGS = [['en-US', 'English'], ['fi-FI', 'Suomi'], ['de-DE', 'Deutsch'], ['fr-FR', 'Français'], ['it-IT', 'Italiano'],
                     ['nl-NL', 'Nederlands'], ['sv-SE', 'Svenska']];
const voice = {rec: null, lang: null, final: '', timer: 0, engine: null};
(async () => {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const canRecord = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  let server = false;
  if (canRecord) {
    try { const j = await (await fetch('/api/transcribe')).json(); server = !!j.available && !j.over_cap; } catch {}
  }
  if (!server && !SR) return;
  voice.engine = server ? 'server' : 'browser';
  const NOTE = {
    server: 'Your recording is sent to ElevenLabs to turn it into text; we keep only the text.',
    browser: "Speech-to-text is done by your browser's provider (Google in Chrome, Microsoft in Edge, Apple in Safari); we only receive the text."};
  const TITLE = {
    server: 'Ask by voice: your recording is sent to ElevenLabs to turn it into text; we keep only the text',
    browser: 'Ask by voice: your browser turns speech into text (Chrome and Edge send the audio to Google or Microsoft, Safari to Apple); we only receive the text'};
  const langs = () => voice.engine === 'server' ? [['auto', 'Detect language'], ...VOICE_LANGS] : VOICE_LANGS;
  const pick = () => {
    const saved = localStorage.getItem('bp_voice_lang'); if (langs().some(l => l[0] === saved)) return saved;
    if (voice.engine === 'server') return 'auto';  // Scribe detects the language well; a wrong forced hint garbles it
    for (const n of navigator.languages || [navigator.language || '']) {
      const hit = VOICE_LANGS.find(l => l[0].toLowerCase() === n.toLowerCase()) || VOICE_LANGS.find(l => l[0].slice(0, 2) === n.slice(0, 2).toLowerCase());
      if (hit) return hit[0];
    }
    return 'en-US';
  };
  const mic = document.createElement('button');
  mic.id = 'mic'; mic.type = 'button'; mic.className = 'mic'; mic.setAttribute('aria-label', 'Ask by voice'); mic.setAttribute('aria-pressed', 'false');
  mic.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" fill="currentColor"/><path d="M6 11a6 6 0 0 0 12 0M12 17v4M8.5 21h7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
  $('#go').before(mic);
  const strip = document.createElement('div'); strip.id = 'voice'; strip.className = 'voice'; strip.hidden = true; strip.setAttribute('aria-live', 'polite');
  strip.innerHTML = `<div class="vrow"><span class="vdot"></span><b class="vstate">Listening</b>
      <select class="vlang" aria-label="Language to listen for"></select>
      <span class="grow"></span><button type="button" class="linkish vdone" hidden>done</button><button type="button" class="linkish vstop">stop</button></div>
    <div class="vtext"><span class="vmeter" hidden aria-hidden="true"><i></i></span><span class="vtime" hidden></span><span class="vfin"></span><span class="vint"></span></div>
    <div class="vnote"></div>`;
  $('.ask').after(strip);
  const sel = strip.querySelector('.vlang');
  const setEngine = e => {
    voice.engine = e; mic.title = TITLE[e]; strip.querySelector('.vnote').textContent = NOTE[e];
    sel.innerHTML = langs().map(([c, n]) => `<option value="${c}">${c === 'auto' ? n : `${n} · ${c}`}</option>`).join('');
    voice.lang = pick(); sel.value = voice.lang;
  };
  setEngine(voice.engine);
  const show = (state, msg) => {
    strip.hidden = state === 'idle'; strip.dataset.state = state; mic.classList.toggle('on', state === 'listening');
    mic.setAttribute('aria-pressed', state === 'listening');
    const sb = strip.querySelector('.vstop'); sb.textContent = state === 'error' ? 'dismiss' : voice.engine === 'server' ? 'cancel' : 'stop';
    sb.hidden = state === 'asking' || state === 'transcribing';
    const rec = state === 'listening' && voice.engine === 'server';
    strip.querySelector('.vdone').hidden = !rec; strip.querySelector('.vmeter').hidden = !rec; strip.querySelector('.vtime').hidden = !rec;
    strip.querySelector('.vstate').textContent = msg || {listening: 'Listening', transcribing: 'Transcribing', asking: 'Asking', error: 'Voice'}[state] || '';
  };
  const text = (fin, int) => { strip.querySelector('.vfin').textContent = fin; strip.querySelector('.vint').textContent = int; };
  const fail = why => { show('error', 'Voice'); text(why, ''); voice.timer = setTimeout(() => { if (!voice.rec) show('idle'); }, 6000); };
  const stop = () => { if (voice.rec) { const r = voice.rec; voice.rec = null; try { r.abort(); } catch {} } };

  // ---- server engine: record, detect the end of speech, upload
  const MAX_S = 20, SILENCE_S = 1.5, NO_SPEECH_S = 7;
  const record = async () => {
    stop(); clearTimeout(voice.timer);
    const sess = {aborted: false, abort() { this.aborted = true; this.cleanup(); }, cleanup() {}};
    voice.rec = sess; voice.final = '';
    text('', 'Allow the microphone, then speak…'); show('listening');
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, channelCount: 1}}); }
    catch (e) {
      if (voice.rec !== sess) return; voice.rec = null;
      fail(e && e.name === 'NotAllowedError' ? 'Microphone access is blocked: allow it in the site settings, or type the question.'
        : e && e.name === 'NotFoundError' ? 'No microphone found. Type the question instead.' : 'Could not start the microphone. Type the question instead.');
      return;
    }
    if (voice.rec !== sess) { stream.getTracks().forEach(t => t.stop()); return; }
    const mime = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/mp4'].find(m => MediaRecorder.isTypeSupported(m)) || '';
    let mr;
    try { mr = new MediaRecorder(stream, {...(mime ? {mimeType: mime} : {}), audioBitsPerSecond: 32000}); }
    catch { stream.getTracks().forEach(t => t.stop()); voice.rec = null; fail('This browser cannot record audio. Type the question instead.'); return; }
    const chunks = []; mr.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
    const AC = window.AudioContext || window.webkitAudioContext; let ac = null, an = null, buf = null;
    try { ac = new AC(); an = ac.createAnalyser(); an.fftSize = 1024; ac.createMediaStreamSource(stream).connect(an); buf = new Float32Array(an.fftSize); } catch { ac = null; }
    if (ac && ac.state !== 'running') ac.resume().catch(() => {});  // until it runs there is no meter: stop on click / at 20 s
    const meter = strip.querySelector('.vmeter i'), clock = strip.querySelector('.vtime');
    const t0 = performance.now(); let vad = false, heard = false, lastLoud = t0, floor = 0.004, tick = 0, done = false;
    sess.cleanup = () => {
      clearInterval(tick); stream.getTracks().forEach(t => t.stop()); if (ac) ac.close().catch(() => {});
      if (mr.state !== 'inactive') try { mr.stop(); } catch {}
    };
    const finish = () => { if (done || voice.rec !== sess) return; done = true; clearInterval(tick); try { mr.stop(); } catch { sess.cleanup(); } };
    sess.finish = finish;
    mr.onstop = async () => {
      sess.cleanup();
      if (sess.aborted || voice.rec !== sess) return;
      const secs = (performance.now() - t0) / 1000;
      if (vad && !heard) { voice.rec = null; fail('Nothing heard. Press the mic and speak, or type the question.'); return; }
      const blob = new Blob(chunks, {type: mr.mimeType || mime || 'audio/webm'});
      show('transcribing'); text('', 'Turning speech into text…');
      const lang = voice.lang === 'auto' ? '' : voice.lang;
      let r, j = {};
      try {
        r = await fetch(`/api/transcribe?lang=${encodeURIComponent(lang)}&secs=${secs.toFixed(1)}`,
                        {method: 'POST', body: blob, headers: {'Content-Type': blob.type.split(';')[0] || 'application/octet-stream'}});
        j = await r.json().catch(() => ({}));
      } catch { r = null; }
      if (voice.rec !== sess) return;
      voice.rec = null;
      if (!r || !r.ok) {
        if (r && (r.status === 503 || (r.status === 429 && /budget/.test(j.detail || ''))) && SR) setEngine('browser');  // fall back next time
        fail((j && j.detail) || 'Speech-to-text is unreachable. Type the question instead.'); return;
      }
      const q = (j.text || '').trim();
      if (!q) { fail('Nothing heard. Press the mic and speak, or type the question.'); return; }
      voice.final = q; voice.heard = j.language; submit(sess);
    };
    tick = setInterval(() => {
      const now = performance.now(), el = (now - t0) / 1000;
      clock.textContent = `0:${String(Math.floor(el)).padStart(2, '0')}`;
      if (an && ac.state === 'running') {
        vad = true; an.getFloatTimeDomainData(buf);
        let s = 0; for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i];
        const rms = Math.sqrt(s / buf.length);
        if (!heard) floor = Math.min(0.05, floor * 0.95 + rms * 0.05);  // ambient level before speech starts
        const loud = rms > Math.max(0.015, floor * 3);
        if (loud) { lastLoud = now; if (!heard && el > 0.15) { heard = true; text('', 'Listening… stops when you pause'); } }
        meter.style.width = `${Math.min(100, Math.round(rms * 400))}%`;
        if (heard && (now - lastLoud) / 1000 > SILENCE_S) finish();
        if (!heard && el > NO_SPEECH_S) finish();  // onstop then says "Nothing heard" without uploading
      }
      if (el >= MAX_S) finish();
    }, 50);
    mr.start();
    text('', 'Speak your question…');
  };

  // ---- browser engine: Web Speech API
  const listen = () => {
    stop(); clearTimeout(voice.timer);
    const rec = new SR(); voice.rec = rec; voice.final = '';
    rec.lang = voice.lang; rec.interimResults = true; rec.continuous = false; rec.maxAlternatives = 1;
    rec.onresult = e => {
      if (voice.rec !== rec) return;
      let fin = '', int = '';
      for (let i = 0; i < e.results.length; i++) (e.results[i].isFinal ? (fin += e.results[i][0].transcript) : (int += e.results[i][0].transcript));
      voice.final = fin.trim(); text(fin, int ? (fin ? ' ' : '') + int : '');
      $('#q').value = (fin + int).trim();
      if (fin && !int) submit(rec);
    };
    rec.onerror = e => {
      if (voice.rec !== rec) return;
      voice.rec = null;
      const why = e.error === 'not-allowed' || e.error === 'service-not-allowed' ? 'Microphone access is blocked: allow it in the site settings, or type the question.'
        : e.error === 'no-speech' ? 'Nothing heard. Press the mic and speak, or type the question.'
        : e.error === 'audio-capture' ? 'No microphone found. Type the question instead.'
        : e.error === 'network' ? 'Speech recognition needs a connection. Type the question instead.'
        : e.error === 'language-not-supported' ? 'This browser cannot listen for that language. Pick another one, or type.'
        : e.error === 'aborted' ? '' : 'Voice input stopped. Type the question instead.';
      if (!why) { show('idle'); return; }
      fail(why);
    };
    rec.onend = () => { if (voice.rec !== rec) return; voice.rec = null; if (voice.final) submit(rec); else show('idle'); };
    text('', 'Speak your question…'); show('listening');
    try { rec.start(); } catch { voice.rec = null; show('idle'); }
  };
  const start = () => { speakStop(); return voice.engine === 'server' ? record() : listen(); };  // don't record our own voice
  const submit = rec => {
    if (rec.submitted) return; rec.submitted = true;
    if (voice.rec === rec) { voice.rec = null; try { rec.stop(); } catch {} }
    const q = voice.final; if (!q) { show('idle'); return; }
    $('#q').value = q; show('asking', 'Asking'); text(q, '');
    speakVoiceAsked(q, voice.engine === 'server' && voice.lang === 'auto' ? voice.heard : voice.lang);
    voice.timer = setTimeout(() => show('idle'), 1200);
    ask();
  };
  // a click on the mic while recording means "done, send it"; the strip's cancel/stop discards
  mic.onclick = () => {
    if (!voice.rec) start();
    else if (voice.rec.finish) voice.rec.finish();
    else { stop(); show('idle'); }
  };
  strip.querySelector('.vdone').onclick = () => { if (voice.rec && voice.rec.finish) voice.rec.finish(); };
  strip.querySelector('.vstop').onclick = () => { stop(); show('idle'); };
  sel.onchange = () => { voice.lang = sel.value; localStorage.setItem('bp_voice_lang', voice.lang); if (voice.rec && !voice.rec.finish) start(); };
  window.bpVoice = {start, stop, get lang() { return voice.lang; }, get engine() { return voice.engine; }};
})();

// ------------------------------------------------------------ spoken answers (ElevenLabs text-to-speech)
// Self-contained: renderAnswer calls speakTools(counting) and the voice code calls speakVoiceAsked / speakStop.
// The server says the answer as one short sentence in the question's language (it builds the sentence from the
// answer it returned; we only send the answer's speak_id). A question asked by voice is answered out loud once the
// X-ray count has finished, unless auto-read is off (remembered); every answer card gets a read-aloud button.
// When the server has no text-to-speech (no key, no permission, budget used) nothing is shown; it is asked again
// every few minutes, so the button appears once it is switched on.
const speak = {on: false, checked: 0, recheck: 180, audio: null, url: '', seq: null, busy: false, voiceQ: null, voiceLang: null, spokenSeq: null,
               auto: localStorage.getItem('bp_speak_auto') !== '0'};
async function speakCheck(force) {
  if (!force && performance.now() - speak.checked < speak.recheck * 1000) return;
  speak.checked = performance.now();
  try { const j = await (await fetch('/api/speak')).json(); speak.on = !!j.available && !j.over_cap; if (j.recheck_s) speak.recheck = Math.max(60, j.recheck_s); }
  catch { speak.on = false; }
  speakTools(false, true);
}
function speakStop() {
  if (speak.audio) { speak.audio.pause(); speak.audio.removeAttribute('src'); speak.audio.load(); }
  if (speak.url) { URL.revokeObjectURL(speak.url); speak.url = ''; }
  speak.seq = null; speak.busy = false; speakTools(false, true);
}
function speakVoiceAsked(q, lang) { speak.voiceQ = String(q || '').trim(); speak.voiceLang = lang || null; }
async function speakNow(r, lang = null) {
  if (!r || !r.speak_id) return;
  speakStop(); speak.seq = r._seq; speak.busy = true; speakTools(false, true);
  try {
    const resp = await fetch('/api/speak', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({id: r.speak_id, lang})});
    if (speak.seq !== r._seq) return;
    if (!resp.ok) { if (resp.status === 503) { speak.on = false; speak.checked = performance.now(); } speakStop(); return; }
    speak.url = URL.createObjectURL(await resp.blob());
    if (speak.seq !== r._seq) { URL.revokeObjectURL(speak.url); speak.url = ''; return; }
    if (!speak.audio) { speak.audio = new Audio(); speak.audio.onended = speak.audio.onerror = () => { speak.seq = null; speakTools(false, true); }; }
    speak.audio.src = speak.url; speak.busy = false; speakTools(false, true);
    await speak.audio.play();
  } catch { if (speak.seq === r._seq) speakStop(); }
}
function speakTools(counting, refresh) {
  const box = $('#qtools'); if (!box || !res) return;
  if (speak.seq != null && speak.seq !== res._seq) speakStop();  // a new answer silences the old one
  // no button mid-count: each tick re-renders the card, so a click there would land on a button that is gone
  const off = !speak.on || !res.speak_id || res.method === 'rate-limit' || counting;
  let b = box.querySelector('.speakbtn'), t = box.querySelector('.speakauto');
  if (off) { if (b) b.remove(); if (t) t.remove(); if (!refresh && !counting) speakCheck(); return; }
  if (!b) {
    b = document.createElement('button'); b.type = 'button'; b.className = 'speakbtn'; box.appendChild(b);
    b.onclick = ev => { ev.stopPropagation(); speak.seq === res._seq ? speakStop() : speakNow(res); };
  }
  const playing = speak.seq === res._seq;
  b.setAttribute('aria-label', playing ? 'Stop reading aloud' : 'Read the answer aloud');
  b.title = playing ? 'Stop' : 'Read aloud (ElevenLabs voice)';
  b.setAttribute('aria-pressed', String(playing));
  b.innerHTML = playing
    ? '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg>'
    : '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M4 9h4l5-4v14l-5-4H4z" fill="currentColor"/><path d="M16 9a4 4 0 0 1 0 6M18.5 6.5a7.5 7.5 0 0 1 0 11" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
  if (window.bpVoice) {  // auto-read only matters when you can ask by voice
    if (!t) {
      t = document.createElement('button'); t.type = 'button'; t.className = 'speakauto'; box.appendChild(t);
      t.onclick = ev => { ev.stopPropagation(); speak.auto = !speak.auto; localStorage.setItem('bp_speak_auto', speak.auto ? '1' : '0'); if (!speak.auto) speakStop(); speakTools(false, true); };
    }
    t.setAttribute('aria-pressed', String(speak.auto));
    t.title = speak.auto ? 'Answers to voice questions are read aloud: click to mute' : 'Voice questions are answered silently: click to read answers aloud';
    t.setAttribute('aria-label', speak.auto ? 'Mute spoken answers to voice questions' : 'Read answers to voice questions aloud');
    t.style.width = 'auto'; t.style.padding = '0 6px'; t.style.fontSize = '11px';
    t.textContent = speak.auto ? 'auto' : 'muted';
  }
  // a voice question: speak once, after the count (renderAnswer calls us with counting=false when it has finished)
  if (!counting && !refresh && speak.auto && speak.spokenSeq !== res._seq && speak.voiceQ && speak.voiceQ === String(res.question || '').trim()) {
    const lang = speak.voiceLang; speak.spokenSeq = res._seq; speak.voiceQ = null; speakNow(res, lang);
  }
}
speakCheck(true);
window.bpSpeak = {get on() { return speak.on; }, get audio() { return speak.audio; }, get auto() { return speak.auto; }, speakNow: () => speakNow(res), stop: speakStop, check: () => speakCheck(true)};

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
  if (RMOTION.matches) { q.value = text; return; }  // reduced motion: the question appears at once, not typed out
  const dt = Math.max(12, Math.min(40, 1400 / text.length));
  for (const ch of text) { q.value += ch; await sleep(dt); }
}
async function runStep() {
  const s = tour[tourI];
  $('#caption').hidden = false; document.body.classList.add('touring');
  $('#capstep').textContent = `Tour · ${tourI + 1} of ${tour.length}`;
  $('#captitle').textContent = s.title; $('#captext').textContent = s.caption || '';
  capFit();
  $('#tnext').textContent = tourI === tour.length - 1 ? 'Finish' : 'Next';
  $('#tprev').disabled = tourI === 0;
  const myI = tourI;
  if (s.path && (!cur || cur.path !== s.path)) {
    tab = s.source || tab;
    await select({path: s.path, source: s.source, split: s.split || ''}, 'replace');
    loadList();
  }
  if (s.question) {
    secOpen.vs = secOpen.how = false; $('#evwrap').open = false;
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
// open one folded section of the answer card (ev: Evidence, vs: Frontier models, how: How it was worked out) and bring it
// into view, keeping the big number on screen when it fits (on a phone, keepView leaves the drawing in view)
async function openSec(name, keepView = false) {
  const d = name === 'ev' ? $('#evwrap') : $(`#answer details[data-sec="${name}"]`); if (!d || d.hidden) return;
  if (name !== 'ev') secOpen[name] = true;
  d.open = true;
  await sleep(50);
  if (PHONE.matches) { if (!keepView) d.scrollIntoView({behavior: smooth(), block: 'start'}); }
  else {
    const side = $('#side'), top = el => el.getBoundingClientRect().top - side.getBoundingClientRect().top + side.scrollTop;
    const card = top($('#answer')) - 12, want = top(d) + d.offsetHeight - side.clientHeight + 16;
    side.scrollTo({top: Math.max(0, Math.min(card, Math.max(side.scrollTop, want))), behavior: smooth()});
  }
  await sleep(900);
}
async function doAction(act) {
  const [k, arg] = act.split(':');
  if (k === 'wait') await sleep(+arg);
  else if (k === 'toggle') {
    const i = +arg, r0 = res; if (!items[i]) return;
    await openSec('ev');  // the evidence list is folded: open it so the change is seen
    const row = $(`#ev div[data-i="${i}"]`); if (row && PHONE.matches) { row.scrollIntoView({behavior: smooth(), block: 'center'}); await sleep(600); }
    if (res !== r0 || !items[i]) return;
    hotItem(i, true); rowHot(i, true, true); await sleep(700);
    if (res !== r0 || !items[i]) return;  // the tour moved on meanwhile
    items[i].on = !items[i].on; redraw(); hotItem(i, false); flashRow(i); await sleep(900);
  } else if (k === 'add') {
    const [u, v] = arg.split(',').map(Number); const r = img.getBoundingClientRect();
    setAdding(true); await sleep(500); addAt(r.left + u * r.width, r.top + v * r.height); await sleep(600); setAdding(false);
  } else if (k === 'mode') await setMode(arg);
  else if (k === 'storey') { storeyFocus = arg; $('#storey').value = arg; applyStorey(true); await sleep(600); }
  // on a phone the 3D view is the point of a 3D step: open the section without scrolling the drawing away
  else if (k === 'trace') { if (arg === 'close') { secOpen.how = false; const d = $('#answer details[data-sec="how"]'); if (d) d.open = false; } else await openSec('how', mode === '3d'); }
  else if (k === 'scroll') await openSec(arg === '.vs' ? 'vs' : arg.replace(/^\./, ''));
  else if (k === 'open') await openSec(arg);
  else if (k === 'hover') { const i = +arg; if (!items[i]) return; hotItem(i, true); rowHot(i, true, true); await sleep(1400); hotItem(i, false); rowHot(i, false); }
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
  else if (!q && res) { askSeq++; res = null; items = []; marks = []; ov.innerHTML = ''; $('#answer').hidden = true; $('#evwrap').hidden = true; setAnswered(false); $('#q').value = ''; fit(); }
}
window.addEventListener('popstate', () => { if (tour) endTour(); restore(false); });

// ------------------------------------------------------------ keyboard
document.addEventListener('keydown', e => {
  const typing = e.target.matches('input, textarea, select');
  if (xr && !typing && !['Shift', 'Control', 'Alt', 'Meta'].includes(e.key)) {  // any key skips the count (and does only that)
    if (e.key === ' ' || e.key === 'Enter') e.preventDefault();
    xraySkip(); if (e.key !== 'Escape') return;
  }
  if (e.key === 'Escape') {
    if (!sheetWrap.hidden) closeSheet();
    else if (tour) endTour();
    else if (adding) setAdding(false);
    else if (popOpen) closePop();
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
$('#scrim').onclick = () => closePop(false);

// ------------------------------------------------------------ start
(async () => {
  const p = new URLSearchParams(location.search);  // read before restore(), which rewrites the URL
  await restore(true);
  if (p.has('tour')) startTour(p.get('tour') === 'auto');
})();
