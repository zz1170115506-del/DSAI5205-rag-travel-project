import {displayText} from './english.mjs?v=20261029-en';
// Walking routes and images are supplied by AMap; no sketch line or alternate basemap.
const esc=v=>displayText(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const maps=new Set(),cache=new Map(),pending=new Map();
let observer;
export function walkingLink(a,b){return 'https://www.google.com/maps/dir/?'+new URLSearchParams({api:'1',origin:'Hong Kong '+a.name,destination:'Hong Kong '+b.name,travelmode:'walking'});}
export function walkingMapHTML(a,b,leg,open=false){
 if(leg?.transit_guide?.mode!=='walk'||!a||!b||a.id===b.id)return '';
 return `<details class="walk-mini-panel" data-walk-origin="${esc(a.id)}" data-walk-destination="${esc(b.id)}" ${open?'open':''}><summary><strong>Walking map <span aria-hidden="true">↗</span></strong><span>${esc(a.name)} → ${esc(b.name)}</span></summary><div class="walk-mini-body"><div class="walk-route-result" aria-live="polite"><div class="walk-route-placeholder" role="status">Loading the AMap walking route...</div></div><div class="walk-mini-actions"><button type="button" class="small-button" data-walk-fetch hidden>Retry</button><button type="button" class="small-button" data-walk-reset hidden>Change route locations</button><a href="${esc(walkingLink(a,b))}" target="_blank" rel="noopener noreferrer">Other navigation ↗</a></div></div></details>`;
}
export function disposeWalkingMaps(){observer?.disconnect();for(const item of maps)item.disposed=true;maps.clear();}
function routeImage(value){return typeof value==='string'&&value.length<=2100000&&/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(value)?value:null;}
function navigationURL(value){try{const url=new URL(value);return url.origin==='https://uri.amap.com'&&url.pathname==='/direction'?url.href:null;}catch{return null;}}
async function getRoute(key,args,api){
 const saved=cache.get(key);if(saved&&Date.now()-saved.time<600000)return saved.value;
 let request=pending.get(key);
 if(!request){request=api('/api/walking-map',args).then(value=>{if(value.mode==='live'||(value.mode==='ambiguous_location'&&value.candidates)){if(cache.size>=20)cache.delete(cache.keys().next().value);cache.set(key,{value,time:Date.now()});}return value;}).finally(()=>pending.delete(key));pending.set(key,request);}
 return request;
}
export function attachWalkingMaps(root,places,api){
 const byId=new Map(places.map(p=>[p.id,p]));
 observer=new IntersectionObserver(entries=>{for(const entry of entries){const host=entry.target;if(!entry.isIntersecting||!host.clientWidth||!host.clientHeight)continue;observer.unobserve(host);mount(host,byId,api);}},{threshold:.05});
 root.querySelectorAll('.walk-route-result').forEach(host=>observer.observe(host));
}
function mount(target,byId,api){
 const wrapper=target.closest('.walk-mini-panel'),a=byId.get(wrapper.dataset.walkOrigin),b=byId.get(wrapper.dataset.walkDestination);
 if(!a||!b)return;
 const button=wrapper.querySelector('[data-walk-fetch]'),reset=wrapper.querySelector('[data-walk-reset]');
 const item={disposed:false};maps.add(item);
 let choiceData=null,selectedArgs=null;
 function show(data){
  if(item.disposed||!wrapper.isConnected)return;
  if(data.mode==='ambiguous_location'&&data.candidates){
   choiceData=data.candidates;selectedArgs=null;reset.hidden=true;
   target.innerHTML=`<p class="walk-route-notice">Several places share this name. Confirm the start and destination.</p><div class="walk-poi-choices">${[[a,'origin'],[b,'destination']].map(([place,key])=>`<label>${key==='origin'?'Start':'Destination'} · ${esc(place.name)}<select data-walk-choice="${key}">${(data.candidates[place.id]??[]).length>1?'<option value="">Select a location</option>':''}${(data.candidates[place.id]??[]).map(poi=>`<option value="${esc(poi.id)}">${esc(poi.name)} · ${esc(poi.address||poi.district||'Open the provider map for the source address')}</option>`).join('')}</select></label>`).join('')}</div><details class="walk-map-notes"><summary>View location candidates</summary><div class="walk-candidate-links">${Object.values(data.candidates).flat().map(poi=>`<a href="${esc(poi.map_url)}" target="_blank" rel="noopener noreferrer">${esc(poi.name)} · ${esc(poi.address||poi.district)} ↗</a>`).join('')}</div></details>`;
   button.textContent='View route';button.hidden=false;return;
  }
  if(data.mode==='invalid_selection'){selectedArgs=null;choiceData=null;cache.delete(JSON.stringify({origin_id:a.id,destination_id:b.id}));}
  if(data.mode!=='live'){
   const message={disabled:'AMap is disabled.',not_configured:'AMap is not configured.',invalid_selection:'The selected location has changed. Please choose again.',ambiguous_location:'The location could not be confirmed. Check it on the provider map.'}[data.mode]||'The route could not load. Please try again later.';
   reset.hidden=!selectedArgs;target.innerHTML=`<p class="walk-route-notice" role="status">${esc(message)}</p>`;button.textContent='Retry';button.hidden=false;return;
  }
  reset.hidden=!selectedArgs;
  const image=routeImage(data.map_image),nav=navigationURL(data.navigation_url),leg=data.legs?.[0];
  target.innerHTML=`<div class="walk-live-heading"><strong>${esc(data.distance_m)} m · About ${Math.ceil(data.duration_s/60)} minutes</strong>${nav?`<a href="${esc(nav)}" target="_blank" rel="noopener noreferrer">Navigate with AMap ↗</a>`:''}</div>${image?`<button type="button" class="walk-image-zoom" aria-label="Enlarge AMap walking route"><img class="walk-route-image" src="${image}" alt="AMap: ${esc(a.name)} to ${esc(b.name)} walking route, including provider attribution"></button>`:'<p class="walk-route-notice">The route image is unavailable. Open the route in AMap.</p>'}<p class="walk-source">AMap${image?' · Select the route image to enlarge':''}</p><details class="walk-map-notes"><summary>Route information</summary><p>Start: ${esc(leg?.origin)} (marker 1) · Destination: ${esc(leg?.destination)} (marker 2).</p><p>Retrieved: ${esc(data.source?.fetched_at)}.Follow current road and entrance conditions on site.</p></details>`;
  button.hidden=true;
 }
 async function load(){
  if(button.disabled||item.disposed)return;
  const args=selectedArgs?{...selectedArgs}:{origin_id:a.id,destination_id:b.id};
  if(choiceData&&!selectedArgs){
   const origin=target.querySelector('[data-walk-choice="origin"]'),destination=target.querySelector('[data-walk-choice="destination"]');
   if(!origin?.value||!destination?.value){target.querySelector('.walk-route-notice').textContent='Choose both the start and destination.';return;}
   args.origin_poi_id=origin.value;args.destination_poi_id=destination.value;selectedArgs={...args};
  }
  button.disabled=true;target.innerHTML='<div class="walk-route-placeholder" role="status">Loading the AMap walking route...</div>';
  try{show(await getRoute(JSON.stringify(args),args,api));}
  catch{if(!item.disposed&&wrapper.isConnected){target.innerHTML='<p class="walk-route-notice" role="status">The route could not load. Please try again later.</p>';button.textContent='Retry';button.hidden=false;}}
  finally{if(!item.disposed)button.disabled=false;}
 }
 target.addEventListener('change',event=>{if(!event.target.matches('[data-walk-choice]'))return;const choices=[...target.querySelectorAll('[data-walk-choice]')];if(choices.length===2&&choices.every(v=>v.value))load();});
 target.addEventListener('click',e=>{const zoom=e.target.closest('.walk-image-zoom');if(!zoom)return;const dialog=document.querySelector('#detail-dialog'),content=document.querySelector('#detail-content'),src=routeImage(zoom.querySelector('img').getAttribute('src'));if(!dialog||!content||!src)return;content.innerHTML=`<h2>${esc(a.name)} → ${esc(b.name)}</h2><img class="walk-full-image" src="${src}" alt="AMap walking route, including provider attribution"><p class="fine-print">AMap</p>`;if(!dialog.open)dialog.showModal();});
 reset.addEventListener('click',()=>{selectedArgs=null;choiceData=null;reset.hidden=true;load();});
 button.addEventListener('click',load);
 load();
}
