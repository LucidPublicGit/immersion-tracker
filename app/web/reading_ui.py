"""Reading UI — progress, missing Tadoku chars, Log to Tadoku."""

READING_CSS = """
.page-reading { max-width: 920px; }
.page-reading .mast { margin-bottom: 0.5rem; }
.page-reading .lede { color: var(--muted); margin: 0.15rem 0 0; }
.reading-help {
  font-size: 0.86rem; color: var(--muted); line-height: 1.45;
  margin: 0.5rem 0 0.85rem; max-width: 36rem;
}
.reading-toolbar {
  display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center;
  margin: 0 0 0.75rem;
}
.reading-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.65rem;
  margin-bottom: 1rem;
}
@media (max-width: 640px) {
  .reading-summary { grid-template-columns: 1fr; }
}
.reading-stat {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 0.7rem 0.8rem;
}
.reading-stat .k {
  font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--muted); font-weight: 600;
}
.reading-stat .v {
  font-family: var(--mono); font-size: 1.3rem; font-weight: 700;
  color: var(--ink); margin-top: 0.2rem;
}
.reading-stat .sub {
  font-size: 0.8rem; color: var(--muted); margin-top: 0.2rem;
}
.reading-stat.stat-progress .v { color: var(--blue); }
.reading-stat.stat-not .v { color: var(--accent); }
.reading-stat.stat-on .v { color: var(--green); }
.bucket-card {
  background: var(--panel);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  margin-bottom: 0.85rem;
  overflow: hidden;
}
.bucket-card.has-not { border-color: var(--accent); }
.bucket-head {
  padding: 0.75rem 0.9rem 0.55rem;
  background: var(--panel-2);
  border-bottom: 1px solid var(--line);
}
.bucket-title {
  font-family: var(--display);
  font-weight: 600;
  font-size: 1.05rem;
  color: var(--ink);
}
.bucket-meta {
  font-size: 0.82rem;
  color: var(--muted);
  margin-top: 0.25rem;
}
.bucket-metrics {
  display: flex; flex-wrap: wrap; gap: 0.75rem 1.35rem; margin-top: 0.55rem;
}
.bucket-metrics .m { display: flex; flex-direction: column; gap: 0.1rem; }
.bucket-metrics .mk {
  font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--muted); font-weight: 600;
}
.bucket-metrics .mv {
  font-family: var(--mono); font-size: 1.15rem; font-weight: 700; color: var(--ink);
}
.bucket-metrics .mv.progress { color: var(--blue); }
.bucket-metrics .mv.not { color: var(--accent); }
.bucket-metrics .mv.on { color: var(--green); }
.bucket-metrics .ms {
  font-size: 0.78rem; color: var(--muted); font-family: var(--mono);
}
.pos-bar {
  position: relative;
  height: 6px; background: var(--paper-2); border: 1px solid var(--line);
  border-radius: 2px; overflow: hidden; margin: 0.4rem 0 0.1rem;
}
.pos-bar .seg-on {
  position: absolute; left: 0; top: 0; bottom: 0;
  background: var(--green); opacity: 0.85;
}
.pos-bar .seg-not {
  position: absolute; top: 0; bottom: 0;
  background: var(--accent); opacity: 0.5;
}
.pos-bar-legend {
  display: flex; flex-wrap: wrap; gap: 0.55rem 0.85rem;
  font-size: 0.72rem; color: var(--muted); margin-top: 0.2rem;
}
.pos-bar-legend span::before {
  content: ''; display: inline-block; width: 0.55rem; height: 0.55rem;
  border-radius: 1px; margin-right: 0.28rem; vertical-align: -0.05rem;
}
.pos-bar-legend .lg-on::before { background: var(--green); opacity: 0.85; }
.pos-bar-legend .lg-not::before { background: var(--accent); opacity: 0.55; }
.bucket-body { padding: 0.65rem 0.9rem 0.85rem; }
.bucket-actions { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.15rem; }
.reading-empty {
  padding: 1.5rem; text-align: center; color: var(--muted);
  border: 1px dashed var(--line-strong); background: var(--panel);
}
#reading-msg { min-height: 1.2em; font-size: 0.88rem; margin: 0.35rem 0; }
#reading-msg.ok { color: var(--green); }
#reading-msg.err { color: var(--red); }
.btn {
  font: inherit; cursor: pointer;
  border: 1px solid var(--line-strong);
  background: var(--panel);
  color: var(--ink);
  padding: 0.45rem 0.85rem;
  border-radius: var(--radius);
}
.btn:hover { background: var(--paper-2); }
.btn.primary {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--accent-ink);
  font-weight: 600;
}
.btn.primary:hover { filter: brightness(0.95); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.adv-details {
  margin: 0.85rem 0 0;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--panel);
  padding: 0.35rem 0.75rem 0.55rem;
}
.adv-details summary {
  cursor: pointer; font-size: 0.86rem; color: var(--muted); font-weight: 600;
  padding: 0.35rem 0;
}
.prefs-bar {
  display: flex; flex-wrap: wrap; gap: 0.65rem 1rem; align-items: flex-end;
  padding: 0.35rem 0 0.25rem;
}
.prefs-bar label {
  display: flex; flex-direction: column; gap: 0.2rem;
  font-size: 0.78rem; color: var(--muted); font-weight: 600;
}
.prefs-bar input[type=number] {
  font-family: var(--mono); font-size: 0.95rem; width: 6.5rem;
  border: 1px solid var(--line-strong); border-radius: var(--radius);
  padding: 0.35rem 0.45rem; background: var(--panel-2); color: var(--ink);
}
.mode-toggle {
  display: inline-flex; border: 1px solid var(--line-strong);
  border-radius: var(--radius); overflow: hidden;
}
.mode-toggle button {
  border: 0; border-right: 1px solid var(--line); background: var(--panel);
  padding: 0.4rem 0.85rem; cursor: pointer; font: inherit; font-weight: 600;
}
.mode-toggle button:last-child { border-right: 0; }
.mode-toggle button.active { background: var(--accent); color: var(--accent-ink); }
"""

READING_JS = r"""
function esc(s){
  return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function fmtChars(n){
  return Math.round(Number(n)||0).toLocaleString();
}
function fmtScore(n){
  const x = Number(n)||0;
  if(!x) return '0';
  return (Math.round(x * 1000) / 1000).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 3,
  });
}
function setReadingMsg(t, kind){
  const el = document.getElementById('reading-msg');
  if(!el) return;
  el.textContent = t || '';
  el.className = kind ? ('reading-msg ' + kind) : 'reading-msg';
}

function paintPrefs(d){
  const mode = (d.log_mode||'manual');
  const modeEl = document.getElementById('pref-mode');
  const thrEl = document.getElementById('pref-threshold');
  const idleEl = document.getElementById('pref-idle');
  if(modeEl){
    modeEl.querySelectorAll('[data-mode]').forEach(btn=>{
      const on = btn.dataset.mode === mode || (mode==='manual' && btn.dataset.mode==='pending');
      btn.classList.toggle('active', on);
    });
  }
  if(thrEl && document.activeElement !== thrEl) thrEl.value = d.min_submit_characters||500;
  if(idleEl && document.activeElement !== idleEl){
    idleEl.value = d.auto_submit_idle_minutes!=null ? d.auto_submit_idle_minutes : 30;
  }
}

function paintSummary(d){
  const el = document.getElementById('reading-summary');
  const notChars = Number(d.total_not_on_tadoku_chars!=null
    ? d.total_not_on_tadoku_chars
    : ((d.total_tadoku_awaiting_chars||0) + (d.total_unlogged_chars||0)))||0;
  const countEl = document.getElementById('reading-count');
  if (countEl) {
    countEl.textContent = notChars > 0 ? fmtChars(notChars) : '0';
    countEl.classList.toggle('zero', !(notChars > 0));
  }
  if (typeof openFoldIfWork === 'function') {
    openFoldIfWork('reading-fold', 'immersion.reading.open', notChars > 0);
  }
  const subEl = document.getElementById('reading-sub');
  if (subEl) {
    subEl.textContent = notChars > 0
      ? (fmtChars(notChars) + ' chars since last log')
      : 'Hoshi · nothing pending';
  }
  if(!el) return;
  const onChars = Number(d.total_tadoku_pushed_chars)||0;
  const notScore = Number(d.total_not_on_tadoku_score!=null
    ? d.total_not_on_tadoku_score
    : (d.total_tadoku_awaiting_score||0))||0;
  const onScore = Number(d.total_tadoku_pushed_score)||0;
  const progressChars = Number(d.total_progress_chars)||0;
  const progressLabel = d.total_progress_label || (fmtChars(progressChars) + ' chars');
  el.innerHTML = `
    <div class="reading-stat stat-progress">
      <div class="k">Progress</div>
      <div class="v">${esc(progressLabel)}</div>
      <div class="sub">Where you are in your books</div>
    </div>
    <div class="reading-stat stat-not">
      <div class="k">Since last Tadoku log</div>
      <div class="v">${fmtChars(notChars)}</div>
      <div class="sub">≈ ${fmtScore(notScore)} pts · not on Tadoku yet</div>
    </div>
    <div class="reading-stat stat-on">
      <div class="k">On Tadoku</div>
      <div class="v">${fmtChars(onChars)}</div>
      <div class="sub">≈ ${fmtScore(onScore)} pts</div>
    </div>
  `;
  paintPrefs(d);
}

function paintBuckets(d){
  const root = document.getElementById('bucket-list');
  if(!root) return;
  const buckets = d.buckets||[];
  if(!buckets.length){
    root.innerHTML = `<div class="reading-empty">No books tracked yet.<br/>
      Sync Hoshi after you read on the Boox.</div>`;
    return;
  }
  root.innerHTML = buckets.map(b => {
    const notChars = Number(b.not_on_tadoku_chars!=null
      ? b.not_on_tadoku_chars
      : ((b.tadoku_awaiting_chars||0) + (b.unlogged_chars||b.pending_chars||0)))||0;
    const notScore = Number(b.not_on_tadoku_score)||0;
    const pushed = Number(b.tadoku_pushed_chars)||0;
    const onScore = Number(b.tadoku_pushed_score)||0;
    const pos = b.position_chars!=null ? Number(b.position_chars) : null;
    const tot = b.book_total_chars ? Number(b.book_total_chars) : null;
    const pct = b.position_percent!=null ? Number(b.position_percent)
      : (pos!=null && tot ? Math.min(100, 100 * pos / tot) : null);

    const cls = ['bucket-card', notChars>0 ? 'has-not' : ''].filter(Boolean).join(' ');

    let progressLabel = '—';
    if(pos!=null && tot){
      progressLabel = `${fmtChars(pos)} / ${fmtChars(tot)}`;
      if(pct!=null) progressLabel += ` (${pct}%)`;
    } else if(pos!=null){
      progressLabel = fmtChars(pos) + ' chars';
    }

    let posHtml = '';
    if(tot && tot>0 && pos!=null){
      const nowPct = Math.max(0, Math.min(100, pct!=null ? pct : 100*pos/tot));
      const counted = pushed + notChars;
      let onPct = 0, notPct = 0;
      if(counted > 0){
        onPct = Math.min(nowPct, nowPct * (pushed / counted));
        notPct = Math.max(0, nowPct - onPct);
      } else {
        notPct = nowPct;
      }
      posHtml = `
        <div class="pos-bar">
          ${onPct>0.05 ? `<i class="seg-on" style="width:${onPct}%"></i>` : ''}
          ${notPct>0.05 ? `<i class="seg-not" style="left:${onPct}%;width:${notPct}%"></i>` : ''}
        </div>
        <div class="pos-bar-legend">
          <span class="lg-on">On Tadoku</span>
          <span class="lg-not">Since last log</span>
        </div>`;
    }

    const actions = notChars>0 ? `
      <div class="bucket-actions">
        <button type="button" class="primary" data-act="log-tadoku" data-id="${b.id}">
          Log to Tadoku · ${fmtChars(notChars)} chars
        </button>
      </div>
      <div class="bucket-meta">Forces a log of everything since your last Tadoku log (ignores auto min).</div>
    ` : `
      <div class="bucket-meta">Nothing new to log — keep reading (or wait for auto min if enabled).</div>
    `;

    return `<article class="${cls}" data-bucket="${b.id}">
      <div class="bucket-head">
        <div class="bucket-title">${esc(b.title||'Untitled')}</div>
        <div class="bucket-metrics">
          <div class="m">
            <span class="mk">Progress</span>
            <span class="mv progress">${esc(progressLabel)}</span>
          </div>
          <div class="m">
            <span class="mk">Since last Tadoku log</span>
            <span class="mv not">${fmtChars(notChars)}</span>
            <span class="ms">≈ ${fmtScore(notScore)} pts</span>
          </div>
          <div class="m">
            <span class="mk">On Tadoku</span>
            <span class="mv on">${fmtChars(pushed)}</span>
            <span class="ms">≈ ${fmtScore(onScore)} pts</span>
          </div>
        </div>
        ${posHtml}
      </div>
      <div class="bucket-body">
        ${actions}
      </div>
    </article>`;
  }).join('');

  root.querySelectorAll('[data-act="log-tadoku"]').forEach(btn => {
    btn.addEventListener('click', () => logToTadoku(Number(btn.dataset.id), btn));
  });
}

async function loadReading(){
  setReadingMsg('Loading…');
  try{
    const r = await fetch('/api/hoshi/reading');
    if(!r.ok) throw new Error('HTTP '+r.status);
    const data = await r.json();
    paintSummary(data);
    paintBuckets(data);
    setReadingMsg('');
  }catch(e){
    setReadingMsg('Failed: '+e.message, 'err');
  }
}

async function savePrefs(partial){
  setReadingMsg('Saving…');
  try{
    const r = await fetch('/api/hoshi/settings', {
      method:'PATCH',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(partial),
    });
    const data = await r.json().catch(()=>({}));
    if(!r.ok) throw new Error(data.detail || ('HTTP '+r.status));
    setReadingMsg('Saved', 'ok');
    await loadReading();
  }catch(e){
    setReadingMsg(String(e.message||e), 'err');
  }
}

async function logToTadoku(id, btn){
  if(btn) btn.disabled = true;
  setReadingMsg('Logging to Tadoku…');
  try{
    const r = await fetch(`/api/hoshi/buckets/${id}/log-to-tadoku`, {method:'POST'});
    const data = await r.json().catch(()=>({}));
    if(!r.ok && r.status !== 207){
      throw new Error(data.reason || data.detail || ('HTTP '+r.status));
    }
    const n = Number(data.chars_logged)||0;
    const failed = Number(data.failed)||0;
    if(failed>0){
      setReadingMsg(`Logged ${fmtChars(n)} chars; ${failed} log(s) failed to push`, 'err');
    } else if(n>0){
      setReadingMsg(`Logged ${fmtChars(n)} chars to Tadoku`, 'ok');
    } else {
      setReadingMsg(data.reason || 'Nothing to log', data.ok===false?'err':'ok');
    }
    await loadReading();
  }catch(e){
    setReadingMsg(String(e.message||e), 'err');
  } finally {
    if(btn) btn.disabled = false;
  }
}

async function pollHoshi(){
  setReadingMsg('Syncing Hoshi…');
  try{
    const r = await fetch('/api/hoshi/sync', {method:'POST'});
    const data = await r.json().catch(()=>({}));
    if(!r.ok && !data.ok) throw new Error(data.reason || data.detail || ('HTTP '+r.status));
    const parts = [];
    if(data.chars_bucketed) parts.push(`+${fmtChars(data.chars_bucketed)} new`);
    if(data.skipped_reread) parts.push('re-reads ignored');
    setReadingMsg(parts.length ? parts.join(' · ') : (data.reason || 'Up to date'), data.ok===false?'err':'ok');
    await loadReading();
  }catch(e){
    setReadingMsg(String(e.message||e), 'err');
  }
}

async function logAllToTadoku(){
  if(!confirm('Log all books’ missing chars to Tadoku now?')) return;
  setReadingMsg('Logging all to Tadoku…');
  try{
    const r = await fetch('/api/hoshi/log-all-to-tadoku', {method:'POST'});
    const data = await r.json().catch(()=>({}));
    if(!r.ok) throw new Error(data.detail || data.reason || ('HTTP '+r.status));
    setReadingMsg(`Logged ${fmtChars(data.chars_logged||0)} chars across ${data.books||0} book(s)`, 'ok');
    await loadReading();
  }catch(e){
    setReadingMsg(String(e.message||e), 'err');
  }
}

function bindReadingPanel(){
  if (window._readingBound) return;
  window._readingBound = true;
  document.getElementById('btn-poll')?.addEventListener('click', pollHoshi);
  document.getElementById('btn-log-all')?.addEventListener('click', logAllToTadoku);
  document.getElementById('btn-refresh')?.addEventListener('click', loadReading);
  document.getElementById('pref-mode')?.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-mode]');
    if(!btn) return;
    const mode = btn.dataset.mode === 'pending' ? 'manual' : btn.dataset.mode;
    savePrefs({log_mode: mode});
  });
  document.getElementById('btn-save-prefs')?.addEventListener('click', () => {
    const thr = parseInt(document.getElementById('pref-threshold')?.value||'500', 10);
    const idle = parseFloat(document.getElementById('pref-idle')?.value||'30');
    savePrefs({
      min_submit_characters: thr||500,
      auto_submit_idle_minutes: isNaN(idle)?30:idle,
    });
  });
  loadReading();
}
document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('reading-summary') || document.getElementById('bucket-list')) {
    bindReadingPanel();
  }
});
"""


def reading_panel_html(*, compact: bool = False) -> str:
    """Shared reading body for full page and Inbox fold (IDs for READING_JS)."""
    help_html = ""
    if not compact:
        help_html = """
  <p class="reading-help">
    <strong>Since last Tadoku log</strong> is everything not yet on tadoku.app.
    <strong>Log to Tadoku</strong> forces a manual log of that total (ignores auto min),
    then the counter resets until you hit the auto min again (if auto is on).
  </p>"""
    return f"""
{help_html}
  <div class="reading-toolbar">
    <button type="button" class="primary" id="btn-poll">Sync Hoshi</button>
    <button type="button" class="secondary" id="btn-log-all">Log all to Tadoku</button>
    <button type="button" class="secondary" id="btn-refresh">Refresh</button>
    {"<a class='chip' href='/reading'>Full page</a>" if compact else ""}
  </div>
  <div id="reading-msg" class="reading-msg" role="status" aria-live="polite"></div>
  <div class="reading-summary" id="reading-summary"></div>
  <div id="bucket-list"></div>

  <details class="adv-details">
    <summary>Auto log settings</summary>
    <div class="prefs-bar" id="prefs-bar">
      <div>
        <div style="font-size:0.78rem;color:var(--muted);font-weight:600;margin-bottom:0.25rem">Mode</div>
        <div class="mode-toggle" id="pref-mode">
          <button type="button" data-mode="pending">Manual only</button>
          <button type="button" data-mode="auto">Auto after min</button>
        </div>
      </div>
      <label>Auto min chars
        <input type="number" min="1" id="pref-threshold" value="500"/>
      </label>
      <label>Idle minutes (auto)
        <input type="number" min="0" step="1" id="pref-idle" value="30"/>
      </label>
      <button type="button" class="secondary" id="btn-save-prefs">Save</button>
    </div>
  </details>
"""


def reading_fold_html(*, default_open: bool = False) -> str:
    """Inbox fold wrapping Hoshi reading panel."""
    open_attr = " open" if default_open else ""
    return f"""
<details class="fold fold-reading fold-quiet" id="reading-fold"{open_attr}>
  <summary>
    <span class="chev">▶</span>
    Reading
    <span class="count-badge zero" id="reading-count">0</span>
    <span class="sub" id="reading-sub">Hoshi · Tadoku gap</span>
  </summary>
  <div class="fold-body page-reading">
    {reading_panel_html(compact=True)}
  </div>
</details>
"""


def reading_page() -> str:
    from app.web.pages import _shell

    body = f"""
<main id="main" class="page page-reading" tabindex="-1">
  <header class="mast">
    <h1>Reading</h1>
    <div class="meta">Hoshi character progress · Tadoku gap · also on <a href="/queue">Inbox</a></div>
  </header>
  {reading_panel_html(compact=False)}
</main>
<script>
{READING_JS}
</script>
"""
    return _shell(
        "Reading — Immersion Tracker",
        body,
        active="reading",
        extra_css=READING_CSS,
    )
