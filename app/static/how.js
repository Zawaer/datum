/* "How it works" explainer (/how): scroll-driven chapters, no libraries.
   Every number is copied from README.md or the run summaries the page footer cites. The room outlines are the
   solver's real output for the German area question (POST /api/ask, method swiss-dxf, rounded to 4 decimals),
   and CURVE is analysis/out/selective_all_curve.csv thinned to about one point per 0.8 % of coverage. */
(() => {
'use strict';
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const NS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs = {}, parent) => {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(e);
  return e;
};
const mqReduce = matchMedia('(prefers-reduced-motion: reduce)');
const mqNarrow = matchMedia('(max-width: 960px)');
let reduced = mqReduce.matches;
const ROOT = window.BP_ROOT || '';
$$('a[data-href]').forEach(a => a.setAttribute('href', ROOT + a.dataset.href));
const nf = new Intl.NumberFormat('en-US');

// count a number up (or set it at once under reduced motion)
function tween(from, to, ms, draw) {
  if (reduced || ms <= 0) { draw(to); return; }
  const t0 = performance.now();
  const f = now => {
    const k = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - k, 3);
    draw(from + (to - from) * e);
    if (k < 1) requestAnimationFrame(f);
  };
  requestAnimationFrame(f);
}

/* ================================================================ scroll engine */
const hooks = {};
const chapters = $$('.hw-chap');
function activate(step) {
  const chap = step.closest('.hw-chap');
  const i = +step.dataset.step;
  $$('.hw-step', chap).forEach(s => s.classList.toggle('is-active', s === step));
  if (chap.dataset.step === String(i) && chap.dataset.seen) return;
  const prev = +chap.dataset.step;
  chap.dataset.step = i;
  chap.dataset.seen = '1';
  if (hooks[chap.id]) hooks[chap.id](i, prev);
}
let stepObs = null;
function observeSteps() {
  if (stepObs) stepObs.disconnect();
  // a thin trigger band: mid-screen on desktop, below the sticky graphic on a phone
  const margin = mqNarrow.matches ? '-94% 0px -5% 0px' : '-48% 0px -51% 0px';
  stepObs = new IntersectionObserver(es => es.forEach(e => e.isIntersecting && activate(e.target)), {rootMargin: margin});
  $$('.hw-step').forEach(s => stepObs.observe(s));
}

// which chapter is on screen: the chapter bar, and pausing the routing animation off screen
const visible = new Set();
const tocLinks = $$('.hw-toc a');
const chapObs = new IntersectionObserver(es => {
  es.forEach(e => (e.isIntersecting ? visible.add(e.target.id) : visible.delete(e.target.id)));
  const on = chapters.find(c => visible.has(c.id));
  tocLinks.forEach(a => {
    const cur = on && a.dataset.chap === on.id;
    a.classList.toggle('is-on', !!cur);
    if (cur) a.setAttribute('aria-current', 'step'); else a.removeAttribute('aria-current');
  });
  routeLoop();
}, {rootMargin: '-40% 0px -40% 0px'});
chapters.forEach(c => chapObs.observe(c));
const tocBar = $('.hw-toc');
function progress() {
  const h = document.documentElement.scrollHeight - innerHeight;
  tocBar.style.setProperty('--p', h > 0 ? Math.min(1, scrollY / h).toFixed(4) : 0);
}
addEventListener('scroll', progress, {passive: true});

/* ================================================================ 1 · routing */
const QS = [
  {code: 'EN', lang: 'en', kind: 'scanned Finnish plan', r: 1, text: 'How many separate WC rooms (toilet rooms marked WC) are on this floor plan?'},
  {code: 'FI', lang: 'fi', kind: 'scanned Finnish plan', r: 1, text: 'Kuinka monta makuuhuonetta (MH) pohjapiirustuksessa on?'},
  {code: 'DE', lang: 'de', kind: 'Swiss plan with its CAD file', r: 0, text: 'Wie viele Wohnungen sind auf diesem Grundriss dargestellt?'},
  {code: 'FR', lang: 'fr', kind: 'Swiss plan with its CAD file', r: 0, text: 'Combien d’appartements (logements) figurent sur ce plan d’étage ?'},
  {code: 'IT', lang: 'it', kind: 'BIM model (IFC)', r: 0, text: 'Qual è il numero di porte nel modello «BIM-Speed Frigento - Palazzo Testa Cipriano (baseline)»?'},
  {code: 'NL', lang: 'nl', kind: 'BIM model (IFC)', r: 0, text: 'Hoeveel deuren bevat het model ‘BIM-Speed Warmond demo site (baseline)’?'},
  {code: 'EN', lang: 'en', kind: 'BIM model, free-text question', r: 2, text: 'What component types comprise the ventilation system and their respective counts?'},
];
const SHARE = [34.7, 64.9, 0.4];
const routeChap = $('#route'), routeG = $('#routeG'), wires = $('#wires');
const rtCards = $$('.hw-rt', routeG), langBtns = $$('.hw-langs button', routeG);
let qi = 0, qPaused = false, qTimer = 0, trunk = null, branches = [], dots = [], rafId = 0, lastSpawn = 0;

function layoutWires() {
  const g = routeG.getBoundingClientRect();
  const q = $('.hw-q', routeG).getBoundingClientRect(), r = $('#router').getBoundingClientRect();
  const rel = (x, y) => [(x - g.left).toFixed(1), (y - g.top).toFixed(1)];
  wires.innerHTML = '';
  wires.setAttribute('viewBox', `0 0 ${g.width} ${g.height}`);
  const [qx, qy] = rel(q.left + q.width / 2, q.bottom), [rx, ry] = rel(r.left + r.width / 2, r.top);
  trunk = el('path', {d: `M${qx},${qy} L${rx},${ry}`}, wires);
  const [bx, by] = rel(r.left + r.width / 2, r.bottom);
  branches = rtCards.map(c => {
    const b = c.getBoundingClientRect();
    const [cx, cy] = rel(b.left + b.width / 2, b.top);
    const m = (+by + +cy) / 2;
    return el('path', {d: `M${bx},${by} C${bx},${m} ${cx},${m} ${cx},${cy}`}, wires);
  });
  const st = +routeChap.dataset.step;
  branches.forEach((p, j) => p.classList.toggle('is-hot', st >= 1 && j === QS[qi].r));
  dots = [];
}

function showQ(i, user) {
  qi = (i + QS.length) % QS.length;
  const q = QS[qi], t = $('#qText');
  const apply = () => {
    t.textContent = q.text; t.lang = q.lang;
    $('#qLang').textContent = q.code; $('#qKind').textContent = q.kind;
    t.classList.remove('is-out');
  };
  if (reduced || user) apply(); else { t.classList.add('is-out'); setTimeout(apply, 220); }
  langBtns.forEach((b, j) => { b.classList.toggle('is-cur', j === qi); b.setAttribute('aria-pressed', j === qi ? 'true' : 'false'); });
  rtCards.forEach((c, j) => c.classList.toggle('is-hot', +routeChap.dataset.step >= 1 && j === q.r));
  branches.forEach((p, j) => p.classList.toggle('is-hot', +routeChap.dataset.step >= 1 && j === q.r));
  if (+routeChap.dataset.step >= 1) spawn(q.r, true);
}
langBtns.forEach((b, j) => b.addEventListener('click', () => { qPaused = true; showQ(j, true); }));

function spawn(r, hero) {
  if (reduced || !trunk) return;
  const c = el('circle', {r: hero ? 5 : 3, class: r === 2 ? 'llm' : ''}, wires);
  dots.push({c, r, t: 0, speed: hero ? 0.0009 : 0.0011 + Math.random() * 0.0004});
}
function pickRoute() {
  const x = Math.random() * 100;
  return x < SHARE[0] ? 0 : x < SHARE[0] + SHARE[1] ? 1 : 2;
}
function frame(now) {
  rafId = 0;
  if (!visible.has('route') || reduced) return;
  const step = +routeChap.dataset.step;
  if (step >= 2 && now - lastSpawn > 45) { spawn(pickRoute(), false); lastSpawn = now; }
  const dt = 16;
  const tl = trunk.getTotalLength();
  for (const d of dots) {
    d.t += d.speed * dt;
    const b = branches[d.r], bl = b.getTotalLength(), s = d.t * (tl + bl);
    const p = s < tl ? trunk.getPointAtLength(s) : b.getPointAtLength(Math.min(bl, s - tl));
    d.c.setAttribute('cx', p.x.toFixed(1)); d.c.setAttribute('cy', p.y.toFixed(1));
    d.c.setAttribute('opacity', d.t > 0.92 ? Math.max(0, (1 - d.t) / 0.08).toFixed(2) : 1);
  }
  dots = dots.filter(d => (d.t < 1 ? true : (d.c.remove(), false)));
  rafId = requestAnimationFrame(frame);
}
function routeLoop() {
  const on = visible.has('route');
  if (on && !reduced && !rafId) rafId = requestAnimationFrame(frame);
  clearInterval(qTimer); qTimer = 0;
  if (on && !reduced) qTimer = setInterval(() => { if (!qPaused) showQ(qi + 1); }, 3200);
}
hooks.route = (i, prev) => {
  showQ(qi, true);
  if (i >= 2 && prev < 2) $$('.hw-count', routeG).forEach(c => tween(0, +c.dataset.to, 1200, v => { c.textContent = nf.format(Math.round(v)); }));
};

/* ================================================================ 2 · the drawing */
const PLAN = 'data/swiss_dwellings/site11487_bldg17991_floor47889.pdf';
const ROOMS = [
  ['3.01 Schlafzimmer', 17.1, [[0.4516,0.1725],[0.4516,0.1843],[0.4766,0.1843],[0.4765,0.2972],[0.3611,0.2971],[0.3608,0.1854],[0.3927,0.1855],[0.3927,0.1724]]],
  ['3.02 Bad', 4.57, [[0.4804,0.1843],[0.5143,0.1843],[0.5142,0.2797],[0.5053,0.2797],[0.5052,0.2973],[0.4803,0.2972]]],
  ['3.03 Wohnen', 16.93, [[0.6028,0.338],[0.5069,0.3379],[0.5069,0.3347],[0.5053,0.3347],[0.5053,0.3072],[0.5071,0.3072],[0.5071,0.3024],[0.5171,0.3024],[0.5172,0.1843],[0.6029,0.1844]]],
  ['3.05 Küche', 8.77, [[0.4496,0.3818],[0.3613,0.3817],[0.3611,0.3022],[0.4496,0.3023]]],
  ['3.06 Korridor', 4.42, [[0.5033,0.3379],[0.4919,0.3378],[0.4919,0.3819],[0.453,0.3819],[0.453,0.3023],[0.5035,0.3024],[0.5035,0.3072],[0.505,0.3072],[0.505,0.3347],[0.5033,0.3347]]],
  ['3.07 Schlafzimmer', 10.95, [[0.6028,0.4261],[0.496,0.4259],[0.496,0.3879],[0.4955,0.3879],[0.4955,0.344],[0.6028,0.3441]]],
];
const SOLVER_TOTAL = 62.74;
const plan = $('#plan'), proofChap = $('#proof');
let W = 2150, H = 1521;                       // page raster size at dpi 200 is read from the image once loaded
const CROP = [0.336, 0.150, 0.628, 0.448];    // the part of the sheet around apartment A
const roomEls = [], rowEls = [];
let shown = 0, revealTimer = 0, totalNow = 0;

function centroid(pts) {
  let a = 0, cx = 0, cy = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x0, y0] = pts[i], [x1, y1] = pts[(i + 1) % pts.length], f = x0 * y1 - x1 * y0;
    a += f; cx += (x0 + x1) * f; cy += (y0 + y1) * f;
  }
  return a ? [cx / (3 * a), cy / (3 * a)] : pts[0];
}
function inside([x, y], pts) {
  let c = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) c = !c;
  }
  return c;
}
// the plan prints each room's name at about its centre: put the number badge below it, still inside the room
function badgeAt(pts) {
  const [cx, cy] = centroid(pts), ys = pts.map(p => p[1]), h = Math.max(...ys) - Math.min(...ys);
  for (const k of [0.3, 0.22, 0.15]) if (inside([cx, cy + k * h], pts)) return [cx, cy + k * h];
  return [cx, cy];
}
function buildPlan() {
  plan.innerHTML = '';
  plan.setAttribute('viewBox', `${CROP[0] * W} ${CROP[1] * H} ${(CROP[2] - CROP[0]) * W} ${(CROP[3] - CROP[1]) * H}`);
  el('rect', {x: 0, y: 0, width: W, height: H, fill: '#fff'}, plan);
  const img = el('image', {x: 0, y: 0, width: W, height: H, preserveAspectRatio: 'none'}, plan);
  img.addEventListener('error', () => { $('#noimg').hidden = false; });
  img.setAttribute('href', imgURL);
  roomEls.length = 0;
  ROOMS.forEach(([label, , pts], i) => {
    const poly = el('polygon', {class: 'room', points: pts.map(([x, y]) => `${(x * W).toFixed(1)},${(y * H).toFixed(1)}`).join(' '), pathLength: 1}, plan);
    const [cx, cy] = badgeAt(pts);
    const g = el('g', {class: 'badge'}, plan);
    el('circle', {cx: cx * W, cy: cy * H, r: 9}, g);
    const t = el('text', {x: cx * W, y: cy * H}, g); t.textContent = i + 1;
    poly.addEventListener('mouseenter', () => hover(i, true));
    poly.addEventListener('mouseleave', () => hover(i, false));
    poly.addEventListener('click', () => { if (rowEls[i].classList.contains('is-on')) { const c = $('input', rowEls[i]); c.checked = !c.checked; recount(); } });
    el('title', {}, poly).textContent = `${i + 1} · ${label}: ${ROOMS[i][1].toFixed(2)} m²`;
    roomEls.push({poly, g});
  });
  sizeBadges();
  for (let i = 0; i < shown; i++) setRoom(i, true, true);
  recount(true);
}
const imgURL = '/api/render?path=' + encodeURIComponent(PLAN) + '&dpi=200';
function sizeBadges() {
  const w = plan.clientWidth || 600, u = (CROP[2] - CROP[0]) * W / w;   // user units per CSS pixel
  roomEls.forEach(({g}) => {
    $('circle', g).setAttribute('r', (10 * u).toFixed(1));
    $('text', g).style.fontSize = (12 * u).toFixed(1) + 'px';
  });
}
function buildList() {
  const tb = $('#rooms tbody');
  ROOMS.forEach(([label, v], i) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td><input type="checkbox" checked aria-label="count ${label}, ${v.toFixed(2)} m²"></td><td>${i + 1}</td><td>${label}</td><td class="hw-r">${v.toFixed(2)}</td>`;
    $('input', tr).addEventListener('change', recount);
    tr.addEventListener('mouseenter', () => hover(i, true));
    tr.addEventListener('mouseleave', () => hover(i, false));
    $('input', tr).tabIndex = -1;
    tb.appendChild(tr); rowEls.push(tr);
  });
}
function hover(i, on) {
  if (!rowEls[i].classList.contains('is-on')) return;
  rowEls[i].classList.toggle('is-hover', on);
  roomEls[i] && roomEls[i].poly.classList.toggle('is-hover', on);
}
function setRoom(i, on, instant) {
  rowEls[i].classList.toggle('is-on', on);
  $('input', rowEls[i]).tabIndex = on ? 0 : -1;
  if (roomEls[i]) { roomEls[i].poly.classList.toggle('is-on', on); roomEls[i].g.classList.toggle('is-on', on); }
  if (!instant) recount();
}
function recount(instant) {
  let sum = 0, off = 0;
  rowEls.forEach((tr, i) => {
    const c = $('input', tr).checked, on = tr.classList.contains('is-on');
    tr.classList.toggle('is-off', on && !c);
    if (roomEls[i]) { roomEls[i].poly.classList.toggle('is-off', on && !c); roomEls[i].g.classList.toggle('is-off', on && !c); }
    if (on && c) sum += ROOMS[i][1];
    if (on && !c) off++;
  });
  sum = Math.round(sum * 100) / 100;
  const out = $('#total'), from = totalNow;
  totalNow = sum;
  tween(from, sum, instant === true ? 0 : 350, v => { out.textContent = v.toFixed(2); });
  $('#changed').hidden = !off;
}
function revealTo(n, stagger) {
  clearTimeout(revealTimer);
  const next = () => {
    if (shown < n) { setRoom(shown, true); shown++; revealTimer = setTimeout(next, stagger); }
  };
  if (shown > n) { for (let i = n; i < shown; i++) setRoom(i, false, true); shown = n; recount(); }
  if (reduced || !stagger) { while (shown < n) setRoom(shown++, true, true); recount(); return; }
  next();
}
hooks.proof = i => revealTo(i === 0 ? 0 : ROOMS.length, i === 1 ? 480 : 0);

/* ================================================================ 3 · the coverage curve */
const CURVE = [[5.4,100.0,0.999],[7.0,99.77,0.995],[7.8,99.8,0.993],[8.7,99.73,0.989],[12.5,99.0,0.987],[13.4,99.0,0.984],[23.0,99.31,0.98],[24.1,99.18,0.974],[47.1,99.55,0.97],[48.0,99.52,0.963],[50.5,99.45,0.959],[51.4,99.45,0.951],[53.6,99.47,0.95],[54.5,99.48,0.944],[55.4,99.42,0.938],[56.3,99.4,0.935],[57.2,99.34,0.933],[58.2,99.35,0.93],[59.2,99.34,0.925],[60.1,99.28,0.917],[60.9,99.25,0.908],[62.2,99.18,0.9],[63.1,99.03,0.888],[63.9,98.94,0.874],[64.7,98.91,0.859],[65.6,98.8,0.847],[66.4,98.73,0.833],[67.3,98.62,0.817],[68.1,98.51,0.801],[69.0,98.43,0.793],[69.9,98.38,0.786],[70.7,98.37,0.781],[71.7,98.35,0.776],[72.5,98.33,0.771],[73.4,98.33,0.766],[74.3,98.25,0.76],[75.1,98.19,0.754],[76.0,98.14,0.747],[76.9,98.08,0.739],[77.7,98.04,0.731],[78.6,98.01,0.722],[79.4,97.91,0.712],[80.3,97.83,0.703],[81.2,97.78,0.689],[82.0,97.64,0.674],[82.8,97.45,0.653],[83.6,97.21,0.626],[84.4,96.92,0.601],[85.3,96.54,0.583],[86.1,96.21,0.55],[86.9,95.93,0.52],[87.6,95.8,0.5],[88.5,95.73,0.482],[89.4,95.56,0.461],[90.2,95.29,0.425],[91.0,94.92,0.389],[91.8,94.43,0.353],[92.6,94.12,0.336],[93.4,93.69,0.304],[94.2,93.28,0.278],[95.0,92.86,0.25],[95.8,92.42,0.223],[96.6,91.97,0.198],[97.5,91.51,0.168],[98.3,91.09,0.124],[99.1,90.73,0.08],[99.9,90.16,0.007],[100.0,90.05,0.0]];
const curve = $('#curve'), tip = $('#tip');
const CX = [56, 540], CY = [292, 18], YD = [88, 100];
const sx = c => CX[0] + (CX[1] - CX[0]) * c / 100;
const sy = a => CY[0] + (CY[1] - CY[0]) * (a - YD[0]) / (YD[1] - YD[0]);
let cross = null, curI = CURVE.findIndex(p => p[2] === 0.5);
function buildCurve() {
  const grid = el('g', {class: 'grid'}, curve), axis = el('g', {class: 'axis'}, curve);
  for (let a = 88; a <= 100; a += 2) {
    el('line', {x1: CX[0], x2: CX[1], y1: sy(a), y2: sy(a)}, grid);
    el('text', {x: CX[0] - 8, y: sy(a) + 4, 'text-anchor': 'end'}, axis).textContent = a + ' %';
  }
  for (const c of [0, 25, 50, 75, 100]) {
    el('line', {x1: sx(c), x2: sx(c), y1: CY[0], y2: CY[0] + 5}, grid);
    el('text', {x: sx(c), y: CY[0] + 18, 'text-anchor': c === 100 ? 'end' : c === 0 ? 'start' : 'middle'}, axis).textContent = c + ' %';
  }
  el('text', {x: (CX[0] + CX[1]) / 2, y: CY[0] + 34, 'text-anchor': 'middle', class: 'ttl'}, axis).textContent = 'share of questions answered (the rest: “not sure”)';
  el('text', {x: CX[0], y: 10, class: 'ttl'}, axis).textContent = 'right, of those answered';
  el('path', {class: 'line', pathLength: 1, d: 'M' + CURVE.map(([c, a]) => `${sx(c).toFixed(1)},${sy(a).toFixed(1)}`).join('L')}, curve);
  // the two points the text talks about
  const mA = el('g', {class: 'mk'}, curve), ax = sx(87.6), ay = sy(95.8);
  el('circle', {cx: ax, cy: ay, r: 5}, mA);
  el('line', {x1: ax - 6, x2: ax - 40, y1: ay + 4, y2: ay + 24}, mA);
  el('text', {x: ax - 44, y: ay + 28, 'text-anchor': 'end', class: 'strong'}, mA).textContent = 'say “not sure” below 0.5:';
  el('text', {x: ax - 44, y: ay + 44, 'text-anchor': 'end'}, mA).textContent = 'answers 87.6 %, 95.8 % right';
  const mB = el('g', {class: 'mk base'}, curve), bx = sx(100), by = sy(90.05);
  el('circle', {cx: bx, cy: by, r: 5}, mB);
  el('text', {x: bx - 12, y: by + 18, 'text-anchor': 'end', class: 'strong'}, mB).textContent = 'answer everything: 90.0 %';
  cross = el('g', {class: 'cross', visibility: 'hidden'}, curve);
  el('line', {y1: CY[1], y2: CY[0]}, cross);
  el('circle', {r: 5}, cross);
  // hover + keyboard
  curve.addEventListener('pointermove', e => {
    const r = curve.getBoundingClientRect(), x = (e.clientX - r.left) * 560 / r.width;
    const c = Math.max(0, Math.min(100, (x - CX[0]) / (CX[1] - CX[0]) * 100));
    let best = 0;
    CURVE.forEach((p, i) => { if (Math.abs(p[0] - c) < Math.abs(CURVE[best][0] - c)) best = i; });
    showCross(best);
  });
  curve.addEventListener('pointerleave', hideCross);
  curve.addEventListener('focus', () => showCross(curI));
  curve.addEventListener('blur', hideCross);
  curve.addEventListener('keydown', e => {
    const k = {ArrowLeft: -1, ArrowRight: 1, ArrowDown: -1, ArrowUp: 1}[e.key];
    if (k) { e.preventDefault(); showCross(Math.max(0, Math.min(CURVE.length - 1, curI + k))); }
    else if (e.key === 'Home') { e.preventDefault(); showCross(0); }
    else if (e.key === 'End') { e.preventDefault(); showCross(CURVE.length - 1); }
  });
}
function showCross(i) {
  curI = i;
  const [c, a, t] = CURVE[i], x = sx(c), y = sy(a);
  cross.setAttribute('visibility', 'visible');
  const [ln, ci] = cross.children;
  ln.setAttribute('x1', x); ln.setAttribute('x2', x); ci.setAttribute('cx', x); ci.setAttribute('cy', y);
  const r = curve.getBoundingClientRect(), wr = $('#curveWrap').getBoundingClientRect(), k = r.width / 560;
  tip.hidden = false;
  tip.textContent = `confidence ≥ ${t.toFixed(2)} · answers ${c.toFixed(1)} % · ${a.toFixed(1)} % right`;
  const px = r.left - wr.left + x * k, half = tip.offsetWidth / 2;
  tip.style.left = Math.max(half + 4, Math.min(wr.width - half - 4, px)) + 'px';
  tip.style.top = (r.top - wr.top + y * k) + 'px';
}
function hideCross() { if (cross) cross.setAttribute('visibility', 'hidden'); tip.hidden = true; }

/* ================================================================ 4 · accuracy, cost, dots */
const SYSTEMS = [  // README results table: accuracy [95 % CI], API $ per 1,000 questions
  {name: 'Ours', sub: 'all 25,420 questions', acc: 90.0, lo: 89.7, hi: 90.4, usd: 0.013, cls: 'ours', cost: '$0.013', short: 'Ours'},
  {name: 'Claude Sonnet 5.5', sub: '+ the CAD / IFC files', acc: 69.8, lo: 60.9, hi: 78.4, usd: 25.76, cls: 'fair', cost: '$25.76', short: 'Sonnet 5.5 + files'},
  {name: 'Gemini 3.1 Pro', sub: 'drawing only', acc: 64.2, lo: 55.9, hi: 72.3, usd: 52.47, cost: '$52.47', short: 'Gemini 3.1 Pro'},
  {name: 'Claude Sonnet 5.5', sub: 'drawing only', acc: 63.2, lo: 54.4, hi: 71.8, usd: 13.06, cost: '$13.06', short: 'Sonnet 5.5'},
  {name: 'Claude Haiku 5.5', sub: 'drawing only', acc: 60.6, lo: 51.5, hi: 69.3, usd: 1.21, cost: '$1.21', short: 'Haiku 5.5'},
  {name: 'Nemotron 3.5 Super VL', sub: 'open weights', acc: 49.0, lo: 40.0, hi: 58.0, usd: 2.59, cost: '$2.59', short: 'Nemotron 3.5'},
];
function buildAcc() {
  const box = $('#acc');
  box.innerHTML = SYSTEMS.map(s => `<div class="hw-arow2 ${s.cls || ''}" aria-hidden="true"><div class="lab">${s.name}<small>${s.sub}</small></div>`
    + `<div class="trk"><i style="--w:${s.acc}%"></i><span class="ci" style="left:${s.lo}%;width:${(s.hi - s.lo).toFixed(1)}%"></span></div>`
    + `<div class="v">${s.acc.toFixed(1)}&nbsp;%</div></div>`).join('')
    + '<div class="hw-axis" aria-hidden="true"><i></i><div>' + [0, 25, 50, 75, 100].map(v => `<span style="left:${v}%">${v} %</span>`).join('') + '</div><i></i></div>';
}
function buildLog() {
  const svg = $('#logcost'), X0 = 196, X1 = 548, lx = v => X0 + (X1 - X0) * (Math.log10(v) + 2) / 4;
  const grid = el('g', {class: 'grid'}, svg), axis = el('g', {class: 'axis'}, svg);
  [[0.01, '$0.01'], [0.1, '$0.10'], [1, '$1'], [10, '$10'], [100, '$100']].forEach(([v, t]) => {
    el('line', {x1: lx(v), x2: lx(v), y1: 44, y2: 272}, grid);
    el('text', {x: lx(v), y: 290, 'text-anchor': 'middle'}, axis).textContent = t;
  });
  const order = [...SYSTEMS].sort((a, b) => a.usd - b.usd);
  order.forEach((s, i) => {
    const y = 64 + i * 40, g = el('g', {class: 'row ' + (s.cls || '')}, svg);
    const lab = el('text', {x: X0 - 12, y: y + 4, 'text-anchor': 'end'}, g);
    lab.textContent = s.short;
    el('line', {x1: X0, x2: lx(s.usd), y1: y, y2: y}, g);
    const c = el('circle', {cx: lx(s.usd), cy: y, r: 7}, g);
    el('text', {x: lx(s.usd) + 12, y: y + 4, class: 'val'}, g).textContent = s.cost;
  });
  const a = lx(0.013), b = lx(25.76), gp = el('g', {class: 'gap'}, svg);
  el('path', {d: `M${a},30 L${a},22 L${b},22 L${b},30`}, gp);
  el('text', {x: (a + b) / 2, y: 16}, gp).textContent = 'about 1,900×';
}
function setLogDots(on) {
  $$('#logcost .row circle').forEach(c => { c.style.transform = on ? 'none' : `translateX(${(196 - +c.getAttribute('cx')).toFixed(1)}px)`; });
}
hooks.cost = i => { setLogDots(i >= 1); if (i === 2) drawDots(true); };
const N_DOTS = 1900;
let dotAnim = 0;
function drawDots(animate) {
  const cv = $('#dots'), w = cv.clientWidth, h = cv.clientHeight;
  if (!w || !h) return;
  const dpr = Math.min(2, devicePixelRatio || 1);
  cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  // a 28 px top line holds our one dot and its label; the grey field fills the rest
  const TOP = 28, fh = h - TOP;
  let cell = Math.floor(Math.sqrt(w * fh / N_DOTS));
  while (cell > 2 && Math.floor(fh / cell) * Math.floor(w / cell) < N_DOTS) cell--;
  const cols = Math.floor(w / cell), r = Math.max(1, cell * 0.34), total = N_DOTS + 1;
  const css = getComputedStyle(document.documentElement);
  const blue = css.getPropertyValue('--ev').trim() || '#0072b2', grey = css.getPropertyValue('--base').trim() || '#8a929d';
  const dot = i => {
    const k = i - 1, x = i === 0 ? cell / 2 : (k % cols) * cell + cell / 2, y = i === 0 ? 10 : TOP + Math.floor(k / cols) * cell + cell / 2;
    ctx.fillStyle = i === 0 ? blue : grey;
    ctx.beginPath(); ctx.arc(x, y, i === 0 ? Math.max(r, 3) : r, 0, Math.PI * 2); ctx.fill();
  };
  cancelAnimationFrame(dotAnim);
  ctx.clearRect(0, 0, w, h);
  const out = $('#dotn');
  ctx.fillStyle = css.getPropertyValue('--ev-ink').trim() || '#005f94';
  ctx.font = '600 13px "IBM Plex Sans", Arial, sans-serif';
  ctx.textBaseline = 'middle';
  ctx.fillText('← ours: $0.013 per 1,000 questions', cell + 10, 10);
  if (!animate || reduced) { for (let i = 0; i < total; i++) dot(i); out.textContent = nf.format(N_DOTS); return; }
  dot(0);
  let done = 1; const t0 = performance.now();
  const step = now => {
    const k = Math.min(1, (now - t0) / 1800), want = 1 + Math.round(N_DOTS * (1 - Math.pow(1 - k, 2)));
    while (done < want) dot(done++);
    out.textContent = nf.format(done - 1);
    if (k < 1) dotAnim = requestAnimationFrame(step);
  };
  dotAnim = requestAnimationFrame(step);
}

/* ================================================================ boot */
function init() {
  buildList();
  buildPlan();
  const probe = new Image();
  probe.onload = () => { if (probe.naturalWidth && (probe.naturalWidth !== W || probe.naturalHeight !== H)) { W = probe.naturalWidth; H = probe.naturalHeight; buildPlan(); } };
  probe.src = imgURL;
  buildCurve();
  buildAcc();
  buildLog();
  setLogDots(false);
  showQ(0, true);
  if ('IntersectionObserver' in window) observeSteps();
  else chapters.forEach(c => { const s = $$('.hw-step', c).pop(); if (s) activate(s); });
  requestAnimationFrame(() => { layoutWires(); drawDots(false); });
  progress();
}
let rz = 0;
addEventListener('resize', () => {
  clearTimeout(rz);
  rz = setTimeout(() => { layoutWires(); sizeBadges(); if (+$('#cost').dataset.step === 2) drawDots(false); hideCross(); }, 120);
});
mqNarrow.addEventListener('change', observeSteps);
mqReduce.addEventListener('change', e => { reduced = e.matches; routeLoop(); });
if ('fonts' in document) document.fonts.ready.then(() => layoutWires());
init();
})();
