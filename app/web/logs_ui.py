"""Logs browser UI — sortable/filterable editable table."""

from __future__ import annotations

from html import escape

from app.web.styles import SHARED_CSS, nav_html

LOGS_CSS = """
.page-logs { max-width: 1280px; }
.page-logs .mast { margin-bottom: 0.55rem; }
.series-filter-banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 0.85rem;
  margin: 0 0 0.65rem;
  padding: 0.55rem 0.75rem;
  border: 2px solid var(--ink);
  background: var(--blue-bg);
  font-size: 0.88rem;
  font-weight: 600;
}
.series-filter-banner[hidden] { display: none; }
.series-filter-banner code {
  font-family: var(--mono);
  font-size: 0.82rem;
  font-weight: 700;
}
.series-filter-banner button {
  appearance: none;
  font: inherit;
  font-size: 0.78rem;
  font-weight: 700;
  padding: 0.3rem 0.55rem;
  border: 1px solid var(--ink);
  background: var(--panel);
  cursor: pointer;
  border-radius: 2px;
}
/* Content filter tabs */
.logs-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0;
  margin: 0 0 0.75rem;
  border: 1px solid var(--line-strong);
  border-bottom: 2px solid var(--ink);
  background: var(--panel-2);
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}
.logs-tabs[role="tablist"] { scrollbar-width: thin; }
.logs-tab {
  appearance: none;
  border: none;
  border-right: 1px solid var(--line);
  border-radius: 0;
  background: transparent;
  color: var(--ink-soft);
  font-family: inherit;
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.01em;
  padding: 0.55rem 0.85rem;
  margin: 0;
  cursor: pointer;
  white-space: nowrap;
  box-shadow: none;
}
.logs-tab:hover {
  background: var(--paper);
  color: var(--ink);
  text-decoration: none;
}
.logs-tab:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
  z-index: 1;
}
.logs-tab.active {
  background: var(--panel);
  color: var(--ink);
  box-shadow: inset 0 -3px 0 var(--accent);
}
.logs-tab .tab-count {
  font-family: var(--mono);
  font-size: 0.68rem;
  font-weight: 600;
  color: var(--faint);
  margin-left: 0.3rem;
}
.logs-tab.active .tab-count { color: var(--muted); }
.logs-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 0.55rem 0.85rem;
  margin-bottom: 0.75rem;
  padding: 0.75rem 0.85rem;
  border: 1px solid var(--line-strong);
  background: var(--panel);
}
.logs-toolbar .field { min-width: 7rem; flex: 1 1 8rem; }
.logs-toolbar .field.grow { flex: 2 1 14rem; }
.logs-toolbar .field.hidden-by-tab { display: none; }
.logs-toolbar label {
  margin-top: 0;
  margin-bottom: 0.2rem;
}
.logs-toolbar input, .logs-toolbar select {
  font-size: 0.86rem;
  padding: 0.4rem 0.5rem;
}
.logs-toolbar .actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: center;
  margin-left: auto;
}
.logs-meta {
  font-family: var(--mono);
  font-size: 0.78rem;
  color: var(--muted);
  margin: 0 0 0.55rem;
}
.logs-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--line-strong);
  background: var(--panel);
}
table.logs-table {
  min-width: 1080px;
  width: 100%;
  border-collapse: collapse;
  font-size: 0.84rem;
}
table.logs-table th, table.logs-table td {
  border-bottom: 1px solid var(--line);
  padding: 0.4rem 0.45rem;
  text-align: left;
  vertical-align: middle;
}
table.logs-table th {
  position: sticky;
  top: 0;
  z-index: 1;
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
  font-weight: 700;
  background: var(--panel-2);
  border-bottom: 1px solid var(--line-strong);
  white-space: nowrap;
  user-select: none;
}
table.logs-table th[data-sort] {
  cursor: pointer;
}
table.logs-table th[data-sort]:hover { color: var(--ink); }
table.logs-table th.sorted { color: var(--accent); }
table.logs-table th .sort-ind {
  font-family: var(--mono);
  font-size: 0.65rem;
  opacity: 0.7;
  margin-left: 0.2rem;
}
table.logs-table tr:hover td { background: var(--paper-2); }
table.logs-table tr.editing td { background: var(--amber-bg); }
table.logs-table .col-id { font-family: var(--mono); color: var(--faint); width: 3rem; }
table.logs-table .col-amt { font-family: var(--mono); white-space: nowrap; }
table.logs-table .col-score { font-family: var(--mono); font-size: 0.8rem; }
table.logs-table .col-title { min-width: 10rem; max-width: 18rem; }
table.logs-table .col-actions { white-space: nowrap; }
table.logs-table .col-actions button {
  margin: 0.08rem 0.1rem;
  padding: 0.28rem 0.45rem;
  font-size: 0.75rem;
}
table.logs-table .col-actions .log-del-btn.is-armed,
.recent-table .log-del-btn.is-armed {
  background: #7f1d1d;
  color: #fff;
  border-color: #450a0a;
  animation: log-del-pulse 1s ease infinite alternate;
}
@keyframes log-del-pulse {
  from { filter: brightness(1); }
  to { filter: brightness(1.12); }
}
table.logs-table td input,
table.logs-table td select {
  width: 100%;
  min-width: 0;
  font-size: 0.82rem;
  padding: 0.28rem 0.35rem;
}
table.logs-table td input.cell-num { max-width: 5rem; font-family: var(--mono); }
table.logs-table td input.cell-se { max-width: 3.2rem; font-family: var(--mono); }
.badge-status {
  display: inline-block;
  font-family: var(--mono);
  font-size: 0.72rem;
  padding: 0.12rem 0.4rem;
  border: 1px solid var(--line-strong);
  background: var(--panel-2);
  border-radius: 2px;
}
.badge-status.pending { background: var(--amber-bg); border-color: #d4b86a; color: var(--amber); }
.badge-status.ready { background: var(--blue-bg); border-color: #8aadc8; color: var(--blue); }
.badge-status.pushed { background: var(--green-bg); border-color: #8fbf95; color: var(--green); }
.badge-status.failed { background: var(--red-bg); border-color: #d4a09a; color: var(--red); }
.badge-status.skipped, .badge-status.n\\/a { opacity: 0.75; }
.logs-create {
  margin-top: 1rem;
  border: 1px solid var(--line-strong);
  background: var(--panel);
  padding: 0.85rem 0.95rem;
}
.logs-create h2 {
  margin: 0 0 0.35rem;
  font-size: 0.95rem;
}
.logs-create .row { margin-top: 0.25rem; }
.logs-create .form-actions { margin-top: 0.75rem; }
.drawer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(28, 25, 20, 0.35);
  z-index: 40;
  display: none;
  align-items: stretch;
  justify-content: flex-end;
}
.drawer-overlay.open { display: flex; }
.edit-drawer {
  width: min(420px, 100vw);
  background: var(--panel);
  border-left: 2px solid var(--ink);
  box-shadow: -8px 0 24px rgba(28,25,20,0.12);
  padding: 1rem 1.1rem 1.5rem;
  overflow-y: auto;
}
.edit-drawer h2 {
  margin: 0 0 0.25rem;
  font-size: 1.05rem;
  font-family: var(--display);
}
.edit-drawer .drawer-sub {
  font-size: 0.78rem;
  color: var(--muted);
  font-family: var(--mono);
  margin-bottom: 0.75rem;
}
.edit-drawer .drawer-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-top: 1rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--line);
}
button.danger {
  background: var(--red);
  color: #fff;
  border-color: #7a2a24;
}
button.danger:hover { background: #8a3028; }
.edit-drawer button.danger { margin-left: auto; }
button.danger.log-del-btn.is-armed {
  background: #7f1d1d;
  border-color: #450a0a;
}
"""

LOGS_JS = r"""
const CONTENT_TYPES = ['anime','show','movie','youtube','book','manga','visual_novel','game','podcast','study'];
const ACTIVITIES = ['listening','reading','writing','speaking','study'];
const UNITS = ['minutes','minutes_high_density','pages','two_column_pages','comic_pages','characters','sentences'];
const TADOKU_MODES = ['auto','pending','never'];
const TADOKU_STATUSES = ['pending','ready','pushed','failed','skipped','n/a'];
const SOURCES = ['manual','youtube','plex','steam','sheet','other'];

/* Top filter tabs — Recent is default */
const LOG_TABS = [
  { id: 'recent', label: 'Recent' },
  { id: 'all', label: 'All' },
];
const RECENT_LIMIT = 50;

const state = {
  rows: [],
  sortKey: 'timestamp',
  sortDir: 'desc',
  tab: 'recent',
  filter: { q: '', status: '', content_type: '', source: '', series_key: '' },
  limit: 200,
  editingId: null,
};

function currentTab(){
  return LOG_TABS.find(t => t.id === state.tab) || LOG_TABS[0];
}
function paintTabs(){
  const host = document.getElementById('logs-tabs');
  if(!host) return;
  host.querySelectorAll('.logs-tab').forEach(btn => {
    const on = btn.dataset.tab === state.tab;
    btn.classList.toggle('active', on);
    btn.setAttribute('aria-selected', on ? 'true' : 'false');
    btn.tabIndex = on ? 0 : -1;
  });
}
function setTab(tabId){
  if(!LOG_TABS.some(t => t.id === tabId)) return;
  state.tab = tabId;
  // Recent always newest-first
  if(tabId === 'recent'){
    state.sortKey = 'timestamp';
    state.sortDir = 'desc';
  }
  paintTabs();
  loadLogs();
}
function bindTabs(){
  const host = document.getElementById('logs-tabs');
  if(!host || host._bound) return;
  host._bound = true;
  host.addEventListener('click', (ev) => {
    const btn = ev.target.closest('.logs-tab');
    if(!btn || !host.contains(btn)) return;
    setTab(btn.dataset.tab);
  });
  host.addEventListener('keydown', (ev) => {
    const tabs = [...host.querySelectorAll('.logs-tab')];
    const i = tabs.findIndex(t => t.dataset.tab === state.tab);
    if(ev.key === 'ArrowRight' && i >= 0 && i < tabs.length - 1){
      ev.preventDefault(); setTab(tabs[i+1].dataset.tab); tabs[i+1].focus();
    } else if(ev.key === 'ArrowLeft' && i > 0){
      ev.preventDefault(); setTab(tabs[i-1].dataset.tab); tabs[i-1].focus();
    } else if(ev.key === 'Home'){
      ev.preventDefault(); setTab(tabs[0].dataset.tab); tabs[0].focus();
    } else if(ev.key === 'End'){
      ev.preventDefault(); setTab(tabs[tabs.length-1].dataset.tab); tabs[tabs.length-1].focus();
    }
  });
}

function escapeHtml(s){
  return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function setMsg(t, kind){
  const el = document.getElementById('logs-msg');
  if(!el) return;
  el.textContent = t || '';
  el.className = 'form-msg' + (kind ? ' ' + kind : '');
}
function epLabel(e){
  const s=e.season, ep=e.episode;
  if(s!=null && ep!=null) return `S${String(s).padStart(2,'0')}E${String(ep).padStart(2,'0')}`;
  if(s!=null) return `S${String(s).padStart(2,'0')}`;
  if(ep!=null) return `E${String(ep).padStart(2,'0')}`;
  return '';
}
function fmtWhen(ts){
  if(!ts) return '—';
  return String(ts).slice(0,19).replace('T',' ');
}
function statusBadge(st){
  const s = (st||'').toLowerCase();
  return `<span class="badge-status ${escapeHtml(s)}">${escapeHtml(st||'—')}</span>`;
}
function cmp(a, b, key){
  let va = a[key], vb = b[key];
  if(key === 'timestamp' || key === 'updated_at'){
    va = va || ''; vb = vb || '';
    return va < vb ? -1 : va > vb ? 1 : 0;
  }
  if(key === 'amount' || key === 'tadoku_score_estimate' || key === 'id' || key === 'season' || key === 'episode'){
    const na = Number(va), nb = Number(vb);
    if(!isNaN(na) && !isNaN(nb)) return na - nb;
  }
  if(key === 'ep'){
    const as = a.season==null?9999:a.season, bs = b.season==null?9999:b.season;
    if(as!==bs) return as-bs;
    const ae = a.episode==null?9999:a.episode, be = b.episode==null?9999:b.episode;
    return ae-be;
  }
  va = (va==null?'':String(va)).toLowerCase();
  vb = (vb==null?'':String(vb)).toLowerCase();
  return va.localeCompare(vb);
}
function sortedRows(){
  const rows = state.rows.slice();
  const dir = state.sortDir === 'asc' ? 1 : -1;
  rows.sort((a,b)=>{
    const c = cmp(a,b,state.sortKey);
    return c === 0 ? (a.id - b.id) : c * dir;
  });
  return rows;
}
function paintSortHeaders(){
  document.querySelectorAll('table.logs-table th[data-sort]').forEach(th=>{
    const k = th.getAttribute('data-sort');
    const on = k === state.sortKey;
    th.classList.toggle('sorted', on);
    let ind = th.querySelector('.sort-ind');
    if(!ind){
      ind = document.createElement('span');
      ind.className = 'sort-ind';
      th.appendChild(ind);
    }
    ind.textContent = on ? (state.sortDir === 'asc' ? '▲' : '▼') : '';
  });
}
function renderTable(){
  const tb = document.getElementById('logs-tbody');
  const meta = document.getElementById('logs-meta');
  if(!tb) return;
  const rows = sortedRows();
  const tab = currentTab();
  if(meta){
    const tabLabel = tab.label || state.tab;
    meta.textContent = rows.length
      ? `${tabLabel} · ${rows.length} log(s) · click headers to sort · Edit opens full form`
      : `No logs in ${tabLabel}. Try another type or clear search.`;
  }
  paintSortHeaders();
  if(!rows.length){
    tb.innerHTML = `<tr><td colspan="12" class="empty-q" style="border:0">Nothing here. Adjust filters or add a log below.</td></tr>`;
    return;
  }
  tb.innerHTML = rows.map(e=>{
    const tt = e.tadoku_title || e.title || '';
    const ep = epLabel(e);
    return `<tr data-id="${e.id}">
      <td class="col-id col-hide-md">${e.id}</td>
      <td class="mono">${escapeHtml(fmtWhen(e.timestamp))}</td>
      <td>${escapeHtml(e.content_type||'')}</td>
      <td class="col-title" title="${escapeHtml(tt)}">${escapeHtml(tt)}</td>
      <td class="ep">${escapeHtml(ep||'—')}</td>
      <td class="col-amt">${e.amount} <span class="muted">${escapeHtml(e.unit||'')}</span></td>
      <td class="col-hide-sm">${escapeHtml(e.activity||'')}</td>
      <td class="col-hide-sm">${escapeHtml(e.source||'')}</td>
      <td>${statusBadge(e.tadoku_status)}</td>
      <td class="muted col-hide-md">${escapeHtml(e.tadoku_mode||'')}</td>
      <td class="col-score col-hide-md">${e.tadoku_score_estimate!=null?Number(e.tadoku_score_estimate).toFixed(2):'—'}</td>
      <td class="col-actions">
        <button type="button" class="secondary" onclick="openEdit(${e.id})">Edit</button>
        <button type="button" class="danger log-del-btn" data-log-id="${e.id}"
          onclick="armOrDeleteLogRow(this)" title="Delete this log">Delete</button>
      </td>
    </tr>`;
  }).join('');
}
/** First click → Confirm?; second click deletes. */
function armOrDeleteLogRow(btn){
  if(!btn) return;
  const id=Number(btn.dataset.logId||btn.getAttribute('data-log-id'));
  if(!id) return;
  if(btn.dataset.armed==='1'){
    deleteLogRow(id, btn);
    return;
  }
  document.querySelectorAll('.log-del-btn.is-armed').forEach(b=>{
    if(b===btn) return;
    b.dataset.armed='';
    b.classList.remove('is-armed');
    b.textContent='Delete';
    b.disabled=false;
  });
  btn.dataset.armed='1';
  btn.classList.add('is-armed');
  btn.textContent='Confirm?';
  if(btn._armTimer) clearTimeout(btn._armTimer);
  btn._armTimer=setTimeout(()=>{
    if(btn.dataset.armed==='1'){
      btn.dataset.armed='';
      btn.classList.remove('is-armed');
      btn.textContent='Delete';
    }
  }, 4000);
}
async function deleteLogRow(id, btn){
  if(btn){ btn.disabled=true; btn.textContent='…'; }
  setMsg('Deleting #'+id+'…');
  try{
    const r=await fetch('/api/logs/'+id,{method:'DELETE'});
    if(!r.ok){
      setMsg('Delete failed', 'err');
      if(btn){ btn.disabled=false; btn.dataset.armed=''; btn.classList.remove('is-armed'); btn.textContent='Delete'; }
      return;
    }
    setMsg('Deleted #'+id, 'ok');
    if(state.editingId===id) closeEdit();
    await loadLogs();
  }catch(e){
    setMsg('Delete failed (network)', 'err');
    if(btn){ btn.disabled=false; btn.dataset.armed=''; btn.classList.remove('is-armed'); btn.textContent='Delete'; }
  }
}
function toggleSort(key){
  if(state.sortKey === key){
    state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
  } else {
    state.sortKey = key;
    state.sortDir = (key === 'timestamp' || key === 'id' || key === 'amount') ? 'desc' : 'asc';
  }
  renderTable();
}
function bindSortHeaders(){
  document.querySelectorAll('table.logs-table th[data-sort]').forEach(th=>{
    th.addEventListener('click', ()=> toggleSort(th.getAttribute('data-sort')));
  });
}
function readFilters(){
  state.filter.q = (document.getElementById('f-q')?.value || '').trim();
  state.filter.status = document.getElementById('f-status')?.value || '';
  state.filter.source = document.getElementById('f-source')?.value || '';
  // Type from toolbar select (independent of Recent/All scope)
  state.filter.content_type = document.getElementById('f-type')?.value || '';
  // series_key is sticky from URL/Progress deep-link until cleared (not in toolbar form)
  const limEl = document.getElementById('f-limit');
  if(state.tab === 'recent' && !state.filter.series_key){
    state.limit = RECENT_LIMIT;
  } else {
    const lim = parseInt(limEl?.value || '200', 10);
    state.limit = isNaN(lim) ? 200 : Math.min(500, Math.max(20, lim));
  }
  // Hide limit control on Recent (fixed window) unless series deep-link forces All
  const limField = document.getElementById('f-limit-wrap');
  if(limField) limField.classList.toggle('hidden-by-tab', state.tab === 'recent' && !state.filter.series_key);
  paintSeriesBanner();
}
function paintSeriesBanner(){
  const ban = document.getElementById('series-filter-banner');
  if(!ban) return;
  const sk = (state.filter.series_key || '').trim();
  if(!sk){
    ban.hidden = true;
    ban.innerHTML = '';
    return;
  }
  ban.hidden = false;
  ban.innerHTML =
    `<span>Series filter: <code class="mono">${escapeHtml(sk)}</code></span>` +
    `<button type="button" class="secondary" id="btn-clear-series">Clear series</button>`;
  document.getElementById('btn-clear-series')?.addEventListener('click', clearSeriesFilter);
}
function clearSeriesFilter(){
  state.filter.series_key = '';
  try{
    const u = new URL(window.location.href);
    u.searchParams.delete('series_key');
    history.replaceState(null, '', u.pathname + u.search + u.hash);
  }catch(e){}
  paintSeriesBanner();
  loadLogs();
}
function applyUrlParams(){
  try{
    const u = new URL(window.location.href);
    const sk = (u.searchParams.get('series_key') || '').trim();
    const q = (u.searchParams.get('q') || '').trim();
    if(sk){
      state.filter.series_key = sk;
      // Deep-link from Progress: show full series history, not Recent window
      state.tab = 'all';
      const limEl = document.getElementById('f-limit');
      if(limEl && (!limEl.value || Number(limEl.value) < 200)) limEl.value = '200';
    }
    if(q){
      state.filter.q = q;
      const fq = document.getElementById('f-q');
      if(fq) fq.value = q;
    }
    const ct = (u.searchParams.get('content_type') || '').trim();
    if(ct){
      const ft = document.getElementById('f-type');
      if(ft){ ft.value = ct; state.filter.content_type = ct; }
    }
  }catch(e){}
}
function syncLogsUrl(){
  try{
    const u = new URL(window.location.href);
    if(state.filter.series_key) u.searchParams.set('series_key', state.filter.series_key);
    else u.searchParams.delete('series_key');
    if(state.filter.q) u.searchParams.set('q', state.filter.q);
    else u.searchParams.delete('q');
    history.replaceState(null, '', u.pathname + u.search + u.hash);
  }catch(e){}
}
async function loadLogs(){
  readFilters();
  paintTabs();
  syncLogsUrl();
  const params = new URLSearchParams();
  params.set('limit', String(state.limit));
  if(state.filter.q) params.set('q', state.filter.q);
  if(state.filter.status) params.set('tadoku_status', state.filter.status);
  if(state.filter.content_type) params.set('content_type', state.filter.content_type);
  if(state.filter.source) params.set('source', state.filter.source);
  if(state.filter.series_key) params.set('series_key', state.filter.series_key);
  setMsg('Loading…');
  try{
    const r = await fetch('/api/logs?' + params.toString());
    if(!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    state.rows = Array.isArray(data) ? data : [];
    renderTable();
    const tab = currentTab();
    const sk = state.filter.series_key
      ? ` · series ${state.filter.series_key}`
      : '';
    setMsg(`${tab.label}: ${state.rows.length} log(s)${sk}`, 'ok');
  }catch(e){
    state.rows = [];
    renderTable();
    setMsg('Failed to load logs', 'err');
  }
}
function optionsHtml(list, selected, {blankLabel}={}){
  let html = '';
  if(blankLabel != null){
    html += `<option value="">${escapeHtml(blankLabel)}</option>`;
  }
  for(const v of list){
    html += `<option value="${escapeHtml(v)}"${v===selected?' selected':''}>${escapeHtml(v)}</option>`;
  }
  return html;
}
function findRow(id){
  return state.rows.find(r => r.id === id);
}
function openEdit(id){
  const e = findRow(id);
  if(!e){ setMsg('Log not in current list — reload', 'err'); return; }
  state.editingId = id;
  const overlay = document.getElementById('edit-overlay');
  const body = document.getElementById('edit-body');
  if(!overlay || !body) return;
  const ts = e.timestamp ? String(e.timestamp).slice(0,16) : '';
  body.innerHTML = `
    <h2>Edit log #${e.id}</h2>
    <p class="drawer-sub">Changes save to SQLite and mark Google Sheets for sync.</p>
    <label for="ed-title">Title</label>
    <input id="ed-title" value="${escapeHtml(e.title||'')}"/>
    <div class="row">
      <div>
        <label for="ed-type">Content type</label>
        <select id="ed-type">${optionsHtml(CONTENT_TYPES, e.content_type)}</select>
      </div>
      <div>
        <label for="ed-source">Source</label>
        <select id="ed-source">${optionsHtml(SOURCES, e.source)}</select>
      </div>
    </div>
    <div class="row">
      <div>
        <label for="ed-season">Season</label>
        <input id="ed-season" class="cell-se" type="number" step="1" value="${e.season!=null?e.season:''}" placeholder="—"/>
      </div>
      <div>
        <label for="ed-episode">Episode</label>
        <input id="ed-episode" class="cell-se" type="number" step="1" value="${e.episode!=null?e.episode:''}" placeholder="—"/>
      </div>
    </div>
    <div class="row">
      <div>
        <label for="ed-amount">Amount</label>
        <input id="ed-amount" class="cell-num" type="number" step="any" min="0" value="${e.amount}"/>
      </div>
      <div>
        <label for="ed-unit">Unit</label>
        <select id="ed-unit">${optionsHtml(UNITS, e.unit)}</select>
      </div>
    </div>
    <div class="row">
      <div>
        <label for="ed-activity">Activity</label>
        <select id="ed-activity">${optionsHtml(ACTIVITIES, e.activity)}</select>
      </div>
      <div>
        <label for="ed-series">Series key</label>
        <input id="ed-series" value="${escapeHtml(e.series_key||'')}" placeholder="anime:…"/>
      </div>
    </div>
    <div class="row">
      <div>
        <label for="ed-status">Tadoku status</label>
        <select id="ed-status">${optionsHtml(TADOKU_STATUSES, e.tadoku_status)}</select>
      </div>
      <div>
        <label for="ed-mode">Tadoku mode</label>
        <select id="ed-mode">${optionsHtml(TADOKU_MODES, e.tadoku_mode)}</select>
      </div>
    </div>
    <label for="ed-ts">Timestamp (local ISO)</label>
    <input id="ed-ts" type="datetime-local" value="${escapeHtml(ts)}"/>
    <label for="ed-notes">Notes</label>
    <input id="ed-notes" value="${escapeHtml(e.notes||'')}"/>
    <label for="ed-tags">Tags</label>
    <input id="ed-tags" value="${escapeHtml(e.tags||'')}"/>
    <div class="drawer-actions">
      <button type="button" class="process" onclick="saveEdit()">Save</button>
      <button type="button" class="secondary" onclick="closeEdit()">Cancel</button>
      <button type="button" class="danger" onclick="deleteEdit()">Delete</button>
    </div>`;
  overlay.classList.add('open');
  overlay.setAttribute('aria-hidden', 'false');
}
function closeEdit(){
  state.editingId = null;
  const overlay = document.getElementById('edit-overlay');
  if(overlay){
    overlay.classList.remove('open');
    overlay.setAttribute('aria-hidden', 'true');
  }
}
function numOrNull(v){
  if(v === '' || v == null) return null;
  const n = Number(v);
  return isNaN(n) ? null : n;
}
async function saveEdit(){
  const id = state.editingId;
  if(!id) return;
  const body = {
    title: document.getElementById('ed-title').value.trim(),
    content_type: document.getElementById('ed-type').value,
    source: document.getElementById('ed-source').value,
    season: numOrNull(document.getElementById('ed-season').value),
    episode: numOrNull(document.getElementById('ed-episode').value),
    amount: Number(document.getElementById('ed-amount').value),
    unit: document.getElementById('ed-unit').value,
    activity: document.getElementById('ed-activity').value,
    series_key: document.getElementById('ed-series').value.trim() || null,
    tadoku_status: document.getElementById('ed-status').value,
    tadoku_mode: document.getElementById('ed-mode').value,
    notes: document.getElementById('ed-notes').value || null,
    tags: document.getElementById('ed-tags').value.trim() || null,
  };
  const tsRaw = document.getElementById('ed-ts').value;
  if(tsRaw){
    // datetime-local → ISO; treat as local then send as-is with seconds
    body.timestamp = tsRaw.length === 16 ? tsRaw + ':00' : tsRaw;
  }
  if(!body.title){ setMsg('Title required', 'err'); return; }
  if(!(body.amount > 0)){ setMsg('Amount must be > 0', 'err'); return; }
  setMsg(`Saving #${id}…`);
  try{
    const r = await fetch('/api/logs/' + id, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    let j = null;
    try{ j = await r.json(); }catch(e){}
    if(!r.ok){
      setMsg(j && j.detail ? String(j.detail) : 'Save failed', 'err');
      return;
    }
    setMsg(`Saved #${id} → ${j.tadoku_status} / ${j.tadoku_mode}`, 'ok');
    closeEdit();
    await loadLogs();
  }catch(e){
    setMsg('Save failed (network)', 'err');
  }
}
async function deleteEdit(){
  const id = state.editingId;
  if(!id) return;
  if(!confirm(`Delete log #${id}? This removes it from the database and will sync to Sheets.`)) return;
  setMsg(`Deleting #${id}…`);
  try{
    const r = await fetch('/api/logs/' + id, { method: 'DELETE' });
    if(!r.ok){
      setMsg('Delete failed', 'err');
      return;
    }
    setMsg(`Deleted #${id}`, 'ok');
    closeEdit();
    await loadLogs();
  }catch(e){
    setMsg('Delete failed (network)', 'err');
  }
}
async function createLog(submit){
  const modeSel = document.getElementById('c-mode').value || null;
  const body = {
    content_type: document.getElementById('c-type').value,
    title: document.getElementById('c-title').value.trim(),
    amount: Number(document.getElementById('c-amount').value),
    unit: document.getElementById('c-unit').value || null,
    activity: document.getElementById('c-activity').value || null,
    series_key: document.getElementById('c-series').value.trim() || null,
    season: numOrNull(document.getElementById('c-season').value),
    episode: numOrNull(document.getElementById('c-episode').value),
    source: 'manual',
    tadoku_mode: submit ? 'auto' : modeSel,
    notes: document.getElementById('c-notes').value.trim() || null,
  };
  if(!body.title){ setMsg('Title required', 'err'); return; }
  if(!(body.amount > 0)){ setMsg('Amount must be > 0', 'err'); return; }
  setMsg(submit ? 'Logging & submitting…' : 'Creating…');
  try{
    const r = await fetch('/api/logs', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    let j = null;
    try{ j = await r.json(); }catch(e){}
    if(!r.ok){
      setMsg(j && j.detail ? JSON.stringify(j.detail) : 'Create failed', 'err');
      return;
    }
    let status = j.tadoku_status;
    if(submit && j.id){
      const ar = await fetch('/api/logs/' + j.id + '/approve', { method: 'POST' });
      let aj = null;
      try{ aj = await ar.json(); }catch(e){}
      if(!ar.ok){
        setMsg(`Created #${j.id}, submit failed`, 'err');
        await loadLogs();
        return;
      }
      status = aj.tadoku_status || status;
    }
    setMsg(`${submit ? 'Submitted' : 'Created'} #${j.id} · ${j.tadoku_title || j.title} · ${status}`, 'ok');
    document.getElementById('c-title').value = '';
    document.getElementById('c-amount').value = '';
    document.getElementById('c-notes').value = '';
    await loadLogs();
  }catch(e){
    setMsg(submit ? 'Submit failed (network)' : 'Create failed (network)', 'err');
  }
}
function onOverlayClick(ev){
  if(ev.target && ev.target.id === 'edit-overlay') closeEdit();
}
document.addEventListener('keydown', (ev)=>{
  if(ev.key === 'Escape') closeEdit();
});
applyUrlParams();
bindTabs();
paintTabs();
bindSortHeaders();
loadLogs();
"""


def logs_page(*, tautulli: str, tadoku: str, sheets: str, plex: str) -> str:
    nav = nav_html(
        "logs",
        tautulli=tautulli,
        tadoku=tadoku,
        sheets=sheets,
        plex=plex,
    )
    fonts = (
        '<link rel="preconnect" href="https://fonts.googleapis.com"/>'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>'
        '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700'
        '&family=IBM+Plex+Sans:wght@400;600;700&family=IBM+Plex+Serif:wght@500;600'
        '&display=swap" rel="stylesheet"/>'
    )
    type_opts = "".join(
        f'<option value="{escape(t)}">{escape(t)}</option>'
        for t in (
            "anime",
            "show",
            "movie",
            "youtube",
            "book",
            "manga",
            "visual_novel",
            "game",
            "podcast",
            "study",
        )
    )
    unit_opts = "".join(
        f'<option value="{escape(u)}">{escape(u)}</option>'
        for u in (
            "minutes",
            "minutes_high_density",
            "pages",
            "two_column_pages",
            "comic_pages",
            "characters",
            "sentences",
        )
    )
    activity_opts = "".join(
        f'<option value="{escape(a)}">{escape(a)}</option>'
        for a in ("listening", "reading", "writing", "speaking", "study")
    )
    # Tab strip HTML (Recent default / active)
    tab_btns = []
    for t in (
        ("recent", "Recent"),
        ("all", "All"),
    ):
        tid, label = t
        active = " active" if tid == "recent" else ""
        sel = "true" if tid == "recent" else "false"
        tab_btns.append(
            f'<button type="button" class="logs-tab{active}" role="tab" '
            f'data-tab="{escape(tid)}" aria-selected="{sel}" '
            f'id="tab-{escape(tid)}">{escape(label)}</button>'
        )
    tabs_html = "\n    ".join(tab_btns)

    body = f"""
<main id="main" class="page page-wide page-logs" tabindex="-1">
  <div class="mast">
    <h1>Logs</h1>
    <div class="meta">Browse · sort · edit immersion logs (SQLite → Sheets sync)</div>
  </div>

  <div class="logs-tabs" id="logs-tabs" role="tablist" aria-label="Log scope">
    {tabs_html}
  </div>

  <div class="series-filter-banner" id="series-filter-banner" hidden></div>

  <div class="logs-toolbar" role="search">
    <div class="field grow">
      <label for="f-q">Search</label>
      <input id="f-q" type="search" placeholder="Title, series key, notes…" autocomplete="off"
        onkeydown="if(event.key==='Enter')loadLogs()"/>
    </div>
    <div class="field">
      <label for="f-type">Type</label>
      <select id="f-type" onchange="loadLogs()">
        <option value="">All types</option>
        {type_opts}
      </select>
    </div>
    <div class="field">
      <label for="f-status">Status</label>
      <select id="f-status" onchange="loadLogs()">
        <option value="">All</option>
        <option value="pending">pending</option>
        <option value="ready">ready</option>
        <option value="pushed">pushed</option>
        <option value="failed">failed</option>
        <option value="skipped">skipped</option>
        <option value="n/a">n/a</option>
      </select>
    </div>
    <div class="field">
      <label for="f-source">Source</label>
      <select id="f-source" onchange="loadLogs()">
        <option value="">All</option>
        <option value="manual">manual</option>
        <option value="youtube">youtube</option>
        <option value="plex">plex</option>
        <option value="sheet">sheet</option>
        <option value="other">other</option>
      </select>
    </div>
    <div class="field" id="f-limit-wrap" style="flex:0 0 5.5rem">
      <label for="f-limit">Limit</label>
      <select id="f-limit" onchange="loadLogs()">
        <option value="50">50</option>
        <option value="100">100</option>
        <option value="200" selected>200</option>
        <option value="500">500</option>
      </select>
    </div>
    <div class="actions">
      <button type="button" class="secondary" onclick="loadLogs()">Refresh</button>
      <a class="chip" href="/queue">Queue</a>
      <a class="chip" href="/catalog">Catalog</a>
    </div>
  </div>

  <p class="logs-meta" id="logs-meta">loading…</p>
  <div id="logs-msg" class="form-msg" role="status"></div>

  <div class="logs-table-wrap">
    <table class="logs-table data-table">
      <thead>
        <tr>
          <th data-sort="id" class="col-hide-md">ID</th>
          <th data-sort="timestamp">When</th>
          <th data-sort="content_type">Type</th>
          <th data-sort="title">Title</th>
          <th data-sort="ep">S/E</th>
          <th data-sort="amount">Amount</th>
          <th data-sort="activity" class="col-hide-sm">Activity</th>
          <th data-sort="source" class="col-hide-sm">Source</th>
          <th data-sort="tadoku_status">Status</th>
          <th data-sort="tadoku_mode" class="col-hide-md">Mode</th>
          <th data-sort="tadoku_score_estimate" class="col-hide-md">Score</th>
          <th></th>
        </tr>
      </thead>
      <tbody id="logs-tbody"></tbody>
    </table>
  </div>

  <details class="help-fold logs-create-fold" id="logs-create-fold">
    <summary>Add manual log</summary>
    <div class="help-body">
      <div class="logs-create card-form" style="border:0;margin:0;padding:0">
        <p class="field-hint" style="margin-top:0">Full create form. Faster one-shot: FAB (+) or Inbox Quick log. Identity-normalizes titles (yanineko → ヤニねこ).</p>
        <div class="row">
          <div>
            <label for="c-title">Title</label>
            <input id="c-title" placeholder="Work or show name" autocomplete="off"/>
          </div>
          <div>
            <label for="c-type">Content type</label>
            <select id="c-type">{type_opts}</select>
          </div>
        </div>
        <div class="row">
          <div>
            <label for="c-amount">Amount</label>
            <input id="c-amount" type="number" step="any" min="0" placeholder="e.g. 24"/>
          </div>
          <div>
            <label for="c-unit">Unit</label>
            <select id="c-unit">{unit_opts}</select>
          </div>
        </div>
        <div class="row">
          <div>
            <label for="c-activity">Activity</label>
            <select id="c-activity">{activity_opts}</select>
          </div>
          <div>
            <label for="c-mode">Tadoku mode</label>
            <select id="c-mode">
              <option value="">— type default —</option>
              <option value="auto">auto</option>
              <option value="pending">pending</option>
              <option value="never">never</option>
            </select>
          </div>
        </div>
        <div class="row">
          <div>
            <label for="c-series">Series key <span class="faint">(optional)</span></label>
            <input id="c-series" placeholder="book:kokoro" autocomplete="off"/>
          </div>
          <div>
            <label for="c-season">Season / Episode</label>
            <div style="display:flex;gap:0.4rem">
              <input id="c-season" type="number" step="1" placeholder="S" style="flex:1"/>
              <input id="c-episode" type="number" step="1" placeholder="E" style="flex:1"/>
            </div>
          </div>
        </div>
        <label for="c-notes">Notes</label>
        <input id="c-notes" placeholder="optional"/>
        <div class="form-actions">
          <div class="btn-row" style="margin-left:0">
            <button type="button" class="primary process" onclick="createLog(true)">Add &amp; submit</button>
            <button type="button" class="secondary" onclick="createLog(false)">Add only</button>
          </div>
        </div>
      </div>
    </div>
  </details>
</main>

<div class="drawer-overlay" id="edit-overlay" aria-hidden="true" onclick="onOverlayClick(event)">
  <div class="edit-drawer" id="edit-body" role="dialog" aria-modal="true" aria-label="Edit log"></div>
</div>
"""
    # Concatenate JS (contains braces — must not go through f-string)
    body = body + f"<script>\n{LOGS_JS}\n</script>\n"
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        '  <meta charset="utf-8"/>\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1"/>\n'
        '  <meta name="color-scheme" content="light"/>\n'
        "  <title>Logs · Immersion Tracker</title>\n"
        '  <link rel="icon" type="image/png" sizes="32x32" href="/static/brand/favicon-32.png"/>\n'
        '  <link rel="icon" type="image/png" sizes="16x16" href="/static/brand/favicon-16.png"/>\n'
        f"  {fonts}\n"
        f"  <style>{SHARED_CSS}{LOGS_CSS}</style>\n"
        "</head>\n<body>\n"
        f"{nav}\n{body}\n"
        "</body>\n</html>"
    )
