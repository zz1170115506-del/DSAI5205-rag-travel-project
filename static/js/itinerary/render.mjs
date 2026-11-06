import {displayText,englishGuide} from '../core/english.mjs?v=20261029-en';
import {dateLabel} from '../core/trip-dates.mjs?v=20261029-en';
import {walkingMapHTML} from './walking-map.mjs?v=20261029-en';
const esc=v=>displayText(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sourceURL=v=>{try{const u=new URL(v);return u.protocol==='https:'?esc(u.href):'#';}catch{return '#';}};

export function createPlanRenderer({getStatus=()=>({}),traceHTML=()=>''}={}){
 const state={get status(){return getStatus();}};
function transitGuideHTML(g){
  g=englishGuide(g);
  if(!g)return '';
  return `<details class="transit-guide ${g.mode==='walk'?'walking-guide':''}" aria-label="Transport directions"><summary class="transit-heading"><strong>${esc(g.title)}</strong><span>${g.estimated_minutes===null?'Destination access first':'About '+esc(g.estimated_minutes)+' minutes · Estimate'}</span></summary>${g.origin_note?`<p class="transit-origin-note">${esc(g.origin_note)}</p>`:''}<ol class="transit-steps">${g.steps.map(step=>`<li class="transit-step ${esc(step.kind)}">${step.line_id?`<span class="rail-badge rail-${esc(step.line_id)}">${esc(step.line_name)} · ${esc(step.color_name)}</span>`:''}<span>${esc(step.text.replace(/；地图虚线不是实际步行路径。/g,'。'))}</span>${step.kind==='ride'?`<details class="station-sequence"><summary>Ride ${step.stop_count} stops · Show stations</summary><p>${step.stations.map(esc).join(' → ')}</p></details>`:''}</li>`).join('')}</ol><details class="transit-sources"><summary>${g.mode==='walk'?'Estimate and limitations':'Official transport sources'} · Checked ${esc(g.checked)}</summary>${g.sources.map(src=>`<a href="${sourceURL(src.url)}" target="_blank" rel="noopener noreferrer">${esc(src.name)} ↗</a>`).join('')}<p>${esc(g.notice)}</p></details></details>`;
}
function accessHTML(access){
 if(!access?.options?.length)return '';
 const first=access.options[0];
 return `<details class="stop-access"><summary>MTR access: ${esc(first.station)} station · ${esc(first.exit)} Exit${access.connector?' · Additional connection needed':''}</summary>${access.options.map(o=>`<p><strong>${esc(o.station)} station ${esc(o.exit)} Exit</strong> · ${esc(o.walk_note)} Allow about ${esc(o.walk_minutes)} minutes (estimate).${o.basis==='station_map_reference'?' Street access is based on the station map.':''}</p>`).join('')}${access.sources.map(src=>`<a href="${sourceURL(src.url)}" target="_blank" rel="noopener noreferrer">${esc(src.name)} ↗</a>`).join('')}<p>Exit information checked ${esc(access.checked)}; See the connection guide; current access and step-free travel are not guaranteed.</p></details>`;
}

function dayHTML(day,plan,index){
 const flex=day.kind==='flex',heading=`<span class="day-num">${String(day.day).padStart(2,'0')}</span><div><h3>${day.date?`<span class="day-date">${esc(dateLabel(day.date))} · ${esc(day.weekday)}</span>`:''}${esc(day.title)}</h3><p>${flex?'Rest / free time · Add activities as needed':`${day.stops.length} stops · Expected finish ${esc(day.end)}  · ${plan.history_transport_refreshed?'Original draft ':''}Estimated transfers: ${esc(day.transfer_minutes)} minutes`}</p></div>`;
 const route=day.stops.length>1&&day.stops.every(s=>s.place.provider!=='amap')?`<div class="map-actions"><span class="fine-print">Day ${day.day} · AMap walking route reference</span><button class="small-button" data-action="route" data-day="${index}">View AMap route${state.status.amap_configured?'':state.status.amap_enabled===false?' · Disabled':' · Not configured'} ↗</button></div><div class="route-result" data-route-day="${index}" aria-live="polite"></div>`:'';
 const body=flex?`<p class="flex-reason">${esc(day.reason)}</p><div class="flex-activities">${(day.activities??[]).map(a=>`<div><strong>${esc(a.period)}</strong><p>${esc(a.text)}</p></div>`).join('')}</div>`:`${route}${transitGuideHTML(day.start_guide)}${day.stops.map((stop,i)=>`<div class="stop"><div class="stop-time">${esc(stop.start)}<br>— ${esc(stop.end)}</div><div class="stop-content"><h4>${esc(stop.place.name)}</h4>${stop.place.provider==='amap'?'<span class="badge">AMap · Provisional stop</span>':''}<p>${esc(stop.place.summary)}</p>${stop.free_before_minutes?`<p class="fine-print">Free time before this stop: ${esc(stop.free_before_minutes)} minutes, allowing for evening activities. Adjust as needed.</p>`:''}${accessHTML(stop.transit_access)}${stop.place.provider==='amap'?`<a class="text-button" href="${sourceURL(stop.place.map_url)}" target="_blank" rel="noopener noreferrer">View location & source on AMap ↗</a>`:`<button class="text-button" data-action="detail" data-id="${esc(stop.place.id)}">Details & sources ↗</button>`}${day.legs[i]?`<div class="leg"><p>↓ Next: ${esc(day.stops[i+1].place.name)} · ${plan.history_transport_refreshed?'Original draft ':''}Allow for transport: ${esc(day.legs[i].minutes)} minutes (estimate)</p>${transitGuideHTML(day.legs[i].transit_guide)}${walkingMapHTML(stop.place,day.stops[i+1].place,day.legs[i],index===0&&i===0)}</div>`:''}</div></div>`).join('')}`;
 const content=body+`<p class="fine-print">${esc(day.meal_note)}</p>`;
 return plan.days.length>7?`<details class="day-card long-day ${flex?'flex-day':''}" ${index===0?'open':''}><summary class="day-heading">${heading}<span class="day-expand">Expand / collapse</span></summary><div class="day-body">${content}</div></details>`:`<article class="day-card ${flex?'flex-day':''}"><div class="day-heading">${heading}</div>${content}</article>`;
}
function planHTML(plan) {
 return `<div class="plan-tools"><h3>Your ${plan.days_requested??plan.days.length} day Hong Kong itinerary${plan.start_date?`<span class="plan-date-range">${esc(dateLabel(plan.start_date))} — ${esc(dateLabel(plan.end_date))}</span>`:''}</h3><button class="small-button" data-action="download">Download ↓</button></div><div class="plan-scroll" tabindex="0" role="region" aria-label="Scrollable itinerary">${plan.days.map((day,i)=>dayHTML(day,plan,i)).join('')}</div>`;
}

return {planHTML,dayHTML};
}
