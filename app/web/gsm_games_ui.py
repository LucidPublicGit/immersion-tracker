"""Game matching workbench using the tracker's existing shell and controls."""


def game_matches_page():
    from app.web.pages import _shell
    body=r'''
<main id="main" class="page page-wide" tabindex="-1">
  <div class="mast"><h1>Match GSM games</h1><div class="meta"><a href="/inbox">← Inbox</a></div></div>
  <p>Match names from your PCs to one shared game. Each PC can keep its own game IDs.</p>
  <div class="gm-toolbar"><label>Show <select id="gm-filter"><option value="review">Needs review</option><option value="all">All names</option><option value="saved">Saved matches</option></select></label>
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
  const sources=gmData.sources.filter(s=>filter==='all'||(filter==='saved'?s.explicit:
    !s.game_id||s.suggestions.some(g=>g.id!==s.game_id&&g.score>=.85)));
  if(!sources.length){const empty=document.createElement('p');empty.textContent=filter==='review'?'No unmatched names. Choose All names to adjust an existing association.':'No names in this view.';holder.append(empty);}
  for(const source of sources){
    const row=document.createElement('section');row.className='gm-row';
    row.innerHTML='<div class="gm-source"><strong></strong><span class="muted"></span></div><span class="gm-arrow" aria-hidden="true">→</span><div class="gm-target"><label>Shared game<select></select></label><div class="gm-actions"><button class="secondary gm-preview-button">Preview match</button><button class="secondary gm-remove">Remove saved match</button></div></div><div class="gm-preview" hidden></div>';
    row.querySelector('strong').textContent=source.name||'(unnamed source)';
    if(!source.name)row.querySelector('.gm-preview-button').disabled=true;
    row.querySelector('.gm-source span').textContent=source.lines.toLocaleString()+' lines · '+(source.explicit?'saved match':source.title?'linked to '+source.title:'not matched');
    const select=row.querySelector('select');select.append(new Option('Choose a game…',''));
    select.setAttribute('aria-label','Shared game for '+source.name);
    for(const game of gmData.games)select.append(new Option(game.title+' · '+(game.type||'unclassified')+' · '+(game.vndb_id||game.id.slice(0,8)),game.id));
    select.value=source.game_id||(source.suggestions[0]?.id||'');
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
    row.querySelector('.gm-preview-button').addEventListener('click',()=>{if(select.value)showPreview(select.value);else gmStatus('Choose the shared game first.');});
    const remove=row.querySelector('.gm-remove');remove.hidden=!source.explicit;remove.addEventListener('click',()=>showPreview(null));
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
    return _shell('Match GSM games · Immersion Tracker',body,active='queue',extra_css=css)
