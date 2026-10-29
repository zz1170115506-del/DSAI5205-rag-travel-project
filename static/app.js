'use strict';
import {loadEnglish,displayText,displayJSON,englishGuide} from './english.mjs?v=20261029-en';
import {readAPIResponse} from './api-response.mjs?v=20261029-en';
import {inlineAnswerHTML} from './answer-citations.mjs?v=20261029-en';
import {mapHTML,attachPlanMaps,disposeMaps} from './itinerary-map.js?v=20261029-en';
import {travelDates,addDays,dateLabel} from './trip-dates.mjs?v=20261029-en';
import {walkingMapHTML,attachWalkingMaps,disposeWalkingMaps} from './walking-map.mjs?v=20261029-en';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const attr=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const esc=v=>attr(displayText(v));
const sourceURL=v=>{try{const u=new URL(v);return u.protocol==='https:'?attr(u.href):'#';}catch{return '#';}};
const mapsURL=p=>'https://www.google.com/maps/search/?api=1&query='+encodeURIComponent('Hong Kong '+p.name);
const state={places:[],status:{},must:new Set(),turns:[],conversation:null,busy:false,ready:false,plan:null,histories:[],historyFilter:'all',historyBusy:false};
const welcome=$('#chat-messages').innerHTML;
let toastTimer, searchTimer, libraryRequest=0;
let historyRequest=0,pendingHistoryDelete=null,pendingHistoryRename=null;
const libraryPending=new Map(),libraryCache=new Map();
const loading=t=>`<div class="loading" role="status"><span class="spinner"></span><span>${esc(t)}</span></div>`;
const errorHTML=t=>`<div class="error" role="alert">${esc(t)}</div>`;
function toast(t){if($('#journey-panel').open){$('#journey-notice').textContent=displayText(t);$('#journey-notice').hidden=false;}clearTimeout(toastTimer);$('#toast').textContent=displayText(t);$('#toast').classList.remove('hidden');toastTimer=setTimeout(()=>$('#toast').classList.add('hidden'),3200);}
function switchView(name,update=true){
  closeJourney();
  if(!['home','ask','places','about'].includes(name))name='home';
  $$('.view').forEach(v=>v.classList.toggle('hidden',v.id!=='view-'+name));
  $$('.tab').forEach(v=>{v.classList.toggle('active',v.dataset.view===name);if(v.dataset.view===name)v.setAttribute('aria-current','page');else v.removeAttribute('aria-current');});
  document.body.dataset.view=name;
  if(update&&location.hash!=='#'+name)history.pushState(null,'','#'+name);
  window.scrollTo({top:0,behavior:'instant'});
}
async function api(path,body){
  const c=new AbortController(), timer=setTimeout(()=>c.abort(),70000);
  try{const headers=body?{'Content-Type':'application/json'}:{};if(path==='/api/chat')headers.Accept='application/x-ndjson';
    const r=await fetch(path,{method:body?'POST':'GET',headers,body:body?JSON.stringify(body):undefined,signal:c.signal});
    return await readAPIResponse(r);
  }catch(e){if(e.name==='AbortError')throw Error('The request timed out. Check the service and try again.');if(e instanceof TypeError)throw Error('Connection interrupted. Check your network and retry, or check My Journey for a saved result.');throw Error(displayText(e.message));}finally{clearTimeout(timer);}
}
function syncMust(){$('#only-selected').disabled=state.busy||state.must.size===0;if(!state.must.size)$('#only-selected').checked=false;[...$('#must-visit').options].forEach(o=>o.selected=state.must.has(o.value));$$('[data-action="must"]').forEach(b=>{b.textContent=state.must.has(b.dataset.id)?'Added ✓':'Add to must-visits +';b.setAttribute('aria-pressed',String(state.must.has(b.dataset.id)));});}
function addMust(id){if(state.must.has(id)){state.must.delete(id);toast('Removed from must-visits');}else{state.must.add(id);toast('Added to must-visits. Open Ask & Plan to build your trip.');}syncMust();}

function card(p, i) {
  return `<article class="place-card"><div class="card-top"><span class="subtle">${esc(p.region)} / ${esc(p.area)}</span><span class="card-number">${String(i+1).padStart(2,'0')}</span></div><h3>${esc(p.name)}</h3>${p.en&&displayText(p.name)!==p.en?`<span class="card-en">${esc(p.en)}</span>`:''}<div class="tags">${p.tags.map(t => `<span class="tag">${esc(t)}</span>`).join('')}<span class="tag">${p.kind === 'food' ? 'Dining option' : p.indoor ? 'Includes indoor space':'Mostly outdoors'}</span></div><p>${esc(p.summary)}</p><div class="card-actions"><button class="text-button" data-action="detail" data-id="${esc(p.id)}">View details ↗</button><button class="small-button" data-action="must" data-id="${esc(p.id)}" aria-pressed="${state.must.has(p.id)}">${state.must.has(p.id)?'Added ✓':'Add to must-visits +'}</button><a href="${sourceURL(p.source)}" target="_blank" rel="noopener noreferrer">Official source ↗</a></div>${p.match_reason ? `<div class="match-note">${esc(p.match_reason)}</div>`:''}</article>`;
}

function traceHTML(trace) {
  if(!trace?.length)return '';
  return `<details class="trace"><summary>Tool calls · MCP communication</summary>${trace.map(t => `<code>${esc(t.server)} · ${esc(t.transport)} · ${esc(t.elapsed_ms)} ms\n${esc(t.steps.join(' → '))}\nArguments: ${attr(displayJSON(t.arguments))}\nStatus: ${esc(t.status)}; Live AMap call: ${t.live_amap ? 'Yes':'No'}</code>`).join('')}</details>`;
}

function transitGuideHTML(g){
  g=englishGuide(g);
  if(!g)return '';
  return `<section class="transit-guide ${g.mode==='walk'?'walking-guide':''}" aria-label="Transport directions"><div class="transit-heading"><strong>${esc(g.title)}</strong><span>${g.estimated_minutes===null?'Destination access first':'About '+esc(g.estimated_minutes)+' minutes · Estimate'}</span></div>${g.origin_note?`<p class="transit-origin-note">${esc(g.origin_note)}</p>`:''}<ol class="transit-steps">${g.steps.map(step=>`<li class="transit-step ${esc(step.kind)}">${step.line_id?`<span class="rail-badge rail-${esc(step.line_id)}">${esc(step.line_name)} · ${esc(step.color_name)}</span>`:''}<span>${esc(step.text.replace(/；地图虚线不是实际步行路径。/g,'。'))}</span>${step.kind==='ride'?`<details class="station-sequence"><summary>Ride ${step.stop_count} stops · Show stations</summary><p>${step.stations.map(esc).join(' → ')}</p></details>`:''}</li>`).join('')}</ol><details class="transit-sources"><summary>${g.mode==='walk'?'Estimate and limitations':'Official transport sources'} · Checked ${esc(g.checked)}</summary>${g.sources.map(src=>`<a href="${sourceURL(src.url)}" target="_blank" rel="noopener noreferrer">${esc(src.name)} ↗</a>`).join('')}<p>${esc(g.notice)}</p></details></section>`;
}
function accessHTML(access){
 if(!access?.options?.length)return '';
 const first=access.options[0];
 return `<details class="stop-access"><summary>MTR access: ${esc(first.station)} station · ${esc(first.exit)} Exit${access.connector?' · Additional connection needed':''}</summary>${access.options.map(o=>`<p><strong>${esc(o.station)} station ${esc(o.exit)} Exit</strong> · ${esc(o.walk_note)} Allow about ${esc(o.walk_minutes)} minutes (estimate).${o.basis==='station_map_reference'?' Street access is based on the station map.':''}</p>`).join('')}${access.sources.map(src=>`<a href="${sourceURL(src.url)}" target="_blank" rel="noopener noreferrer">${esc(src.name)} ↗</a>`).join('')}<p>Exit information checked ${esc(access.checked)}; See the connection guide; current access and step-free travel are not guaranteed.</p></details>`;
}

function dayHTML(day,plan,index){
 const flex=day.kind==='flex',heading=`<span class="day-num">${String(day.day).padStart(2,'0')}</span><div><h3>${day.date?`<span class="day-date">${esc(dateLabel(day.date))} · ${esc(day.weekday)}</span>`:''}${esc(day.title)}</h3><p>${flex?'Rest / free time · Add activities as needed':`${day.stops.length} stops · Expected finish ${esc(day.end)}  · ${plan.history_transport_refreshed?'Original draft ':''}Estimated transfers: ${esc(day.transfer_minutes)} minutes`}</p></div>`;
 const route=day.stops.length>1?`<div class="map-actions"><span class="fine-print">Day ${day.day} · AMap walking route reference</span><button class="small-button" data-action="route" data-day="${index}">View AMap route${state.status.amap_configured?'':state.status.amap_enabled===false?' · Disabled':' · Not configured'} ↗</button></div><div class="route-result" data-route-day="${index}" aria-live="polite"></div>`:'';
 const body=flex?`<p class="flex-reason">${esc(day.reason)}</p><div class="flex-activities">${(day.activities??[]).map(a=>`<div><strong>${esc(a.period)}</strong><p>${esc(a.text)}</p></div>`).join('')}</div>`:`${route}${transitGuideHTML(day.start_guide)}${day.stops.map((stop,i)=>`<div class="stop"><div class="stop-time">${esc(stop.start)}<br>— ${esc(stop.end)}</div><div class="stop-content"><h4>${esc(stop.place.name)}</h4><p>${esc(stop.place.summary)}</p>${stop.free_before_minutes?`<p class="fine-print">Free time before this stop: ${esc(stop.free_before_minutes)} minutes, allowing for evening activities. Adjust as needed.</p>`:''}${accessHTML(stop.transit_access)}<button class="text-button" data-action="detail" data-id="${esc(stop.place.id)}">Details & sources ↗</button>${day.legs[i]?`<div class="leg"><p>↓ Next: ${esc(day.stops[i+1].place.name)} · ${plan.history_transport_refreshed?'Original draft ':''}Allow for transport: ${esc(day.legs[i].minutes)} minutes (estimate)</p>${transitGuideHTML(day.legs[i].transit_guide)}${walkingMapHTML(stop.place,day.stops[i+1].place,day.legs[i],index===0&&i===0)}</div>`:''}</div></div>`).join('')}`;
 const content=body+`<p class="fine-print">${esc(day.meal_note)}</p>`;
 return plan.days.length>7?`<details class="day-card long-day ${flex?'flex-day':''}" ${index===0?'open':''}><summary class="day-heading">${heading}<span class="day-expand">Expand / collapse</span></summary><div class="day-body">${content}</div></details>`:`<article class="day-card ${flex?'flex-day':''}"><div class="day-heading">${heading}</div>${content}</article>`;
}
function planHTML(plan) {
 const coverage=plan.coverage,summary=coverage?`<p class="plan-coverage">Total ${coverage.calendar_days} days · ${coverage.sightseeing_days} days with planned stops${coverage.flex_days?` · ${coverage.flex_days} rest / free days`:''}${plan.days.length>7?' · Open a day to see details':''}</p>`:'';
 return `<div class="plan-tools"><h3>Your ${plan.days_requested??plan.days.length} day Hong Kong itinerary${plan.start_date?`<span class="plan-date-range">${esc(dateLabel(plan.start_date))} — ${esc(dateLabel(plan.end_date))}</span>`:''}</h3><div><button class="small-button" data-action="download">Download itinerary ↓</button> <button class="small-button" data-action="toggle-plan">Collapse</button></div></div>${plan.only_selected?'<p class="selection-note">Only your selected places are scheduled. No extra attractions were added.</p>':''}${summary}${plan.history_transport_refreshed?'<p class="fine-print">Transport references have been refreshed. The original timetable is unchanged; replan to update timings.</p>':''}${mapHTML(plan)}${plan.days.map((day,i)=>dayHTML(day,plan,i)).join('')}<div class="plan-notes">${plan.warnings.map(w=>`<p>· ${esc(w)}</p>`).join('')}</div>${traceHTML(plan.trace)}`;
}

function downloadPlan(plan=state.plan) {
  if(!plan)return;
  const lines=['HK Slow | Hong Kong itinerary draft','Routes and exits are local references to official information. Timings are estimates; check operations, exits, weather and tickets before departure.',''];
  if(plan.start_date)lines.push(`Travel dates: ${plan.start_date} to ${plan.end_date} (Total ${plan.days_requested} days, including the first and last day)`,'');
  const appendGuide=g=>{if(!g)return;g=englishGuide(g);lines.push(g.title,g.origin_note||'');g.steps.forEach((step,i)=>lines.push(`${i+1}. ${step.text}`));if(g.estimated_minutes!==null)lines.push(`Estimated transport allowance: ${g.estimated_minutes} minutes (project estimate)`);g.sources.forEach(src=>lines.push(`Transport source: ${src.name} ${src.url} (Checked ${src.checked})`));lines.push(g.notice,'');};
  if(plan.history_transport_refreshed)lines.push('The historical timetable has not been recalculated. Replan using the refreshed transport references.','');
  for(const day of plan.days) {
    lines.push(`Day ${day.day} | ${day.date?day.date+' · '+day.weekday+' | ':''}${day.title}`);
    if(day.kind==='flex'){lines.push(day.reason,...(day.activities??[]).map(a=>`${a.period}: ${a.text}`));}
    appendGuide(day.start_guide);
    day.stops.forEach((stop,i)=>{
      if(stop.free_before_minutes)lines.push(`Free time before this stop: ${stop.free_before_minutes} minutes`);
      lines.push(`${stop.start}–${stop.end} ${stop.place.name}`,stop.place.summary,`Source: ${stop.place.source}`);
      for(const option of stop.transit_access?.options??[])lines.push(`MTR access: ${option.station} station ${option.exit} Exit.${option.walk_note}`);
      if(day.legs[i]){lines.push(`Next stop: ${day.stops[i+1].place.name}; Allow for transport: ${day.legs[i].minutes} minutes (estimate)`);appendGuide(day.legs[i].transit_guide);}
      lines.push('');
    });lines.push(day.meal_note,'');
  }
  lines.push('Check before departure',...plan.warnings.map(w=>'· '+w),'',`Knowledge version: ${state.status.knowledge_version}`,`Transport data version: ${plan.transit_version??'Not provided'}`,`Planning method: ${plan.algorithm}`);
  const blob=new Blob(['\ufeff'+lines.map(displayText).join('\n')],{type:'text/plain;charset=utf-8'});
  const url=URL.createObjectURL(blob), a=document.createElement('a');a.href=url;a.download='HKSlow_HongKong_itinerary.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Itinerary and transport guide exported');
}
function showDetail(id) {
  const p=state.places.find(p=>p.id===id); if(!p)return;
  $('#detail-content').innerHTML=`<span class="eyebrow">${esc(p.region)} / ${esc(p.area)}</span><h2>${esc(p.name)}</h2>${p.en&&displayText(p.name)!==p.en?`<span class="card-en">${esc(p.en)}</span>`:''}<div class="tags">${p.tags.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div><p>${esc(p.summary)}</p><p class="tip">${esc(p.tip)}</p><p class="fine-print">Suggested visit: ${esc(p.duration)} minutes, a project planning assumption. Source summary checked: ${esc(p.checked)}，This does not confirm current hours, fares or events.</p><div class="detail-actions"><a href="${sourceURL(p.source)}" target="_blank" rel="noopener noreferrer">Official source ↗</a><a href="${esc(mapsURL(p))}" target="_blank" rel="noopener noreferrer">Find on a map ↗</a><button class="small-button" data-action="must" data-id="${esc(p.id)}">${state.must.has(p.id)?'Added ✓':'Add to must-visits +'}</button><button class="small-button" data-action="amap" data-id="${esc(p.id)}">Search AMap${state.status.amap_configured?'':state.status.amap_enabled===false?' · Disabled':' · Not configured'}</button></div><div id="amap-result"></div>`;
  if(!$('#detail-dialog').open)$('#detail-dialog').showModal();
}
async function searchAmap(id,btn) {
  btn.disabled=true; $('#amap-result').innerHTML=loading('Checking AMap configuration...');
  try{const res=await api('/api/amap/search',{place_id:id});$('#amap-result').innerHTML=`<p class="fine-print">${esc(res.message)}</p>${res.results ? `<pre>${attr(displayJSON(res.results))}</pre>`:''}`;}
  catch(err){$('#amap-result').innerHTML=errorHTML(err.message);}
  finally{btn.disabled=false;}
}


function readTrip(){const start=$('#start-date').value,end=$('#end-date').value;const dates=start||end?travelDates(start,end):{days:$('#days').value?Number($('#days').value):null,start_date:null,end_date:null};return{...dates,region:$('#plan-region').value,pace:$('input[name="pace"]:checked').value,interests:$$('#interest-options input:checked').map(v=>v.value),rain:$('#rain').checked,public_only:$('#public-only').checked,must_visit:[...state.must],only_selected:state.must.size>0&&$('#only-selected').checked,start_station:$('#start-station').value,excluded_places:state.tripMemory?.excluded_places??[]};}
function applyTrip(t){state.tripMemory=t;
  $('#start-date').value=t.start_date??'';$('#end-date').value=t.end_date??'';updateDateHint('plan');
  $('#start-station').value=t.start_station??'';$('#days').value=t.days??'';$('#plan-region').value=t.region??'全部';$$('input[name="pace"]').forEach(v=>v.checked=v.value===(t.pace??'轻松'));
  $$('#interest-options input').forEach(v=>v.checked=(t.interests??['海港夜景','本地美食']).includes(v.value));$('#rain').checked=!!t.rain;$('#public-only').checked=!!t.public_only;state.must=new Set(t.must_visit??[]);syncMust();$('#only-selected').checked=!!t.only_selected&&state.must.size>0;
  $('#trip-memory').textContent=`This trip: ${displayText(t.region??'全部')} · ${t.start_date?t.start_date+' to '+t.end_date+' · ':''}${t.days??'To confirm'} days · ${displayText(t.pace??'轻松')} · ${t.rain?'Indoor only':'Indoor / outdoor'}${t.public_only?' · Public-space attractions':''}${t.start_station?' · From '+displayText(t.start_station):''}${t.only_selected?' · Selected places only':''}${t.excluded_places?.length?' · Excluded '+t.excluded_places.map(id=>displayText(state.places.find(p=>p.id===id)?.name??id)).join(', '):''}${state.must.size?' · Must-visits '+[...state.must].map(id=>displayText(state.places.find(p=>p.id===id)?.name??id)).join(', '):''}`;
}
function setBusy(value){state.busy=value;$$('#plan-form input,#plan-form select').forEach(field=>field.disabled=value);if(!value)$('#only-selected').disabled=state.must.size===0;['#ask-submit','#plan-submit','#home-submit','#new-chat'].forEach(s=>$(s).disabled=value||!state.ready);$('#use-model').disabled=value||!state.status.model_configured;$$('.history-row button').forEach(b=>b.disabled=value||state.historyBusy);$$('.suggestions button').forEach(b=>b.disabled=value);}
function modelLabel(){const model=$('#use-model').checked;$('#chat-mode').textContent=model?'Smart Assist':'';$('#chat-mode').classList.toggle('hidden',!model);$('#model-mode-note').textContent=model?'Smart Assist is on. Your questions, bounded conversation, preferences, itinerary and relevant source or map evidence are sent to the configured model service.':'Currently using the local knowledge demo. Enable Smart Assist for model-based conversation and itinerary changes.';}
function externalHTML(data,showMessage=true){
  if(!data)return '';
  if(data.mode==='local')return `<p class="fine-print">Found a curated official-source record.</p><div class="cards-grid">${data.results.map(card).join('')}</div>`;
  return `${showMessage?`<p class="fine-print">${esc(data.message)}</p>`:''}${data.mode!=='live'&&data.search_links?.length?`<div class="map-search-links">${data.search_links.map(link=>`<a class="small-button" href="${sourceURL(link.url)}" target="_blank" rel="noopener noreferrer">${esc(link.name)} ↗</a>`).join('')}<span class="fine-print">External search link; no place evidence has been retrieved yet.</span></div>`:''}<div class="external-results">${(data.results??[]).map(p=>`<article class="external-card"><span class="badge">AMap · Not manually reviewed</span><h4>${esc(p.name)}</h4><p>${esc(p.address||p.district||'Open the provider map for the source address')}</p><p>${esc(p.category)} · Coordinates ${esc(p.location?.join(', '))}</p><a href="${sourceURL(p.map_url)}" target="_blank" rel="noopener noreferrer">View on AMap ↗</a><p>Source: ${esc(p.source?.name)} · ${esc(p.source?.fetched_at)}</p><details><summary>Evidence JSON & source</summary><pre>${attr(displayJSON(p))}</pre></details></article>`).join('')}</div>`;
}
function renderTurns(){
 disposeWalkingMaps();disposeMaps();
 $('#chat-messages').innerHTML=state.turns.length?state.turns.map((turn,i)=>{const d=turn.result;return `<article class="chat-turn" data-turn="${i}"><div class="user-message"><p>${esc(turn.question)}</p></div><div class="assistant-message"><div class="assistant-name"><span>✧ HK Slow · Travel assistant</span><span>${d.answer.mode==='model'?(d.answer.retrieval_source==='amap'?'AI + map evidence':'Smart Assist'):d.answer.mode==='map_lookup'?'Map supplement':'Curated sources'}</span></div><div class="answer-text">${inlineAnswerHTML(d.answer,d.external_lookup)}</div>${externalHTML(d.external_lookup,false)}${d.sources?.length?`<div class="chat-sources">${d.sources.map(p=>`<button class="small-button" data-action="detail" data-id="${esc(p.id)}">${esc(p.name)} · Source ↗</button>`).join('')}</div>`:''}${d.plan?`<div class="chat-plan">${planHTML({...d.plan,trace:[]})}</div>`:''}<details class="trace"><summary>Sources & execution trace · ${esc(d.answer.notice)}</summary><code>${attr(displayJSON({metrics:d.metrics,stop_reason:d.stop_reason,steps:d.trace}))}</code></details></div></article>`;}).join(''):welcome;
 syncMust();attachPlanMaps($('#chat-messages'),state.turns);attachWalkingMaps($('#chat-messages'),state.places,api);
}
function showLatestAnswer(){
 const scroll=$('#chat-scroll'),answer=$('#chat-messages .chat-turn:last-child .assistant-message');
 if(answer)scroll.scrollTop+=answer.getBoundingClientRect().top-scroll.getBoundingClientRect().top-12;
}
function expandChat(expanded){
 document.body.classList.toggle('chat-expanded',expanded);
 const button=$('#expand-chat');button.setAttribute('aria-pressed',String(expanded));
 button.textContent=expanded?'Restore layout ↙':'Expand chat ↗';
 button.title=expanded?'Restore the standard chat layout':'Expand the conversation';
}
function rememberId(){try{if(state.conversation&&state.status.history_enabled!==false)localStorage.setItem('hk-travel-active-v13',state.conversation);else localStorage.removeItem('hk-travel-active-v13');}catch{if(state.status.history_enabled!==false)toast('The browser could not save the active chat link. You can reopen it from recent conversations.');}}
function historyIcon(kind){return `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${{favorite:'<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3l-5.6 2.9 1.1-6.2L3 9.6l6.2-.9Z"/>',pinned:'<path d="m16 3 5 5-4 2-3 5-2 1-4-4 1-2 5-3Z"/><path d="m9 15-6 6"/>',rename:'<path d="m16 3 5 5-12 12-6 1 1-6Z"/><path d="m13 6 5 5"/>',delete:'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>'}[kind]}</svg>`;}
function renderHistory(){
 if(state.status.history_enabled===false){state.histories=[];$('#history-count').textContent='Temporary session';$('.history-filters').classList.add('hidden');$('#history-list').innerHTML='<p class="fine-print">The anonymous demo does not expose shared conversation history.</p>';$('.history-note').textContent='Continue in this page. Refresh starts a new chat; sessions expire after 30 minutes idle or a server restart.';return;}
 const favoriteCount=state.histories.filter(c=>c.favorite).length;
 $('#history-favorite-count').textContent=favoriteCount;
 $$('[data-history-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.historyFilter===state.historyFilter)));
 const rows=state.histories.filter(c=>state.historyFilter!=='favorite'||c.favorite);
 $('#history-list').innerHTML=rows.length?rows.map(c=>`<div class="history-row ${c.id===state.conversation?'active':''} ${c.pinned?'is-pinned':''}"><button class="history-open" data-history="${esc(c.id)}" title="${esc(c.title)}${c.pinned?' · Pinned':''}" aria-current="${c.id===state.conversation?'true':'false'}">${esc(c.title)}</button><div class="history-actions">${['favorite','pinned'].map(flag=>{const label=(flag==='favorite'?(c.favorite?'Remove favourite':'Favourites'):(c.pinned?'Unpin':'Pin'));return `<button class="history-icon history-${flag}" data-history-flag="${flag}" data-history-id="${esc(c.id)}" data-flag-value="${!c[flag]}" aria-pressed="${!!c[flag]}" title="${label}" aria-label="${label}conversation ${esc(c.title)}">${historyIcon(flag)}</button>`;}).join('')}<button class="history-icon history-rename" data-rename-history="${esc(c.id)}" title="Rename" aria-label="Rename conversation ${esc(c.title)}">${historyIcon('rename')}</button><button class="history-icon history-delete" data-delete-history="${esc(c.id)}" title="Delete" aria-label="Deleteconversation ${esc(c.title)}">${historyIcon('delete')}</button></div></div>`).join(''):`<p class="fine-print history-empty">${state.historyFilter==='favorite'?'No favourites yet. Select the star beside a conversation to save it.':'Start with a travel idea.'}</p>`;
 $$('.history-row button').forEach(b=>b.disabled=state.busy||state.historyBusy);
}
async function loadHistory(){if(state.status.history_enabled===false){renderHistory();return;}const request=++historyRequest,data=await api('/api/history');if(request!==historyRequest)return;state.histories=data.conversations;$('#history-count').textContent=`${data.conversations.length} / ${data.capacity}`;renderHistory();}
async function updateHistoryFlag(button){
 if(state.busy||state.historyBusy)return;
 const id=button.dataset.historyId,flag=button.dataset.historyFlag;
 if(!['favorite','pinned'].includes(flag))return;
 state.historyBusy=true;renderHistory();
 try{await api('/api/history/update',{id,[flag]:button.dataset.flagValue==='true'});await loadHistory();toast(flag==='favorite'?(button.dataset.flagValue==='true'?'Conversation added to favourites':'Removed from favourites'):(button.dataset.flagValue==='true'?'Conversation pinned':'Conversation unpinned'));}
 catch(e){toast(e.message);}finally{state.historyBusy=false;renderHistory();const focus=$$('.history-row [data-history-flag]').find(b=>b.dataset.historyId===id&&b.dataset.historyFlag===flag);(focus??$('[data-history-filter="favorite"]')).focus();}
}
function requestHistoryRename(id){
 if(state.busy||state.historyBusy)return;
 const row=state.histories.find(c=>c.id===id);if(!row)return;
 pendingHistoryRename=id;$('#history-rename-input').value=row.title;$('#history-rename-error').textContent='';$('#history-rename-dialog').showModal();$('#history-rename-input').select();
}
async function saveHistoryRename(event){
 event.preventDefault();if(!pendingHistoryRename||state.busy||state.historyBusy)return;
 const title=$('#history-rename-input').value.trim();if(!title){$('#history-rename-error').textContent='Enter a conversation name.';return;}
 const id=pendingHistoryRename;state.historyBusy=true;renderHistory();$('#save-history-rename').disabled=true;
 try{await api('/api/history/rename',{id,title});await loadHistory();$('#history-rename-dialog').close();toast('Conversation renamed');}
 catch(e){$('#history-rename-error').textContent=e.message;}
 finally{state.historyBusy=false;$('#save-history-rename').disabled=false;renderHistory();const button=$$('[data-rename-history]').find(b=>b.dataset.renameHistory===id);button?.focus();}
}
function requestHistoryDelete(id){
 if(state.busy||state.historyBusy)return;
 const record=state.histories.find(c=>c.id===id);if(!record)return;
 pendingHistoryDelete=id;$('#history-delete-title').textContent=record.title;$('#history-delete-error').textContent='';$('#history-delete-dialog').showModal();
}
async function confirmHistoryDelete(){
 if(!pendingHistoryDelete||state.busy||state.historyBusy)return;
 const id=pendingHistoryDelete;state.historyBusy=true;renderHistory();$('#confirm-history-delete').disabled=true;
 try{await api('/api/history/delete',{id});$('#history-delete-dialog').close();if(state.conversation===id)newChat();await loadHistory();toast('Saved conversation deleted');$('#new-chat').focus();}
 catch(e){$('#history-delete-error').textContent=e.message;}
 finally{state.historyBusy=false;$('#confirm-history-delete').disabled=false;renderHistory();}
}
async function openHistory(id){if(state.busy)return;try{const saved=await api('/api/history/read',{id});state.conversation=id;state.turns=saved.turns;$('#use-model').checked=!!saved.use_model&&!!state.status.model_configured;modelLabel();applyTrip(saved.checkpoint.trip);renderTurns();rememberId();await loadHistory();switchView('ask');showLatestAnswer();}catch(e){toast(e.message);}}
function newChat(){if(state.busy)return;state.conversation=null;state.turns=[];$('#use-model').checked=false;modelLabel();rememberId();applyTrip({});renderTurns();$('#question').value='';loadHistory().catch(e=>toast(e.message));}
async function send(question){
 question=question.trim();if(!state.ready||state.busy||question.length<2)return;
 switchView('ask');setBusy(true);$('#chat-messages').insertAdjacentHTML('beforeend',loading($('#use-model').checked?'Finding sources, selecting tools and preparing suggestions...':'Searching curated sources and planning around your preferences...'));$('#chat-scroll').scrollTop=$('#chat-scroll').scrollHeight;
 try{const data=await api('/api/chat',{question,language:'en',conversation_id:state.conversation,use_model:$('#use-model').checked,trip:readTrip()});state.conversation=data.conversation_id;state.turns.push({question,result:data});state.turns=state.turns.slice(-20);applyTrip(data.trip);$('#question').value='';rememberId();renderTurns();await loadHistory();showLatestAnswer();}
 catch(e){renderTurns();$('#chat-messages').insertAdjacentHTML('beforeend',errorHTML(e.message));$('#chat-scroll').scrollTop=$('#chat-scroll').scrollHeight;}
 finally{setBusy(false);}
}
function queueLibrarySearch(immediate=false){
 clearTimeout(searchTimer);const id=++libraryRequest;
 $('#library-notice').innerHTML='';$('#place-grid').innerHTML='';$('#library-count').textContent='';
 if($('#place-search').value.trim().length===1){$('#place-grid').setAttribute('aria-busy','false');$('#library-notice').innerHTML='<p class="search-notice">Enter at least 2 characters, or clear the search to browse all curated places.</p>';return;}
 if(immediate)filterLibrary(id);else searchTimer=setTimeout(()=>filterLibrary(id),650);
}
async function filterLibrary(id){
 const payload={query:$('#place-search').value.trim(),region:$('#library-region').value},key=JSON.stringify(payload);
 $('#place-grid').setAttribute('aria-busy','true');$('#place-grid').classList.add('external-mode');
 $('#place-grid').innerHTML=loading('Searching curated sources; AMap will supplement missing places when needed...');
 try{
  let data=libraryCache.get(key);
  if(!data||Date.now()-data.time>180000){
   let request=libraryPending.get(key);
   if(!request){request=api('/api/places/search',payload).then(value=>{libraryPending.delete(key);return value;},err=>{libraryPending.delete(key);throw err;});libraryPending.set(key,request);}
   const value=await request;data={value,time:Date.now()};
   if(['live','empty'].includes(value.mode)){if(libraryCache.size>=30)libraryCache.delete(libraryCache.keys().next().value);libraryCache.set(key,data);}
  }
  if(id!==libraryRequest)return;
  const result=data.value,local=result.provider==='curated_local';
  $('#place-grid').classList.toggle('external-mode',!local);
  if(local){
   $('#place-grid').innerHTML=result.results.length?result.results.map(card).join(''):'<div class="empty">'+esc(result.message)+'</div>';
   $('#library-notice').innerHTML=payload.query?`<p class="search-notice">${result.results.length?'Curated matches: '+result.results.length+' related places.':esc(result.message)}</p>`:'';
   $('#library-count').textContent=result.results.length+' curated places';
  }else{
   $('#library-notice').innerHTML=`<div class="search-notice map-supplement"><strong>No sufficient curated matches for“${esc(result.query)}”</strong><p>${result.mode==='live'?'AMap returned '+result.results.length+' place candidates.':esc(result.message)}</p></div>`;
   $('#place-grid').innerHTML=externalHTML(result,false);
   $('#library-count').textContent=result.mode==='live'?result.results.length+' AMap candidates':result.mode==='empty'?'No AMap results':result.mode==='filtered_external'?'No candidates in this area':'AMap search incomplete';
  }
  syncMust();
 }catch(e){if(id===libraryRequest){$('#place-grid').innerHTML=errorHTML(e.message);$('#library-count').textContent='Search incomplete';}}
 finally{if(id===libraryRequest)$('#place-grid').setAttribute('aria-busy','false');}
}
function geometryHTML(lines){
 const valid=lines.flat().filter(p=>Array.isArray(p)&&p.length===2&&p.every(Number.isFinite));if(valid.length<2)return '';
 const xs=valid.map(p=>p[0]),ys=valid.map(p=>p[1]),minX=Math.min(...xs),minY=Math.min(...ys),dx=Math.max(.001,Math.max(...xs)-minX),dy=Math.max(.001,Math.max(...ys)-minY);
 return `<svg class="route-geometry" viewBox="0 0 640 300" role="img" aria-label="AMap walking geometry without a basemap">${lines.map(line=>`<polyline points="${line.filter(p=>p.every(Number.isFinite)).map(p=>`${25+(p[0]-minX)/dx*590},${275-(p[1]-minY)/dy*250}`).join(' ')}" fill="none" stroke="#216653" stroke-width="3"/>`).join('')}</svg>`;
}
async function showRoute(button){
 const turn=state.turns[Number(button.closest('[data-turn]').dataset.turn)],day=turn?.result.plan?.days[Number(button.dataset.day)];if(!day)return;
 const target=button.closest('.chat-plan').querySelector(`[data-route-day="${Number(button.dataset.day)}"]`);button.disabled=true;target.innerHTML=loading('Checking AMap locations and walking routes...');
 try{const data=await api('/api/amap/route',{place_ids:day.stops.map(s=>s.place.id).slice(0,6)});if(data.mode!=='live'){target.innerHTML=`<div class="error">${esc(data.message)}</div>`;return;}
 const image=typeof data.map_image==='string'&&/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(data.map_image)?`<img class="route-image" src="${data.map_image}" alt="Walking route image returned by AMap, including provider attribution">`:geometryHTML(data.polylines);
 target.innerHTML=`${image}<p class="fine-print">AMap walking reference: ${(data.distance_m/1000).toFixed(1)} km · About ${Math.ceil(data.duration_s/60)} minutes.${esc(data.message)}${data.map_image?'':' Only the returned path geometry is shown; no basemap is available.'}<br>Source: ${esc(data.source.name)} · ${esc(data.source.fetched_at)}</p>`;
 }catch(e){target.innerHTML=errorHTML(e.message);}finally{button.disabled=false;}
}
function statusHTML(s){
 const r=s.retrieval||{};
 const hybrid=r.configured_mode==='hybrid';
 const ready=r.index_ready&&r.dependency_available;
 const retrievalLabel=hybrid?(ready?'Semantic + keyword · Index ready':'Keyword search · Semantic index not ready'):'Keyword search';
 const retrievalNote=hybrid?'Semantic and keyword retrieval find related places. Keyword search remains available if embeddings fail. Inspect each answer trace for actual retrieval and sources.':'Find places by name, neighbourhood and keywords. Answers include source and execution information.';
 return `<div class="status-card"><h3>Knowledge & retrieval</h3><span class="badge">${s.place_count} records · ${retrievalLabel}</span><p>${retrievalNote}</p></div><div class="status-card"><h3>Model & tools</h3><span class="badge">${s.model_configured?'Configured · Enable Smart Assist':'Not configured'}</span><p>${s.model_configured?esc(s.model_name)+' is available for answers and tool selection.':'Local knowledge tools are available.'}When enabled, questions, bounded history and relevant source or map evidence are sent to the configured model service.</p></div><div class="status-card"><h3>AMap places & routes</h3><span class="badge">${s.amap_configured?'Configured · On-demand search':s.amap_enabled===false?'Automatic lookup disabled':'Not configured · No external lookup'}</span><p>The itinerary overview uses OpenStreetMap. AMap separately provides place searches and walking routes, subject to account permissions and Hong Kong coverage.</p></div>`;
}
async function init(){
 try{await loadEnglish();const [s,data]=await Promise.all([api('/api/status'),api('/api/places')]);state.status=s;state.places=data.places;
  $('#place-count').textContent=s.place_count;$('#data-version').textContent=s.knowledge_version;$('#status-grid').innerHTML=statusHTML(s);
  $('#interest-options').innerHTML=s.interests.map(t=>`<label><input type="checkbox" value="${attr(t)}" ${['海港夜景','本地美食'].includes(t)?'checked':''}><span>${esc(t)}</span></label>`).join('');
  $('#must-visit').innerHTML=state.places.map(p=>`<option value="${esc(p.id)}">${esc(p.name)} · ${esc(p.region)}</option>`).join('');$('#place-grid').innerHTML=state.places.map(card).join('');$('#library-count').textContent=`${data.places.length} places`;
  $('#start-station').innerHTML='<option value="">Not set · Show destination access first</option>'+s.transit_stations.map(name=>`<option value="${attr(name)}">${esc(name)} station</option>`).join('');
  $('#home-start-date').value=s.today_hk;$('#home-end-date').value=addDays(s.today_hk,1);updateDateHint('home');
  $('#model-hint').textContent=s.model_configured?s.model_name:'Not configured';state.ready=true;setBusy(false);await loadHistory();
  let saved;try{if(s.history_enabled!==false)saved=localStorage.getItem('hk-travel-active-v13');else localStorage.removeItem('hk-travel-active-v13');}catch{}if(saved&&/^[a-f0-9]{32}$/.test(saved)){try{const record=await api('/api/history/read',{id:saved});state.conversation=saved;state.turns=record.turns;applyTrip(record.checkpoint.trip);$('#use-model').checked=!!record.use_model&&!!s.model_configured;renderTurns();await loadHistory();}catch{state.conversation=null;rememberId();}}
  modelLabel();$('.trip-settings').open=true;
 }catch(e){$('#app-error').innerHTML=`${esc(e.message)} <button class="small-button" data-action="retry-init">Retry connection</button>`;$('#app-error').classList.remove('hidden');}
}
function updateDateHint(scope){
 const home=scope==='home',start=$(home?'#home-start-date':'#start-date'),end=$(home?'#home-end-date':'#end-date'),hint=$(home?'#home-date-hint':'#plan-date-hint');
 start.setCustomValidity('');end.setCustomValidity('');
 try{const dates=travelDates(start.value,end.value);hint.textContent=`Total ${dates.days} days · Including the first and last day`;hint.classList.remove('date-invalid');if(!home)$('#days').value=dates.days;}
 catch(e){hint.textContent=!start.value&&!end.value?'Choose dates to calculate the trip length':e.message;hint.classList.toggle('date-invalid',!!(start.value||end.value));if(start.value||end.value)end.setCustomValidity(e.message);}
}
for(const scope of ['home','plan'])for(const selector of scope==='home'?['#home-start-date','#home-end-date']:['#start-date','#end-date'])$(selector).addEventListener('input',()=>updateDateHint(scope));
$('#home-form').addEventListener('submit',e=>{e.preventDefault();if(!state.ready||state.busy)return;
 try{const dates=travelDates($('#home-start-date').value,$('#home-end-date').value),t={...dates,region:$('#home-region').value,pace:$('#home-pace').value,interests:$$('[data-interest][aria-pressed="true"]').map(b=>b.dataset.interest),rain:false,public_only:false,must_visit:[...state.must]};newChat();applyTrip(t);send(`Plan a ${t.days} day Hong Kong itinerary from ${t.start_date} to ${t.end_date}, area: ${displayText(t.region)}, pace: ${displayText(t.pace)}.`);}catch(err){toast(err.message);}
});
$('#plan-form').addEventListener('submit',e=>{e.preventDefault();try{const t=readTrip();send(`Plan a ${t.days} day itinerary from ${t.start_date} to ${t.end_date} using my selected preferences.`);}catch(err){toast(err.message);}});
$('#ask-form').addEventListener('submit',e=>{e.preventDefault();send($('#question').value);});
$('#question').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('#ask-form').requestSubmit();}});
function closeJourney(){if($('#journey-panel').open)$('#journey-panel').close();}
function journeyTab(name){
 if(!['history','settings'].includes(name))return;
 $$('[data-journey-tab]').forEach(button=>{const active=button.dataset.journeyTab===name;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;});
 $('#journey-history').hidden=name!=='history';$('#journey-settings').hidden=name!=='settings';$('#journey-notice').hidden=true;
}
$('#open-journey').addEventListener('click',()=>{$('#journey-notice').hidden=true;$('#journey-panel').showModal();$('#open-journey').setAttribute('aria-expanded','true');$('.journey-tabs [aria-selected="true"]').focus();});
$('#close-journey').addEventListener('click',closeJourney);
$('#journey-panel').addEventListener('close',()=>{$('#open-journey').setAttribute('aria-expanded','false');$('#open-journey').focus();});
$('#journey-panel').addEventListener('click',event=>{if(event.target!==$('#journey-panel'))return;const bounds=event.target.getBoundingClientRect();if(event.clientX<bounds.left||event.clientX>bounds.right||event.clientY<bounds.top||event.clientY>bounds.bottom)closeJourney();});
$$('[data-journey-tab]').forEach(button=>button.addEventListener('click',()=>journeyTab(button.dataset.journeyTab)));
$('.journey-tabs').addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const current=$('.journey-tabs [aria-selected="true"]').dataset.journeyTab;const target=event.key==='Home'?'history':event.key==='End'?'settings':current==='history'?'settings':'history';journeyTab(target);$(`[data-journey-tab="${target}"]`).focus();});
$('#expand-chat').addEventListener('click',()=>expandChat(!document.body.classList.contains('chat-expanded')));
document.addEventListener('keydown',event=>{
 if(event.key==='Escape'&&document.body.classList.contains('chat-expanded')&&!$('dialog[open]')){expandChat(false);$('#expand-chat').focus();}
});
$('#new-chat').addEventListener('click',newChat);$('#use-model').addEventListener('change',modelLabel);
$('#history-rename-form').addEventListener('submit',saveHistoryRename);
$('#cancel-history-rename').addEventListener('click',()=>$('#history-rename-dialog').close());
$('#history-rename-dialog').addEventListener('close',()=>{pendingHistoryRename=null;});
$('#cancel-history-delete').addEventListener('click',()=>$('#history-delete-dialog').close());
$('#confirm-history-delete').addEventListener('click',confirmHistoryDelete);
$('#history-delete-dialog').addEventListener('close',()=>{const id=pendingHistoryDelete;pendingHistoryDelete=null;const button=$$('[data-delete-history]').find(b=>b.dataset.deleteHistory===id);button?.focus();});
$('#must-visit').addEventListener('change',()=>{const ids=[...$('#must-visit').selectedOptions].map(v=>v.value);state.must=new Set(ids);syncMust();});
$('#place-search').addEventListener('input',e=>{if(!e.isComposing)queueLibrarySearch();});$('#place-search').addEventListener('compositionend',()=>queueLibrarySearch());$('#library-region').addEventListener('change',()=>queueLibrarySearch(true));$('#library-search-form').addEventListener('submit',e=>{e.preventDefault();queueLibrarySearch(true);});
$('#close-dialog').addEventListener('click',()=>$('#detail-dialog').close());
$('#detail-dialog').addEventListener('click',e=>{if(e.target===$('#detail-dialog')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}});
document.addEventListener('click',async e=>{
 const view=e.target.closest('button[data-view],a[data-view]');if(view){e.preventDefault();switchView(view.dataset.view);return;}
 const interest=e.target.closest('[data-interest]');if(interest){const on=interest.getAttribute('aria-pressed')!=='true';interest.setAttribute('aria-pressed',String(on));interest.classList.toggle('selected',on);return;}
 const theme=e.target.closest('[data-theme]');if(theme){$$('[data-interest]').forEach(b=>{const on=b.dataset.interest===theme.dataset.theme;b.setAttribute('aria-pressed',String(on));b.classList.toggle('selected',on);});$('#home-form').requestSubmit();return;}
 const prompt=e.target.closest('[data-prompt]');if(prompt){send(prompt.dataset.prompt);return;}
 const open=e.target.closest('[data-history]');if(open){openHistory(open.dataset.history);return;}
 const filter=e.target.closest('[data-history-filter]');if(filter){state.historyFilter=filter.dataset.historyFilter;renderHistory();return;}
 const flag=e.target.closest('[data-history-flag]');if(flag){updateHistoryFlag(flag);return;}
 const rename=e.target.closest('[data-rename-history]');if(rename){requestHistoryRename(rename.dataset.renameHistory);return;}
 const del=e.target.closest('[data-delete-history]');if(del){requestHistoryDelete(del.dataset.deleteHistory);return;}
 const b=e.target.closest('[data-action]');if(!b)return;
 if(b.dataset.action==='must')addMust(b.dataset.id);
 if(b.dataset.action==='detail')showDetail(b.dataset.id);
 if(b.dataset.action==='amap')searchAmap(b.dataset.id,b);
 if(b.dataset.action==='download'){const t=state.turns[Number(b.closest('[data-turn]').dataset.turn)];downloadPlan(t?.result.plan);}
 if(b.dataset.action==='toggle-plan'){const box=b.closest('.chat-plan');const folded=box.dataset.folded!=='true';box.dataset.folded=String(folded);box.querySelectorAll('.map-panel,.map-actions,.route-result,.day-card,.plan-notes').forEach(v=>v.classList.toggle('hidden',folded));b.textContent=folded?'Expand':'Collapse';}
 if(b.dataset.action==='route')showRoute(b);
 if(b.dataset.action==='retry-init'){$('#app-error').classList.add('hidden');init();}
});
window.addEventListener('popstate',()=>switchView(location.hash.slice(1),false));window.addEventListener('hashchange',()=>switchView(location.hash.slice(1),false));switchView(location.hash.slice(1)||'home',false);init();
