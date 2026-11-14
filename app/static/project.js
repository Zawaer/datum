// Projects (app/projects.py): drop several drawings (or a .zip) and ask them as one building.
// Additive to app.js: it wraps ask / renderAnswer / select / syncURL by name, and the single-file flow is unchanged
// when no project is open. A clarify ({question, options}) on any answer, project or not, becomes one-tap buttons.
(() => {
  let proj = null;          // the open project: {id, sheets, buildings, files}
  let agg = null;           // the last whole-building answer, while one of its floors is open
  const PKEY = 'bp_projects';
  const kindName = {arch: 'Architectural', slab: 'Slab', piping: 'Piping'};
  const inProj = path => !!(proj && proj.files.some(f => f.path === path));
  const sheetLabel = s => [s.level && s.level.label, s.sheet_id].filter(Boolean).join(' · ') || s.title || s.file;

  // ------------------------------------------------------------ the project panel (side) / floor strip (phone)
  const panel = document.createElement('section');
  panel.id = 'proj'; panel.hidden = true; panel.setAttribute('aria-label', 'Project sheets');
  document.querySelector('#side .ask').before(panel);
  function curRef() {
    if (!proj || !cur) return null;
    const s = proj.sheets.find(s => s.path === cur.path && (s.pages <= 1 || s.page === (cur.page || 0)));
    return s ? s.ref : null;
  }
  function renderPanel() {
    if (!proj) { panel.hidden = true; document.body.classList.remove('hasproj'); return; }
    panel.hidden = false; document.body.classList.add('hasproj');
    const ref = curRef(), multiB = proj.buildings.length > 1;
    const groups = proj.buildings.map(b => {
      const rows = proj.sheets.filter(s => s.building === b).map(s => `<button type="button" class="psheet${s.ref === ref ? ' on' : ''}" data-ref="${esc(s.ref)}" title="${esc(s.file)}${s.pages > 1 ? ` · page ${s.page + 1}` : ''}">
          <span class="plv">${esc(s.level ? s.level.label : s.sheet_id || 'Sheet')}</span>
          <span class="pti">${esc(s.sheet_id && s.level ? s.sheet_id + ' · ' : '')}${esc(s.title || s.file)}</span>
          ${s.kind ? `<span class="pki">${esc(kindName[s.kind] || s.kind)}</span>` : ''}</button>`).join('');
      return `${multiB ? `<div class="pbld">${esc(b)}</div>` : ''}${rows}`;
    }).join('');
    const n = proj.sheets.length;
    panel.innerHTML = `<div class="phead"><span><b>Project</b> · ${esc(multiB ? proj.buildings.length + ' buildings' : proj.buildings[0] || '')} · ${n} sheet${n === 1 ? '' : 's'}</span>
        <label class="padd" tabindex="0" title="Add drawings to this project">Add files<input type="file" multiple hidden accept="${esc($('#file').accept)},.zip"></label>
        <button type="button" class="pclose" aria-label="Close the project" title="Close the project">✕</button></div>
      <div class="plist">${groups}</div>`;
    panel.querySelectorAll('.psheet').forEach(b => b.onclick = () => openRef(b.dataset.ref));
    panel.querySelector('.padd input').onchange = e => { const fs = [...e.target.files]; e.target.value = ''; if (fs.length) projectUpload(fs); };
    panel.querySelector('.padd').onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); panel.querySelector('.padd input').click(); } };
    panel.querySelector('.pclose').onclick = () => closeProject();
  }
  function closeProject() {
    proj = null; agg = null; renderPanel();
    const u = new URL(location.href); u.searchParams.delete('project'); history.replaceState(null, '', u.pathname + u.search);
  }
  async function openSheet_(s) {
    if (!cur || cur.path !== s.path) await select({path: s.path, source: 'upload', split: 'upload', kind: s.kind});
    if (s.pages > 1 && (cur.page || 0) !== s.page) { cur.pin = s.page; showImage(cur.view, s.page); }
    renderPanel();
  }
  async function openRef(ref) {
    const s = proj && proj.sheets.find(x => x.ref === ref); if (!s) return;
    agg = null; await openSheet_(s); suggest();
  }
  function suggest() {
    if (!proj) return;
    const plans = proj.sheets.filter(s => s.level && (!s.kind || s.kind === 'arch'));
    const qs = [];
    if (plans.length > 1) qs.push('How many doors in the whole building?', 'What is the total floor area of the building?');
    const other = plans.find(s => s.ref !== curRef());
    if (other) qs.push(`How many doors on ${other.level.label}?`);
    if (qs.length) renderChips([], qs);
  }

  // ------------------------------------------------------------ uploads: several files, or a .zip, make a project
  const isZip = f => /\.zip$/i.test(f.name);
  async function projectUpload(files) {
    const fails = [];
    try {
      if (!proj) {
        const r = await fetch('/api/projects', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
        if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
        proj = await r.json();
      }
      for (let i = 0; i < files.length; i++) {
        const f = files[i], msg = `Adding ${files.length > 1 ? `${i + 1} of ${files.length}: ` : ''}${f.name} (${(f.size / 1e6).toFixed(1)} MB)…`;
        loading(msg);
        const rid = Math.random().toString(36).slice(2, 14);
        const unwatch = watchQueue('rid=' + rid, q => loading(q ? 'Queued behind other uploads…' : msg));
        try {
          const r = await fetch(`/api/projects/${proj.id}/upload?name=${encodeURIComponent(f.name)}&rid=${rid}`, {method: 'POST', body: f}).finally(unwatch);
          const d = await r.json();
          if (!r.ok) { fails.push(`${f.name}: ${d.detail || r.statusText}`); continue; }
          proj = d.project;
          for (const s of d.skipped || []) fails.push(`${s.name}: ${s.why}`);
          for (const u of d.uploads || []) uploads = [u, ...uploads.filter(x => x.path !== u.path)].slice(0, 30);
          localStorage.setItem('bp_uploads', JSON.stringify(uploads));
        } catch (err) { fails.push(`${f.name}: ${err.message}`); }
      }
      loading('');
      remember();
      if (!proj.sheets.length) { hint('Nothing could be added: ' + fails.join('; ')); proj = null; renderPanel(); return; }
      const plans = proj.sheets.filter(s => s.drawing && (!s.kind || s.kind === 'arch'));
      const first = [...(plans.length ? plans : proj.sheets)].sort((a, b) => ((a.level || {}).n ?? 50) - ((b.level || {}).n ?? 50))[0];
      agg = null;
      await openSheet_(first);
      suggest();
      if (fails.length) hint('Not added: ' + fails.join('; ').slice(0, 300));
      $('#q').focus();
    } catch (err) { loading(''); hint('Upload failed: ' + err.message); }
  }
  function remember() {
    const list = JSON.parse(localStorage.getItem(PKEY) || '[]').filter(x => x !== proj.id);
    localStorage.setItem(PKEY, JSON.stringify([proj.id, ...list].slice(0, 10)));
    const u = new URL(location.href);
    if (u.searchParams.get('project') !== proj.id) { u.searchParams.set('project', proj.id); history.replaceState(null, '', u.pathname + u.search); }
  }
  // the file picker and drag-and-drop: one file goes the old way; several (or a .zip) become a project
  $('#file').multiple = true;
  $('#file').accept += ',.zip';
  const small = document.querySelector('#uploadbox small');
  if (small) small.textContent = 'PDF, image, DXF or IFC · several files or a .zip make a project';
  const oneUpload = $('#file').onchange;
  $('#file').onchange = e => {
    const fs = [...e.target.files];
    if (fs.length > 1 || fs.some(isZip)) { e.target.value = ''; closePicker(); projectUpload(fs); } else oneUpload(e);
  };
  window.addEventListener('drop', e => {
    const fs = [...(e.dataTransfer?.files || [])];
    if (!(fs.length > 1 || fs.some(isZip) || (proj && fs.length && inProj(cur && cur.path)))) return;
    e.preventDefault(); e.stopImmediatePropagation(); $('#dropzone').hidden = true;
    projectUpload(fs);
  }, true);

  // ------------------------------------------------------------ asking a project
  const ask1 = ask;
  ask = async function () {  // eslint-disable-line no-global-assign
    if (!proj || !cur || !inProj(cur.path)) return ask1();
    const question = $('#q').value.trim(); if (!question) return;
    const seq = ++askSeq; agg = null;
    setAdding(false); pickTip(null); sheetFull(false);
    const a = $('#answer'); a.hidden = false; a.classList.remove('pop'); setAnswered(true); $('#atail').innerHTML = '';
    if (PHONE.matches) $('#q').blur();
    res = null; items = []; ov.innerHTML = ''; $('#evwrap').hidden = true; renderSheetEv();
    const t0 = performance.now();
    $('#ahead').innerHTML = `<div class="qecho">${esc(question)}</div><div class="thinking"><div><span class="spin"></span> <span class="tstep">Reading the project's sheets</span>…</div><small class="ttime"></small></div>`;
    const tick = () => { if (seq !== askSeq || res) return; const t = $('#ahead .ttime'); if (t) t.textContent = `${((performance.now() - t0) / 1000).toFixed(1)} s`; setTimeout(tick, 100); };
    tick();
    let r;
    try {
      const resp = await fetch(`/api/projects/${proj.id}/ask`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({question, sheet: curRef()})});
      r = await resp.json();
      if (!resp.ok) r = {answer: null, confidence: 0, evidence: [], explanation: r.detail || `server error ${resp.status}`, method: resp.status === 429 ? 'rate-limit' : 'error'};
    } catch (err) { r = {answer: null, confidence: 0, evidence: [], explanation: 'could not reach the server: ' + err.message, method: 'error'}; }
    if (seq !== askSeq) return;
    r.question = question;
    const sh = r.project && r.project.sheet;
    if (sh) { const s = proj.sheets.find(x => x.ref === sh.ref); if (s) await openSheet_(s); }
    if (r.project && r.project.parts && r.project.parts.length) agg = r;
    show(r);
  };
  $('#go').onclick = () => ask();

  // one result on screen: the same steps as app.js's ask() after its fetch
  async function show(r) {
    const seq = ++askSeq;
    res = r; res._seq = seq; showSecond = false;
    sheetResult(res); recordTakeoff(res); syncURL('replace');
    const a = $('#answer'); a.hidden = false; setAnswered(true); a.classList.remove('pop'); void a.offsetWidth; a.classList.add('pop');
    ov.innerHTML = '';
    setupEvidence();
    if (res.sheet_type && typeof res.answer === 'number' && Math.abs(items.reduce((s, e) => s + contrib(e), 0) - res.answer) > 0.005 * Math.abs(res.answer) + 1e-6) res._nocount = true;
    renderAnswer(items.length && typeof res.answer === 'number' && !res._nocount ? 0 : null);
    if (mode === '3d' && cur.shown) await setMode('2d');
    const go = () => { zoomToEvidence(); draw(true); };
    if (cur.shown && img.complete && img.naturalWidth && img.getAttribute('src') === '/api/render?path=' + encodeURIComponent(cur.shown) + (cur.page ? '&page=' + cur.page : '')) go();
    else pendingDraw = go;
    renderEvidence(); renderPanel();
  }
  async function openPart(i) {
    const A = agg, p = A && A.project.parts[i]; if (!p) return;
    const s = proj.sheets.find(x => x.ref === p.ref); if (!s) return;
    await openSheet_(s); agg = A;
    const r = {...p.result, question: A.question, _part: i, _agg: A};
    show(r);
  }
  async function backToTotal() {
    const A = agg; if (!A) return;
    ov.innerHTML = ''; items = [];
    show(A); agg = A;
  }

  // ------------------------------------------------------------ clarify buttons, best-guess label, per-floor parts
  const unitOf = r => r.unit || '';
  const valTxt = (v, u) => v == null ? 'no answer' : `${Number(v).toLocaleString('en-US', {maximumFractionDigits: 1})}${u ? ' ' + u : ''}`;
  // a clarify pick rides on the question as "(sheet: <ref>)" / "(room: Library)": shown as "… · Level 01"
  const PICK = /\s*\((room|closets|area|building|sheet): ([^)]*)\)/i;
  function prettyQ(q) {
    const said = [];
    const base = String(q).replace(new RegExp(PICK.source, 'gi'), (m, k, v) => {
      const s = k.toLowerCase() === 'sheet' && proj && proj.sheets.find(x => x.ref === v.trim());
      said.push(s ? sheetLabel(s) : v.trim() === 'all' ? (k.toLowerCase() === 'sheet' ? 'whole building' : 'all') : `${v.trim()}${/area/i.test(k) ? ' area' : ''}`);
      return '';
    }).trim();
    return said.length ? `${base} · ${said.join(' · ')}` : base;
  }
  function decorate() {
    if (!res) return;
    const ah = $('#ahead'); if (!ah || ah.querySelector('.thinking')) return;
    ah.querySelectorAll('.clar, .bestg, .pparts, .pscope').forEach(x => x.remove());
    const anchor = ah.querySelector('.qrow') || ah.firstElementChild;
    const qe = ah.querySelector('.qrow .qecho');
    if (qe && PICK.test(res.question || '')) qe.textContent = prettyQ(res.question);
    const add = (html, after) => { const t = document.createElement('div'); t.innerHTML = html; const el = t.firstElementChild; (after ? after.after(el) : ah.append(el)); return el; };
    let last = anchor;
    const c = res.clarify;
    if (c && c.options && c.options.length) {
      last = add(`<div class="clar" role="group" aria-label="${esc(c.question)}"><div class="clq">${esc(c.question)}</div>
        <div class="clopts">${c.options.map((o, i) => `<button type="button" class="clopt" data-i="${i}">${esc(o.label)}</button>`).join('')}</div></div>`, last);
      last.querySelectorAll('.clopt').forEach(b => b.onclick = () => { const o = c.options[+b.dataset.i]; $('#q').value = o.value; ask(); });
    }
    const pr = res.project;
    const chip = ah.querySelector('.sheetchip');
    if (chip && res.method === 'project-sum') { chip.textContent = `${pr.building} · ${pr.parts.length} floor plans`; chip.title = pr.why || ''; }
    if (res.best_guess && res.answer != null) {
      last = add(`<div class="bestg">Best guess${pr && pr.label ? `: ${esc(pr.label)}` : ''}. Pick above to be sure.</div>`, last);
    } else if (pr && pr.why && !(pr.parts || []).length) {
      last = add(`<div class="pscope">Read on ${esc(pr.why)}</div>`, last);
    }
    const A = res._agg || (pr && pr.parts && pr.parts.length ? res : null);
    if (A) {
      const parts = A.project.parts, u = unitOf(A);
      const rows = parts.map((p, i) => `<button type="button" class="ppart${res._part === i ? ' on' : ''}" data-i="${i}">
          <span>${esc(p.label)}</span><b>${esc(valTxt(p.value ?? (typeof p.answer === 'number' ? p.answer : null), p.unit || u))}</b><i aria-hidden="true">›</i></button>`).join('');
      const back = res._agg ? `<button type="button" class="linkish pback">‹ ${esc(A.project.building)} total: ${esc(valTxt(A.answer, u))}</button>` : '';
      const el = add(`<div class="pparts">${back}<div class="pcap">${res._agg ? 'Floors' : 'Per floor · tap one to see its marks'}</div>${rows}</div>`);
      el.querySelectorAll('.ppart').forEach(b => b.onclick = () => openPart(+b.dataset.i));
      const bk = el.querySelector('.pback'); if (bk) bk.onclick = backToTotal;
    }
  }
  const how1 = howOf;
  howOf = function (r) {  // eslint-disable-line no-global-assign
    if (r && r.method === 'project-sum' && r.answer != null) return {cls: 'sht', t: `Summed over ${r.project.parts.length} floor plans`, how: 'each floor was read on its own sheet; tap a floor to see its marks'};
    return how1(r);
  };
  const render1 = renderAnswer;
  renderAnswer = function (...args) { render1(...args); try { decorate(); } catch (e) { console.error(e); } };  // eslint-disable-line no-global-assign

  // ------------------------------------------------------------ leaving the project, URL state
  const select1 = select;
  select = async function (d, how) {  // eslint-disable-line no-global-assign
    if (proj && d && !inProj(d.path)) { proj = null; agg = null; renderPanel(); }
    return select1(d, how);
  };
  const sync1 = syncURL;
  syncURL = function (how) {  // eslint-disable-line no-global-assign
    sync1(how);
    if (!proj) return;
    const u = new URL(location.href);
    if (u.searchParams.get('project') !== proj.id) { u.searchParams.set('project', proj.id); history.replaceState(null, '', u.pathname + u.search); }
  };
  (async () => {  // a shared link: ?project=<id> opens the project
    const id = new URLSearchParams(location.search).get('project');
    if (!id || !/^[0-9a-f]{12}$/.test(id)) return;
    try {
      const r = await fetch('/api/projects/' + id);
      if (!r.ok) { hint('This project is no longer on the server (projects are cleared when it is rebuilt).'); return; }
      proj = await r.json();
      if (!cur || !inProj(cur.path)) {
        const plans = proj.sheets.filter(s => !s.kind || s.kind === 'arch');
        if (proj.sheets.length) await openSheet_((plans.length ? plans : proj.sheets)[0]);
      }
      renderPanel(); suggest();
    } catch (e) { /* the page still works without it */ }
  })();
  window.bpProject = () => proj;
})();
