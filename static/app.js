'use strict';
import {mapHTML,attachPlanMaps,disposeMaps} from './itinerary-map.js?v=1.3.23';
import {travelDates,addDays,dateLabel} from './trip-dates.mjs?v=1.3.8';
import {walkingMapHTML,attachWalkingMaps,disposeWalkingMaps} from './walking-map.mjs?v=1.3.23';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sourceURL=v=>{try{const u=new URL(v);return u.protocol==='https:'?esc(u.href):'#';}catch{return '#';}};
const mapsURL=p=>'https://www.google.com/maps/search/?api=1&query='+encodeURIComponent('香港 '+p.name);
const state={places:[],status:{},must:new Set(),turns:[],conversation:null,busy:false,ready:false,plan:null,histories:[],historyFilter:'all',historyBusy:false};
const welcome=$('#chat-messages').innerHTML;
let toastTimer, searchTimer, libraryRequest=0;
let historyRequest=0,pendingHistoryDelete=null,pendingHistoryRename=null;
const libraryPending=new Map(),libraryCache=new Map();
const loading=t=>`<div class="loading" role="status"><span class="spinner"></span><span>${esc(t)}</span></div>`;
const errorHTML=t=>`<div class="error" role="alert">${esc(t)}</div>`;
function toast(t){if($('#journey-panel').open){$('#journey-notice').textContent=t;$('#journey-notice').hidden=false;}clearTimeout(toastTimer);$('#toast').textContent=t;$('#toast').classList.remove('hidden');toastTimer=setTimeout(()=>$('#toast').classList.add('hidden'),3200);}
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
  try{const r=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,signal:c.signal});
    if(!r.ok){let obj={};try{obj=await r.json();}catch{}throw Error(typeof obj.detail==='string'?obj.detail:'服务暂不可用，请重试。');}return await r.json();
  }catch(e){if(e.name==='AbortError')throw Error('等待超时，请检查服务后重试。');if(e instanceof TypeError)throw Error('连接不到本地服务，请确认启动窗口仍在运行。');throw e;}finally{clearTimeout(timer);}
}
function syncMust(){$('#only-selected').disabled=state.busy||state.must.size===0;if(!state.must.size)$('#only-selected').checked=false;[...$('#must-visit').options].forEach(o=>o.selected=state.must.has(o.value));$$('[data-action="must"]').forEach(b=>{b.textContent=state.must.has(b.dataset.id)?'已加入 ✓':'加入必去 +';b.setAttribute('aria-pressed',String(state.must.has(b.dataset.id)));});}
function addMust(id){if(state.must.has(id)){state.must.delete(id);toast('已从必去地点移除');}else{state.must.add(id);toast('已加入必去地点，可在“问一问”规划');}syncMust();}

function card(p, i) {
  return `<article class="place-card"><div class="card-top"><span class="subtle">${esc(p.region)} / ${esc(p.area)}</span><span class="card-number">${String(i+1).padStart(2,'0')}</span></div><h3>${esc(p.name)}</h3><span class="card-en">${esc(p.en)}</span><div class="tags">${p.tags.map(t => `<span class="tag">${esc(t)}</span>`).join('')}<span class="tag">${p.kind === 'food' ? '餐饮候选' : p.indoor ? '有室内空间':'露天为主'}</span></div><p>${esc(p.summary)}</p><div class="card-actions"><button class="text-button" data-action="detail" data-id="${esc(p.id)}">查看详情 ↗</button><button class="small-button" data-action="must" data-id="${esc(p.id)}" aria-pressed="${state.must.has(p.id)}">${state.must.has(p.id)?'已加入 ✓':'加入必去 +'}</button><a href="${sourceURL(p.source)}" target="_blank" rel="noopener noreferrer">官方来源 ↗</a></div>${p.match_reason ? `<div class="match-note">${esc(p.match_reason)}</div>`:''}</article>`;
}

function traceHTML(trace) {
  if(!trace?.length)return '';
  return `<details class="trace"><summary>查看这次工具调用 · MCP 真实通信记录</summary>${trace.map(t => `<code>${esc(t.server)} · ${esc(t.transport)} · ${esc(t.elapsed_ms)} ms\n${esc(t.steps.join(' → '))}\n参数：${esc(JSON.stringify(t.arguments,null,2))}\n状态：${esc(t.status)}；高德实时调用：${t.live_amap ? '是':'否'}</code>`).join('')}</details>`;
}

function transitGuideHTML(g){
  if(!g)return '';
  return `<section class="transit-guide ${g.mode==='walk'?'walking-guide':''}" aria-label="具体交通指引"><div class="transit-heading"><strong>${esc(g.title)}</strong><span>${g.estimated_minutes===null?'先看出口与接驳':'约 '+esc(g.estimated_minutes)+' 分钟 · 估算'}</span></div>${g.origin_note?`<p class="transit-origin-note">${esc(g.origin_note)}</p>`:''}<ol class="transit-steps">${g.steps.map(step=>`<li class="transit-step ${esc(step.kind)}">${step.line_id?`<span class="rail-badge rail-${esc(step.line_id)}">${esc(step.line_name)} · ${esc(step.color_name)}</span>`:''}<span>${esc(step.text.replace(/；地图虚线不是实际步行路径。/g,'。'))}</span>${step.kind==='ride'?`<details class="station-sequence"><summary>乘坐 ${step.stop_count} 站 · 展开站序</summary><p>${step.stations.map(esc).join(' → ')}</p></details>`:''}</li>`).join('')}</ol><details class="transit-sources"><summary>${g.mode==='walk'?'估算依据与边界':'官方交通来源'} · 核对 ${esc(g.checked)}</summary>${g.sources.map(src=>`<a href="${sourceURL(src.url)}" target="_blank" rel="noopener noreferrer">${esc(src.name)} ↗</a>`).join('')}<p>${esc(g.notice)}</p></details></section>`;
}
function accessHTML(access){
 if(!access?.options?.length)return '';
 const first=access.options[0];
 return `<details class="stop-access"><summary>港铁到达参考：${esc(first.station)}站 · ${esc(first.exit)} 出口${access.connector?' · 另需接驳':''}</summary>${access.options.map(o=>`<p><strong>${esc(o.station)}站 ${esc(o.exit)} 出口</strong> · ${esc(o.walk_note)} 步行预留约 ${esc(o.walk_minutes)} 分钟（估算）。${o.basis==='station_map_reference'?' 街面衔接按站区图整理。':''}</p>`).join('')}${access.sources.map(src=>`<a href="${sourceURL(src.url)}" target="_blank" rel="noopener noreferrer">${esc(src.name)} ↗</a>`).join('')}<p>出口核对 ${esc(access.checked)}；接驳段请看交通指引，不保证当前开放或全程无障碍。</p></details>`;
}

function dayHTML(day,plan,index){
 const flex=day.kind==='flex',heading=`<span class="day-num">${String(day.day).padStart(2,'0')}</span><div><h3>${day.date?`<span class="day-date">${esc(dateLabel(day.date))} · ${esc(day.weekday)}</span>`:''}${esc(day.title)}</h3><p>${flex?'休息／自由活动 · 可按需补充地点':`${day.stops.length} 个停留点 · 预计 ${esc(day.end)} 结束 · ${plan.history_transport_refreshed?'原草案':''}转场估算共 ${esc(day.transfer_minutes)} 分钟`}</p></div>`;
 const route=day.stops.length>1?`<div class="map-actions"><span class="fine-print">第 ${day.day} 天 · 高德步行参考路线</span><button class="small-button" data-action="route" data-day="${index}">查看高德路线${state.status.amap_configured?'':state.status.amap_enabled===false?' · 未启用':' · 待配置'} ↗</button></div><div class="route-result" data-route-day="${index}" aria-live="polite"></div>`:'';
 const body=flex?`<p class="flex-reason">${esc(day.reason)}</p><div class="flex-activities">${(day.activities??[]).map(a=>`<div><strong>${esc(a.period)}</strong><p>${esc(a.text)}</p></div>`).join('')}</div>`:`${route}${transitGuideHTML(day.start_guide)}${day.stops.map((stop,i)=>`<div class="stop"><div class="stop-time">${esc(stop.start)}<br>— ${esc(stop.end)}</div><div class="stop-content"><h4>${esc(stop.place.name)}</h4><p>${esc(stop.place.summary)}</p>${stop.free_before_minutes?`<p class="fine-print">此站前留有 ${esc(stop.free_before_minutes)} 分钟自由活动时间，便于衔接傍晚安排；可自行调整。</p>`:''}${accessHTML(stop.transit_access)}<button class="text-button" data-action="detail" data-id="${esc(stop.place.id)}">详情与出处 ↗</button>${day.legs[i]?`<div class="leg"><p>↓ 前往 ${esc(day.stops[i+1].place.name)} · ${plan.history_transport_refreshed?'原草案':''}交通预留 ${esc(day.legs[i].minutes)} 分钟（估算）</p>${transitGuideHTML(day.legs[i].transit_guide)}${walkingMapHTML(stop.place,day.stops[i+1].place,day.legs[i],index===0&&i===0)}</div>`:''}</div></div>`).join('')}`;
 const content=body+`<p class="fine-print">${esc(day.meal_note)}</p>`;
 return plan.days.length>7?`<details class="day-card long-day ${flex?'flex-day':''}" ${index===0?'open':''}><summary class="day-heading">${heading}<span class="day-expand">展开 / 收起</span></summary><div class="day-body">${content}</div></details>`:`<article class="day-card ${flex?'flex-day':''}"><div class="day-heading">${heading}</div>${content}</article>`;
}
function planHTML(plan) {
 const coverage=plan.coverage,summary=coverage?`<p class="plan-coverage">共 ${coverage.calendar_days} 天 · ${coverage.sightseeing_days} 天地点行程${coverage.flex_days?` · ${coverage.flex_days} 天休息／自由活动`:''}${plan.days.length>7?' · 点击日期卡展开详情':''}</p>`:'';
 return `<div class="plan-tools"><h3>你的 ${plan.days_requested??plan.days.length} 天香港草案${plan.start_date?`<span class="plan-date-range">${esc(dateLabel(plan.start_date))} — ${esc(dateLabel(plan.end_date))}</span>`:''}</h3><div><button class="small-button" data-action="download">下载行程 ↓</button> <button class="small-button" data-action="toggle-plan">收起</button></div></div>${plan.only_selected?'<p class="selection-note">已按你的选择，只安排所选地点；未自动补入其他景点。</p>':''}${summary}${plan.history_transport_refreshed?'<p class="fine-print">这份历史草案已补上新版交通参考；原时间表未重排，建议重新规划更新时间。</p>':''}${mapHTML(plan)}${plan.days.map((day,i)=>dayHTML(day,plan,i)).join('')}<div class="plan-notes">${plan.warnings.map(w=>`<p>· ${esc(w)}</p>`).join('')}</div>${traceHTML(plan.trace)}`;
}

function downloadPlan(plan=state.plan) {
  if(!plan)return;
  const lines=['港慢游｜香港旅行草案','线路与出口为官方资料的本地参考；时间为估算，出发前核对运营、出口、天气与票务。',''];
  if(plan.start_date)lines.push(`旅行日期：${plan.start_date} 至 ${plan.end_date}（共 ${plan.days_requested} 天，包含首尾当天）`,'');
  const appendGuide=g=>{if(!g)return;lines.push(g.title,g.origin_note||'');g.steps.forEach((step,i)=>lines.push(`${i+1}. ${step.text}`));if(g.estimated_minutes!==null)lines.push(`交通参考预留约 ${g.estimated_minutes} 分钟（项目估算）`);g.sources.forEach(src=>lines.push(`交通来源：${src.name} ${src.url}（核对 ${src.checked}）`));lines.push(g.notice,'');};
  if(plan.history_transport_refreshed)lines.push('历史时间表未重排，请按新版交通参考重新规划。','');
  for(const day of plan.days) {
    lines.push(`第 ${day.day} 天｜${day.date?day.date+' · '+day.weekday+'｜':''}${day.title}`);
    if(day.kind==='flex'){lines.push(day.reason,...(day.activities??[]).map(a=>`${a.period}：${a.text}`));}
    appendGuide(day.start_guide);
    day.stops.forEach((stop,i)=>{
      if(stop.free_before_minutes)lines.push(`此站前自由活动约 ${stop.free_before_minutes} 分钟`);
      lines.push(`${stop.start}–${stop.end} ${stop.place.name}`,stop.place.summary,`来源：${stop.place.source}`);
      for(const option of stop.transit_access?.options??[])lines.push(`港铁到达参考：${option.station}站 ${option.exit} 出口。${option.walk_note}`);
      if(day.legs[i]){lines.push(`下一站：${day.stops[i+1].place.name}；交通预留 ${day.legs[i].minutes} 分钟（估算）`);appendGuide(day.legs[i].transit_guide);}
      lines.push('');
    });lines.push(day.meal_note,'');
  }
  lines.push('出发前核对',...plan.warnings.map(w=>'· '+w),'',`资料版本：${state.status.knowledge_version}`,`交通资料版本：${plan.transit_version??'未提供'}`,`规划方法：${plan.algorithm}`);
  const blob=new Blob(['\ufeff'+lines.join('\n')],{type:'text/plain;charset=utf-8'});
  const url=URL.createObjectURL(blob), a=document.createElement('a');a.href=url;a.download='港慢游_香港行程.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('行程与交通指引已导出');
}
function showDetail(id) {
  const p=state.places.find(p=>p.id===id); if(!p)return;
  $('#detail-content').innerHTML=`<span class="eyebrow">${esc(p.region)} / ${esc(p.area)}</span><h2>${esc(p.name)}</h2><span class="card-en">${esc(p.en)}</span><div class="tags">${p.tags.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div><p>${esc(p.summary)}</p><p class="tip">${esc(p.tip)}</p><p class="fine-print">建议停留 ${esc(p.duration)} 分钟，为本项目规划假设。资料摘要核对日 ${esc(p.checked)}，不代表营业、票价和活动实时有效。</p><div class="detail-actions"><a href="${sourceURL(p.source)}" target="_blank" rel="noopener noreferrer">官方资料 ↗</a><a href="${esc(mapsURL(p))}" target="_blank" rel="noopener noreferrer">在地图中查找 ↗</a><button class="small-button" data-action="must" data-id="${esc(p.id)}">${state.must.has(p.id)?'已加入 ✓':'加入必去 +'}</button><button class="small-button" data-action="amap" data-id="${esc(p.id)}">高德查询${state.status.amap_configured?'':state.status.amap_enabled===false?' · 未启用':' · 待配置'}</button></div><div id="amap-result"></div>`;
  if(!$('#detail-dialog').open)$('#detail-dialog').showModal();
}
async function searchAmap(id,btn) {
  btn.disabled=true; $('#amap-result').innerHTML=loading('检查高德服务配置……');
  try{const res=await api('/api/amap/search',{place_id:id});$('#amap-result').innerHTML=`<p class="fine-print">${esc(res.message)}</p>${res.results ? `<pre>${esc(JSON.stringify(res.results,null,2))}</pre>`:''}`;}
  catch(err){$('#amap-result').innerHTML=errorHTML(err.message);}
  finally{btn.disabled=false;}
}


function readTrip(){const start=$('#start-date').value,end=$('#end-date').value;const dates=start||end?travelDates(start,end):{days:$('#days').value?Number($('#days').value):null,start_date:null,end_date:null};return{...dates,region:$('#plan-region').value,pace:$('input[name="pace"]:checked').value,interests:$$('#interest-options input:checked').map(v=>v.value),rain:$('#rain').checked,public_only:$('#public-only').checked,must_visit:[...state.must],only_selected:state.must.size>0&&$('#only-selected').checked,start_station:$('#start-station').value,excluded_places:state.tripMemory?.excluded_places??[]};}
function applyTrip(t){state.tripMemory=t;
  $('#start-date').value=t.start_date??'';$('#end-date').value=t.end_date??'';updateDateHint('plan');
  $('#start-station').value=t.start_station??'';$('#days').value=t.days??'';$('#plan-region').value=t.region??'全部';$$('input[name="pace"]').forEach(v=>v.checked=v.value===(t.pace??'轻松'));
  $$('#interest-options input').forEach(v=>v.checked=(t.interests??['海港夜景','本地美食']).includes(v.value));$('#rain').checked=!!t.rain;$('#public-only').checked=!!t.public_only;state.must=new Set(t.must_visit??[]);syncMust();$('#only-selected').checked=!!t.only_selected&&state.must.size>0;
  $('#trip-memory').textContent=`这趟旅程：${t.region??'全部'} · ${t.start_date?t.start_date+' 至 '+t.end_date+' · ':''}${t.days??'待确认'} 天 · ${t.pace??'轻松'} · ${t.rain?'只选室内':'不限室内'}${t.public_only?' · 景点限公共空间':''}${t.start_station?' · 从'+t.start_station+'站出发':''}${t.only_selected?' · 只安排已选地点':''}${t.excluded_places?.length?' · 已排除 '+t.excluded_places.map(id=>state.places.find(p=>p.id===id)?.name??id).join('、'):''}${state.must.size?' · 必去 '+[...state.must].map(id=>state.places.find(p=>p.id===id)?.name??id).join('、'):''}`;
}
function setBusy(value){state.busy=value;$$('#plan-form input,#plan-form select').forEach(field=>field.disabled=value);if(!value)$('#only-selected').disabled=state.must.size===0;['#ask-submit','#plan-submit','#home-submit','#new-chat'].forEach(s=>$(s).disabled=value||!state.ready);$('#use-model').disabled=value||!state.status.model_configured;$$('.history-row button').forEach(b=>b.disabled=value||state.historyBusy);$$('.suggestions button').forEach(b=>b.disabled=value);}
function modelLabel(){const model=$('#use-model').checked;$('#chat-mode').textContent=model?'大模型多轮助手':'本地规则演示';$('#model-mode-note').textContent=model?'已开启：模型会结合最近对话、偏好与已有行程理解追问；这些内容将发送给所配置的模型服务。':'当前为本地规则演示。开启“使用大模型”后，才能由模型理解上下文与行程修改。';}
function inlineText(answer){const valid=new Set(answer.citations??[]);return esc(answer.text).replace(/\[([a-z0-9-]+)\]/g,(all,id)=>valid.has(id)?`<button class="inline-citation" data-action="detail" data-id="${esc(id)}">出处 ↗</button>`:all);}
function externalHTML(data,showMessage=true){
  if(!data)return '';
  if(data.mode==='local')return `<p class="fine-print">找到本地官方来源记录。</p><div class="cards-grid">${data.results.map(card).join('')}</div>`;
  return `${showMessage?`<p class="fine-print">${esc(data.message)}</p>`:''}${data.mode!=='live'&&data.search_links?.length?`<div class="map-search-links">${data.search_links.map(link=>`<a class="small-button" href="${sourceURL(link.url)}" target="_blank" rel="noopener noreferrer">${esc(link.name)} ↗</a>`).join('')}<span class="fine-print">跳转搜索，尚未取得地点数据。</span></div>`:''}<div class="external-results">${(data.results??[]).map(p=>`<article class="external-card"><span class="badge">高德地图 · 未人工审核</span><h4>${esc(p.name)}</h4><p>${esc(p.address||p.district||'地址未提供')}</p><p>${esc(p.category)} · 坐标 ${esc(p.location?.join(', '))}</p><a href="${sourceURL(p.map_url)}" target="_blank" rel="noopener noreferrer">在高德地图查看 ↗</a><p>数据来源：${esc(p.source?.name)} · ${esc(p.source?.fetched_at)}</p><details><summary>查看地点 JSON 与来源</summary><pre>${esc(JSON.stringify(p,null,2))}</pre></details></article>`).join('')}</div>`;
}
function renderTurns(){
 disposeWalkingMaps();disposeMaps();
 $('#chat-messages').innerHTML=state.turns.length?state.turns.map((turn,i)=>{const d=turn.result;return `<article class="chat-turn" data-turn="${i}"><div class="user-message"><p>${esc(turn.question)}</p></div><div class="assistant-message"><div class="assistant-name"><span>✧ 港慢游 · 旅行助手</span><span>${d.answer.mode==='model'?'模型模式':d.answer.mode==='map_lookup'?'地图补充':'本地资料'}</span></div><div class="answer-text">${inlineText(d.answer)}</div>${externalHTML(d.external_lookup,false)}${d.sources?.length?`<div class="chat-sources">${d.sources.map(p=>`<button class="small-button" data-action="detail" data-id="${esc(p.id)}">${esc(p.name)} · 出处 ↗</button>`).join('')}</div>`:''}${d.plan?`<div class="chat-plan">${planHTML({...d.plan,trace:[]})}</div>`:''}<details class="trace"><summary>资料与执行记录 · ${esc(d.answer.notice)}</summary><code>${esc(JSON.stringify({metrics:d.metrics,stop_reason:d.stop_reason,steps:d.trace},null,2))}</code></details></div></article>`;}).join(''):welcome;
 syncMust();attachPlanMaps($('#chat-messages'),state.turns);attachWalkingMaps($('#chat-messages'),state.places,api);
}
function rememberId(){try{if(state.conversation)localStorage.setItem('hk-travel-active-v13',state.conversation);else localStorage.removeItem('hk-travel-active-v13');}catch{toast('浏览器未保存当前对话入口，仍可从最近对话重新打开。');}}
function historyIcon(kind){return `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${{favorite:'<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3l-5.6 2.9 1.1-6.2L3 9.6l6.2-.9Z"/>',pinned:'<path d="m16 3 5 5-4 2-3 5-2 1-4-4 1-2 5-3Z"/><path d="m9 15-6 6"/>',rename:'<path d="m16 3 5 5-12 12-6 1 1-6Z"/><path d="m13 6 5 5"/>',delete:'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>'}[kind]}</svg>`;}
function renderHistory(){
 const favoriteCount=state.histories.filter(c=>c.favorite).length;
 $('#history-favorite-count').textContent=favoriteCount;
 $$('[data-history-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.historyFilter===state.historyFilter)));
 const rows=state.histories.filter(c=>state.historyFilter!=='favorite'||c.favorite);
 $('#history-list').innerHTML=rows.length?rows.map(c=>`<div class="history-row ${c.id===state.conversation?'active':''} ${c.pinned?'is-pinned':''}"><button class="history-open" data-history="${esc(c.id)}" title="${esc(c.title)}${c.pinned?' · 已置顶':''}" aria-current="${c.id===state.conversation?'true':'false'}">${esc(c.title)}</button><div class="history-actions">${['favorite','pinned'].map(flag=>{const label=(flag==='favorite'?(c.favorite?'取消收藏':'收藏'):(c.pinned?'取消置顶':'置顶'));return `<button class="history-icon history-${flag}" data-history-flag="${flag}" data-history-id="${esc(c.id)}" data-flag-value="${!c[flag]}" aria-pressed="${!!c[flag]}" title="${label}" aria-label="${label}对话 ${esc(c.title)}">${historyIcon(flag)}</button>`;}).join('')}<button class="history-icon history-rename" data-rename-history="${esc(c.id)}" title="重命名" aria-label="重命名对话 ${esc(c.title)}">${historyIcon('rename')}</button><button class="history-icon history-delete" data-delete-history="${esc(c.id)}" title="删除" aria-label="删除对话 ${esc(c.title)}">${historyIcon('delete')}</button></div></div>`).join(''):`<p class="fine-print history-empty">${state.historyFilter==='favorite'?'还没有收藏，点击对话旁的星标即可收藏。':'从一个旅行想法开始。'}</p>`;
 $$('.history-row button').forEach(b=>b.disabled=state.busy||state.historyBusy);
}
async function loadHistory(){const request=++historyRequest,data=await api('/api/history');if(request!==historyRequest)return;state.histories=data.conversations;$('#history-count').textContent=`${data.conversations.length} / ${data.capacity}`;renderHistory();}
async function updateHistoryFlag(button){
 if(state.busy||state.historyBusy)return;
 const id=button.dataset.historyId,flag=button.dataset.historyFlag;
 if(!['favorite','pinned'].includes(flag))return;
 state.historyBusy=true;renderHistory();
 try{await api('/api/history/update',{id,[flag]:button.dataset.flagValue==='true'});await loadHistory();toast(flag==='favorite'?(button.dataset.flagValue==='true'?'已收藏这段对话':'已取消收藏'):(button.dataset.flagValue==='true'?'已置顶这段对话':'已取消置顶'));}
 catch(e){toast(e.message);}finally{state.historyBusy=false;renderHistory();const focus=$$('.history-row [data-history-flag]').find(b=>b.dataset.historyId===id&&b.dataset.historyFlag===flag);(focus??$('[data-history-filter="favorite"]')).focus();}
}
function requestHistoryRename(id){
 if(state.busy||state.historyBusy)return;
 const row=state.histories.find(c=>c.id===id);if(!row)return;
 pendingHistoryRename=id;$('#history-rename-input').value=row.title;$('#history-rename-error').textContent='';$('#history-rename-dialog').showModal();$('#history-rename-input').select();
}
async function saveHistoryRename(event){
 event.preventDefault();if(!pendingHistoryRename||state.busy||state.historyBusy)return;
 const title=$('#history-rename-input').value.trim();if(!title){$('#history-rename-error').textContent='请输入对话名称。';return;}
 const id=pendingHistoryRename;state.historyBusy=true;renderHistory();$('#save-history-rename').disabled=true;
 try{await api('/api/history/rename',{id,title});await loadHistory();$('#history-rename-dialog').close();toast('已重命名对话');}
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
 try{await api('/api/history/delete',{id});$('#history-delete-dialog').close();if(state.conversation===id)newChat();await loadHistory();toast('已删除这段本机历史');$('#new-chat').focus();}
 catch(e){$('#history-delete-error').textContent=e.message;}
 finally{state.historyBusy=false;$('#confirm-history-delete').disabled=false;renderHistory();}
}
async function openHistory(id){if(state.busy)return;try{const saved=await api('/api/history/read',{id});state.conversation=id;state.turns=saved.turns;$('#use-model').checked=!!saved.use_model&&!!state.status.model_configured;modelLabel();applyTrip(saved.checkpoint.trip);renderTurns();rememberId();await loadHistory();switchView('ask');$('#chat-scroll').scrollTop=$('#chat-scroll').scrollHeight;}catch(e){toast(e.message);}}
function newChat(){if(state.busy)return;state.conversation=null;state.turns=[];$('#use-model').checked=false;modelLabel();rememberId();applyTrip({});renderTurns();$('#question').value='';loadHistory().catch(e=>toast(e.message));}
async function send(question){
 question=question.trim();if(!state.ready||state.busy||question.length<2)return;
 switchView('ask');setBusy(true);$('#chat-messages').insertAdjacentHTML('beforeend',loading($('#use-model').checked?'正在查找资料、选择工具并整理建议……':'正在检索资料、按条件安排旅程……'));$('#chat-scroll').scrollTop=$('#chat-scroll').scrollHeight;
 try{const data=await api('/api/chat',{question,conversation_id:state.conversation,use_model:$('#use-model').checked,trip:readTrip()});state.conversation=data.conversation_id;state.turns.push({question,result:data});state.turns=state.turns.slice(-20);applyTrip(data.trip);$('#question').value='';rememberId();renderTurns();await loadHistory();$('#chat-scroll').scrollTop=$('#chat-scroll').scrollHeight;}
 catch(e){renderTurns();$('#chat-messages').insertAdjacentHTML('beforeend',errorHTML(e.message));$('#chat-scroll').scrollTop=$('#chat-scroll').scrollHeight;}
 finally{setBusy(false);}
}
function queueLibrarySearch(immediate=false){
 clearTimeout(searchTimer);const id=++libraryRequest;
 $('#library-notice').innerHTML='';$('#place-grid').innerHTML='';$('#library-count').textContent='';
 if($('#place-search').value.trim().length===1){$('#place-grid').setAttribute('aria-busy','false');$('#library-notice').innerHTML='<p class="search-notice">请输入至少 2 个字符，清空可查看本地全部地点。</p>';return;}
 if(immediate)filterLibrary(id);else searchTimer=setTimeout(()=>filterLibrary(id),650);
}
async function filterLibrary(id){
 const payload={query:$('#place-search').value.trim(),region:$('#library-region').value},key=JSON.stringify(payload);
 $('#place-grid').setAttribute('aria-busy','true');$('#place-grid').classList.add('external-mode');
 $('#place-grid').innerHTML=loading('正在检索资料库；未收录的地点将自动向高德查询……');
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
   $('#library-notice').innerHTML=payload.query?`<p class="search-notice">${result.results.length?'资料库内找到 '+result.results.length+' 个相关地点。':esc(result.message)}</p>`:'';
   $('#library-count').textContent=result.results.length+' 个本地地点';
  }else{
   $('#library-notice').innerHTML=`<div class="search-notice map-supplement"><strong>资料库中未找到“${esc(result.query)}”</strong><p>${result.mode==='live'?'已自动调用高德，以下为地图返回的 '+result.results.length+' 个候选地点。':esc(result.message)}</p></div>`;
   $('#place-grid').innerHTML=externalHTML(result,false);
   $('#library-count').textContent=result.mode==='live'?result.results.length+' 个高德候选':result.mode==='empty'?'高德暂无结果':result.mode==='filtered_external'?'当前地区无候选':'高德查询未完成';
  }
  syncMust();
 }catch(e){if(id===libraryRequest){$('#place-grid').innerHTML=errorHTML(e.message);$('#library-count').textContent='查询未完成';}}
 finally{if(id===libraryRequest)$('#place-grid').setAttribute('aria-busy','false');}
}
function geometryHTML(lines){
 const valid=lines.flat().filter(p=>Array.isArray(p)&&p.length===2&&p.every(Number.isFinite));if(valid.length<2)return '';
 const xs=valid.map(p=>p[0]),ys=valid.map(p=>p[1]),minX=Math.min(...xs),minY=Math.min(...ys),dx=Math.max(.001,Math.max(...xs)-minX),dy=Math.max(.001,Math.max(...ys)-minY);
 return `<svg class="route-geometry" viewBox="0 0 640 300" role="img" aria-label="高德返回的步行路径，无地图底图">${lines.map(line=>`<polyline points="${line.filter(p=>p.every(Number.isFinite)).map(p=>`${25+(p[0]-minX)/dx*590},${275-(p[1]-minY)/dy*250}`).join(' ')}" fill="none" stroke="#216653" stroke-width="3"/>`).join('')}</svg>`;
}
async function showRoute(button){
 const turn=state.turns[Number(button.closest('[data-turn]').dataset.turn)],day=turn?.result.plan?.days[Number(button.dataset.day)];if(!day)return;
 const target=button.closest('.chat-plan').querySelector(`[data-route-day="${Number(button.dataset.day)}"]`);button.disabled=true;target.innerHTML=loading('正在核对高德地点与步行路线……');
 try{const data=await api('/api/amap/route',{place_ids:day.stops.map(s=>s.place.id).slice(0,6)});if(data.mode!=='live'){target.innerHTML=`<div class="error">${esc(data.message)}</div>`;return;}
 const image=typeof data.map_image==='string'&&/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(data.map_image)?`<img class="route-image" src="${data.map_image}" alt="高德地图返回的步行路线图，含供应商署名">`:geometryHTML(data.polylines);
 target.innerHTML=`${image}<p class="fine-print">高德步行参考：${(data.distance_m/1000).toFixed(1)} 公里 · 约 ${Math.ceil(data.duration_s/60)} 分钟。${esc(data.message)}${data.map_image?'':' 当前仅渲染返回的路径，无地图底图。'}<br>来源：${esc(data.source.name)} · ${esc(data.source.fetched_at)}</p>`;
 }catch(e){target.innerHTML=errorHTML(e.message);}finally{button.disabled=false;}
}
function statusHTML(s){
 const r=s.retrieval||{};
 const hybrid=r.configured_mode==='hybrid';
 const ready=r.index_ready&&r.dependency_available;
 const retrievalLabel=hybrid?(ready?'语义＋关键词 · 索引就绪':'关键词检索 · 语义待准备'):'关键词检索';
 const retrievalNote=hybrid?'结合语义相似度与关键词查找相关地点；语义检索不可用时自动使用关键词检索。每条回答可查看实际检索方式与出处。':'按名称、街区和文本关键词查找相关地点，回答可查出处与执行记录。';
 return `<div class="status-card"><h3>本地资料与检索</h3><span class="badge">${s.place_count} 条 · ${retrievalLabel}</span><p>${retrievalNote}</p></div><div class="status-card"><h3>大模型工具助手</h3><span class="badge">${s.model_configured?'已配置 · 手动开启':'尚未配置'}</span><p>${s.model_configured?esc(s.model_name)+' 可用于问答与工具选择。':'当前使用规则工具演示。'}开启后，问题、有限历史及工具资料会发送给配置的模型服务。</p></div><div class="status-card"><h3>高德地点与路线</h3><span class="badge">${s.amap_configured?'已配置 · 按需查询':s.amap_enabled===false?'自动查询未启用':'尚未配置 · 不发外部请求'}</span><p>行程默认显示 OpenStreetMap 真实底图，无需高德 Key。高德另提供地点查询和步行路线接口，启用后需验证香港覆盖和权限。</p></div>`;
}
async function init(){
 try{const [s,data]=await Promise.all([api('/api/status'),api('/api/places')]);state.status=s;state.places=data.places;
  $('#place-count').textContent=s.place_count;$('#data-version').textContent=s.knowledge_version;$('#status-grid').innerHTML=statusHTML(s);
  $('#interest-options').innerHTML=s.interests.map(t=>`<label><input type="checkbox" value="${esc(t)}" ${['海港夜景','本地美食'].includes(t)?'checked':''}><span>${esc(t)}</span></label>`).join('');
  $('#must-visit').innerHTML=state.places.map(p=>`<option value="${esc(p.id)}">${esc(p.name)} · ${esc(p.region)}</option>`).join('');$('#place-grid').innerHTML=state.places.map(card).join('');$('#library-count').textContent=`${data.places.length} 个地点`;
  $('#start-station').innerHTML='<option value="">暂不指定 · 先看目的地出口</option>'+s.transit_stations.map(name=>`<option value="${esc(name)}">${esc(name)}站</option>`).join('');
  $('#home-start-date').value=s.today_hk;$('#home-end-date').value=addDays(s.today_hk,1);updateDateHint('home');
  $('#model-hint').textContent=s.model_configured?s.model_name:'待配置';state.ready=true;setBusy(false);await loadHistory();
  let saved;try{saved=localStorage.getItem('hk-travel-active-v13');}catch{}if(saved&&/^[a-f0-9]{32}$/.test(saved)){try{const record=await api('/api/history/read',{id:saved});state.conversation=saved;state.turns=record.turns;applyTrip(record.checkpoint.trip);$('#use-model').checked=!!record.use_model&&!!s.model_configured;renderTurns();await loadHistory();}catch{state.conversation=null;rememberId();}}
  modelLabel();$('.trip-settings').open=true;
 }catch(e){$('#app-error').innerHTML=`${esc(e.message)} <button class="small-button" data-action="retry-init">重试连接</button>`;$('#app-error').classList.remove('hidden');}
}
function updateDateHint(scope){
 const home=scope==='home',start=$(home?'#home-start-date':'#start-date'),end=$(home?'#home-end-date':'#end-date'),hint=$(home?'#home-date-hint':'#plan-date-hint');
 start.setCustomValidity('');end.setCustomValidity('');
 try{const dates=travelDates(start.value,end.value);hint.textContent=`共 ${dates.days} 天 · 包含出发与结束当天`;hint.classList.remove('date-invalid');if(!home)$('#days').value=dates.days;}
 catch(e){hint.textContent=!start.value&&!end.value?'选择日期，自动计算天数':e.message;hint.classList.toggle('date-invalid',!!(start.value||end.value));if(start.value||end.value)end.setCustomValidity(e.message);}
}
for(const scope of ['home','plan'])for(const selector of scope==='home'?['#home-start-date','#home-end-date']:['#start-date','#end-date'])$(selector).addEventListener('input',()=>updateDateHint(scope));
$('#home-form').addEventListener('submit',e=>{e.preventDefault();if(!state.ready||state.busy)return;
 try{const dates=travelDates($('#home-start-date').value,$('#home-end-date').value),t={...dates,region:$('#home-region').value,pace:$('#home-pace').value,interests:$$('[data-interest][aria-pressed="true"]').map(b=>b.dataset.interest),rain:false,public_only:false,must_visit:[...state.must]};newChat();applyTrip(t);send(`请安排香港${t.start_date}至${t.end_date}的${t.days}天行程，${t.region==='全部'?'不限地区':t.region}，节奏${t.pace}。`);}catch(err){toast(err.message);}
});
$('#plan-form').addEventListener('submit',e=>{e.preventDefault();try{const t=readTrip();send(`请按已选偏好安排${t.start_date}至${t.end_date}的${t.days}天行程。`);}catch(err){toast(err.message);}});
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
 if(b.dataset.action==='toggle-plan'){const box=b.closest('.chat-plan');const folded=box.dataset.folded!=='true';box.dataset.folded=String(folded);box.querySelectorAll('.map-panel,.map-actions,.route-result,.day-card,.plan-notes').forEach(v=>v.classList.toggle('hidden',folded));b.textContent=folded?'展开':'收起';}
 if(b.dataset.action==='route')showRoute(b);
 if(b.dataset.action==='retry-init'){$('#app-error').classList.add('hidden');init();}
});
window.addEventListener('popstate',()=>switchView(location.hash.slice(1),false));window.addEventListener('hashchange',()=>switchView(location.hash.slice(1),false));switchView(location.hash.slice(1)||'home',false);init();
