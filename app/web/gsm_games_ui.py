"""Game matching workbench using the tracker's existing shell and controls."""


def game_matches_page(embedded=False):
    from app.web.pages import _shell
    body=r'''
<main id="main" class="page page-wide" tabindex="-1">
  <div class="mast"><h1>Match GSM games</h1><div class="meta"><a href="/inbox">← Inbox</a></div></div>
  <p>Stored game names provide automatic suggestions. Optional local AI can compare a source name with those same games; it does not call a provider API. Accept exact-name suggestions or preview another match. Saved aliases automatically apply to future uploads.</p>
  <p class="muted">Ignore a title to exclude it and future arrivals. Discard local history also removes this tracker’s copies; your PC history is unchanged.</p>
  <div class="gm-toolbar"><label>Show <select id="gm-filter"><option value="review">Needs review</option><option value="all">All names</option><option value="saved">Saved matches</option><option value="ignored">Ignored titles</option></select></label>
    <button class="secondary" id="gm-reload">Refresh</button><span id="gm-message" role="status" aria-live="polite"></span></div>
  <details class="help-fold"><summary>Add a game that is missing from the list</summary>
    <form id="gm-new-game" class="gm-toolbar"><label>Title <input name="title" required maxlength="200"></label>
      <label>Kind <select name="type"><option>Visual Novel</option><option>Game</option></select></label>
      <label>VNDB ID <input name="vndb_id" placeholder="v123 (optional)"></label><button>Add game</button></form></details>
  <div class="gm-head" aria-hidden="true"><span>Name recorded by GSM</span><span></span><span>Shared game</span></div>
  <div id="gm-rows" aria-busy="true"></div>
  <p class="muted">Preview a match before saving it. It groups shared tracker history and future uploads under the selected game.
    Review any unfinished GSM export before changing a match. Sentence IDs, text and original play times are preserved.</p>
</main>
<script>
let gmData={games:[],sources:[]};
const gmMessage=document.getElementById('gm-message');
async function gmRequest(path,body){
  const response=await fetch('/api/gsm/game-matches'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const value=await response.json();if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'Check the game title and selected match, then try again.');return value;
}
function gmStatus(text){gmMessage.textContent=text;}
function gmRender(){
  const holder=document.getElementById('gm-rows');holder.replaceChildren();
  const filter=document.getElementById('gm-filter').value;
  const sources=gmData.sources.filter(s=>filter==='all'||(filter==='ignored'?s.ignored:!s.ignored&&(filter==='saved'?s.explicit:
    !s.game_id||s.suggestions.some(g=>g.id!==s.game_id&&g.score>=.85))));
  if(!sources.length){const empty=document.createElement('p');empty.textContent=filter==='review'?'No unmatched names. Choose All names to adjust an existing association.':'No names in this view.';holder.append(empty);}
  for(const source of sources){
    const row=document.createElement('section');row.className='gm-row';
    row.innerHTML='<div class="gm-source"><strong></strong><span class="muted"></span></div><span class="gm-arrow" aria-hidden="true">→</span><div class="gm-target"><label>Shared game<select></select></label><div class="gm-actions"><button class="secondary gm-preview-button">Preview match</button><button class="primary gm-accept" hidden>Accept suggestion</button><button class="secondary gm-ai">Compare with local AI</button><button class="secondary gm-remove">Remove saved match</button><button class="secondary gm-ignore">Ignore title</button><button class="danger gm-discard">Discard local history</button></div></div><div class="gm-preview" hidden></div>';
    row.querySelector('strong').textContent=source.name||'(unnamed source)';
    if(!source.name||source.ignored)row.querySelector('.gm-preview-button').disabled=true;
    row.querySelector('.gm-source span').textContent=source.lines.toLocaleString()+' lines · '+(source.ignored?'ignored':source.explicit?'saved match':source.title?'linked to '+source.title:'not matched');
    const origin=document.createElement('small');origin.className='muted';origin.textContent=source.origin||'Shared GSM history';row.querySelector('.gm-source').append(origin);
    const select=row.querySelector('select');select.append(new Option('Choose a game…',''));
    select.setAttribute('aria-label','Shared game for '+source.name);
    for(const game of gmData.games)select.append(new Option(game.title+' · '+(game.type||'unclassified')+' · '+(game.vndb_id||game.id.slice(0,8)),game.id));
    select.value=source.game_id||(source.suggestions[0]?.id||'');select.disabled=source.ignored;
    const preview=row.querySelector('.gm-preview');
    select.addEventListener('change',()=>{preview.hidden=true;preview.replaceChildren();});
    async function showPreview(gameId){
      try{
        const value=await gmRequest('/preview',{name:source.name,game_id:gameId});
        preview.replaceChildren();preview.hidden=false;
        const title=document.createElement('strong');title.textContent=source.name+' → '+value.target;preview.append(title);
        const counts=document.createElement('p');counts.textContent=value.changed_lines.toLocaleString()+' of '+value.lines.toLocaleString()+' lines will change game association.'+(value.already_skipped?' Previously skipped lines stay excluded.':'');preview.append(counts);
        for(const sample of value.samples){const line=document.createElement('blockquote');line.textContent=sample;preview.append(line);}
        if(value.export_pending){const warning=document.createElement('p');warning.textContent='Finish or skip the pending GSM export first, then preview this match again.';preview.append(warning);return;}
        const apply=document.createElement('button');apply.textContent=gameId?'Save match':'Remove match';
        apply.addEventListener('click',async()=>{apply.disabled=true;try{await gmRequest('/apply',{name:source.name,game_id:gameId,revision:value.revision});await gmLoad();gmStatus(gameId?'Match saved for existing history and future syncs.':'Original game associations restored.');}catch(error){gmStatus(error.message);apply.disabled=false;}});preview.append(apply);
      }catch(error){gmStatus(error.message);}
    }
    async function sourcePolicy(action){
      try{
        const value=await gmRequest('/source-preview',{name:source.name,action});
        if(value.export_pending){gmStatus('Finish or skip the pending GSM export first.');return;}
        const name=source.name||'(unnamed source)';
        const message=action==='discard'?`Discard ${value.lines} local history lines for “${name}” and ignore future arrivals? Original PC history is unchanged.`:
          action==='ignore'?`Ignore “${name}”? Its ${value.lines} local lines will be excluded and future arrivals skipped.`:
          `Enable future arrivals for “${name}” again? Discarded history will not be restored.`;
        if(!confirm(message))return;
        await gmRequest('/source-policy',{name:source.name,action,revision:value.revision});
        await gmLoad();gmStatus(action==='restore'?'Source enabled again.':action==='discard'?'Local history discarded; future arrivals ignored.':'Title ignored; existing local history retained.');
      }catch(error){gmStatus(error.message);}
    }
    const ignore=row.querySelector('.gm-ignore');ignore.textContent=source.ignored?'Stop ignoring':'Ignore title';ignore.onclick=()=>sourcePolicy(source.ignored?'restore':'ignore');
    const discard=row.querySelector('.gm-discard');discard.hidden=!source.lines;discard.onclick=()=>sourcePolicy('discard');
    const exact=source.suggestions.filter(s=>s.exact===true);
    const accept=row.querySelector('.gm-accept');accept.hidden=source.ignored||source.explicit||exact.length!==1;
    accept.onclick=async()=>{
      accept.disabled=true;
      try{
        const body={name:source.name,game_id:exact[0].id};
        await gmRequest('/accept-suggestion',body);await gmLoad();gmStatus('Exact-name match saved for existing history and future uploads.');
      }catch(error){gmStatus(error.message);accept.disabled=false;}
    };
    if(exact.length===1&&!source.ignored){const hint=document.createElement('p');hint.className='muted';hint.textContent='Suggested: '+exact[0].title+' (matching stored game name)';row.querySelector('.gm-source').append(hint);}
    const ai=row.querySelector('.gm-ai');ai.disabled=!source.name||source.ignored;
    ai.onclick=async()=>{
      ai.disabled=true;gmStatus('Comparing the source name with stored games locally…');
      try{
        const value=await gmRequest('/suggestions',{name:source.name});
        if(!value.available){gmStatus('Local comparison unavailable: '+value.reason);return;}
        const candidates=value.suggestions||[];
        if(!candidates.length){gmStatus('Local model has no strong suggestion. Choose a game manually.');return;}
        preview.replaceChildren();preview.hidden=false;
        const note=document.createElement('p');note.textContent='Local AI suggestions from stored games. Review a match before saving.';preview.append(note);
        for(const candidate of candidates){const button=document.createElement('button');button.className='secondary';button.textContent='Review '+candidate.display_title;button.onclick=()=>{select.value=candidate.series_key;showPreview(candidate.series_key);};preview.append(button);}
        gmStatus('Local comparison complete; no game association was changed.');
      }catch(error){gmStatus(error.message);}finally{ai.disabled=false;}
    };
    row.querySelector('.gm-preview-button').addEventListener('click',()=>{if(select.value)showPreview(select.value);else gmStatus('Choose the shared game first.');});
    const remove=row.querySelector('.gm-remove');remove.hidden=!source.explicit||source.ignored;remove.addEventListener('click',()=>showPreview(null));
    holder.append(row);
  }
  holder.setAttribute('aria-busy','false');
}
async function gmLoad(){try{gmData=await gmRequest('');gmRender();gmStatus(gmData.sources.length+' recorded names · '+gmData.games.length+' shared games');}catch(error){gmStatus(error.message);document.getElementById('gm-rows').setAttribute('aria-busy','false');}}
document.getElementById('gm-filter').addEventListener('change',gmRender);
document.getElementById('gm-reload').addEventListener('click',gmLoad);
document.getElementById('gm-new-game').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;const fields=new FormData(form);try{await gmRequest('/game',{title:fields.get('title'),type:fields.get('type'),vndb_id:fields.get('vndb_id')||null});form.reset();await gmLoad();gmStatus('Game added. Choose it next to the recorded name and preview the match.');}catch(error){gmStatus(error.message);}});
gmLoad();
</script>'''
    css='''
    .gm-toolbar{display:flex;flex-wrap:wrap;align-items:end;gap:1rem;margin:1.2rem 0}
    .gm-toolbar label,.gm-target label{display:grid;gap:.4rem}
    .gm-head,.gm-row{display:grid;grid-template-columns:minmax(0,1fr) 2rem minmax(0,1.5fr);gap:1rem}
    .gm-head{font-size:.8rem;padding:1rem 0;color:var(--muted)}
    .gm-row{padding:1.3rem 0;border-top:1px solid var(--line)}
    .gm-source{display:grid;align-content:start;gap:.5rem;overflow-wrap:anywhere}
    .gm-arrow{padding-top:1.4rem;font-size:1.4rem}.gm-target select{max-width:100%;width:100%}
    .gm-actions{display:flex;gap:.6rem;flex-wrap:wrap;margin-top:.6rem}
    .gm-preview{grid-column:1/-1;padding:1rem;border-left:3px solid var(--accent);background:var(--panel)}
    .gm-preview[hidden]{display:none}.gm-preview blockquote{margin:.7rem 0;padding-left:1rem;line-height:1.6;overflow-wrap:anywhere}
    @media(max-width:700px){.gm-head{display:none}.gm-row{grid-template-columns:minmax(0,1fr)}.gm-arrow{padding:0}.gm-preview{grid-column:1}}
    '''
    if embedded:css+='header.topbar,.skip-link,#fab-log,.mast .meta{display:none!important}body{padding:0}main.page{margin:0}'
    return _shell('Match GSM games · Immersion Tracker',body,active='queue',extra_css=css)
