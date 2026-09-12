"""Shared Tadoku queue JS used by home embed and /queue page."""

# Single source of truth for queue list + approve/skip actions.
QUEUE_JS = r"""
function escapeHtml(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function epLabel(e){
  const s=e.season, ep=e.episode;
  if(s!=null && ep!=null) return `S${String(s).padStart(2,'0')}E${String(ep).padStart(2,'0')}`;
  if(s!=null) return `S${String(s).padStart(2,'0')}`;
  if(ep!=null) return `E${String(ep).padStart(2,'0')}`;
  return '—';
}
function isYouTube(e){
  const ct=(e.content_type||'').toLowerCase();
  const src=(e.source||'').toLowerCase();
  return ct==='youtube' || src==='youtube';
}
function groupKey(e){
  // All YouTube logs share one queue group (manual review / batch approve)
  if(isYouTube(e)) return 'yt:all';
  if(e.series_key) return 'sk:'+e.series_key;
  return 't:'+(e.content_type||'')+'|'+(e.title||'');
}
function groupTitle(e){
  if(isYouTube(e)) return 'YouTube';
  if(e.series_key) return e.title || e.series_key;
  return e.title || '(untitled)';
}
function sortEp(a,b){
  const as=a.season==null?9999:a.season, bs=b.season==null?9999:b.season;
  if(as!==bs) return as-bs;
  const ae=a.episode==null?9999:a.episode, be=b.episode==null?9999:b.episode;
  if(ae!==be) return ae-be;
  return a.id-b.id;
}
function sortYouTube(a,b){
  const ta=a.timestamp||'', tb=b.timestamp||'';
  if(ta!==tb) return ta<tb?-1:1;
  return a.id-b.id;
}
function setMsg(t){
  const el=document.getElementById('msg');
  if(el) el.textContent=t||'';
}
function numOrNull(v){
  if(v===''||v==null) return null;
  const n=Number(v);
  return Number.isFinite(n)?n:null;
}

/* —— Quick log: catalog typeahead + next ep autofill —— */
const QL_TYPE_DEFAULTS={
  anime:{activity:'listening',unit:'minutes',amount:24},
  show:{activity:'listening',unit:'minutes',amount:24},
  movie:{activity:'listening',unit:'minutes',amount:90},
  youtube:{activity:'listening',unit:'minutes',amount:null},
  manga:{activity:'reading',unit:'comic_pages',amount:null},
  book:{activity:'reading',unit:'pages',amount:null},
  visual_novel:{activity:'reading',unit:'characters',amount:null},
  game:{activity:'reading',unit:'characters',amount:null},
  podcast:{activity:'listening',unit:'minutes',amount:null},
  study:{activity:'study',unit:'minutes',amount:null},
};
let _qlCatalog=null;      // [{series_key,display_title,content_type,default_unit,aliases,search}]
let _qlProgressByKey=null; // series_key → progress item
let _qlIndexPromise=null;
let _qlHits=[];
let _qlActive=-1;
let _qlSelectedKey='';

function qlNorm(s){
  return String(s||'').toLowerCase().normalize('NFKC').replace(/[\s\-_]+/g,' ').trim();
}
function qlSetHint(t){
  const el=document.getElementById('ql-hint');
  if(el) el.textContent=t||'';
}
function qlHideSuggest(){
  const box=document.getElementById('ql-suggest');
  if(box){ box.hidden=true; box.innerHTML=''; }
  _qlHits=[]; _qlActive=-1;
}
function qlSetSelect(id, value){
  const el=document.getElementById(id);
  if(!el || value==null || value==='') return;
  const want=String(value);
  if([...el.options].some(o=>o.value===want)) el.value=want;
}
async function qlEnsureIndex(){
  if(_qlCatalog && _qlProgressByKey) return;
  if(_qlIndexPromise) return _qlIndexPromise;
  _qlIndexPromise=(async()=>{
    try{
      const [cat, prog]=await Promise.all([
        fetch('/api/catalog').then(r=>r.json()),
        fetch('/api/progress').then(r=>r.json()),
      ]);
      _qlCatalog=(Array.isArray(cat)?cat:[]).map(c=>{
        const aliases=String(c.aliases||'').split(/[|\n;]/).map(s=>s.trim()).filter(Boolean);
        const blob=[c.display_title,c.series_key,...aliases].join(' ');
        return {
          series_key:c.series_key,
          display_title:c.display_title||c.series_key,
          content_type:c.content_type||'anime',
          default_unit:c.default_unit||null,
          aliases,
          search:qlNorm(blob),
        };
      });
      _qlProgressByKey={};
      for(const it of (prog&&prog.items)||[]){
        if(it&&it.series_key) _qlProgressByKey[it.series_key]=it;
      }
    }catch(e){
      _qlCatalog=_qlCatalog||[];
      _qlProgressByKey=_qlProgressByKey||{};
      qlSetHint('Catalog load failed — type freely');
    }
  })();
  return _qlIndexPromise;
}
function qlSearch(q){
  const needle=qlNorm(q);
  if(!needle || !_qlCatalog) return [];
  const scored=[];
  for(const c of _qlCatalog){
    if(!c.search.includes(needle) && !qlNorm(c.display_title).includes(needle)) continue;
    let score=0;
    const title=qlNorm(c.display_title);
    if(title===needle) score=100;
    else if(title.startsWith(needle)) score=80;
    else if(qlNorm(c.series_key).includes(needle)) score=60;
    else score=40;
    // prefer works with recent progress
    const p=_qlProgressByKey[c.series_key];
    if(p&&p.last_logged) score+=10;
    if(p&&(p.progress_status||'')==='active') score+=5;
    scored.push({c,score,p});
  }
  scored.sort((a,b)=>b.score-a.score||a.c.display_title.localeCompare(b.c.display_title));
  return scored.slice(0,12);
}
function qlNextEpisode(p){
  // Next unlogged S/E (or volume in episode field for manga/book).
  if(!p) return {season:null,episode:null,label:''};
  let s=p.progress_season;
  let e=p.progress_episode;
  if(e==null && p.max_episode!=null) e=p.max_episode;
  if(e==null && p.episodes_logged) e=p.episodes_logged;
  if(e==null){
    // no progress position yet
    if((p.content_type||'')==='anime'||(p.content_type||'')==='show'){
      return {season:s!=null?s:1, episode:1, label:'start S01E01'};
    }
    return {season:null,episode:null,label:'no prior position'};
  }
  e=Number(e)+1;
  if(s!=null){
    const tot=(p.season_totals&&p.season_totals[String(s)])||null;
    if(tot!=null && e>Number(tot)){
      s=Number(s)+1;
      e=1;
    }
  }
  const tag=s!=null
    ? `S${String(s).padStart(2,'0')}E${String(e).padStart(2,'0')}`
    : `E${String(e).padStart(2,'0')}`;
  const cur=p.current_display||p.progress_label||'';
  return {season:s, episode:e, label:`next ${tag}${cur?` (was ${cur})`:''}`};
}
async function qlLastLog(seriesKey){
  try{
    const r=await fetch('/api/logs?series_key='+encodeURIComponent(seriesKey)+'&limit=5');
    if(!r.ok) return null;
    const rows=await r.json();
    return Array.isArray(rows)&&rows.length?rows[0]:null;
  }catch(e){ return null; }
}
function qlPaintSuggest(hits){
  const box=document.getElementById('ql-suggest');
  if(!box) return;
  _qlHits=hits;
  _qlActive=hits.length?0:-1;
  if(!hits.length){ qlHideSuggest(); return; }
  box.hidden=false;
  box.innerHTML=hits.map((h,i)=>{
    const c=h.c, p=h.p;
    const pos=p?(p.current_display||p.progress_label||''):'';
    const sub=[c.content_type,c.series_key,pos].filter(Boolean).join(' · ');
    return `<button type="button" role="option" class="ql-opt${i===_qlActive?' is-active':''}" data-i="${i}">`+
      `<span class="ql-opt-title">${escapeHtml(c.display_title)}</span>`+
      `<span class="ql-opt-sub">${escapeHtml(sub)}</span></button>`;
  }).join('');
  box.querySelectorAll('.ql-opt').forEach(btn=>{
    btn.addEventListener('mousedown',ev=>{ ev.preventDefault(); qlPick(Number(btn.dataset.i)); });
  });
}
async function qlOnTitleInput(){
  const raw=document.getElementById('ql-title')?.value||'';
  // free typing clears pinned series until a suggestion is chosen again
  if(_qlSelectedKey){
    _qlSelectedKey='';
    const sk=document.getElementById('ql-series');
    if(sk) sk.value='';
  }
  await qlEnsureIndex();
  if(!raw.trim()){ qlHideSuggest(); qlSetHint('Pick a catalog work to fill type / next ep.'); return; }
  qlPaintSuggest(qlSearch(raw));
}
function qlOnTitleKey(ev){
  const box=document.getElementById('ql-suggest');
  if(!box||box.hidden||!_qlHits.length) return;
  if(ev.key==='ArrowDown'){
    ev.preventDefault();
    _qlActive=Math.min(_qlHits.length-1,_qlActive+1);
    qlPaintSuggest(_qlHits);
  }else if(ev.key==='ArrowUp'){
    ev.preventDefault();
    _qlActive=Math.max(0,_qlActive-1);
    qlPaintSuggest(_qlHits);
  }else if(ev.key==='Enter' && _qlActive>=0){
    ev.preventDefault();
    qlPick(_qlActive);
  }else if(ev.key==='Escape'){
    qlHideSuggest();
  }
}
async function qlPick(i){
  const hit=_qlHits[i];
  if(!hit) return;
  const c=hit.c;
  let p=hit.p||(_qlProgressByKey&&_qlProgressByKey[c.series_key])||null;
  _qlSelectedKey=c.series_key;
  const titleEl=document.getElementById('ql-title');
  const skEl=document.getElementById('ql-series');
  if(titleEl) titleEl.value=c.display_title;
  if(skEl) skEl.value=c.series_key;
  qlHideSuggest();

  const ct=c.content_type||'anime';
  qlSetSelect('ql-type', ct);
  const defs=QL_TYPE_DEFAULTS[ct]||QL_TYPE_DEFAULTS.anime;

  // Prefer last log's unit/activity/amount; else catalog default_unit; else type defaults
  const last=await qlLastLog(c.series_key);
  const unit=(last&&last.unit)||c.default_unit||defs.unit;
  const activity=(last&&last.activity)||defs.activity;
  let amount=(last&&last.amount!=null)?last.amount:defs.amount;
  qlSetSelect('ql-unit', unit);
  qlSetSelect('ql-activity', activity);
  const amtEl=document.getElementById('ql-amount');
  if(amtEl){
    if(amount!=null && Number(amount)>0) amtEl.value=String(amount);
    else if(!amtEl.value) amtEl.value=defs.amount!=null?String(defs.amount):'';
  }

  const next=qlNextEpisode(p);
  const sEl=document.getElementById('ql-season');
  const eEl=document.getElementById('ql-episode');
  if(sEl) sEl.value=next.season!=null?String(next.season):'';
  if(eEl) eEl.value=next.episode!=null?String(next.episode):'';
  qlSetHint(`${c.display_title} · ${ct}${next.label?' · '+next.label:''}${last?` · last ${last.amount} ${last.unit}`:''}`);
}

/** Manual one-shot log from Inbox (avoids Manual Entry sheet re-apply race). */
async function quickLog(submit){
  const title=(document.getElementById('ql-title')?.value||'').trim();
  const amount=Number(document.getElementById('ql-amount')?.value);
  if(!title){ setMsg('Title required'); return; }
  if(!(amount>0)){ setMsg('Amount must be > 0'); return; }
  const series_key=(document.getElementById('ql-series')?.value||'').trim()||null;
  const body={
    content_type:document.getElementById('ql-type')?.value||'anime',
    title,
    amount,
    unit:document.getElementById('ql-unit')?.value||'minutes',
    activity:document.getElementById('ql-activity')?.value||null,
    series_key,
    season:numOrNull(document.getElementById('ql-season')?.value),
    episode:numOrNull(document.getElementById('ql-episode')?.value),
    source:'manual',
    tadoku_mode:submit?'auto':'pending',
  };
  if(!body.activity) delete body.activity;
  if(!body.series_key) delete body.series_key;
  const btn=document.getElementById('ql-submit');
  if(btn) btn.disabled=true;
  setMsg(submit?'Logging & submitting…':'Queueing…');
  try{
    const r=await fetch('/api/logs',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body),
    });
    let j=null; try{ j=await r.json(); }catch(e){}
    if(!r.ok){
      setMsg(j&&j.detail?JSON.stringify(j.detail):'Create failed');
      return;
    }
    let status=j.tadoku_status||'';
    let note=`#${j.id} · ${j.tadoku_title||j.title||title}`;
    if(submit && j.id){
      const ar=await fetch('/api/logs/'+j.id+'/approve',{method:'POST'});
      let aj=null; try{ aj=await ar.json(); }catch(e){}
      if(!ar.ok){
        setMsg(`${note} created, submit failed: ${aj&&aj.detail?JSON.stringify(aj.detail):ar.status}`);
        await loadQueue();
        return;
      }
      status=aj.tadoku_status||status;
      note=`#${j.id} · ${aj.tadoku_title||aj.title||j.tadoku_title||title}`;
    }
    setMsg(`${submit?'Submitted':'Queued'} ${note} · ${status}`);
    if(typeof showAppToast==='function' && j.id){
      showAppToast(`${submit?'Submitted':'Queued'} ${note}`,{logId:j.id});
    }
    // keep series pinned; bump episode; clear amount only if not using last-log pattern
    const ep=document.getElementById('ql-episode');
    if(ep && ep.value!=='' && Number.isFinite(Number(ep.value))){
      ep.value=String(Number(ep.value)+1);
    }
    // refresh progress cache for next ep accuracy
    _qlProgressByKey=null;
    _qlIndexPromise=null;
    if(typeof loadQueue==='function') await loadQueue();
    if(typeof loadRecentLogs==='function') await loadRecentLogs();
  }catch(e){
    setMsg('Network error');
  }finally{
    if(btn) btn.disabled=false;
  }
}
function setQueueCount(n){
  const b=document.getElementById('q-count');
  if(!b) return;
  b.textContent=String(n);
  b.classList.toggle('zero', n===0);
  const sub=document.getElementById('q-sub');
  if(sub) sub.textContent=n?`${n} item(s) need attention`:'queue clear';
}

/* Next automatic process_ready (scheduler) */
let _autoNextAt=null;   // Date or null
let _autoEnabled=true;
let _autoTickTimer=null;
let _autoRefreshTimer=null;

function fmtCountdown(sec){
  if(sec<=0) return '0:00';
  const m=Math.floor(sec/60);
  const s=sec%60;
  return `${m}:${String(s).padStart(2,'0')}`;
}
function paintAutoChip(){
  const el=document.getElementById('auto-chip');
  if(!el) return;
  el.classList.remove('off','soon');
  if(!_autoEnabled){
    el.textContent='auto off';
    el.classList.add('off');
    el.title='Scheduler disabled';
    return;
  }
  if(!_autoNextAt){
    el.textContent='auto …';
    el.title='Waiting for schedule';
    return;
  }
  const sec=Math.max(0, Math.ceil((_autoNextAt.getTime()-Date.now())/1000));
  if(sec<=0){
    el.textContent='auto ·';
    el.title='Submitting…';
    return;
  }
  el.textContent=`auto ${fmtCountdown(sec)}`;
  el.title=`Next automatic submit in ${fmtCountdown(sec)}`;
  if(sec<=15) el.classList.add('soon');
}
function startAutoChip(){
  if(_autoTickTimer) return;
  _autoTickTimer=setInterval(()=>{
    paintAutoChip();
    // After fire time, re-fetch next_run (job may have rescheduled)
    if(_autoNextAt && Date.now()>=_autoNextAt.getTime()){
      refreshAutoSchedule();
    }
  },1000);
  if(!_autoRefreshTimer){
    // Drift-correct next_run from server occasionally
    _autoRefreshTimer=setInterval(refreshAutoSchedule, 60000);
  }
}
async function refreshAutoSchedule(){
  try{
    const s=await (await fetch('/api/tadoku/settings')).json();
    applyAutoSchedule(s.auto_process);
  }catch(e){}
}
function applyAutoSchedule(ap){
  if(!ap){
    _autoEnabled=false;
    _autoNextAt=null;
    paintAutoChip();
    return;
  }
  _autoEnabled=!!ap.enabled;
  if(ap.next_process_at){
    const d=new Date(ap.next_process_at);
    _autoNextAt=isNaN(d.getTime())?null:d;
  }else{
    _autoNextAt=null;
  }
  paintAutoChip();
  startAutoChip();
}
function sessionLabel(s){
  const st=s.session_status||(s.session_cookie_configured?'unknown':'missing');
  const map={
    ok:'session ✓',
    missing:'session MISSING',
    expired:'session EXPIRED',
    error:'session ERROR',
    skipped:'session (dry-run)',
    disabled:'session (live off)',
    unknown:s.session_cookie_configured?'session ?':'session MISSING',
  };
  return map[st]||('session '+st);
}
function authLabel(s){
  if(s.tadoku_credentials_configured) return 'login ✓';
  if(s.tadoku_password_configured||s.tadoku_username) return 'login partial';
  return 'login MISSING';
}
function paintSessionBanner(s){
  const ban=document.getElementById('session-banner');
  if(!ban) return;
  const st=s.session_status||'';
  const credsOk=!!s.tadoku_credentials_configured;
  ban.classList.remove('warn','bad','ok','hidden');
  // Hide only when session is healthy; still show form if login not configured
  if((st==='ok'||st==='disabled'||st==='skipped')&&credsOk){
    ban.classList.add('hidden');
    ban.innerHTML='';
    return;
  }
  if(st==='expired'||st==='missing'||!credsOk) ban.classList.add('bad');
  else ban.classList.add('warn');
  const detail=escapeHtml(s.session_detail||'');
  const user=escapeHtml(s.tadoku_username||'');
  const pwHint=s.tadoku_password_configured
    ?'Password saved (leave blank to keep)'
    :'Tadoku password';
  const how=`Save your <a href="https://tadoku.app" target="_blank" rel="noopener">tadoku.app</a>
    username and password. The app signs in automatically and keeps a session cookie
    (never shown here). Save credentials before using <b>Refresh Tadoku login</b>.`;
  ban.innerHTML=`
    <div class="session-banner-text"><b>${escapeHtml(sessionLabel(s))}</b>
      · ${escapeHtml(authLabel(s))}
      ${detail?` — ${detail}`:''}<br><span class="faint">${how}</span></div>
    <form class="session-banner-form" id="tadoku-login-form" autocomplete="on"
      onsubmit="return saveTadokuCredentials(event)">
      <input type="text" id="tadoku-username" name="username" autocomplete="username"
        spellcheck="false" placeholder="username or email" value="${user}" />
      <input type="password" id="tadoku-password" name="password"
        autocomplete="current-password" spellcheck="false"
        placeholder="${escapeHtml(pwHint)}" />
      <button type="submit" class="approve" id="btn-save-tadoku-login">Save login</button>
      <button type="button" class="approve" id="btn-refresh-tadoku-login"
        onclick="refreshTadokuLogin()">Refresh Tadoku login</button>
      <button type="button" class="secondary" onclick="probeSession()">Re-check</button>
      <button type="button" class="secondary" onclick="clearTadokuLogin()">Clear login</button>
    </form>`;
}
async function loadSettings(forceCheck){
  try{
    const q=forceCheck?'?check_session=1':'';
    const s=await (await fetch('/api/tadoku/settings'+q)).json();
    const c=s.contest||{};
    const reg=s.registration_id_set?'reg ✓':'reg MISSING';
    const cook=sessionLabel(s);
    const auth=authLabel(s);
    const src=s.session_cookie_source&&s.session_cookie_source!=='none'
      ?` (${s.session_cookie_source})`:'';
    const el=document.getElementById('contest');
    if(el) el.textContent=
      `Contest: ${c.name||'(none)'} · ${reg} · ${auth} · ${cook}${src} · auto_submit=${s.auto_submit_on_approve}`;
    paintSessionBanner(s);
    applyAutoSchedule(s.auto_process);
  }catch(e){}
}
async function probeSession(){
  setMsg('Checking session…');
  await loadSettings(true);
  setMsg('Session re-checked');
}
async function saveTadokuCredentials(ev){
  if(ev&&ev.preventDefault) ev.preventDefault();
  const userEl=document.getElementById('tadoku-username');
  const passEl=document.getElementById('tadoku-password');
  const username=(userEl&&userEl.value||'').trim();
  const password=passEl?passEl.value:'';
  if(!username){ setMsg('Enter Tadoku username or email'); return false; }
  setMsg('Saving login…');
  const body={username};
  // Blank password = keep previously saved password (do not send empty wipe)
  if(password) body.password=password;
  else body.password='';
  const r=await fetch('/api/tadoku/credentials',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body),
  });
  let j=null;
  try{ j=await r.json(); }catch(e){}
  if(!r.ok){
    setMsg(j&&j.detail?String(j.detail):await r.text());
    return false;
  }
  if(passEl) passEl.value='';
  setMsg(j&&j.tadoku_credentials_configured
    ?'Login saved (password encrypted). Use Refresh Tadoku login to verify.'
    :'Login saved');
  await loadSettings(false);
  return false;
}
async function refreshTadokuLogin(){
  const btn=document.getElementById('btn-refresh-tadoku-login');
  const prev=btn?btn.textContent:'Refresh Tadoku login';
  if(btn){ btn.disabled=true; btn.textContent='Refreshing…'; }
  setMsg('Refreshing Tadoku login…');
  try{
    const r=await fetch('/api/tadoku/auth/refresh',{method:'POST'});
    let j=null;
    try{ j=await r.json(); }catch(e){}
    if(!r.ok){
      setMsg(j&&j.detail?String(j.detail):'Refresh failed');
      return;
    }
    setMsg(j&&j.authenticated
      ?'Tadoku login refreshed · session saved'
      :`Refresh finished · status=${j&&j.session_status||'?'}`);
    await loadSettings(false);
  }catch(e){
    setMsg('Refresh failed (network)');
  }finally{
    if(btn){ btn.disabled=false; btn.textContent=prev; }
  }
}
async function clearTadokuLogin(){
  if(!confirm('Clear saved Tadoku username, password, and session?')) return;
  setMsg('Clearing login…');
  const r=await fetch('/api/tadoku/credentials',{method:'DELETE'});
  let j=null;
  try{ j=await r.json(); }catch(e){}
  if(!r.ok){
    setMsg(j&&j.detail?String(j.detail):'Clear failed');
    return;
  }
  setMsg('Tadoku login cleared');
  await loadSettings(false);
}
async function loadQueue(){
  const root=document.getElementById('groups');
  if(!root) return;
  const r=await fetch('/api/queue?limit=200');
  const data=await r.json();
  const map=new Map();
  for(const e of data){
    const k=groupKey(e);
    if(!map.has(k)) map.set(k,[]);
    map.get(k).push(e);
  }
  const keys=[...map.keys()].sort((a,b)=>{
    // YouTube mega-group first (common review path)
    if(a==='yt:all') return -1;
    if(b==='yt:all') return 1;
    const ta=groupTitle(map.get(a)[0]).toLowerCase();
    const tb=groupTitle(map.get(b)[0]).toLowerCase();
    return ta.localeCompare(tb);
  });
  setQueueCount(data.length);
  root.innerHTML='';
  if(!keys.length){
    root.innerHTML='<div class="empty-q empty-state">Nothing to review. New Plex/YouTube/Hoshi items will appear here.</div>';
    return;
  }
  for(const k of keys){
    const yt=k==='yt:all';
    const items=map.get(k).slice().sort(yt?sortYouTube:sortEp);
    const head=items[0];
    const actionIds=items.map(e=>e.id);
    const scoreSum=items.reduce((s,e)=>s+(e.tadoku_score_estimate||0),0);
    const amountSum=items.reduce((s,e)=>s+(e.amount||0),0);
    const unit=items[0].unit||'';
    let metaBits;
    if(yt){
      const channels=new Set(items.map(e=>(e.series_key||'').replace(/^yt:/,'')).filter(Boolean));
      metaBits=`${items.length} video(s)${channels.size?` · ${channels.size} channel(s)`:''}`;
    }else{
      const epSummary=items.map(epLabel).filter(x=>x!=='—').join(', ') || 'no S/E';
      metaBits=`${items.length} · ${epSummary}`;
    }
    const typeLabel=yt?'youtube':(head.content_type||'');
    const skLabel=yt?'':(head.series_key?` · ${escapeHtml(head.series_key)}`:'');
    const div=document.createElement('div');
    div.className='group'+(yt?' group-youtube':'');
    div.innerHTML=`
      <div class="group-head">
        <h2>${escapeHtml(groupTitle(head))}
          <span class="muted"> · ${escapeHtml(typeLabel)}${skLabel}</span>
        </h2>
        <div class="group-meta">${escapeHtml(metaBits)} · Σ ${amountSum} ${escapeHtml(unit)} · ~${scoreSum.toFixed(2)}</div>
        <div class="group-actions">
          <button class="approve-group" ${actionIds.length?'':'disabled'}
            onclick='batchApprove(${JSON.stringify(actionIds)})'>Approve group</button>
          <button class="skip-group" ${actionIds.length?'':'disabled'}
            onclick='batchSkip(${JSON.stringify(actionIds)})'>Skip group</button>
        </div>
      </div>
      <table class="queue-table">
        <thead><tr>
          <th>ID</th><th>When</th><th>${yt?'Channel':'S/E'}</th><th>Title</th><th>Amt</th><th>Score</th>
          <th class="col-actions-q">Review</th>
        </tr></thead>
        <tbody></tbody>
      </table>`;
    const tb=div.querySelector('tbody');
    for(const e of items){
      const tr=document.createElement('tr');
      const tt=e.tadoku_title||e.title;
      const mid=yt
        ? escapeHtml((e.series_key||'').replace(/^yt:/,'')||'—')
        : escapeHtml(epLabel(e));
      const statusSel=statusSelectHtml(e.id, e.tadoku_status);
      const modeSel=modeSelectHtml(e.id, e.tadoku_mode);
      tr.dataset.logId=String(e.id);
      tr.innerHTML=`
        <td class="row-id">${e.id}</td>
        <td>${(e.timestamp||'').slice(0,19)}</td>
        <td class="ep">${mid}</td>
        <td>${escapeHtml(tt)}</td>
        <td>${e.amount} ${escapeHtml(e.unit||'')}</td>
        <td>${e.tadoku_score_estimate!=null?Number(e.tadoku_score_estimate).toFixed(2):'—'}</td>
        <td class="col-actions-q">
          <div class="row-review">
            <button type="button" class="approve" onclick="act(${e.id},'approve')">Approve</button>
            <button type="button" class="skip" onclick="act(${e.id},'skip')">Skip</button>
            <details class="row-config">
              <summary title="Status &amp; mode">Edit</summary>
              <div class="row-config-body">
                <label>Status ${statusSel}</label>
                <label>Mode ${modeSel}</label>
              </div>
            </details>
          </div>
        </td>`;
      tb.appendChild(tr);
    }
    root.appendChild(div);
  }
}
const QUEUE_STATUSES=['pending','ready','failed','skipped','pushed','n/a'];
const QUEUE_MODES=['auto','pending','never'];
function statusSelectHtml(id, selected){
  const sel=selected||'pending';
  const opts=QUEUE_STATUSES.map(s=>
    `<option value="${s}"${s===sel?' selected':''}>${s}</option>`).join('');
  return `<select class="status-select badge-select status-${escapeHtml(sel)}"
    data-log-id="${id}" data-field="tadoku_status" data-last="${escapeHtml(sel)}"
    onfocus="this.dataset.last=this.value"
    onchange="patchQueueField(${id},'tadoku_status',this.value,this)"
    title="Tadoku status (saved to DB / Sheets)">${opts}</select>`;
}
function modeSelectHtml(id, selected){
  const sel=selected||'pending';
  const opts=QUEUE_MODES.map(s=>
    `<option value="${s}"${s===sel?' selected':''}>${s}</option>`).join('');
  return `<select class="mode-select badge-select"
    data-log-id="${id}" data-field="tadoku_mode" data-last="${escapeHtml(sel)}"
    onfocus="this.dataset.last=this.value"
    onchange="patchQueueField(${id},'tadoku_mode',this.value,this)"
    title="Tadoku mode for this log + series catalog (future episodes inherit)">${opts}</select>`;
}
async function patchQueueField(id, field, value, el){
  const prev=el?el.dataset.last:null;
  if(el) el.disabled=true;
  setMsg(`Saving #${id} ${field}…`);
  try{
    const body={[field]:value};
    const r=await fetch(`/api/logs/${id}`,{
      method:'PATCH',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body),
    });
    let j=null;
    try{ j=await r.json(); }catch(e){}
    if(!r.ok){
      const detail=j&&j.detail?String(j.detail):(await r.text());
      setMsg(`Save failed #${id}: ${detail}`);
      if(el&&prev!=null){ el.value=prev; }
      return;
    }
    if(el) el.dataset.last=value;
    setMsg(`#${id} → ${j.tadoku_status} / ${j.tadoku_mode}${j.tadoku_remote_id?' · '+j.tadoku_remote_id:''}`);
    // Refresh so groups update (e.g. pushed/skipped leave the queue)
    loadQueue();
    loadRecentLogs();
    if(typeof refreshMetrics==='function') refreshMetrics();
  }catch(e){
    setMsg(`Save failed #${id} (network)`);
    if(el&&prev!=null) el.value=prev;
  }finally{
    if(el) el.disabled=false;
  }
}
function setRecentCount(n){
  const b=document.getElementById('recent-count');
  if(!b) return;
  b.textContent=String(n);
  b.classList.toggle('zero', n===0);
  const sub=document.getElementById('recent-sub');
  if(sub) sub.textContent=n?`${n} recently submitted`:'none yet · local only';
}
function tadokuLogPageUrl(remoteId){
  // Live tadoku.app log pages use UUID remote ids from the immersion API.
  const rid=String(remoteId||'').trim();
  if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(rid)) return '';
  return 'https://tadoku.app/logs/'+encodeURIComponent(rid);
}
function openTadokuLog(href){
  if(!href) return;
  window.open(href,'_blank','noopener,noreferrer');
}
async function loadRecentLogs(){
  const root=document.getElementById('recent-logs');
  if(!root) return;
  let data=[];
  try{
    const r=await fetch('/api/tadoku/recent?limit=30');
    if(!r.ok) throw new Error('recent '+r.status);
    data=await r.json();
  }catch(e){
    root.innerHTML='<div class="empty-q">Could not load recent logs.</div>';
    setRecentCount(0);
    return;
  }
  if(!Array.isArray(data)) data=[];
  setRecentCount(data.length);
  if(!data.length){
    root.innerHTML='<div class="empty-q">No pushed logs yet. Approve or auto-submit something and it will show up here.</div>';
    return;
  }
  let html=`<div class="recent-table-wrap"><table class="recent-table">
    <thead><tr>
      <th>ID</th><th>Sent</th><th>Logged</th><th>S/E</th><th>Title</th><th>Amt</th><th>Score</th><th>Remote</th><th class="col-actions-q"> </th>
    </tr></thead><tbody>`;
  for(const e of data){
    const tt=e.tadoku_title||e.title;
    const sent=(e.updated_at||'').slice(0,19)||'—';
    const logged=(e.timestamp||'').slice(0,19)||'—';
    const rid=(e.tadoku_remote_id||'').trim();
    const ridShort=rid.length>14?rid.slice(0,8)+'…'+rid.slice(-4):rid;
    const href=tadokuLogPageUrl(rid);
    const rowClass=href?'recent-row is-link':'recent-row';
    const rowAttrs=href
      ?` data-href="${escapeHtml(href)}" role="link" tabindex="0" title="Open on tadoku.app"`
      :' title="No tadoku.app page (missing remote id)"';
    const titleCell=href
      ?`<a class="tadoku-log-link" href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(tt)}</a>
        <span class="muted"> · ${escapeHtml(e.content_type||'')}</span>`
      :`${escapeHtml(tt)}
        <span class="muted"> · ${escapeHtml(e.content_type||'')}</span>`;
    const remoteCell=href
      ?`<a class="tadoku-log-link remote-id" href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(rid)}">${escapeHtml(ridShort)}</a>`
      :`<span class="remote-id" title="${escapeHtml(rid)}">${escapeHtml(ridShort||'—')}</span>`;
    const delLabel=escapeHtml(tt||('#'+e.id));
    html+=`<tr class="${rowClass}"${rowAttrs} data-log-id="${e.id}">
      <td class="row-id">${e.id}</td>
      <td class="sent-at">${escapeHtml(sent)}</td>
      <td>${escapeHtml(logged)}</td>
      <td class="ep">${escapeHtml(epLabel(e))}</td>
      <td>${titleCell}</td>
      <td>${e.amount} ${escapeHtml(e.unit||'')}</td>
      <td>${e.tadoku_score_estimate!=null?Number(e.tadoku_score_estimate).toFixed(2):'—'}</td>
      <td>${remoteCell}</td>
      <td class="col-actions-q">
        <button type="button" class="danger log-del-btn" data-log-id="${e.id}"
          data-label="${delLabel}" title="Delete this log">Delete</button>
      </td>
    </tr>`;
  }
  html+='</tbody></table></div>';
  root.innerHTML=html;
  root.querySelectorAll('tr.recent-row.is-link').forEach(tr=>{
    const go=(ev)=>{
      // Let real anchors / delete controls handle their own click
      if(ev && ev.target && ev.target.closest && ev.target.closest('a,button,.log-del-btn')) return;
      openTadokuLog(tr.dataset.href);
    };
    tr.addEventListener('click', go);
    tr.addEventListener('keydown', e=>{
      if(e.target && e.target.closest && e.target.closest('button')) return;
      if(e.key==='Enter'||e.key===' '){ e.preventDefault(); openTadokuLog(tr.dataset.href); }
    });
  });
  root.querySelectorAll('.log-del-btn').forEach(btn=>{
    btn.addEventListener('click', (ev)=>{ ev.preventDefault(); ev.stopPropagation(); armOrDeleteLog(btn); });
  });
}
/** First click arms Confirm; second click DELETEs. Auto-disarms after a few seconds. */
function armOrDeleteLog(btn){
  if(!btn) return;
  const id=Number(btn.dataset.logId||btn.getAttribute('data-log-id'));
  if(!id) return;
  if(btn.dataset.armed==='1'){
    deleteLogById(id, btn);
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
async function deleteLogById(id, btn){
  if(btn){ btn.disabled=true; btn.textContent='…'; }
  try{
    const r=await fetch('/api/logs/'+id,{method:'DELETE'});
    if(!r.ok){
      setMsg('Delete #'+id+' failed');
      if(btn){ btn.disabled=false; btn.dataset.armed=''; btn.classList.remove('is-armed'); btn.textContent='Delete'; }
      return;
    }
    setMsg('Deleted #'+id);
    if(typeof loadRecentLogs==='function') loadRecentLogs();
    if(typeof loadQueue==='function') loadQueue();
    if(typeof refreshMetrics==='function') refreshMetrics();
    if(typeof loadLogs==='function') loadLogs();
  }catch(e){
    setMsg('Delete #'+id+' failed (network)');
    if(btn){ btn.disabled=false; btn.dataset.armed=''; btn.classList.remove('is-armed'); btn.textContent='Delete'; }
  }
}
async function act(id,kind){
  const r=await fetch(`/api/logs/${id}/${kind}`,{method:'POST'});
  const body=r.ok?await r.json():null;
  setMsg(r.ok
    ? `${kind} #${id} → ${body.tadoku_status}${body.tadoku_remote_id?' ('+body.tadoku_remote_id+')':''}`
    : await r.text());
  loadQueue();
  loadRecentLogs();
  if(typeof refreshMetrics==='function') refreshMetrics();
}
async function batchApprove(ids){
  if(!ids||!ids.length) return;
  const r=await fetch('/api/logs/batch/approve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids})});
  const j=await r.json();
  setMsg(r.ok?`group approve: pushed=${j.pushed} failed=${j.failed} skipped=${j.skipped}`:JSON.stringify(j));
  loadQueue();
  loadRecentLogs();
  if(typeof refreshMetrics==='function') refreshMetrics();
}
async function batchSkip(ids){
  if(!ids||!ids.length) return;
  const r=await fetch('/api/logs/batch/skip',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids})});
  const j=await r.json();
  setMsg(r.ok?`group skip: ${j.skipped}`:JSON.stringify(j));
  loadQueue();
  if(typeof refreshMetrics==='function') refreshMetrics();
}
async function processAll(){
  const r=await fetch('/api/tadoku/process',{method:'POST'});
  const j=await r.json();
  setMsg(`pushed=${j.pushed} failed=${j.failed}`);
  loadQueue();
  loadRecentLogs();
  if(typeof refreshMetrics==='function') refreshMetrics();
  // Manual submit does not reset the interval job; still refresh countdown state
  refreshAutoSchedule();
  if(typeof loadGsmPanel==='function') loadGsmPanel();
}

/* ===== GSM → Tadoku (Queue / Home fold) ===== */
let _gsmPrefs={
  log_mode:'manual',
  min_submit_characters:10000,
  auto_submit_idle_minutes:30,
  deduplicate:false,
  strip_punctuation:true,
  collapse_repeated_blocks:true,
  require_japanese:true,
  auto_log_at_time_enabled:false,
  auto_log_at_hour:4,
  timezone:'',
};

function gsmSetBanner(html, kind){
  const el=document.getElementById('gsm-banner');
  if(!el) return;
  el.className='gsm-banner'+(kind?(' '+kind):'');
  el.innerHTML=html||'';
}
function gsmSetMsg(t, kind){
  const el=document.getElementById('gsm-msg');
  if(!el) return;
  el.textContent=t||'';
  el.className='gsm-msg'+(kind?(' '+kind):'');
}
/** Ready-to-log character count on the fold summary (visible when collapsed). */
function gsmSetCount(n){
  const b=document.getElementById('gsm-count');
  if(!b) return;
  const chars=Number(n)||0;
  b.textContent=chars.toLocaleString();
  b.classList.toggle('zero', chars===0);
  b.title=chars?`${chars.toLocaleString()} character(s) ready to log`:'Nothing ready to log';
  openFoldIfWork('gsm-fold', 'immersion.gsm.open', chars>0);
}
/** Open a details fold once when work exists and user has no explicit pref. */
function openFoldIfWork(id, key, hasWork){
  if(!hasWork) return;
  const fold=document.getElementById(id);
  if(!fold || fold.tagName!=='DETAILS') return;
  try{
    if(localStorage.getItem(key)!=null) return;
  }catch(e){ return; }
  fold.open=true;
}
/** Format 0–23 hour as "4:00 AM" / "12:00 PM". */
function gsmFormatHour(h){
  let n=Number(h);
  if(isNaN(n)) n=4;
  n=((Math.trunc(n)%24)+24)%24;
  const ampm=n<12?'AM':'PM';
  const h12=n%12===0?12:n%12;
  return `${h12}:00 ${ampm}`;
}
/**
 * Summary mode label (right side of fold). Highest wins: manual < daily < auto.
 * Continuous idle auto outranks daily-at-time; daily outranks pure manual.
 */
function gsmModeSubLabel(prefs){
  const p=prefs||_gsmPrefs||{};
  if((p.log_mode||'manual')==='auto') return 'auto';
  if(p.auto_log_at_time_enabled) return 'daily';
  return 'manual';
}
function gsmShowReadyUI(on){
  ['gsm-stats','gsm-actions','gsm-table-wrap','gsm-count-meta'].forEach(id=>{
    const el=document.getElementById(id);
    if(el) el.hidden=!on;
  });
  ['gsm-submit-btn','gsm-refresh-btn','gsm-mark-btn','gsm-pref-save','gsm-auto-save'].forEach(id=>{
    const b=document.getElementById(id);
    if(b) b.disabled=!on;
  });
}
/** Live counting toggles (may differ from saved prefs until Save). */
function gsmLiveCounting(){
  const dedupeEl=document.getElementById('gsm-pref-dedupe');
  const stripEl=document.getElementById('gsm-pref-strip-punct');
  const collapseEl=document.getElementById('gsm-pref-collapse-blocks');
  const jpEl=document.getElementById('gsm-pref-require-jp');
  return {
    deduplicate: dedupeEl?!!dedupeEl.checked:!!_gsmPrefs.deduplicate,
    strip_punctuation: stripEl?!!stripEl.checked:(_gsmPrefs.strip_punctuation!==false),
    collapse_repeated_blocks: collapseEl
      ?!!collapseEl.checked
      :(_gsmPrefs.collapse_repeated_blocks!==false),
    require_japanese: jpEl?!!jpEl.checked:(_gsmPrefs.require_japanese!==false),
  };
}
/** Short label for how total_characters was counted (Ready to log / Logging). */
function gsmCountModeLabel(p){
  const strip=!!(p&&p.strip_punctuation);
  const dedupe=!!(p&&p.deduplicate);
  const collapse=!!(p&&p.collapse_repeated_blocks);
  const jp=!!(p&&p.require_japanese);
  const parts=[];
  if(strip) parts.push('punctuation stripped');
  if(collapse) parts.push('block spam collapsed');
  if(jp) parts.push('Japanese only');
  if(dedupe) parts.push('skip repeat lines');
  if(!parts.length) return 'raw (nothing stripped)';
  return parts.join(' · ');
}
/** Visible effect of strip / block-collapse / dedupe on the current pending log. */
function gsmPaintCountMeta(p){
  const meta=document.getElementById('gsm-count-meta');
  const effect=document.getElementById('gsm-count-effect');
  if(!meta) return;
  if(!p || p.needs_cursor_init){
    meta.hidden=true;
    meta.innerHTML='';
    if(effect) effect.textContent='Toggle options to preview Ready to log, then save.';
    return;
  }
  // Explicit booleans from the preview response (what was actually counted).
  const strip=!!p.strip_punctuation;
  const dedupe=!!p.deduplicate;
  const collapse=!!p.collapse_repeated_blocks;
  const requireJp=!!p.require_japanese;
  const dups=Number(p.duplicates_excluded||0);
  const blockLines=Number(p.block_collapse_lines||0);
  const blockChars=Number(p.block_collapse_chars_removed||0);
  const nonJpLines=Number(p.non_jp_lines||0);
  const nonJpChars=Number(p.non_jp_chars_removed||0);
  const raw=Number(p.baseline_characters||0);
  const stripped=Number(
    p.stripped_characters!=null?p.stripped_characters:0
  );
  // total_characters = Ready to log under current toggles
  const total=Number(p.total_characters||0);
  const stripDelta=Math.max(0, raw-stripped);
  // After collapsing within-line block spam (always measured; applied only if toggle on)
  const afterBlocks=Math.max(0, raw-blockChars);
  const fmt=n=>Number(n||0).toLocaleString();
  const mode=gsmCountModeLabel(p);

  let compareHtml='';
  // --- Punctuation: Raw vs Stripped ---
  if(raw>0 || stripped>0){
    const rawActive=!strip;
    const strippedActive=strip;
    compareHtml+=
      `<div class="gsm-raw-strip-caption">1 · Punctuation (comparison only)</div>`+
      `<div class="gsm-raw-strip${strip?' is-active-strip':' is-active-raw'}">`+
        `<span class="gsm-raw-strip-pair${rawActive?' is-chosen':''}">`+
          `<span class="gsm-raw-strip-label">Raw</span> `+
          `<span class="gsm-raw-strip-val">${fmt(raw)}</span>`+
          (rawActive?`<span class="gsm-raw-strip-tag">base</span>`:'')+
        `</span>`+
        `<span class="gsm-raw-strip-pair${strippedActive?' is-chosen':''}">`+
          `<span class="gsm-raw-strip-label">Stripped</span> `+
          `<span class="gsm-raw-strip-val">${fmt(stripped)}</span>`+
          (strippedActive?`<span class="gsm-raw-strip-tag">base</span>`:'')+
        `</span>`+
        (stripDelta>0
          ? `<span class="gsm-raw-strip-diff">−${fmt(stripDelta)} punct</span>`
          : `<span class="gsm-raw-strip-diff same">same</span>`)+
      `</div>`;
  }

  // --- Within-line block spam (toggle + always-measured savings) ---
  if(raw>0){
    const hasSpam=blockLines>0 && blockChars>0;
    const applied=collapse && hasSpam;
    compareHtml+=
      `<div class="gsm-raw-strip-caption">2 · Repeated blocks in a line `+
        (collapse
          ? (hasSpam?'(on — applied to Ready to log)':'(on — none in pending)')
          : (hasSpam?'(off — not applied)':'(off)'))+
      `</div>`+
      `<div class="gsm-raw-strip${collapse?' is-active-strip':' is-active-raw'}${applied?' has-savings':''}">`+
        `<span class="gsm-raw-strip-pair${!collapse?' is-chosen':''}">`+
          `<span class="gsm-raw-strip-label">Full lines</span> `+
          `<span class="gsm-raw-strip-val">${fmt(raw)}</span>`+
        `</span>`+
        `<span class="gsm-raw-strip-pair${collapse?' is-chosen':''}">`+
          `<span class="gsm-raw-strip-label">After collapse</span> `+
          `<span class="gsm-raw-strip-val">${fmt(afterBlocks)}</span>`+
          (collapse?`<span class="gsm-raw-strip-tag">on</span>`:'')+
        `</span>`+
        (hasSpam
          ? `<span class="gsm-raw-strip-diff">−${fmt(blockChars)}`+
              ` · ${fmt(blockLines)} line${blockLines===1?'':'s'}</span>`
          : `<span class="gsm-raw-strip-diff same">no block spam</span>`)+
      `</div>`;
    if(hasSpam && !collapse){
      compareHtml+=
        `<div class="gsm-count-delta gsm-count-warn">`+
          `Repeated blocks found (−${fmt(blockChars)}). Turn on “Collapse repeated blocks” to exclude them from Ready to log.`+
        `</div>`;
    }
  }else if(!total){
    compareHtml+=`<div class="gsm-count-delta muted">Nothing pending — settings will apply to new lines.</div>`;
  }

  // Active chips
  const stripParts=[];
  if(strip) stripParts.push(`Punctuation${stripDelta?` (−${fmt(stripDelta)})`:''}`);
  if(collapse){
    stripParts.push(
      blockLines
        ? `Block spam (−${fmt(blockChars)} · ${fmt(blockLines)} line${blockLines===1?'':'s'})`
        : 'Block spam (none pending)'
    );
  }else if(blockLines){
    stripParts.push(`Block spam off (would −${fmt(blockChars)})`);
  }
  if(requireJp){
    stripParts.push(
      nonJpLines
        ? `Japanese only (−${fmt(nonJpChars)} · ${fmt(nonJpLines)} line${nonJpLines===1?'':'s'})`
        : 'Japanese only'
    );
  }else if(nonJpLines){
    stripParts.push(`Japanese filter off (would −${fmt(nonJpChars)})`);
  }
  if(dedupe){
    stripParts.push(
      dups
        ? `Repeat lines (−${fmt(dups)})`
        : 'Repeat lines'
    );
  }
  const stripSummary=stripParts.length
    ? `Active: ${stripParts.join(' · ')}`
    : 'Active: none (raw counts)';
  const stripChip=
    `<span class="gsm-chip${(strip||dedupe||collapse||requireJp)?' on':''}">${escapeHtml(stripSummary)}</span>`;

  // Ready to log + breakdown
  let loggedNote=
    `<div class="gsm-count-delta gsm-count-delta-log">`+
      `<strong>Ready to log / Logging: ${fmt(total)}</strong>`+
      `<span class="gsm-count-mode"> · ${escapeHtml(mode)}</span>`+
    `</div>`;
  const steps=[];
  steps.push(`Raw ${fmt(raw)}`);
  if(collapse && blockChars>0) steps.push(`block spam −${fmt(blockChars)}`);
  if(strip && stripDelta>0) steps.push(`punct −${fmt(stripDelta)}`);
  // stripDelta is raw−stripped (punct only, no collapse). When both on, punct
  // savings and block savings overlap in display — show total delta to Ready.
  if(dedupe && dups>0) steps.push(`repeat lines −${fmt(dups)}`);
  const totalDelta=Math.max(0, raw-total);
  if(totalDelta>0 || steps.length>1){
    loggedNote+=
      `<div class="gsm-count-delta muted">`+
        `${steps.join(' → ')} → <b>${fmt(total)}</b>`+
        (totalDelta>0?` (total −${fmt(totalDelta)})`:'')+
      `</div>`;
  }

  meta.hidden=false;
  meta.innerHTML=compareHtml+`<div class="gsm-chips">${stripChip}</div>`+loggedNote;
  if(effect){
    if(raw>0 || stripped>0){
      let t=
        `Punctuation: raw ${fmt(raw)} → stripped ${fmt(stripped)}`+
        (stripDelta>0?` (−${fmt(stripDelta)})`:'');
      if(blockChars>0){
        t+=` · Repeated blocks −${fmt(blockChars)} in ${fmt(blockLines)} line(s)`+
          (collapse?' (on)':' (off — turn on to apply)');
      }else if(collapse){
        t+=' · No repeated blocks in pending lines';
      }
      if(dups) t+=` · ${fmt(dups)} repeated line(s) skipped`;
      t+=`. Ready to log: ${fmt(total)} (${mode}). Save to keep.`;
      effect.textContent=t;
    }else{
      effect.textContent=
        'Nothing pending yet. Toggle options above, then save for auto and manual logs.';
    }
  }
}
function gsmPaintPrefs(prefs){
  if(!prefs) return;
  _gsmPrefs=Object.assign({},_gsmPrefs,prefs);
  const mode=(_gsmPrefs.log_mode||'manual')==='auto'?'auto':'manual';
  document.querySelectorAll('#gsm-pref-mode [data-mode]').forEach(btn=>{
    btn.classList.toggle('on', btn.dataset.mode===mode);
  });
  const minEl=document.getElementById('gsm-pref-min');
  const idleEl=document.getElementById('gsm-pref-idle');
  const dedupeEl=document.getElementById('gsm-pref-dedupe');
  const stripEl=document.getElementById('gsm-pref-strip-punct');
  const collapseEl=document.getElementById('gsm-pref-collapse-blocks');
  const jpEl=document.getElementById('gsm-pref-require-jp');
  const dailyEl=document.getElementById('gsm-pref-daily');
  const hourEl=document.getElementById('gsm-pref-hour');
  const tzEl=document.getElementById('gsm-tz-label');
  if(minEl) minEl.value=String(_gsmPrefs.min_submit_characters||10000);
  if(idleEl) idleEl.value=String(_gsmPrefs.auto_submit_idle_minutes??30);
  if(dedupeEl) dedupeEl.checked=!!_gsmPrefs.deduplicate;
  if(stripEl) stripEl.checked=_gsmPrefs.strip_punctuation!==false;
  if(collapseEl) collapseEl.checked=_gsmPrefs.collapse_repeated_blocks!==false;
  if(jpEl) jpEl.checked=_gsmPrefs.require_japanese!==false;
  if(dailyEl) dailyEl.checked=!!_gsmPrefs.auto_log_at_time_enabled;
  if(hourEl) hourEl.value=String(_gsmPrefs.auto_log_at_hour??4);
  if(tzEl){
    const clock=gsmFormatHour(_gsmPrefs.auto_log_at_hour??4);
    const tz=_gsmPrefs.timezone||'local';
    tzEl.textContent=_gsmPrefs.auto_log_at_time_enabled
      ? `Runs daily at ${clock} · ${tz}`
      : `Timezone: ${tz}`;
  }
  const autoLabel=document.getElementById('gsm-stat-auto');
  const autoSub=document.getElementById('gsm-stat-auto-sub');
  if(autoLabel){
    const parts=[];
    if(mode==='auto') parts.push('Idle');
    if(_gsmPrefs.auto_log_at_time_enabled) parts.push('Daily');
    autoLabel.textContent=parts.length?parts.join('+'):'Off';
  }
  if(autoSub){
    const bits=[];
    bits.push(`≥${Number(_gsmPrefs.min_submit_characters||10000).toLocaleString()} chars`);
    if(mode==='auto') bits.push(`${_gsmPrefs.auto_submit_idle_minutes??30}m idle`);
    if(_gsmPrefs.auto_log_at_time_enabled){
      bits.push(`${gsmFormatHour(_gsmPrefs.auto_log_at_hour??4)} daily`);
    }
    autoSub.textContent=bits.join(' · ')||'Manual only';
  }
  // Fold summary (visible when collapsed): manual | daily | auto
  const sub=document.getElementById('gsm-sub');
  if(sub && sub.textContent!=='disabled' && sub.textContent!=='not connected'){
    sub.textContent=gsmModeSubLabel(_gsmPrefs);
  }
}
function gsmEntryStatus(e){
  if(e.ready_for_auto) return 'Ready for auto';
  if(e.below_min) return `Under min (${Number(_gsmPrefs.min_submit_characters||10000).toLocaleString()})`;
  if(e.waiting_idle) return 'Waiting idle…';
  return '';
}
/* game_keys the user unchecked; everything else stays selected (incl. new games) */
let _gsmDeselected=new Set();
let _gsmLastEntries=[];
function gsmIsSelected(key){
  return !_gsmDeselected.has(String(key));
}
function gsmSelectedEntries(entries){
  const list=entries||_gsmLastEntries||[];
  return list.filter(e=>gsmIsSelected(e.game_key));
}
function gsmPruneSelection(entries){
  const live=new Set((entries||[]).map(e=>String(e.game_key)));
  _gsmDeselected=new Set([..._gsmDeselected].filter(k=>live.has(k)));
}
function gsmSyncSelectionUI(){
  const entries=_gsmLastEntries||[];
  const selected=gsmSelectedEntries(entries);
  const chars=selected.reduce((n,e)=>n+Number(e.characters||0),0);
  const charsEl=document.getElementById('gsm-stat-chars');
  const gamesEl=document.getElementById('gsm-stat-games');
  if(charsEl) charsEl.textContent=chars.toLocaleString();
  if(gamesEl){
    if(!entries.length){
      gamesEl.textContent='Nothing new yet';
    }else if(selected.length===entries.length){
      gamesEl.textContent=`${entries.length} game(s) · ${gsmCountModeLabel(gsmLiveCounting())}`;
    }else{
      gamesEl.textContent=
        `${selected.length}/${entries.length} selected · ${chars.toLocaleString()} chars`;
    }
  }
  gsmSetCount(chars);
  const subBtn=document.getElementById('gsm-submit-btn');
  if(subBtn) subBtn.disabled=selected.length===0;
  const all=document.getElementById('gsm-select-all');
  if(all && entries.length){
    all.checked=selected.length===entries.length;
    all.indeterminate=selected.length>0 && selected.length<entries.length;
  }else if(all){
    all.checked=true;
    all.indeterminate=false;
  }
  document.querySelectorAll('#gsm-preview-rows tr[data-game-key]').forEach(tr=>{
    const on=gsmIsSelected(tr.dataset.gameKey);
    tr.classList.toggle('gsm-row-off', !on);
    const cb=tr.querySelector('.gsm-game-cb');
    if(cb) cb.checked=on;
  });
}
function gsmOnRowCheck(ev){
  const cb=ev&&ev.target;
  if(!cb) return;
  const key=String(cb.value||'');
  if(cb.checked) _gsmDeselected.delete(key);
  else _gsmDeselected.add(key);
  gsmSyncSelectionUI();
}
function gsmToggleSelectAll(ev){
  const on=!!(ev&&ev.target?ev.target.checked:true);
  if(on) _gsmDeselected=new Set();
  else _gsmDeselected=new Set((_gsmLastEntries||[]).map(e=>String(e.game_key)));
  gsmSyncSelectionUI();
}
async function loadGsmPanel(opts){
  if(!document.getElementById('gsm-fold')) return;
  const fromUser=!!(opts&&opts.fromUser);
  const btn=document.getElementById('gsm-refresh-btn');
  const prevLabel=btn?btn.textContent:'Refresh';
  if(fromUser && btn){
    btn.disabled=true;
    btn.classList.add('gsm-busy');
    btn.textContent='Refreshing…';
    gsmSetMsg('Refreshing from GameSentenceMiner…','');
  }
  try{
    const st=await (await fetch('/api/gsm/status',{cache:'no-store'})).json();
    gsmPaintPrefs(st.prefs);
    const sub=document.getElementById('gsm-sub');
    if(!st.enabled){
      gsmSetBanner('GameSentenceMiner is turned off in settings.','warn');
      if(sub) sub.textContent='disabled';
      gsmSetCount(0);
      gsmShowReadyUI(false);
      if(fromUser) gsmSetMsg('GSM is disabled in settings.','warn');
      return;
    }
    if(!st.ok){
      gsmSetBanner(
        `<strong>Can’t find GameSentenceMiner data</strong><br>`+
        `<span class="faint">${escapeHtml(st.message||'gsm.db not found')}</span>`+
        (st.detail?`<br><span class="faint">${escapeHtml(st.detail)}</span>`:''),
        'bad'
      );
      if(sub) sub.textContent='not connected';
      gsmSetCount(0);
      gsmShowReadyUI(false);
      if(fromUser) gsmSetMsg(st.message||'GSM not connected.','bad');
      return;
    }
    gsmSetBanner(
      st.cursor_sync_pending
        ? 'Connected · counter reset locally (GSM file sync pending)'
        : (st.writable_cursor
          ? 'Connected to GameSentenceMiner'
          : 'Connected · GSM file is locked for write (counter still resets in this app)'),
      'ok'
    );
    if(sub) sub.textContent=gsmModeSubLabel(st.prefs);
    gsmShowReadyUI(true);
    // Keep Refresh disabled until the full user-triggered load finishes
    if(fromUser && btn){
      btn.disabled=true;
      btn.classList.add('gsm-busy');
      btn.textContent='Refreshing…';
    }
    const summary=await refreshGsmPreview({fromUser});
    if(fromUser){
      const chars=summary&&summary.chars!=null?Number(summary.chars):null;
      const games=summary&&summary.games!=null?Number(summary.games):null;
      const when=new Date().toLocaleTimeString();
      if(chars!=null){
        gsmSetMsg(
          `Updated ${when} · ${chars.toLocaleString()} character(s)`+
          (games!=null?` across ${games} game(s)`:''),
          'ok'
        );
      }else{
        gsmSetMsg(`Updated ${when}.`,'ok');
      }
      const stats=document.getElementById('gsm-stats');
      if(stats){
        stats.classList.remove('gsm-flash');
        void stats.offsetWidth;
        stats.classList.add('gsm-flash');
      }
    }
  }catch(e){
    gsmSetBanner(`Could not load GSM: ${escapeHtml(String(e))}`,'bad');
    gsmSetCount(0);
    gsmShowReadyUI(false);
    if(fromUser) gsmSetMsg(String(e),'bad');
  }finally{
    if(fromUser && btn){
      btn.disabled=false;
      btn.classList.remove('gsm-busy');
      btn.textContent=prevLabel||'Refresh';
    }
  }
}
async function refreshGsmPreview(opts){
  const fromUser=!!(opts&&opts.fromUser);
  const liveOnly=!!(opts&&opts.liveOnly);
  const tbody=document.getElementById('gsm-preview-rows');
  try{
    const live=gsmLiveCounting();
    const qs=new URLSearchParams({
      deduplicate: live.deduplicate?'true':'false',
      strip_punctuation: live.strip_punctuation?'true':'false',
      collapse_repeated_blocks: live.collapse_repeated_blocks?'true':'false',
      require_japanese: live.require_japanese?'true':'false',
    });
    const p=await (await fetch('/api/gsm/preview?'+qs.toString(),{cache:'no-store'})).json();
    // Don't overwrite checkbox state during live toggle preview
    if(p.prefs && !liveOnly) gsmPaintPrefs(p.prefs);
    if(!p.ok && p.status && !p.status.ok){
      gsmSetBanner(escapeHtml(p.message||'GSM not ready'),'bad');
      gsmSetCount(0);
      gsmShowReadyUI(false);
      gsmPaintCountMeta(null);
      return null;
    }
    if(p.needs_cursor_init){
      _gsmLastEntries=[];
      document.getElementById('gsm-stat-chars').textContent='—';
      document.getElementById('gsm-stat-games').textContent='Set a starting point below';
      gsmSetCount(0);
      gsmPaintCountMeta(p);
      if(tbody) tbody.innerHTML=`<tr><td colspan="4" class="muted">${escapeHtml(p.detail||p.message||'')}</td></tr>`;
      const allInit=document.getElementById('gsm-select-all');
      if(allInit){ allInit.checked=true; allInit.indeterminate=false; }
      if(!fromUser && !liveOnly){
        gsmSetMsg('Use “Skip history — start from now” under Counting settings if you don’t want to log past lines.','warn');
      }
      return {chars:0, games:0, needs_cursor_init:true};
    }
    // Reflect applied counting flags from response (for effect line)
    p.deduplicate=p.deduplicate!=null?!!p.deduplicate:live.deduplicate;
    // Prefer explicit API flag (false means raw). Only fall back to live checkbox if missing.
    p.strip_punctuation=p.strip_punctuation!=null?!!p.strip_punctuation:!!live.strip_punctuation;
    p.collapse_repeated_blocks=p.collapse_repeated_blocks!=null
      ?!!p.collapse_repeated_blocks
      :!!live.collapse_repeated_blocks;
    p.require_japanese=p.require_japanese!=null
      ?!!p.require_japanese
      :!!live.require_japanese;
    const entries=p.entries||[];
    _gsmLastEntries=entries;
    gsmPruneSelection(entries);
    gsmPaintCountMeta(p);
    if(tbody){
      if(!entries.length){
        tbody.innerHTML='<tr><td colspan="4" class="muted">Play with GSM running — new text will show up here.</td></tr>';
      }else{
        tbody.innerHTML=entries.map(e=>{
          const st=gsmEntryStatus(e);
          const key=String(e.game_key||'');
          const name=String(e.game_name||'game');
          const on=gsmIsSelected(key);
          return `<tr data-game-key="${escapeHtml(key)}"${on?'':' class="gsm-row-off"'}>
            <td class="gsm-col-check">
              <input type="checkbox" class="gsm-game-cb" value="${escapeHtml(key)}"
                ${on?'checked':''} aria-label="Select ${escapeHtml(name)}"/>
            </td>
            <td>${escapeHtml(name)}</td>
            <td style="text-align:right">${Number(e.characters||0).toLocaleString()}</td>
            <td class="col-hide-sm">
              <span class="muted">${escapeHtml(st)}</span>
              <button type="button" class="secondary gsm-clear-game"
                data-game-key="${escapeHtml(key)}" data-game-name="${escapeHtml(name)}"
                title="Zero Ready-to-log for this game (skip current lines, keep GSM data)">Clear</button>
            </td>
          </tr>`;
        }).join('');
        tbody.querySelectorAll('.gsm-game-cb').forEach(cb=>{
          cb.addEventListener('change', gsmOnRowCheck);
        });
        tbody.querySelectorAll('.gsm-clear-game').forEach(btn=>{
          btn.addEventListener('click', gsmClearGameClick);
        });
      }
    }
    gsmSyncSelectionUI();
    if(!fromUser && !liveOnly) gsmSetMsg('','');
    const selected=gsmSelectedEntries(entries);
    const chars=selected.reduce((n,e)=>n+Number(e.characters||0),0);
    return {chars, games:selected.length, preview:p};
  }catch(e){
    gsmSetMsg(String(e),'bad');
    gsmSetCount(0);
    gsmPaintCountMeta(null);
    return null;
  }
}
async function gsmLogToTadoku(){
  const btn=document.getElementById('gsm-submit-btn');
  if(btn) btn.disabled=true;
  gsmSetMsg('Logging to Tadoku…','');
  try{
    // Use current counting toggles (same as preview), even if not yet saved
    const live=gsmLiveCounting();
    const selected=gsmSelectedEntries(_gsmLastEntries);
    if(!selected.length){
      gsmSetMsg('Select at least one game to log.','warn');
      return;
    }
    const body={
      submit:true,
      deduplicate:live.deduplicate,
      strip_punctuation:live.strip_punctuation,
      collapse_repeated_blocks:live.collapse_repeated_blocks,
      require_japanese:live.require_japanese,
    };
    // Only send filter when a subset is selected (all → omit = backend default)
    if(_gsmDeselected.size){
      body.game_keys=selected.map(e=>String(e.game_key));
    }
    const r=await fetch('/api/gsm/queue',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body),
    });
    const j=await r.json();
    if(!r.ok || j.ok===false){
      gsmSetMsg(j.message||j.detail||JSON.stringify(j),'bad');
    }else{
      const n=(j.created||[]).length;
      const sk=(j.skipped_duplicate||[]).length;
      let msg=n?`Logged ${n} game(s)`:'Nothing new';
      if(sk) msg+=` · ${sk} already present`;
      if(j.submitted){
        msg+=` · Tadoku pushed=${j.submitted.pushed||0}`;
        if(j.submitted.failed) msg+=` failed=${j.submitted.failed}`;
      }
      const cr=j.cursor_result||{};
      if(j.cursor_advanced){
        if(cr.advanced_gsm===false && cr.advanced_local){
          msg+=' · counter reset (GSM file sync pending)';
        }else{
          msg+=' · counter reset';
        }
      }else if(j.submitted && (j.submitted.pushed||0)>0){
        msg+=' · counter will reset when export finishes';
      }
      gsmSetMsg(msg, j.submitted && j.submitted.failed? 'warn':'ok');
      setMsg(msg);
    }
    loadQueue();
    loadRecentLogs();
    if(typeof refreshMetrics==='function') refreshMetrics();
    await loadGsmPanel();
  }catch(e){
    gsmSetMsg(String(e),'bad');
  }finally{
    if(btn) btn.disabled=false;
    gsmSyncSelectionUI();
  }
}
async function gsmSavePrefs(which){
  const mode=document.querySelector('#gsm-pref-mode [data-mode].on')?.dataset.mode||'manual';
  const min=parseInt(document.getElementById('gsm-pref-min')?.value||'10000',10);
  const idle=parseFloat(document.getElementById('gsm-pref-idle')?.value||'30');
  const live=gsmLiveCounting();
  const daily=!!document.getElementById('gsm-pref-daily')?.checked;
  let hour=parseInt(document.getElementById('gsm-pref-hour')?.value||'4',10);
  if(isNaN(hour)) hour=4;
  hour=Math.max(0, Math.min(23, hour));
  // Always persist both counting + auto so auto/manual stay in sync with UI
  try{
    const r=await fetch('/api/gsm/settings',{
      method:'PATCH',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        log_mode:mode,
        min_submit_characters:min||10000,
        auto_submit_idle_minutes:isNaN(idle)?30:idle,
        deduplicate:live.deduplicate,
        strip_punctuation:live.strip_punctuation,
        collapse_repeated_blocks:live.collapse_repeated_blocks,
        require_japanese:live.require_japanese,
        auto_log_at_time_enabled:daily,
        auto_log_at_hour:hour,
      }),
    });
    const j=await r.json();
    if(!r.ok){
      gsmSetMsg(j.detail||JSON.stringify(j),'bad');
      return;
    }
    gsmPaintPrefs(j);
    const label=which==='auto'?'Auto logging saved.':
      which==='counting'?'Counting settings saved.':
      'Settings saved.';
    gsmSetMsg(label,'ok');
    await refreshGsmPreview();
  }catch(e){
    gsmSetMsg(String(e),'bad');
  }
}
let _gsmLivePreviewTimer=null;
function gsmOnCountingToggle(){
  if(_gsmLivePreviewTimer) clearTimeout(_gsmLivePreviewTimer);
  _gsmLivePreviewTimer=setTimeout(()=>{
    refreshGsmPreview({liveOnly:true});
  },120);
}
async function gsmMarkSynced(){
  if(!confirm('Skip all current GSM text for Tadoku?\n\nThis only moves the export counter forward. Your GSM lines are not deleted. New play after this will count again.')) return;
  const btn=document.getElementById('gsm-mark-btn');
  if(btn) btn.disabled=true;
  try{
    const r=await fetch('/api/gsm/mark-synced',{method:'POST'});
    const j=await r.json();
    gsmSetMsg(r.ok?(j.message||'Starting point set.'):(j.detail||j.message||'Failed'), r.ok?'ok':'bad');
    await loadGsmPanel();
  }catch(e){
    gsmSetMsg(String(e),'bad');
  }finally{
    if(btn) btn.disabled=false;
  }
}
async function gsmClearGameClick(ev){
  const btn=ev&&ev.currentTarget;
  if(!btn) return;
  const key=String(btn.dataset.gameKey||'');
  const name=String(btn.dataset.gameName||'this game');
  if(!key) return;
  if(!confirm(`Clear Ready-to-log for ${name}?\n\nSkips current pending characters for this game only. GSM lines are not deleted. Other games are unchanged.`)) return;
  btn.disabled=true;
  try{
    const r=await fetch('/api/gsm/skip-game',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({game_key:key}),
    });
    const j=await r.json();
    gsmSetMsg(r.ok?(j.message||`Cleared ${name}.`):(j.detail||j.message||'Failed'), r.ok?'ok':'bad');
    await loadGsmPanel();
  }catch(e){
    gsmSetMsg(String(e),'bad');
  }finally{
    btn.disabled=false;
  }
}
function bindGsmPanel(){
  if(!document.getElementById('gsm-fold')) return;
  document.getElementById('gsm-refresh-btn')?.addEventListener('click', ()=>loadGsmPanel({fromUser:true}));
  document.getElementById('gsm-submit-btn')?.addEventListener('click', ()=>gsmLogToTadoku());
  document.getElementById('gsm-select-all')?.addEventListener('change', gsmToggleSelectAll);
  document.getElementById('gsm-mark-btn')?.addEventListener('click', ()=>gsmMarkSynced());
  document.getElementById('gsm-pref-save')?.addEventListener('click', ()=>gsmSavePrefs('counting'));
  document.getElementById('gsm-auto-save')?.addEventListener('click', ()=>gsmSavePrefs('auto'));
  document.getElementById('gsm-pref-mode')?.addEventListener('click', (ev)=>{
    const btn=ev.target.closest('[data-mode]');
    if(!btn) return;
    document.querySelectorAll('#gsm-pref-mode [data-mode]').forEach(b=>b.classList.toggle('on', b===btn));
  });
  document.getElementById('gsm-pref-dedupe')?.addEventListener('change', gsmOnCountingToggle);
  document.getElementById('gsm-pref-strip-punct')?.addEventListener('change', gsmOnCountingToggle);
  document.getElementById('gsm-pref-collapse-blocks')?.addEventListener('change', gsmOnCountingToggle);
  document.getElementById('gsm-pref-require-jp')?.addEventListener('change', gsmOnCountingToggle);
  loadGsmPanel();
}

/* ── Audiobookshelf panel (rolling minutes) ─────────────────────────────── */
let _absPrefs={log_mode:'manual',min_submit_minutes:5,auto_submit_idle_minutes:30,auto_log_at_time_enabled:false,auto_log_at_hour:4,timezone:''};
let _absEntries=[];
let _absSelected=new Set();
let _absBusy=false;

function absSetBanner(html, kind){
  const el=document.getElementById('abs-banner');
  if(!el) return;
  el.innerHTML=html||'';
  el.className='gsm-banner abs-banner'+(kind?(' '+kind):'');
}
function absSetMsg(t, kind){
  const el=document.getElementById('abs-msg');
  if(!el) return;
  el.textContent=t||'';
  el.className='gsm-msg'+(kind?(' '+kind):'');
}
function absSetCount(n){
  const b=document.getElementById('abs-count');
  if(!b) return;
  const mins=Number(n)||0;
  b.textContent=mins>0?absFmtHM(mins):'0';
  b.className='count-badge'+(mins>0?'':' zero');
  if(typeof openFoldIfWork==='function') openFoldIfWork('abs-fold','immersion.abs.open', mins>0);
}
/** Minutes (number) → "2h 05m" / "45m" / "0m". */
function absFmtHM(mins){
  const m=Math.max(0, Number(mins)||0);
  const total=Math.round(m);
  const h=Math.floor(total/60);
  const mm=total%60;
  if(h<=0) return mm+'m';
  return h+'h '+String(mm).padStart(2,'0')+'m';
}
function absFmtTime(iso){
  if(!iso) return '—';
  const d=new Date(iso);
  if(Number.isNaN(d.getTime())) return '—';
  try{
    return d.toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
  }catch(e){
    return d.toISOString().slice(0,16).replace('T',' ');
  }
}
function absFmtRel(iso){
  if(!iso) return '';
  const d=new Date(iso);
  if(Number.isNaN(d.getTime())) return '';
  const sec=Math.max(0, Math.round((Date.now()-d.getTime())/1000));
  if(sec<60) return 'just now';
  return absFmtHM(sec/60)+' ago';
}
function absPaintTimeline(p){
  const box=document.getElementById('abs-timeline');
  if(!box) return;
  box.hidden=false;
  const last=document.getElementById('abs-last-logged');
  const nowEl=document.getElementById('abs-now');
  if(last) last.textContent=absFmtTime(p.last_logged_at);
  if(nowEl) nowEl.textContent=absFmtTime(p.server_now||new Date().toISOString());
  const n=(p.entries&&p.entries.length)||0;
  const lt=document.getElementById('abs-leg-total');
  if(lt) lt.textContent=n+' item'+(n===1?'':'s');
}
function absDurationBar(e){
  const lp=Math.max(0, Number(e.logged_pct)||0);
  const pp=Math.max(0, Number(e.pending_pct)||0);
  let ep=Math.max(0, Number(e.empty_pct)||0);
  const sum=lp+pp+ep;
  // Normalize tiny float drift so bar fills cleanly.
  let l=lp, p=pp, em=ep;
  if(sum>0 && Math.abs(sum-100)>0.05){
    l=lp*100/sum; p=pp*100/sum; em=ep*100/sum;
  }
  const durM=Number(e.duration_minutes);
  const logM=Number(e.logged_minutes)||0;
  const penM=Number(e.pending_minutes)||0;
  const hasDur=durM!=null && !Number.isNaN(durM) && durM>0;
  const tip=[
    absFmtHM(logM)+' already logged',
    absFmtHM(penM)+' to log',
    (hasDur ? absFmtHM(durM)+' title length' : '')
  ].filter(Boolean).join(' · ');
  const totalLine=hasDur
    ? `<div class="abs-dur-total"><span class="abs-dur-k">title</span> ${absFmtHM(durM)}</div>`
    : `<div class="abs-dur-total muted">title length unknown</div>`;
  return `<div class="abs-bar-stack" title="${escapeHtml(tip)}">
    <div class="abs-dur-bar" role="img" aria-label="${escapeHtml(tip)}">
      <span class="abs-seg logged" style="width:${l.toFixed(2)}%"></span>
      <span class="abs-seg pending" style="width:${p.toFixed(2)}%"></span>
      <span class="abs-seg empty" style="width:${em.toFixed(2)}%"></span>
    </div>
    ${totalLine}
  </div>`;
}
function absPaintPrefs(prefs){
  _absPrefs=prefs||_absPrefs;
  const mode=(_absPrefs.log_mode||'manual');
  document.querySelectorAll('#abs-pref-mode [data-mode]').forEach(b=>{
    b.classList.toggle('on', b.getAttribute('data-mode')===mode);
  });
  const minEl=document.getElementById('abs-pref-min');
  if(minEl) minEl.value=_absPrefs.min_submit_minutes??5;
  const idleEl=document.getElementById('abs-pref-idle');
  if(idleEl) idleEl.value=_absPrefs.auto_submit_idle_minutes??30;
  const dailyEl=document.getElementById('abs-pref-daily');
  if(dailyEl) dailyEl.checked=!!_absPrefs.auto_log_at_time_enabled;
  const hourEl=document.getElementById('abs-pref-hour');
  if(hourEl && _absPrefs.auto_log_at_hour!=null) hourEl.value=String(_absPrefs.auto_log_at_hour);
  const tz=document.getElementById('abs-tz-label');
  if(tz) tz.textContent=_absPrefs.timezone?('TZ: '+_absPrefs.timezone):'';
  const sub=document.getElementById('abs-sub');
  if(sub){
    const bits=[];
    bits.push(mode==='auto'?'auto':'manual');
    if(_absPrefs.auto_log_at_time_enabled) bits.push('daily');
    sub.textContent=bits.join(' · ')+' · minutes → Tadoku';
  }
}
function absSyncSelectionUI(){
  const boxes=[...document.querySelectorAll('#abs-preview-rows input[type=checkbox][data-key]')];
  const all=document.getElementById('abs-select-all');
  if(all){
    if(!boxes.length){ all.checked=false; all.indeterminate=false; }
    else{
      const n=boxes.filter(b=>b.checked).length;
      all.checked=n===boxes.length;
      all.indeterminate=n>0 && n<boxes.length;
    }
  }
  const btn=document.getElementById('abs-submit-btn');
  if(btn){
    const n=_absSelected.size;
    btn.disabled=_absBusy || n===0;
    btn.textContent=n>0?(`Log selected (${n})`):'Log selected';
  }
  const allBtn=document.getElementById('abs-log-all-btn');
  if(allBtn) allBtn.disabled=_absBusy || _absEntries.length===0;
  const hint=document.getElementById('abs-list-hint');
  if(hint){
    const n=_absSelected.size;
    hint.textContent=n? (n+' selected') : '';
  }
}
function absPaintRows(entries){
  _absEntries=entries||[];
  const tb=document.getElementById('abs-preview-rows');
  if(!tb) return;
  const keys=new Set(_absEntries.map(e=>e.key));
  // Keep prior picks if still present; never auto-check on load.
  _absSelected=new Set([..._absSelected].filter(k=>keys.has(k)));
  if(!_absEntries.length){
    tb.innerHTML='<tr class="abs-empty-row"><td colspan="6" class="abs-empty">No pending listening time</td></tr>';
    absSyncSelectionUI();
    return;
  }
  tb.innerHTML=_absEntries.map(e=>{
    const checked=_absSelected.has(e.key)?' checked':'';
    const readyCls=e.auto_ready?' is-auto':(e.meets_min?' is-min':' is-wait');
    const bm=e.bookmark_minutes!=null?`${absFmtHM(e.bookmark_minutes)} in`:'';
    const act=absFmtRel(e.last_activity_at);
    // Keep cover cell always — never remove node (collapses columns).
    const cover=e.cover_url
      ? `<img class="abs-cover" src="${escapeHtml(e.cover_url)}" alt="" loading="lazy" width="40" height="40" onerror="this.classList.add('abs-cover-ph');this.removeAttribute('src')"/>`
      : `<span class="abs-cover abs-cover-ph" aria-hidden="true"></span>`;
    const meta=[e.author, act?('active '+act):'', bm].filter(Boolean).map(escapeHtml).join(' · ');
    return `<tr class="abs-row${readyCls}" data-key="${escapeHtml(e.key)}">
      <td class="abs-td-check"><label class="abs-check"><input type="checkbox" data-key="${escapeHtml(e.key)}"${checked}/></label></td>
      <td class="abs-td-cover">${cover}</td>
      <td class="abs-td-main">
        <div class="abs-title">${escapeHtml(e.title||e.key)}</div>
        ${meta?`<div class="abs-meta">${meta}</div>`:''}
      </td>
      <td class="abs-td-bar">${absDurationBar(e)}</td>
      <td class="abs-td-mins" title="Time waiting to log to Tadoku">
        <div class="abs-mins-val">${absFmtHM(e.pending_minutes||0)}</div>
        <div class="abs-mins-k">to log</div>
      </td>
      <td class="abs-td-log"><button type="button" class="secondary abs-row-log" data-log-key="${escapeHtml(e.key)}">Log</button></td>
    </tr>`;
  }).join('');
  tb.querySelectorAll('input[data-key]').forEach(inp=>{
    inp.addEventListener('change',()=>{
      const k=inp.getAttribute('data-key');
      if(inp.checked) _absSelected.add(k); else _absSelected.delete(k);
      absSyncSelectionUI();
    });
  });
  tb.querySelectorAll('[data-log-key]').forEach(btn=>{
    btn.addEventListener('click',()=>{
      const k=btn.getAttribute('data-log-key');
      if(k) absLogToTadoku({keys:[k]});
    });
  });
  absSyncSelectionUI();
}
async function loadAbsPanel(opts){
  const fold=document.getElementById('abs-fold');
  if(!fold) return;
  const fromUser=!!(opts&&opts.fromUser);
  try{
    const st=await (await fetch('/api/abs/status',{cache:'no-store'})).json();
    absPaintPrefs(st.prefs||{});
    if(!st.enabled){
      absSetBanner('Audiobookshelf disabled in settings.yaml','warn');
      absSetCount(0);
      ['abs-timeline','abs-actions','abs-table-wrap'].forEach(id=>{ const el=document.getElementById(id); if(el) el.hidden=true; });
      return;
    }
    if(!st.configured){
      absSetBanner('Set <code>audiobookshelf.base_url</code> + <code>AUDIOBOOKSHELF_TOKEN</code> in .env','warn');
      absSetCount(0);
      return;
    }
    const p=await (await fetch('/api/abs/preview?refresh=true',{cache:'no-store'})).json();
    absPaintPrefs(p.prefs||st.prefs||{});
    const entries=p.entries||[];
    const total=Number(p.total_pending_minutes||0);
    absSetCount(total);
    absPaintRows(entries);
    absPaintTimeline({...p, entries, last_logged_at:p.last_logged_at||st.last_logged_at, server_now:p.server_now||st.server_now});
    const actions=document.getElementById('abs-actions');
    const table=document.getElementById('abs-table-wrap');
    if(actions) actions.hidden=false;
    if(table) table.hidden=false;
    const msg=p.message||(st.bootstrapped?'':'first poll will baseline history');
    absSetBanner(
      st.ok
        ? (`Connected${msg?(' · '+escapeHtml(String(msg))):''}`)
        : escapeHtml(String(st.message||'not ready')),
      st.ok?'ok':'warn'
    );
    if(fromUser) absSetMsg('Refreshed','ok');
  }catch(e){
    absSetBanner('ABS status failed: '+escapeHtml(e.message||String(e)),'bad');
  }
}
async function absLogToTadoku(opts){
  if(_absBusy) return;
  const mode=(opts&&opts.mode)||'selected';
  let body;
  if(mode==='all'){
    body={}; // omit keys → all pending
  }else if(opts&&opts.keys){
    body={keys:opts.keys};
  }else{
    const keys=[..._absSelected];
    if(!keys.length){ absSetMsg('Select at least one entry','warn'); return; }
    body={keys};
  }
  _absBusy=true;
  absSyncSelectionUI();
  absSetMsg(mode==='all'?'Logging all…':'Logging…');
  try{
    const r=await fetch('/api/abs/submit',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body),
    });
    const j=await r.json().catch(()=>({}));
    if(!r.ok) throw new Error(j.detail||j.message||r.statusText);
    absSetMsg(j.message||(`Logged ${j.created_count||0}`),'ok');
    if(mode==='all' || (opts&&opts.keys)) _absSelected=new Set();
    else _absSelected=new Set();
    if(typeof loadQueue==='function') loadQueue();
    await loadAbsPanel();
  }catch(e){
    absSetMsg(e.message||String(e),'bad');
  }finally{
    _absBusy=false;
    absSyncSelectionUI();
  }
}
async function absSavePrefs(){
  const modeBtn=document.querySelector('#abs-pref-mode [data-mode].on');
  const body={
    log_mode: modeBtn?modeBtn.getAttribute('data-mode'):'manual',
    min_submit_minutes: Number(document.getElementById('abs-pref-min')?.value||5),
    auto_submit_idle_minutes: Number(document.getElementById('abs-pref-idle')?.value||30),
    auto_log_at_time_enabled: !!document.getElementById('abs-pref-daily')?.checked,
    auto_log_at_hour: Number(document.getElementById('abs-pref-hour')?.value||4),
  };
  try{
    const r=await fetch('/api/abs/settings',{
      method:'PATCH',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body),
    });
    const j=await r.json();
    if(!r.ok) throw new Error(j.detail||r.statusText);
    absPaintPrefs(j);
    absSetMsg('Auto logging saved','ok');
  }catch(e){
    absSetMsg(e.message||String(e),'bad');
  }
}
function bindAbsPanel(){
  if(!document.getElementById('abs-fold')) return;
  document.getElementById('abs-refresh-btn')?.addEventListener('click',()=>loadAbsPanel({fromUser:true}));
  document.getElementById('abs-submit-btn')?.addEventListener('click',()=>absLogToTadoku({mode:'selected'}));
  document.getElementById('abs-log-all-btn')?.addEventListener('click',()=>absLogToTadoku({mode:'all'}));
  document.getElementById('abs-auto-save')?.addEventListener('click',()=>absSavePrefs());
  document.getElementById('abs-select-all')?.addEventListener('change',(ev)=>{
    const on=!!ev.target.checked;
    _absSelected=on?new Set(_absEntries.map(e=>e.key)):new Set();
    document.querySelectorAll('#abs-preview-rows input[data-key]').forEach(b=>{ b.checked=on; });
    absSyncSelectionUI();
  });
  document.getElementById('abs-pref-mode')?.addEventListener('click',(ev)=>{
    const btn=ev.target.closest('[data-mode]');
    if(!btn) return;
    document.querySelectorAll('#abs-pref-mode [data-mode]').forEach(b=>b.classList.toggle('on', b===btn));
  });
  loadAbsPanel();
}

/* Persist fold open/closed across refresh */
function bindFoldOpenPref(id, key){
  /* only <details> — page-mode #queue-fold is a <section> */
  const fold=document.getElementById(id);
  if(!fold || fold.tagName !== 'DETAILS') return;
  try{
    const pref=localStorage.getItem(key);
    if(pref==='0') fold.open=false;
    else if(pref==='1') fold.open=true;
  }catch(e){ /* ignore */ }
  fold.addEventListener('toggle',()=>{
    try{ localStorage.setItem(key, fold.open?'1':'0'); }catch(e){}
  });
}
bindFoldOpenPref('queue-fold', 'immersion.queue.open');
bindFoldOpenPref('recent-logs-fold', 'immersion.recentLogs.open');
bindFoldOpenPref('gsm-fold', 'immersion.gsm.open');
bindFoldOpenPref('abs-fold', 'immersion.abs.open');
bindFoldOpenPref('reading-fold', 'immersion.reading.open');
bindFoldOpenPref('quick-log-fold', 'immersion.quickLog.open');
"""
