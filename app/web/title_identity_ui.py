"""Shared manual work identification for queue and logs."""

TITLE_IDENTITY_JS = r"""
const TITLE_IDENTITY_TYPES=['manga','anime','show','drama','movie','book','novel','nonfiction','web_novel','visual_novel','vn','game'];
const titlePreviewCache=new Map();
const titleAutoSeen=new Set();
const titleAcceptBusy=new Set();
let titleAutoRunning=false;
const titleAutoPending=new Map();
function titlePreviewKey(entry){return JSON.stringify([entry.source,entry.content_type,entry.title]);}
function cachedTitlePreview(entry){
  const saved=titlePreviewCache.get(titlePreviewKey(entry));
  return saved&&Date.now()-saved.at<300000?saved.data:null;
}
function paintTitlePreview(entry){
  const data=cachedTitlePreview(entry);if(!data)return;
  const exact=(data.candidates||[]).filter(c=>c.text_match);
  const text=exact.length===1?`Suggested: ${exact[0].title}`:
    data.candidates?.length?`${data.candidates.length} provider candidates to review`:'No title suggestion available';
  for(const slot of document.querySelectorAll('[data-title-preview-key]')){
    if(slot.dataset.titlePreviewKey===titlePreviewKey(entry)){
      slot.textContent=text;
      const existing=slot.parentElement.querySelector('[data-title-accept-key]');
      if(existing)existing.remove();
      if(data.available&&data.token&&exact.length===1){
        const accept=document.createElement('button');
        accept.type='button';accept.className='primary';accept.textContent='Accept suggestion';
        accept.dataset.titleAcceptKey=titlePreviewKey(entry);
        accept.title=`Save “${exact[0].title}” for unsent logs and future imports with this source title. Already sent logs stay unchanged.`;
        accept.disabled=titleAcceptBusy.has(titlePreviewKey(entry));
        accept.onclick=()=>acceptTitleSuggestion(entry,data,exact[0]);
        slot.after(accept);
      }
      const button=slot.parentElement.querySelector('button[onclick]');
      if(button&&data.candidates?.length)button.textContent=exact.length===1?'Review suggestion':'Review title candidates';
    }
  }
}
async function acceptTitleSuggestion(entry,preview,candidate){
  const key=titlePreviewKey(entry);
  if(titleAcceptBusy.has(key))return;
  const slots=()=>[...document.querySelectorAll('[data-title-preview-key]')].filter(s=>s.dataset.titlePreviewKey===key);
  const current=cachedTitlePreview(entry);
  if(!current||current.token!==preview.token){
    for(const slot of slots()){
      slot.textContent='Suggestion expired or changed. Identify the title again.';
      slot.parentElement.querySelector('[data-title-accept-key]')?.remove();
    }
    return;
  }
  titleAcceptBusy.add(key);
  for(const button of document.querySelectorAll('[data-title-accept-key]'))if(button.dataset.titleAcceptKey===key)button.disabled=true;
  try{
    const r=await fetch(`/api/logs/${entry.id}/title-identity`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:preview.token,provider_id:candidate.provider_id})});
    const saved=await r.json();if(!r.ok)throw new Error(saved.detail||'Could not accept suggestion');
    titlePreviewCache.delete(key);
    for(const slot of slots())slot.textContent=`Accepted: ${saved.title_identity.title}`;
    refreshTitleIdentityViews();
  }catch(err){
    for(const slot of slots())slot.textContent=`Could not accept: ${err.message}`;
  }finally{
    titleAcceptBusy.delete(key);
    for(const button of document.querySelectorAll('[data-title-accept-key]'))if(button.dataset.titleAcceptKey===key)button.disabled=false;
  }
}
async function autoSuggestQueueTitles(entries){
  for(const entry of entries){
    paintTitlePreview(entry);
    if(!entry.title_identity&&TITLE_IDENTITY_TYPES.includes(entry.content_type))titleAutoPending.set(titlePreviewKey(entry),entry);
  }
  if(titleAutoRunning)return;
  titleAutoRunning=true;
  try{
    const r=await fetch('/api/title-identification/settings');if(!r.ok)return;
    const settings=await r.json();if(!settings.auto_suggest_enabled)return;
    for(const entry of titleAutoPending.values()){
      if(entry.title_identity||!settings.supported_types.includes(entry.content_type))continue;
      const key=titlePreviewKey(entry);
      titleAutoPending.delete(key);
      if(titleAutoSeen.has(key))continue;
      if(titleAutoSeen.size>=8){titleAutoPending.clear();break;}
      titleAutoSeen.add(key);
      try{
        const r=await fetch(`/api/logs/${entry.id}/title-preview`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({use_local_ai:false})});
        if(!r.ok)continue;
        const data=await r.json();titlePreviewCache.set(key,{at:Date.now(),data});paintTitlePreview(entry);
      }catch(err){}
    }
  }finally{titleAutoRunning=false;}
}
function titleIdentityActionsHtml(entry){
  if(!TITLE_IDENTITY_TYPES.includes(entry.content_type))return '';
  return `<div class="title-identity-actions" style="display:flex;flex-wrap:wrap;gap:0.35rem;margin-top:0.35rem">
    ${!entry.title_identity?`<span class="muted" data-title-preview-key="${escapeHtml(titlePreviewKey(entry))}" style="flex-basis:100%"></span>`:''}
    <button type="button" class="secondary" onclick="identifyTitle(${entry.id})">${entry.title_identity?'Change title mapping':'Identify title'}</button>
    ${entry.title_identity?`<button type="button" class="secondary" onclick="clearTitleIdentity(${entry.id})">Remove mapping</button>`:''}
  </div>`;
}
function refreshTitleIdentityViews(){
  if(typeof loadQueue==='function') loadQueue();
  if(typeof loadRecentLogs==='function') loadRecentLogs();
  if(typeof loadLogs==='function') loadLogs();
}
async function clearTitleIdentity(id){
  if(!confirm('Remove the saved title mapping for this source title? Future unsent logs will use the original title again. Already sent Tadoku logs stay unchanged.')) return;
  const r=await fetch(`/api/logs/${id}/title-identity`,{method:'DELETE'});
  if(!r.ok){alert('Could not remove mapping.');return;}
  refreshTitleIdentityViews();
}
async function identifyTitle(id){
  let settings, entry;
  try{
    const sr=await fetch('/api/title-identification/settings');if(!sr.ok)throw new Error('Settings unavailable');
    settings=await sr.json();
    const er=await fetch(`/api/logs/${id}`);if(!er.ok)throw new Error('Log unavailable');
    entry=await er.json();
  }catch(err){alert(err.message);return;}
  if(document.querySelector('dialog[data-title-identification]'))return;
  if(!settings.web_enabled){alert('Title provider lookup is disabled. Enable title provider lookup in More → Settings. Saved mappings still work.');return;}
  const provider=settings.provider_by_type?.[entry.content_type]==='jiten'?'Jiten':'AniList';
  const dialog=document.createElement('dialog');
  dialog.dataset.titleIdentification='true';
  dialog.style.cssText='max-width:700px;width:90%;max-height:85vh;overflow:auto;';
  dialog.innerHTML=`<h2>Identify title</h2><p>Original: ${escapeHtml(entry.title)}</p>
    <p>Search ${provider} for the same medium. Confirm the work, checking its full title and staff. The exact Japanese title will be used for unsent Tadoku logs with this source title; the original stays internal. Already sent logs stay unchanged.</p>
    <form><label>Search title <input name="query" maxlength="160" placeholder="Leave blank to search the base title" style="width:95%" /></label>
    <p><label>${provider} link or ID (optional) <input name="provider_reference" maxlength="160" placeholder="Use a known work if search misses it" style="width:95%" /></label></p>
    <p><label><input type="checkbox" name="ai" ${settings.local_ai_enabled?'':'disabled'} /> Use local AI suggestions ${settings.local_ai_enabled?'':'(disabled)'}</label></p>
    <button type="submit">Search</button> <button type="button" class="close-title">Close</button></form>
    <p class="title-status" role="status"></p><div class="title-results"></div>`;
  document.body.appendChild(dialog);dialog.showModal();
  const form=dialog.querySelector('form'), status=dialog.querySelector('.title-status'), results=dialog.querySelector('.title-results');
  let controller, generation=0;
  dialog.querySelector('.close-title').onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>{generation++;if(controller)controller.abort();dialog.remove();});
  const invalidate=()=>{
    generation++;if(controller)controller.abort();results.replaceChildren();
    status.textContent='Search again with the updated options.';
    form.querySelector('button[type="submit"]').disabled=false;
  };
  form.elements.query.addEventListener('input',invalidate);
  form.elements.ai.addEventListener('change',invalidate);
  form.elements.provider_reference.addEventListener('input',invalidate);
  const showPreview=data=>{
    results.replaceChildren();
      const aiMessage=data.ai_reason==='not_requested'?'Local AI was not requested.':
        data.suggested_ids.length?'Local AI marked suggestions; check the evidence before choosing.':
        `Local AI has no suggestion${data.ai_reason?` (${data.ai_reason})`:''}. You can still review provider results.`;
      const lookup=data.lookup_mode==='provider_id'?`${provider} ID ${data.provider_id}`:`“${data.query}”`;
      status.textContent=data.candidates.length?`${data.candidates.length} candidate(s) for ${lookup}. ${aiMessage}`:
        `No matching ${entry.content_type} work with a Japanese title was found. Try a different title or paste a known ${provider} link or ID.`;
      for(const c of data.candidates){
        const row=document.createElement('div');row.style.cssText='padding:12px 0;border-bottom:1px solid #888';
        row.innerHTML=`<strong>${escapeHtml(c.title)}</strong> ${data.suggested_ids.includes(c.provider_id)?' · AI suggestion':''}
          ${c.text_match?`<div>${c.text_match==='native_exact'?'Search exactly matches the Japanese title.':c.text_match==='alias_normalized'?'Search matches a provider alias after spacing and punctuation are normalized.':'Search exactly matches a provider alias.'}</div>`:''}
          ${c.shared_title_prefix?'<p>Another candidate shares this title prefix. Check the full title and publication; shared names or staff do not confirm the same work.</p>':''}
          <div>${escapeHtml(c.aliases.join(' / '))}</div><div>${escapeHtml(c.format)} · ${escapeHtml(c.staff.filter(Boolean).join(' / '))}</div>
          <a href="${escapeHtml(c.provider_url)}" target="_blank" rel="noopener">Check ${escapeHtml(c.provider_label||provider)} ${escapeHtml(c.provider_id)}</a> <button type="button">Use this exact title</button>`;
        row.querySelector('button').onclick=async()=>{
          for(const b of results.querySelectorAll('button'))b.disabled=true;
          try{
            const saved=await fetch(`/api/logs/${id}/title-identity`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:data.token,provider_id:c.provider_id})});
            const value=await saved.json();if(!saved.ok)throw new Error(value.detail||'Save failed');
            dialog.close();refreshTitleIdentityViews();
          }catch(err){status.textContent=err.message;for(const b of results.querySelectorAll('button'))b.disabled=false;}
        };
        results.appendChild(row);
      }
  };
  form.onsubmit=async ev=>{
    ev.preventDefault();if(controller)controller.abort();controller=new AbortController();const current=++generation;
    status.textContent='Searching…';results.replaceChildren();form.querySelector('button[type="submit"]').disabled=true;
    try{
      const r=await fetch(`/api/logs/${id}/title-preview`,{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,
        body:JSON.stringify({query:form.elements.query.value,provider_reference:form.elements.provider_reference.value,use_local_ai:form.elements.ai.checked})});
      const data=await r.json();if(current!==generation||!dialog.isConnected)return;
      if(!r.ok)throw new Error(data.detail||'Search failed');
      if(!data.available){status.textContent=`Lookup unavailable: ${data.reason}. Your logs are unchanged.`;return;}
      titlePreviewCache.set(titlePreviewKey(entry),{at:Date.now(),data});
      showPreview(data);
    }catch(err){if(current===generation&&err.name!=='AbortError')status.textContent=err.message;}
    finally{if(current===generation&&dialog.isConnected)form.querySelector('button[type="submit"]').disabled=false;}
  };
  const saved=cachedTitlePreview(entry);
  if(saved?.available){form.elements.query.value=saved.query;showPreview(saved);}
  else if(settings.auto_suggest_enabled)form.requestSubmit();
}
"""
