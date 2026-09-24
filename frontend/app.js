/* Concord frontend — vanilla JS, one state object, one render function per view, event delegation.
   Views: #/ upload · #/run/{id} progress→review · #/run/{id}/report.
   Dev switch: ?fixture=1 loads ../fixtures/findings.json and makes PATCH a local no-op. */
(() => {
  'use strict';

  // ---------- Config ----------
  const FIXTURE = /(?:\?|&)fixture=1/.test(location.search);
  const API = '/api';
  const STAGES = [
    ['extract',  'Extracting text'],
    ['detect',   'Detecting pair'],
    ['glossary', 'Building glossary'],
    ['align',    'Aligning sections'],
    ['checks',   'Checking numbers and dates'],
    ['semantic', 'Analysing meaning'],
    ['classify', 'Ranking findings'],
  ];
  const TYPE_LABEL = {
    NUMBER_MISMATCH: 'Number mismatch', DATE_MISMATCH: 'Date mismatch', CURRENCY_MISMATCH: 'Currency mismatch',
    OMISSION_MATERIAL: 'Material omission', HEDGE_CHANGE: 'Hedge change', MEANING_SHIFT: 'Meaning shift',
    SCOPE_CHANGE: 'Scope change', OMISSION_MINOR: 'Minor omission', WORDING: 'Wording', FORMAT: 'Format',
  };
  const DISMISS_REASONS = [
    ['false_positive', 'False positive'],
    ['acceptable_variation', 'Acceptable variation'],
    ['will_fix_in_source', 'Will fix in source'],
  ];
  const SEVERITIES = ['Critical', 'Material', 'Cosmetic'];
  const MAX_BYTES = 20 * 1024 * 1024;

  // ---------- State ----------
  const state = {
    route: { view: 'upload', id: null },
    upload: { en: null, zh: null, authoritative: 'EN', error: null, busy: false },
    progress: { stage: null, label: null, doneStages: new Set(), detail: {}, error: null },
    run: null,
    selectedId: null,
    open: { Critical: true, Material: true, Cosmetic: false },
    dismissOpen: null,   // finding id whose reason select is showing
    modal: null,         // { lang, page }
    animatedView: null,  // last view that played the rise animation
    toast: null,
  };
  let es = null, pollTimer = null, toastTimer = null;

  // ---------- Helpers ----------
  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const humanType = t => TYPE_LABEL[t] || (t ? t.toLowerCase().replace(/_/g, ' ').replace(/^./, c => c.toUpperCase()) : '');
  const fmtBytes = n => n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`;
  const pct = n => `${Math.round((n || 0) * 100)}%`;
  const icon = {
    tick: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 8.5l3.2 3L13 4.5"/></svg>',
    tickL: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 8.5l3.2 3L13 4.5"/></svg>',
    slash: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M11 4L5 12"/></svg>',
    dash: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M4 8h8"/></svg>',
    close: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>',
    chev: '<svg class="chev" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 6l4 4 4-4"/></svg>',
    up: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 16V4M6 10l6-6 6 6M4 20h16"/></svg>',
    doc: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>',
    back: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 3L5 8l5 5"/></svg>',
    dl: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2v9M4 7l4 4 4-4M3 13h10"/></svg>',
  };
  const glyphFor = s => s === 'confirmed' ? icon.tick : s === 'dismissed' ? icon.slash : s === 'unresolved' ? icon.dash : '';
  const detectLang = name => /(?:^|[^a-z])(zh|chi|chn|cn|tc|sc|hant|hans)(?:[^a-z]|$)|中文|繁|简/i.test(name) ? 'ZH'
    : /(?:^|[^a-z])(en|eng|english)(?:[^a-z]|$)/i.test(name) ? 'EN' : 'PDF';
  const toast = msg => { state.toast = msg; renderToast(); clearTimeout(toastTimer); toastTimer = setTimeout(() => { state.toast = null; renderToast(); }, 2600); };

  // ---------- Local runs (serverless mode: the server returns the whole run and keeps nothing) ----------
  const localRuns = {}; const LS = 'concord:run:'; let pendingSim = null; const reportCache = {};
  function saveLocal(run) { localRuns[run.run_id] = run; try { localStorage.setItem(LS + run.run_id, JSON.stringify(run)); } catch { /* quota / private mode */ } }
  function loadLocal(id) { if (localRuns[id]) return localRuns[id]; try { const raw = localStorage.getItem(LS + id); if (raw) return (localRuns[id] = JSON.parse(raw)); } catch { /* ignore */ } return null; }
  const absorb = res => { if (res && res.status && Array.isArray(res.findings)) { saveLocal(res); pendingSim = res.run_id; return { run_id: res.run_id }; } return res; };

  // ---------- Languages (slots are en/zh internally; names come from detection) ----------
  const DEFAULT_LANG = { en: { code: 'en', name: 'English', script: 'Latn' }, zh: { code: 'zh-Hant', name: 'Chinese (Traditional)', script: 'Hant' } };
  const langOf = slot => (state.run && state.run.meta && state.run.meta.languages && state.run.meta.languages[slot]) || DEFAULT_LANG[slot];
  const langName = slot => langOf(slot).name || DEFAULT_LANG[slot].name;
  const langCode = slot => langOf(slot).code || DEFAULT_LANG[slot].code;
  const isCJK = slot => /^(zh|ja|ko)/.test(langCode(slot));

  // ---------- API ----------
  async function apiJSON(path, opts) {
    const r = await fetch(path, opts);
    let body = null; try { body = await r.json(); } catch { /* non-JSON */ }
    if (!r.ok) throw new Error((body && body.error) || `${r.status} ${r.statusText}`);
    return body;
  }
  const api = {
    getRun: id => { const l = loadLocal(id); if (l) return Promise.resolve(l);
      return FIXTURE ? apiJSON('../fixtures/findings.json', { cache: 'no-store' }) : apiJSON(`${API}/runs/${id}`, { cache: 'no-store' }); },
    createRun: form => apiJSON(`${API}/runs`, { method: 'POST', body: form }).then(absorb),   // multipart: en, zh, authoritative
    sample: () => apiJSON(`${API}/runs/sample`, { method: 'POST' }).then(absorb),
    patch: (id, fid, body) => {
      const l = loadLocal(id);
      if (l) { const f = l.findings.find(x => x.id === fid); if (f) { Object.assign(f, body); if (f.status !== 'dismissed') f.dismiss_reason = null; } saveLocal(l); return Promise.resolve({ ...f }); }
      return FIXTURE
        ? Promise.resolve({ ...state.run.findings.find(f => f.id === fid), ...body })
        : apiJSON(`${API}/runs/${id}/findings/${fid}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    },
    pageUrl: (id, lang, n) => { const l = loadLocal(id); return l && l.sample ? `${API}/sample/page/${lang}/${n}.png` : `${API}/runs/${id}/page/${lang}/${n}.png`; },
    reportUrl: id => `${API}/runs/${id}/report`,
    exportUrl: id => `${API}/runs/${id}/export.json`,
    eventsUrl: id => `${API}/runs/${id}/events`,
  };

  // ---------- Derived ----------
  const findings = () => (state.run && state.run.findings) || [];
  const bySev = sev => findings().filter(f => f.severity === sev);
  const reviewedCount = () => findings().filter(f => f.status !== 'unreviewed').length;
  const exportUnlocked = () => bySev('Critical').every(f => f.status !== 'unreviewed');
  const selected = () => findings().find(f => f.id === state.selectedId) || null;
  function recount() {
    if (!state.run) return;
    const c = state.run.counts || (state.run.counts = {});
    c.critical = bySev('Critical').length; c.material = bySev('Material').length; c.cosmetic = bySev('Cosmetic').length;
    c.reviewed = reviewedCount(); c.total = findings().length;
    c.unaligned_sections = (state.run.unaligned_sections || []).length;
  }
  function visibleOrder() { // rail order: Critical, Material, Cosmetic (findings arrive ranked already)
    return SEVERITIES.flatMap(bySev);
  }

  // ---------- Router ----------
  function parseHash() {
    const h = location.hash || '#/';
    let m;
    if ((m = h.match(/^#\/run\/([^/]+)\/report\/?$/))) return { view: 'report', id: decodeURIComponent(m[1]) };
    if ((m = h.match(/^#\/run\/([^/]+)\/?$/))) return { view: 'run', id: decodeURIComponent(m[1]) };
    return { view: 'upload', id: null };
  }
  function route() {
    const r = parseHash();
    const changedRun = r.id !== state.route.id;
    state.route = r;
    state.modal = null; renderModal();
    if (r.view === 'upload') { stopStream(); render(); return; }
    if (changedRun || !state.run || state.run.run_id !== r.id) { state.run = null; state.selectedId = null; state.dismissOpen = null; }
    if (r.view === 'report') { stopStream(); render(); return; }
    if (state.run && state.run.status === 'done') { render(); return; }
    loadRun(r.id);
  }

  async function loadRun(id) {
    state.progress = { stage: null, label: null, doneStages: new Set(), detail: {}, error: null };
    render();
    try {
      const run = await api.getRun(id);
      if (state.route.id !== id) return;
      if (pendingSim === id && run.status === 'done') { pendingSim = null; simulateProgress(id, run); return; }
      applyRun(run);
      if (run.status === 'running' || run.status === 'queued' || !run.status) openStream(id);
      render();
    } catch (e) {
      state.progress.error = e.message; render();
    }
  }
  function applyRun(run) {
    state.run = run;
    if (run.status === 'done') {
      recount();
      if (!state.selectedId || !selected()) {
        const first = visibleOrder().find(f => f.status === 'unreviewed') || visibleOrder()[0];
        state.selectedId = first ? first.id : null;
      }
      stopStream();
    } else if (run.status === 'error') {
      state.progress.error = run.error || 'The run failed.'; stopStream();
    }
  }

  // ---------- SSE + polling ----------
  function openStream(id) {
    stopStream();
    if (FIXTURE || !('EventSource' in window)) { startPolling(id); return; }
    try {
      es = new EventSource(api.eventsUrl(id));
      const handle = ev => { let d; try { d = JSON.parse(ev.data); } catch { return; } onProgress(id, d); };
      es.onmessage = handle;
      es.addEventListener('progress', handle);
      es.onerror = () => { stopStream(false); startPolling(id); };
    } catch { startPolling(id); }
  }
  function onProgress(id, d) {
    const p = state.progress;
    if (d.detail && typeof d.detail === 'object') Object.assign(p.detail, d.detail);
    const idx = STAGES.findIndex(s => s[0] === d.stage);
    if (d.stage === 'done' || d.done && d.stage === 'classify') {
      STAGES.forEach(s => p.doneStages.add(s[0]));
      p.stage = 'done'; p.label = null;
      if (d.stage === 'done') { stopStream(); finish(id); return; }
    } else if (idx >= 0) {
      STAGES.slice(0, idx).forEach(s => p.doneStages.add(s[0]));
      if (d.done) { p.doneStages.add(d.stage); p.stage = STAGES[idx + 1] ? STAGES[idx + 1][0] : 'done'; p.label = null; }
      else { p.stage = d.stage; p.label = d.label || null; }
    } else if (d.stage === 'error') {
      p.error = d.label || d.error || 'The run failed.'; stopStream();
    }
    render();
  }
  // Serverless runs arrive finished; step through the stages anyway so the reviewer sees what ran.
  function simulateProgress(id, run) {
    const p = state.progress; state.run = { run_id: id, status: 'running' };
    const m = run.meta || {};
    const labels = { extract: m.en_pages ? `Extracted ${m.en_pages}+${m.zh_pages} pages` : null,
      detect: m.authoritative && m.authoritative !== 'none' ? `Authoritative: ${m.authoritative}` : null,
      glossary: run.glossary ? `${run.glossary.length} defined terms` : null,
      align: `${(run.unaligned_sections || []).length} unaligned section${(run.unaligned_sections || []).length === 1 ? '' : 's'}`,
      semantic: `${run.findings.length} candidate findings` };
    let i = 0;
    const step = () => {
      if (state.route.id !== id) return;
      if (i > 0) p.doneStages.add(STAGES[i - 1][0]);
      if (i === 3) p.detail.unaligned_sections = (run.unaligned_sections || []).length;
      if (i >= STAGES.length) { p.stage = 'done'; render(); setTimeout(() => { if (state.route.id === id) { applyRun(run); render(); } }, 350); return; }
      p.stage = STAGES[i][0]; p.label = labels[STAGES[i][0]] || null; render();
      i += 1; setTimeout(step, 620);
    };
    step();
  }
  async function finish(id) {
    try {
      const run = await api.getRun(id);
      if (state.route.id !== id) return;
      if (run.status === 'done' || run.status === 'error') { applyRun(run); render(); }
      else startPolling(id);
    } catch (e) { state.progress.error = e.message; render(); }
  }
  function startPolling(id) {
    clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      if (state.route.id !== id) { clearInterval(pollTimer); return; }
      try {
        const run = await api.getRun(id);
        if (run.status === 'done' || run.status === 'error') { clearInterval(pollTimer); pollTimer = null; applyRun(run); render(); }
        else if (run.stage) onProgress(id, { stage: run.stage, label: run.stage_label || null, done: false, detail: run.progress_detail || null });
      } catch { /* keep polling */ }
    }, 2000);
  }
  function stopStream(clearPoll = true) {
    if (es) { es.close(); es = null; }
    if (clearPoll && pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  // ---------- Decisions (optimistic PATCH) ----------
  async function decide(fid, patch) {
    const f = findings().find(x => x.id === fid); if (!f || !state.run) return;
    const prev = { status: f.status, dismiss_reason: f.dismiss_reason, note: f.note };
    Object.assign(f, patch);
    if (patch.status && patch.status !== 'dismissed') f.dismiss_reason = null;
    recount();
    const advance = 'status' in patch;
    if (advance) { state.dismissOpen = null; advanceSelection(fid); }
    render();
    try {
      const res = await api.patch(state.run.run_id, fid, patch);
      if (res && typeof res === 'object') {
        let changed = false;
        ['status', 'dismiss_reason', 'note'].forEach(k => { if (k in res && res[k] !== f[k]) { f[k] = res[k]; changed = true; } });
        if (changed) { recount(); render(); }
      }
    } catch (e) {
      Object.assign(f, prev); recount(); render(); toast(`Could not save: ${e.message}`);
    }
  }
  function advanceSelection(fromId) {
    const order = visibleOrder(); const i = order.findIndex(f => f.id === fromId);
    const after = order.slice(i + 1).concat(order.slice(0, i)).find(f => f.status === 'unreviewed');
    if (after) { state.selectedId = after.id; ensureGroupOpen(after); }
  }
  function select(fid) { const f = findings().find(x => x.id === fid); if (!f) return; state.selectedId = fid; state.dismissOpen = null; ensureGroupOpen(f); render(); }
  function move(delta) {
    const order = visibleOrder(); if (!order.length) return;
    const i = Math.max(0, order.findIndex(f => f.id === state.selectedId));
    const next = order[Math.min(order.length - 1, Math.max(0, i + delta))];
    if (next) select(next.id);
  }
  function ensureGroupOpen(f) { if (f && !state.open[f.severity]) state.open[f.severity] = true; }

  // ---------- Render ----------
  const app = $('#app');
  function render() {
    const v = state.route.view;
    const html = v === 'upload' ? viewUpload()
      : v === 'report' ? viewReport()
      : state.progress.error ? viewError()
      : (state.run && state.run.status === 'done') ? viewReview()
      : viewProgress();
    const key = v === 'run' ? (state.run && state.run.status === 'done' ? 'review' : 'progress') : v;
    const animate = state.animatedView !== key;
    state.animatedView = key;
    app.innerHTML = html;
    if (!animate) app.querySelectorAll('.rise').forEach(el => el.classList.remove('rise'));
    afterRender(key);
  }
  function afterRender(key) {
    if (key === 'review') {
      const hdr = $('.rhdr'); if (hdr) document.documentElement.style.setProperty('--hdr', `${hdr.offsetHeight}px`);
      const row = app.querySelector('.frow[aria-selected="true"]'); if (row) row.scrollIntoView({ block: 'nearest' });
      const sel = $('.dismiss-sel select'); if (sel && state.dismissOpen && document.activeElement !== sel) sel.focus();
    }
    if (key === 'report') { const f = $('#report-frame'); if (f) f.focus({ preventScroll: true }); }
  }

  function topbar(right) {
    return `<!-- Top bar: dot + wordmark is the whole brand; the faint label on the right states the product in five words so a first-time viewer needs no onboarding. -->
    <header class="topbar"><a class="wordmark" href="#/" aria-label="Concord home"><span class="dot"></span>Concord</a>
      <span class="label">${right || 'Bilingual filing consistency'}</span></header>`;
  }

  // ----- Upload -----
  function viewUpload() {
    const u = state.upload; const both = u.en && u.zh && !u.en.error && !u.zh.error;
    const zone = (key, title, i) => {
      const f = u[key];
      return `<div class="zone rise ${f && !f.error ? 'has' : ''}" data-zone="${key}" style="--i:${i}" role="group" aria-label="${title}">
        ${f && !f.error ? `<button class="pill xs clear" data-act="clear" data-zone="${key}" aria-label="Remove ${title}">${icon.close} Remove</button>
          <span class="zicon">${icon.doc}</span>
          <span class="ztitle">${esc(title)}</span>
          <span class="fname" title="${esc(f.name)}">${esc(f.name)}</span>
          <span class="fmeta"><span class="mono">${fmtBytes(f.size)}</span><span class="chip tint">${f.lang}</span></span>`
        : `<span class="zicon">${icon.up}</span>
          <span class="ztitle">${esc(title)}</span>
          <span class="zhint">Drop a PDF here or click to browse · up to 20 MB</span>
          ${f && f.error ? `<span class="zerr" role="alert">${esc(f.error)}</span>` : ''}`}
        <input type="file" accept="application/pdf,.pdf" data-zone="${key}" aria-label="${title} PDF">
      </div>`;
    };
    return `${topbar()}
    <main class="upload">
      <h1 class="rise" style="--i:0">Check a bilingual filing</h1>
      <p class="lede rise" style="--i:1">Drop the two language versions of the same filing — any pair. Concord detects the languages, aligns them and flags every number, date and meaning that disagrees.</p>
      <!-- Two equal drop zones side by side: the product is about a PAIR, so both versions get identical weight; nothing else is on screen until both exist. -->
      <div class="zones">${zone('en', 'First version', 2)}${zone('zh', 'Second version', 3)}</div>
      <a class="sample rise" style="--i:4" href="#" data-act="sample">Load sample pair</a>
      ${both ? `<!-- Authoritative version is revealed only once both files exist: asking it earlier is a question the user cannot yet answer. -->
      <div class="authbox rise" style="--i:0">
        <span class="lbl">Authoritative version</span>
        <div class="seg" role="radiogroup" aria-label="Authoritative version">
          ${[['EN', u.en && u.en.lang !== 'PDF' ? u.en.lang : 'First'], ['ZH', u.zh && u.zh.lang !== 'PDF' ? u.zh.lang : 'Second'], ['none', 'Neither']].map(([v, l]) => `<button type="button" role="radio" aria-checked="${u.authoritative === v}" aria-pressed="${u.authoritative === v}" data-act="auth" data-v="${v}">${l}</button>`).join('')}
        </div>
        <span class="note">Pre-selected from the prevail clause when detected</span>
      </div>` : ''}
      <div class="runrow rise" style="--i:1">
        <button class="pill primary" data-act="run" ${both && !u.busy ? '' : 'disabled'} ${both ? '' : 'title="Add both PDFs to run"'}>${u.busy ? 'Uploading…' : 'Run consistency check'}</button>
      </div>
      ${u.error ? `<p class="formerr" role="alert">${esc(u.error)}</p>` : ''}
    </main>`;
  }

  function acceptFile(key, file) {
    if (!file) return;
    const isPdf = /\.pdf$/i.test(file.name) || file.type === 'application/pdf';
    const entry = { file, name: file.name, size: file.size, lang: detectLang(file.name), error: null };
    if (!isPdf) entry.error = 'Only PDF files are accepted.';
    else if (file.size > MAX_BYTES) entry.error = `That file is ${fmtBytes(file.size)}; the limit is 20 MB.`;
    if (entry.error) entry.file = null;
    state.upload[key] = entry; state.upload.error = null;
    // Sensible default for the authoritative control: if the user dropped an obviously-Chinese file into the EN slot, still default EN — the backend re-detects.
    render();
  }
  async function submitRun() {
    const u = state.upload; if (!(u.en && u.zh && u.en.file && u.zh.file)) return;
    u.busy = true; u.error = null; render();
    try {
      const fd = new FormData();
      fd.append('en', u.en.file, u.en.name);
      fd.append('zh', u.zh.file, u.zh.name);
      fd.append('authoritative', u.authoritative);
      const res = await api.createRun(fd);
      u.busy = false;
      if (!res || !res.run_id) throw new Error('No run_id returned');
      location.hash = `#/run/${encodeURIComponent(res.run_id)}`;
    } catch (e) { u.busy = false; u.error = `Could not start the run: ${e.message}`; render(); }
  }
  async function loadSample() {
    const u = state.upload; u.busy = true; u.error = null; render();
    try {
      const res = FIXTURE ? { run_id: 'r_fixture' } : await api.sample();
      u.busy = false;
      location.hash = `#/run/${encodeURIComponent(res.run_id)}`;
    } catch (e) { u.busy = false; u.error = `Could not load the sample: ${e.message}`; render(); }
  }

  // ----- Progress -----
  function viewProgress() {
    const p = state.progress; const id = state.route.id;
    const curIdx = STAGES.findIndex(s => s[0] === p.stage);
    const d = p.detail || {};
    const unreadable = Array.isArray(d.unreadable_pages) ? d.unreadable_pages.length
      : d.unreadable_pages && typeof d.unreadable_pages === 'object' ? Object.values(d.unreadable_pages).flat().length
      : typeof d.unreadable_pages === 'number' ? d.unreadable_pages : 0;
    const unaligned = Array.isArray(d.unaligned_sections) ? d.unaligned_sections.length : typeof d.unaligned_sections === 'number' ? d.unaligned_sections : 0;
    return `${topbar(`Run <span class="mono">${esc(id)}</span>`)}
    <main class="progress">
      <h1 class="rise" style="--i:0">Checking the pair</h1>
      <p class="sub rise" style="--i:1">${state.run ? 'The pipeline is running. This page advances on its own.' : 'Connecting…'}</p>
      <!-- Vertical stage list rather than a spinner: a 40-second wait is tolerable when each step is named and ticks off; it also teaches what the tool does. -->
      <ol class="stages" aria-label="Pipeline stages">
        ${STAGES.map(([sid, name], i) => {
          const done = p.doneStages.has(sid) || p.stage === 'done';
          const cur = !done && (sid === p.stage || (p.stage === null && i === 0 && state.run));
          return `<li class="stage rise ${done ? 'done' : cur ? 'current' : ''}" style="--i:${i + 2}" aria-current="${cur ? 'step' : 'false'}">
            <span class="circ">${done ? icon.tick : ''}</span>
            <span class="stxt"><span class="sname">${name}</span>${cur && p.label ? `<span class="slive">${esc(p.label)}</span>` : ''}</span>
          </li>`; }).join('')}
      </ol>
      ${unreadable || unaligned ? `<div class="pchips">
        ${unreadable ? `<span class="chip"><span class="num">${unreadable}</span> unreadable page${unreadable === 1 ? '' : 's'}</span>` : ''}
        ${unaligned ? `<span class="chip unal"><span class="num">${unaligned}</span> unaligned section${unaligned === 1 ? '' : 's'}</span>` : ''}
      </div>` : ''}
    </main>`;
  }
  function viewError() {
    return `${topbar(`Run <span class="mono">${esc(state.route.id)}</span>`)}
    <main class="progress">
      <h1 class="rise" style="--i:0">This run stopped</h1>
      <div class="errbox rise" style="--i:1"><span>${esc(state.progress.error)}</span>
        <a class="pill" href="#/">${icon.back} Back</a></div>
    </main>`;
  }

  // ----- Review -----
  function viewReview() {
    const run = state.run, m = run.meta || {}, c = run.counts || {};
    const total = findings().length, rev = reviewedCount();
    const unlocked = exportUnlocked();
    const prevail = m.authoritative === 'EN' ? `${langName('en')} prevails` : m.authoritative === 'ZH' ? `${langName('zh')} prevails` : 'No prevailing version';
    const groups = SEVERITIES.map((sev, gi) => {
      const list = bySev(sev); const open = !!state.open[sev];
      return `<section class="grp" data-open="${open}">
        <button class="grp-h" data-act="toggle" data-sev="${sev}" aria-expanded="${open}" aria-controls="grp-${sev}">
          <span class="dot ${sev}"></span>${sev} <span class="n">${list.length}</span>${icon.chev}</button>
        <div id="grp-${sev}" role="listbox" aria-label="${sev} findings" ${open ? '' : 'hidden'}>
          ${list.map((f, i) => `<button class="frow rise" style="--i:${gi * 2 + Math.min(i, 6)}" role="option" data-act="select" data-fid="${f.id}" aria-selected="${f.id === state.selectedId}">
            <span class="dot ${sev}"></span>
            <span class="fbody"><span class="ftype">${esc(humanType(f.type))}</span>
              <span class="fsec" title="${esc(f.section)}">${esc(f.section || '')}</span>
              <span class="fpg">EN p.${f.en?.page ?? '–'} · ZH p.${f.zh?.page ?? '–'}</span></span>
            <span class="glyph ${f.status}" aria-label="${f.status}">${glyphFor(f.status)}</span>
          </button>`).join('') || `<p class="fsec" style="padding:4px 20px 10px">None</p>`}
        </div></section>`;
    }).join('');
    const unal = run.unaligned_sections || [];
    return `<!-- Sticky translucent header: the counts and the export lock must stay in view while the reviewer scrolls a long rail, and blur keeps it feeling like glass rather than a bar. -->
    <header class="rhdr">
      <a class="wordmark brand" href="#/" aria-label="Concord home"><span class="dot"></span></a>
      <div class="titles">
        <div class="ten" title="${esc(m.en_title)}">${esc(m.en_title || 'Untitled filing')}</div>
        <div class="tzh" lang="zh-Hant" title="${esc(m.zh_title)}">${esc(m.zh_title || '')}</div>
        <div class="tco"><b>${esc(m.company || '')}</b>${m.stock_code ? ` · <span class="mono">${esc(m.stock_code)}</span>` : ''}</div>
      </div>
      <div class="stats">
        <span class="chip tint" title="${m.authoritative_detected ? 'Detected from the prevail clause' : 'Set on upload'}">${prevail}</span>
        <!-- Three severity counts are always visible so the presenter can say "three Criticals" without scrolling; colour is carried by an 8px dot only. -->
        <span class="count"><span class="dot Critical"></span>Critical <span class="n">${c.critical ?? bySev('Critical').length}</span></span>
        <span class="count"><span class="dot Material"></span>Material <span class="n">${c.material ?? bySev('Material').length}</span></span>
        <span class="count"><span class="dot Cosmetic"></span>Cosmetic <span class="n">${c.cosmetic ?? bySev('Cosmetic').length}</span></span>
        <span class="reviewed"><span class="t"><b>${rev}</b> of <b>${total}</b> reviewed</span><span class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="${total}" aria-valuenow="${rev}"><i style="width:${total ? (rev / total) * 100 : 0}%"></i></span></span>
        <!-- Export is locked, not hidden: the lock is the product's promise (no sign-off with an undecided Critical) and the tooltip says exactly what unlocks it. -->
        <span class="export" title="${unlocked ? 'Open the sign-off report' : 'Decide every Critical finding to unlock'}">
          <button class="pill primary" data-act="export" ${unlocked ? '' : 'disabled aria-disabled="true"'}>Export sign-off</button>
        </span>
      </div>
    </header>
    ${total === 0 ? emptyState() : `
    <!-- 30/70 split: the rail is a list you scan, the pane is the passage pair you read; the pair needs the width for two side-by-side columns of prose. -->
    <div class="split">
      <nav class="rail" aria-label="Findings">
        ${groups}
        <!-- Unaligned sections sit at the bottom in amber outline chips: they are listed, not findings, because nothing was compared, so they must not be counted as errors. -->
        <div class="unal-box"><div class="grp-h" style="padding-left:0"><span class="dot" style="background:var(--unal)"></span>Unaligned sections <span class="n">${unal.length}</span></div>
          <div class="chips">${unal.map(u => `<span class="chip unal" lang="${u.lang === 'zh' ? 'zh-Hant' : 'en'}" title="${esc(u.lang.toUpperCase())} p.${u.page}">${esc(u.heading)} <span class="faint mono">${esc(u.lang.toUpperCase())} p.${u.page}</span></span>`).join('') || '<span class="faint" style="font-size:12.5px">None</span>'}</div>
          <p class="note">Unchecked, not wrong</p></div>
      </nav>
      <main class="pane">${detail()}</main>
    </div>`}`;
  }
  function emptyState() {
    return `<div class="empty rise"><span class="zicon">${icon.tickL}</span><h2>No discrepancies found</h2><p>Both versions agree on every aligned passage.</p><a class="pill" href="#/">${icon.back} Check another pair</a></div>`;
  }
  function passage(side, lang) {
    if (!side || !side.text) return `<div class="passage" lang="${lang}"><span class="absent">No passage</span></div>`;
    const t = side.text, sp = Array.isArray(side.span) && side.span.length === 2 ? side.span : null;
    let inner;
    if (sp && sp[0] >= 0 && sp[1] > sp[0] && sp[1] <= t.length) inner = `${esc(t.slice(0, sp[0]))}<mark>${esc(t.slice(sp[0], sp[1]))}</mark>${esc(t.slice(sp[1]))}`;
    else inner = esc(t);
    return `<div class="passage" lang="${lang}">${inner}${sp ? '' : '<span class="absent">No span to highlight on this side</span>'}</div>`;
  }
  function detail() {
    const f = selected(); const id = state.run.run_id;
    if (!f) return `<div class="empty"><p>Select a finding on the left.</p></div>`;
    const pageBtn = (lang, n) => `<button class="pill xs" data-act="page" data-lang="${lang}" data-page="${n}" title="Open page ${n} thumbnail (Enter)"><span class="num">${esc(langName(lang))} · p.${n ?? '–'}</span></button>`;
    const decided = f.status !== 'unreviewed';
    return `<div class="pane-in" data-fid="${f.id}">
      <div class="crumb rise" style="--i:0"><span class="dot ${f.severity}"></span><span>${f.severity}</span><span class="faint">·</span><span class="sec">${esc(f.section || '')}</span></div>
      <!-- Two passage columns, English left and Chinese right, in that fixed order: reviewers read the authoritative language first and the order never changes between findings. -->
      <div class="cols">
        <div class="col rise" style="--i:1"><div class="colh"><span lang="${langCode('en')}">${esc(langName('en'))}</span>${pageBtn('en', f.en?.page)}</div>${passage(f.en, langCode('en'))}</div>
        <div class="col rise" style="--i:2"><div class="colh"><span lang="${langCode('zh')}">${esc(langName('zh'))}</span>${pageBtn('zh', f.zh?.page)}</div>${passage(f.zh, langCode('zh'))}</div>
      </div>
      <!-- Explanation is one sentence in ink at body size: it is the thing the reviewer actually reads, so it outranks the badges below it. -->
      <p class="expl rise" style="--i:3">${esc(f.explanation || '')}</p>
      <div class="meta rise" style="--i:4">
        <span class="chip outline"><span class="dot ${f.severity}"></span>${esc(humanType(f.type))}</span>
        <span class="chip" title="${f.source === 'deterministic' ? 'Found by exact number/date/currency checks' : 'Judged by the language model'}">${f.source === 'deterministic' ? 'Deterministic' : 'LLM'}</span>
        <span class="conf">Confidence ${pct(f.confidence)}</span>
        ${decided ? `<span class="decided" style="margin-left:auto">${glyphFor(f.status)} ${f.status[0].toUpperCase() + f.status.slice(1)}${f.dismiss_reason ? ` · ${esc(DISMISS_REASONS.find(r => r[0] === f.dismiss_reason)?.[1] || f.dismiss_reason)}` : ''}</span>` : ''}
      </div>
      <!-- Three decisions, one filled: Confirm is the expected path so it carries the accent; Dismiss and Unresolved stay hairline so the eye is never pulled to them. -->
      <div class="actions rise" style="--i:5" role="group" aria-label="Decision">
        <button class="pill primary" data-act="confirm" aria-pressed="${f.status === 'confirmed'}">Confirm <kbd>C</kbd></button>
        ${state.dismissOpen === f.id ? `<span class="dismiss-sel"><label class="sr" for="dismiss-reason">Dismiss reason</label>
          <select id="dismiss-reason" data-act="dismiss-reason" aria-label="Dismiss reason"><option value="">Reason for dismissing…</option>${DISMISS_REASONS.map(([v, l]) => `<option value="${v}" ${f.dismiss_reason === v ? 'selected' : ''}>${l}</option>`).join('')}</select>
          <button class="pill ghost sm" data-act="dismiss-cancel" aria-label="Cancel dismiss">Cancel</button></span>`
        : `<button class="pill" data-act="dismiss" aria-pressed="${f.status === 'dismissed'}">Dismiss <kbd>D</kbd></button>`}
        <button class="pill" data-act="unresolved" aria-pressed="${f.status === 'unresolved'}">Unresolved <kbd>U</kbd></button>
        <span class="faint" style="font-size:12.5px;margin-left:auto">J / K to move · Enter for page · Esc to close</span>
      </div>
      <div class="notebox rise" style="--i:6"><label for="note-${f.id}">Note</label>
        <textarea id="note-${f.id}" data-act="note" placeholder="Anything the signatory should know about this finding…" aria-label="Reviewer note">${esc(f.note || '')}</textarea></div>
    </div>`;
  }

  // ----- Report -----
  async function fillLocalReport(id, run) {
    const frame = $('#report-frame'); if (!frame) return;
    try {
      if (!reportCache[id]) {
        const r = await fetch(`${API}/report`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(run) });
        reportCache[id] = await r.text();
      }
      if ($('#report-frame')) $('#report-frame').srcdoc = reportCache[id];
    } catch (e) { toast(`Could not render the report: ${e.message}`); }
  }
  function viewReport() {
    const id = state.route.id;
    const local = loadLocal(id);
    if (local) {
      delete reportCache[id]; // decisions may have changed since the last render
      setTimeout(() => fillLocalReport(id, local), 0);
      const blob = URL.createObjectURL(new Blob([JSON.stringify(local, null, 1)], { type: 'application/json' }));
      return `<div class="report">
      <div class="rbar">
        <a class="pill" href="#/run/${encodeURIComponent(id)}">${icon.back} Back to review</a>
        <span class="sp"></span>
        <a class="pill" href="${blob}" download="concord-${esc(id)}.json">Export JSON</a>
        <button class="pill primary" data-act="print">${icon.dl} Download PDF</button>
      </div>
      <div class="rframe"><iframe id="report-frame" title="Sign-off report preview"></iframe></div>
    </div>`;
    }
    return `<div class="report">
      <!-- Report bar mirrors the review header height so the transition feels like the same tool, and the iframe IS the artefact the client receives — nothing is re-rendered client-side. -->
      <div class="rbar">
        <a class="pill" href="#/run/${encodeURIComponent(id)}">${icon.back} Back to review</a>
        <span class="sp"></span>
        <a class="pill" href="${api.exportUrl(id)}" download="concord-${esc(id)}.json">Export JSON</a>
        <button class="pill primary" data-act="print">${icon.dl} Download PDF</button>
      </div>
      <div class="rframe"><iframe id="report-frame" src="${api.reportUrl(id)}" title="Sign-off report preview"></iframe></div>
    </div>`;
  }

  // ----- Modal + toast -----
  const modalRoot = $('#modal-root');
  function renderModal() {
    const m = state.modal;
    if (!m || !state.run) { modalRoot.innerHTML = ''; return; }
    const src = api.pageUrl(state.run.run_id, m.lang, m.page);
    modalRoot.innerHTML = `<div class="modal-bg" data-act="modal-close" role="dialog" aria-modal="true" aria-label="${esc(langName(m.lang))} page ${m.page}">
      <div class="modal" data-stop>
        <div class="mh"><span>${esc(langName(m.lang))} · page <span class="num">${m.page}</span></span>
          <button class="pill sm" data-act="modal-close" autofocus>${icon.close} Close</button></div>
        <div class="mb"><img src="${src}" alt="${m.lang.toUpperCase()} page ${m.page}" onerror="this.outerHTML='<p class=&quot;mfail&quot;>Page thumbnail is not available for this run.</p>'"></div>
      </div></div>`;
    const b = $('button', modalRoot); if (b) b.focus();
  }
  function renderToast() {
    let t = $('.toast');
    if (!state.toast) { if (t) t.remove(); return; }
    if (!t) { t = document.createElement('div'); t.className = 'toast'; t.setAttribute('role', 'status'); document.body.appendChild(t); }
    t.textContent = state.toast;
  }
  function openPage(lang, page) { if (!page) return; state.modal = { lang, page: Number(page) }; renderModal(); }
  function closeModal() { if (!state.modal) return; state.modal = null; renderModal(); }

  // ---------- Events (delegated) ----------
  document.addEventListener('click', e => {
    const el = e.target.closest('[data-act]'); if (!el) return;
    const act = el.dataset.act;
    if (act === 'modal-close') { if (e.target.closest('[data-stop]') && !e.target.closest('button')) return; closeModal(); return; }
    switch (act) {
      case 'sample': e.preventDefault(); loadSample(); break;
      case 'clear': state.upload[el.dataset.zone] = null; render(); break;
      case 'auth': state.upload.authoritative = el.dataset.v; render(); break;
      case 'run': submitRun(); break;
      case 'toggle': state.open[el.dataset.sev] = !state.open[el.dataset.sev]; render(); break;
      case 'select': select(el.dataset.fid); break;
      case 'page': openPage(el.dataset.lang, el.dataset.page); break;
      case 'confirm': if (selected()) decide(selected().id, { status: 'confirmed' }); break;
      case 'unresolved': if (selected()) decide(selected().id, { status: 'unresolved' }); break;
      case 'dismiss': if (selected()) { state.dismissOpen = selected().id; render(); } break;
      case 'dismiss-cancel': state.dismissOpen = null; render(); break;
      case 'export': if (exportUnlocked() && state.run) location.hash = `#/run/${encodeURIComponent(state.run.run_id)}/report`; break;
      case 'print': { const f = $('#report-frame'); try { f.contentWindow.focus(); f.contentWindow.print(); } catch { window.open(f.src, '_blank'); } break; }
    }
  });
  document.addEventListener('change', e => {
    const el = e.target;
    if (el.matches('input[type=file][data-zone]')) { acceptFile(el.dataset.zone, el.files && el.files[0]); return; }
    if (el.matches('[data-act="dismiss-reason"]') && el.value && selected()) decide(selected().id, { status: 'dismissed', dismiss_reason: el.value });
  });
  document.addEventListener('focusout', e => {
    const el = e.target;
    if (el.matches && el.matches('textarea[data-act="note"]') && selected()) {
      const v = el.value.trim() || null;
      if (v !== (selected().note || null)) decide(selected().id, { note: v });
    }
  });
  // Drag and drop on the zones.
  document.addEventListener('dragover', e => { const z = e.target.closest('.zone'); if (z) { e.preventDefault(); z.classList.add('over'); } });
  document.addEventListener('dragleave', e => { const z = e.target.closest('.zone'); if (z && !z.contains(e.relatedTarget)) z.classList.remove('over'); });
  document.addEventListener('drop', e => {
    const z = e.target.closest('.zone'); if (!z) return; e.preventDefault(); z.classList.remove('over');
    const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    acceptFile(z.dataset.zone, file);
  });
  // Keyboard: C/D/U decide, J/K or arrows move, Enter opens the EN page, Esc closes. Ignored while typing.
  document.addEventListener('keydown', e => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const typing = e.target instanceof Element && (/^(TEXTAREA|INPUT|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable);
    if (e.key === 'Escape') {
      if (state.modal) { closeModal(); return; }
      if (state.dismissOpen) { state.dismissOpen = null; render(); return; }
      if (typing) e.target.blur();
      return;
    }
    if (typing) return;
    if (state.route.view !== 'run' || !state.run || state.run.status !== 'done') return;
    const f = selected();
    switch (e.key) {
      case 'j': case 'J': case 'ArrowDown': e.preventDefault(); move(1); break;
      case 'k': case 'K': case 'ArrowUp': e.preventDefault(); move(-1); break;
      case 'c': case 'C': if (f) decide(f.id, { status: 'confirmed' }); break;
      case 'u': case 'U': if (f) decide(f.id, { status: 'unresolved' }); break;
      case 'd': case 'D': if (f) { state.dismissOpen = f.id; render(); } break;
      case 'Enter': { // Enter on a rail row or on the page body opens the EN page; on any other control it keeps its native click.
        const t = e.target instanceof Element ? e.target : document.body;
        if (f && !state.modal && (t.closest('.frow') || !t.closest('button, a'))) { e.preventDefault(); openPage('en', f.en?.page); }
        break; }
    }
  });
  window.addEventListener('hashchange', route);

  // Expose for the presenter's console and for tests; harmless in production.
  window.concord = { state, render, decide, select, api, FIXTURE, onProgress };
  route();
})();
