'use strict';
const $=s=>document.querySelector(s);
const icons={
 activity:'<path d="M2 12h4l3-8 6 16 3-8h4"/>',
 history:'<path d="M3 11a9 9 0 1 1 2 7M3 3v8h8"/><path d="M12 7v5l3 2"/>',
 database:'<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
 message:'<path d="M21 15a3 3 0 0 1-3 3H8l-5 3V6a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3zM7 8h10M7 12h7"/>',
 bell:'<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
 spark:'<path d="m12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3z"/>',
 play:'<path d="m8 4 12 8-12 8z"/>', pause:'<path d="M8 4v16M16 4v16"/>',
 reset:'<path d="M3 11a9 9 0 1 1 2 7M3 3v8h8"/>',step:'<path d="m4 4 11 8-11 8zM20 4v16"/>',
 arrow:'<path d="M4 12h16m-6-6 6 6-6 6"/>', chevron:'<path d="m9 5 7 7-7 7"/>',
 check:'<path d="m5 12 4 4L20 5"/><path d="M20 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9"/>',
 close:'<path d="m6 6 12 12M6 18 18 6"/>',download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
 refresh:'<path d="M3 10a9 9 0 0 1 15-6l3 3M21 2v5h-5M21 14A9 9 0 0 1 6 20l-3-3M3 22v-5h5"/>',
 bolt:'<path d="m13 2-9 12h7l-1 8 10-12h-7z"/>',
 chart:'<path d="M3 3v18h18M6 15l4-6 5 3 6-8"/>',line:'<path d="M3 20 9 4h6l6 16M6 12h12M3 8h18M12 4v16"/>',
 shield:'<path d="m12 2 9 4v6c0 6-9 10-9 10S3 18 3 12V6zM8 12l3 3 5-6"/>'
};
const icon=name=>`<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${icons[name]||icons.activity}</svg>`;
function fillIcons(root=document){root.querySelectorAll('[data-icon]').forEach(el=>el.innerHTML=icon(el.dataset.icon));}
fillIcons();
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(x,dec=0)=>Number(x).toLocaleString('en-US',{maximumFractionDigits:dec,minimumFractionDigits:dec});
const time=s=>new Date(s).toLocaleTimeString('en-US',{timeZone:'America/New_York',hour:'numeric',minute:'2-digit'});
const ruleIcons={load_drop:'activity',reserves:'shield',congestion:'chart',forecast_gap:'chart'};
let state=null, tab='live', selectedRule=null, selectedAlert=null, toastTimer, connected=false;
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,3500);}
async function post(path,data){
 const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
 const body=await response.json();if(!response.ok)throw new Error(body.error||'Request failed');return body;
}
async function act(action,value){try{const s=await post('/api/control',{action,value});render(s);}catch(e){toast(e.message);}}
function setTab(next){tab=next;document.querySelectorAll('.nav-button').forEach(b=>b.classList.toggle('selected',b.dataset.tab===next));['live','data'].forEach(x=>$(`#${x}-view`).hidden=x!==next);const titles={live:['Small signals. Clear answers.','Four conditions, checked against incoming readings every five minutes.'],data:['Nothing behind the curtain.','Inspect the dataset, saved queries and the assumptions they use.']};$('#page-title').textContent=titles[next][0];$('#page-description').textContent=titles[next][1];}
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>setTab(b.dataset.tab)));
$('#play').onclick=()=>act(state?.playing?'pause':'play');
$('#retry').onclick=()=>act('retry');$('#step').onclick=()=>act('step');$('#reset').onclick=()=>act('reset');$('#jump').onclick=()=>act('jump');
$('#speed').onchange=e=>act('speed',Number(e.target.value));
$('#schema-check').onclick=async()=>{try{const r=await post('/api/schema',{});toast(r.unchanged?'Tables and columns are unchanged. Saved queries are still valid.':'Database changes found. Replay paused.');}catch(e){toast(e.message);}};
$('#scenario-button').onclick=()=>$('#scenario-dialog').showModal();$('#close-scenarios').onclick=()=>$('#scenario-dialog').close();$('#close-detail').onclick=()=>{$('#detail-dialog').close();selectedRule=null;selectedAlert=null;};
for(const dialog of document.querySelectorAll('dialog'))dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}});
function metric(label,value,unit,note,ic,warn=false){return `<div class="metric"><div class="metric-top"><span>${label}</span>${icon(ic)}</div><div class="metric-value">${value}<small>${unit}</small></div><div class="metric-note ${warn?'warn':''}">${note}</div></div>`;}
function render(s){
 if(state && s.version < state.version) return;
 state=s;
 const live=s.mode==='live',busy=s.phase!=='ready';
 $('#model-usage').hidden=!live;
 $('#decision-mode').textContent=live?'LIVE MODEL DECISIONS':'SCRIPTED DECISIONS';
 $('#mode-footer').textContent=live?'DuckDB · live OpenAI calls · actions stay local':'DuckDB · scripted decisions · no model charges';
 $('#setup-description').textContent=live?'The model generated four queries. Each passed checks at all 41 replay timestamps.':'Four reviewed SQL templates stand in for model-written SQL.';
 $('#decision-description').textContent=live?'The decision model reads fresh evidence in one batched call per tick. Repeat matches stay quiet.':'Scripted decisions use the query results. Repeat matches stay quiet.';
 if(live){const u=s.usage;$('#model-names').textContent=u.decision_model+' · Responses + Decisions';$('#model-plan-source').textContent=u.plan_source+' · saved API history'+(u.failed_calls?' · '+u.failed_calls+' failed call(s)':'');$('#usage-numbers').innerHTML=[['API calls',u.calls],['Input tokens',u.input_tokens],['Cached input',u.cached_tokens],['Cache writes',u.cache_write_tokens],['Output tokens',u.output_tokens]].map(([label,value])=>`<div><strong>${num(value)}</strong><span>${label}</span></div>`).join('')}
 $('#clock').textContent=time(s.now);
 $('#stream-state').textContent=busy?'Deciding…':s.playing?'Replaying':s.index===40?'Complete':'Paused';
 $('#stream-state').className='status-pill'+(s.playing?' live':'');
 $('#play').innerHTML=icon(s.playing?'pause':'play')+(s.playing?'Pause replay':'Play replay');
 $('#play').disabled=s.index===40||!!s.error||(busy&&!s.playing);$('#step').disabled=s.index===40||busy||!!s.error;$('#jump').disabled=s.index>=20||busy;$('#reset').disabled=busy;
 $('#progress-fill').style.width=`${s.index/40*100}%`;$('#speed').value=s.tick_seconds;
 $('#speed-note').textContent=live?`5 minutes per check · ${s.tick_seconds}s + model time`:`5 minutes every ${s.tick_seconds} second${s.tick_seconds===1?'':'s'}`;
 $('#error-banner').hidden=!s.error;$('#error-text').textContent=s.error||'';$('#retry').hidden=!s.error?.startsWith('decision model call failed');$('#retry').disabled=busy;
 const m=s.metrics, reserve=s.rules.find(r=>r.id==='reserves'),congestion=s.rules.find(r=>r.id==='congestion');
 $('#metrics').innerHTML=metric('DOMINION LOAD',num(m.actual_mw),'MW',`${num(100*(m.actual_mw/m.forecast_mw-1),1)}% vs. forecast`,'activity',m.actual_mw>m.forecast_mw*1.05)+metric('ERCOT RESERVES',num(m.reserve_mw),'MW',reserve.result==='unknown'?'Decision unavailable':reserve.result==='match'?'Below seasonal range':'Within seasonal range','shield',reserve.result==='match')+metric('NODE CONGESTION',`$${num(m.congestion_per_mwh,2)}`,'/MWh',congestion.result==='unknown'?'Decision unavailable':congestion.result==='match'?'In the 90-day top 5%':'Below the top-5% cutoff','chart',congestion.result==='match');
 renderChart(s);
 $('#rule-list').innerHTML=s.rules.map(r=>{const status=!r.enabled?'Paused':r.result==='match'?'Matched':r.result==='unknown'?'Unknown':'Watching';const cls=!r.enabled?'paused':r.result;return `<article class="watch-card ${cls}"><div class="watch-symbol">${icon(ruleIcons[r.id])}</div><div class="watch-body"><button class="watch-name" data-rule="${r.id}">${esc(r.title)}</button><div class="watch-scope">${esc(r.scope)}</div><div class="watch-summary">${esc(r.enabled?r.summary:'This watch is paused.')}</div></div><div class="watch-end"><span class="watch-status ${cls}">${status}</span>${icon('chevron')}</div></article>`;}).join('');
 document.querySelectorAll('[data-rule]').forEach(b=>b.onclick=()=>showRule(b.dataset.rule));
 const triggered=s.notifications.filter(n=>n.kind==='triggered');
 $('#alert-count').textContent=triggered.length;
 $('#notification-list').innerHTML=s.notifications.length?s.notifications.map(n=>{const hasTask=s.tasks.some(t=>t.alert_id===n.id);return `<article class="notification ${n.kind}"><div class="notification-time"><span>${time(n.ts)}</span><span>${n.kind==='recovered'?'Recovered':'New match'}</span></div><h3>${esc(n.title)}</h3><p>${esc(n.summary)}</p><button class="text-button" data-alert="${esc(n.id)}">View evidence</button>${n.kind==='triggered'?`<button class="text-button" data-task="${esc(n.id)}" ${hasTask?'disabled':''}>${hasTask?'Task created ✓':'Create local task ↗'}</button>`:''}</article>`;}).join(''):`<div class="empty-state"><div class="empty-icon">${icon('bell')}</div><h3>Quiet, for now.</h3><p>The watches are ready. Play the replay to see conditions change.</p><button class="text-button" id="empty-jump">Jump to 2:00 PM →</button></div>`;
 if($('#empty-jump'))$('#empty-jump').onclick=()=>act('jump');
 document.querySelectorAll('[data-alert]').forEach(b=>b.onclick=()=>showRule(s.notifications.find(n=>n.id===b.dataset.alert).rule_id,b.dataset.alert));
 document.querySelectorAll('[data-task]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const r=await post('/api/tasks',{alert_id:b.dataset.task});toast(`${r.task.id} created in this demo. No external action taken.`);}catch(e){toast(e.message);b.disabled=false;}});
 $('#task-list').innerHTML=s.tasks.length?s.tasks.map(t=>`<div class="task-item">${icon('check')}<div>${esc(t.title)}<small>${t.id} · ${time(t.created_at)} · Open</small></div></div>`).join(''):'<div class="task-empty">Create a task from any triggered alert.</div>';
 const descriptions={load_readings:'Minute-level Dominion actuals and forecasts',reserve_readings:'Minute-level ERCOT reserve observations',reserve_history:'Prior 3 years · seasonal baseline',congestion_readings:'91 days hourly + the minute-level replay',checks:'Saved query results and decisions'};
 $('#table-list').innerHTML=Object.entries(s.counts).map(([k,v])=>`<div class="table-row"><div><code>${k}</code><small>${descriptions[k]}</small></div><span>${num(v)} rows</span></div>`).join('');
 $('#schema-note').textContent=`Checked at ${time(s.schema_checked_at)} · structure ${s.schema_fingerprint} · checked on startup and every 24 hours`;
 $('#assumptions').innerHTML=s.rules.map(r=>`<div class="assumption"><h3>${esc(r.title)}</h3><p>${esc(r.definition)}</p></div>`).join('');
 $('#scenario-list').innerHTML=s.rules.map((r,i)=>`<div class="scenario"><span class="scenario-number">0${i+1}</span><div><button data-scenario="${r.id}">${esc(r.question)}</button><small>Saved watch · ${esc(r.scope)}</small></div></div>`).join('');
 document.querySelectorAll('[data-scenario]').forEach(b=>b.onclick=()=>{$('#scenario-dialog').close();showRule(b.dataset.scenario);});
 $('#check-total').textContent=`${num(s.checks)} SQL checks completed`;
 $('#connection').textContent=connected?'Local stream connected':'Connecting to local stream';
 if($('#detail-dialog').open&&selectedRule)renderRuleDetail();
}
function renderChart(s){
 const w=780,h=220,left=53,right=15,top=16,bottom=30,lo=10000,hi=14000;
 const x=i=>left+i/40*(w-left-right),y=v=>top+(hi-v)/(hi-lo)*(h-top-bottom);
 const pts=key=>s.history.map((r,i)=>`${x(i).toFixed(1)},${y(r[key]).toFixed(1)}`).join(' ');
 let svg=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Actual and forecast load from 1:40 PM through ${time(s.now)}"><defs><linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#15908a" stop-opacity=".13"/><stop offset="1" stop-color="#15908a" stop-opacity="0"/></linearGradient></defs>`;
 for(const v of [10000,11000,12000,13000,14000])svg+=`<line x1="${left}" x2="${w-right}" y1="${y(v)}" y2="${y(v)}" stroke="#edf1f4" stroke-dasharray="3 4"/><text x="${left-10}" y="${y(v)+4}" text-anchor="end" font-size="10" fill="#a0aeb8">${num(v)}</text>`;
 for(const i of [0,10,20,30,40])svg+=`<text x="${x(i)}" y="${h-5}" text-anchor="middle" font-size="10" fill="#a0aeb8">${['1:40','1:50','2:00','2:10','2:20'][i/10]}</text>`;
 if(s.history.length>1)svg+=`<polygon points="${x(0)},${y(lo)} ${pts('actual_mw')} ${x(s.index)},${y(lo)}" fill="url(#chart-fill)"/><polyline points="${pts('forecast_mw')}" fill="none" stroke="#a6abc9" stroke-width="1.7" stroke-dasharray="5 4"/><polyline points="${pts('actual_mw')}" fill="none" stroke="#128c87" stroke-width="2.5" stroke-linejoin="round"/>`;
 svg+=`<circle cx="${x(s.index)}" cy="${y(s.metrics.actual_mw)}" r="4" fill="#128c87" stroke="white" stroke-width="2"/></svg>`;
 $('#load-chart').innerHTML=svg;
}
function showRule(id,alertId=null){selectedRule=id;selectedAlert=alertId;renderRuleDetail();if(!$('#detail-dialog').open)$('#detail-dialog').showModal();}
function renderRuleDetail(){
 const r=state.rules.find(r=>r.id===selectedRule);if(!r)return;
 const alert=selectedAlert?state.notifications.find(n=>n.id===selectedAlert):null;
 const evidence=alert?.evidence||r.evidence;
 const summary=alert?.summary||r.summary;
 const matched=alert?alert.kind==='triggered':r.result==='match';
 const nice={ts:'Reading time',current_mw:'Current load (MW)',previous_mw:'10 min earlier (MW)',drop_mw:'Load drop (MW)',matched:'Condition matched',reserve_mw:'Reserves (MW)',low_normal_mw:'Seasonal lower bound (MW)',sample_count:'Historical observations',node:'Node',congestion_per_mwh:'Congestion ($/MWh)',p95:'90-day top-5% cutoff',actual_mw:'Actual load (MW)',forecast_mw:'Forecast load (MW)',above_forecast_pct:'Above forecast (%)'};
 $('#detail-eyebrow').textContent=alert?'ALERT EVIDENCE / '+time(alert.ts):'SAVED WATCH / '+r.scope.toUpperCase();
 $('#detail-content').innerHTML=`<h2>${esc(r.title)}</h2><p class="detail-question">“${esc(r.question)}”</p><p>${esc(r.definition)}</p><div class="detail-controls"><label><input type="checkbox" id="rule-enabled" ${r.enabled?'checked':''}>Watch enabled</label><label><input type="checkbox" id="rule-action" ${r.auto_action?'checked':''}>Create a local task on new matches</label></div><div class="decision-box ${matched?'match':''}"><strong>${alert?(matched?'Alert triggered':'Condition recovered'):!r.enabled?'Watch paused':r.result==='unknown'?'Not enough data':matched?'Condition matched':'No match'}</strong><br>${esc(summary)}<br><small>${state.mode==='live'?'Live '+esc(state.usage.decision_model)+' decision':'Scripted decision'} · ${alert?'saved evidence':r.elapsed_ms+' ms SQL query'}</small></div><section class="detail-block"><h3>${alert?'The data behind this alert':'Latest query result'}</h3><div class="detail-evidence">${evidence?Object.entries(evidence).map(([key,value])=>`<div class="evidence-row"><span>${nice[key]||key}</span><strong>${esc(key==='ts'?time(value):typeof value==='boolean'?(value?'Yes':'No'):typeof value==='number'?num(value,Number.isInteger(value)?0:2):value??'—')}</strong></div>`).join(''):'<p>No result yet.</p>'}</div></section><section class="detail-block"><h3>Saved SQL · read-only · ${alert?'evaluated at '+time(alert.ts):'reused every five minutes'}</h3><pre>${esc(r.sql)}</pre><p>${state.mode==='live'?'The model generated this query. <code>$as_of</code> is bound to the replay time; the query passed the read-only guard and fixture checks.':'Each <code>?</code> is bound to the replay time. This mode uses a reviewed SQL template.'}</p></section>`;
 $('#rule-enabled').onchange=async e=>{try{await post('/api/rules',{id:r.id,enabled:e.target.checked});toast(e.target.checked?'Watch enabled. It will check on the next tick.':'Watch paused.');}catch(err){toast(err.message);}};
 $('#rule-action').onchange=async e=>{try{await post('/api/rules',{id:r.id,auto_action:e.target.checked});toast(e.target.checked?'New matches will create a local task.':'Automatic local tasks turned off.');}catch(err){toast(err.message);}};
}
const events=new EventSource('/api/events');events.onopen=()=>{connected=true;$('#connection').textContent='Local stream connected';};events.onmessage=e=>{try{render(JSON.parse(e.data));}catch(err){console.error(err);toast('Could not display the latest update.');}};events.onerror=()=>{connected=false;$('#connection').textContent='Reconnecting to local stream…';};
fetch('/api/state').then(r=>r.json()).then(render).catch(()=>toast('Start the local server to connect to the replay.'));
