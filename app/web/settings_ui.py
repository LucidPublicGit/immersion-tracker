"""Focused app settings and transparent local-model activity."""
SETTINGS_CSS = """
.ai-settings{max-width:900px;margin:auto}.ai-settings section{border:1px solid var(--ink);background:var(--panel);padding:1rem;margin:1rem 0}
.ai-settings label{display:block;margin:.65rem 0}.ai-settings input[type=text]{width:100%;box-sizing:border-box}
.ai-settings .switch{display:flex;align-items:center;gap:.65rem}.ai-settings .switch input{width:18px;min-width:18px}
.ai-settings .hint{font-size:.9rem;color:var(--muted);margin:.3rem 0 1rem}.ai-settings .activity{list-style:none;padding:0;max-height:350px;overflow:auto}
.ai-settings .activity li{padding:.55rem 0;border-bottom:1px solid var(--ink);overflow-wrap:anywhere}
.ai-settings .activity small{display:block;font-family:var(--mono)}.ai-settings #ai-worker-state{font-weight:600}
"""
SETTINGS_BODY = """
<main id="main" class="page ai-settings" tabindex="-1">
<h1>Settings</h1>
<section aria-labelledby="local-ai-heading">
<h2 id="local-ai-heading">Local AI</h2>
<p>Title suggestions use two separate tools. The local model is an embedding encoder, not a chat agent.</p>
<ol>
<li><b>Provider lookup:</b> the app sends a search title to AniList (anime/manga) or Jiten (other supported media), then compares provider titles and aliases. Automatic queue suggestions use this step.</li>
<li><b>Optional local comparison:</b> when you choose “Use local AI suggestions” or “Find similar titles,” the installed model compares the query with known candidates. It does not browse the web, call those APIs or invent a title.</li>
<li><b>GSM matching:</b> source names are compared with stored game names locally. Its optional AI comparison uses those stored games, without provider API calls. Accepted aliases apply to future uploads.</li>
<li><b>Your acceptance:</b> accepting a suggestion saves a source-title mapping for future exports. The original name stays internal. Already-sent Tadoku logs stay unchanged.</li>
</ol>
<form id="ai-settings-form">
<label class="switch"><input type="checkbox" name="local_ai_enabled"> Enable local AI comparison</label>
<label class="switch"><input type="checkbox" name="web_enabled"> Enable title provider lookup</label>
<p class="hint">Provider lookup sends the search title and medium to AniList or Jiten.</p>
<label class="switch"><input type="checkbox" name="auto_suggest_enabled"> Automatically suggest titles on the queue</label>
<p class="hint">Up to eight distinct titles per page session. This uses provider APIs, without loading the local model.</p>
<fieldset id="ai-model-fields">
<legend>Installed embedding model</legend>
<label>Model folder on the native worker host <input type="text" name="model_path" maxlength="1024"></label>
<p class="hint">Use an already-installed Sentence Transformers compatible embedding model. No automatic downloads or chat-model endpoint.</p>
<label>Minimum match similarity <input type="number" name="minimum_similarity" min="-1" max="1" step="0.01"></label>
<p class="hint">Current E5 default: 0.90. Scores vary by model; higher thresholds return fewer suggestions. A score is not identity confidence.</p>
<details><summary>Model-specific prefixes</summary>
<label>Query prefix <input type="text" name="query_prefix" maxlength="100"></label>
<label>Title prefix <input type="text" name="document_prefix" maxlength="100"></label>
<p class="hint">E5 uses “query: ” and “passage: ”. Other encoders may need empty or different prefixes.</p>
</details>
</fieldset>
<p class="hint" id="ai-model-help"></p>
<button type="submit" class="primary" disabled>Save settings</button>
<p id="ai-settings-message" role="status"></p>
</form>
</section>
<section aria-labelledby="ai-activity-heading">
<h2 id="ai-activity-heading">Recent activity</h2>
<p id="ai-worker-state" role="status">Checking native worker…</p>
<p class="hint">The model runs only for requested comparisons and unloads afterward. CPU, memory and foreground-work guards remain fixed.</p>
<button type="button" class="secondary" id="ai-refresh">Refresh activity</button>
<label class="switch"><input type="checkbox" id="ai-live" checked> Live updates</label>
<p class="hint" id="ai-activity-scope"></p>
<ul class="activity" id="ai-activity" aria-label="Recent provider and local model work"></ul>
</section>
</main>
"""
SETTINGS_JS = r"""
const aiForm=document.getElementById('ai-settings-form');
let aiState=null,aiFormDigest=null,aiLoading=false;
function fillAISettings(data){
  for(const [key,value] of Object.entries(data.options))aiForm.elements[key].checked=value;
  const worker=data.worker;aiFormDigest=worker.config_digest;
  document.getElementById('ai-model-fields').disabled=!worker.online||!worker.settings_supported||!worker.config;
  if(worker.config)for(const [key,value] of Object.entries(worker.config))if(aiForm.elements[key])aiForm.elements[key].value=value;
  document.getElementById('ai-model-help').textContent=worker.online&&worker.settings_supported?'Settings apply without an app restart; saving does not start a model job.':'Native worker offline or settings unavailable. You can still save app switches; model settings require the native worker.';
  aiForm.querySelector('button[type=submit]').disabled=false;
}
async function refreshAISettings(fill=false){
  if(aiLoading)return;aiLoading=true;
  try{
    const r=await fetch('/api/settings/local-ai');if(!r.ok)throw new Error('Could not load local AI settings');
    const data=await r.json();aiState=data;
    if(fill)fillAISettings(data);
    const w=data.worker;
    document.getElementById('ai-worker-state').textContent=!w.online?'Native worker offline':w.busy?'Native worker: comparing candidates':!w.enabled?'Native worker disabled':'Native worker idle — models unload after each job';
    document.getElementById('ai-activity-scope').textContent=data.activity_scope;
    const events=[...data.activity];
    for(const e of w.activity||[]){
      let text=e.available?`Completed local model job: ${e.suggestions} suggestions.`:`Local model job declined or stopped: ${e.reason||'unavailable'}.`;
      if(e.seconds!=null)text+=` ${Number(e.seconds).toFixed(1)}s.`;
      if(e.peak_rss_gib!=null)text+=` Peak memory ${Number(e.peak_rss_gib).toFixed(2)} GiB.`;
      events.push({at:e.at,kind:'native worker',message:text});
    }
    events.sort((a,b)=>b.at-a.at);
    const list=document.getElementById('ai-activity');list.replaceChildren();
    if(!events.length){const li=document.createElement('li');li.textContent='No work recorded yet. Queue title lookups and requested model comparisons will appear here.';list.appendChild(li);}
    for(const event of events.slice(0,30)){
      const li=document.createElement('li'),meta=document.createElement('small'),message=document.createElement('span');
      meta.textContent=`${new Date(event.at*1000).toLocaleTimeString()} · ${event.kind}`;
      message.textContent=event.message;li.append(meta,message);list.appendChild(li);
    }
  }catch(err){document.getElementById('ai-settings-message').textContent=err.message;}
  finally{aiLoading=false;}
}
aiForm.onsubmit=async event=>{
  event.preventDefault();const button=aiForm.querySelector('button[type=submit]');button.disabled=true;
  const message=document.getElementById('ai-settings-message');message.textContent='Saving…';
  const body={};for(const key of ['local_ai_enabled','web_enabled','auto_suggest_enabled'])body[key]=aiForm.elements[key].checked;
  if(!document.getElementById('ai-model-fields').disabled){
    body.worker_config={};for(const key of ['model_path','query_prefix','document_prefix'])body.worker_config[key]=aiForm.elements[key].value;
    body.worker_config.minimum_similarity=Number(aiForm.elements.minimum_similarity.value);
    body.expected_worker_config=aiFormDigest;
  }
  try{
    const r=await fetch('/api/settings/local-ai',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const value=await r.json();if(!r.ok)throw new Error(typeof value.detail==='string'?value.detail:'Settings were rejected. Check the fields.');
    aiState=value;fillAISettings(value);message.textContent='Settings saved. Refresh an open queue tab to apply its automatic-suggestion option.';
    await refreshAISettings(false);
  }catch(err){message.textContent=err.message;}
  finally{button.disabled=false;}
};
document.getElementById('ai-refresh').onclick=()=>refreshAISettings(false);
setInterval(()=>{if(!document.hidden&&document.getElementById('ai-live').checked)refreshAISettings(false);},4000);
refreshAISettings(true);
"""
