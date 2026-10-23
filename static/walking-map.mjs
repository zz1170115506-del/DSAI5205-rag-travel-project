// Walking routes and images are supplied by AMap; no sketch line or alternate basemap.
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const maps=new Set(),cache=new Map(),pending=new Map();
let observer;
export function walkingLink(a,b){return 'https://www.google.com/maps/dir/?'+new URLSearchParams({api:'1',origin:'香港 '+a.name,destination:'香港 '+b.name,travelmode:'walking'});}
export function walkingMapHTML(a,b,leg,open=false){
 if(leg?.transit_guide?.mode!=='walk'||!a||!b||a.id===b.id)return '';
 return `<details class="walk-mini-panel" data-walk-origin="${esc(a.id)}" data-walk-destination="${esc(b.id)}" ${open?'open':''}><summary><strong>步行小地图 <span aria-hidden="true">↗</span></strong><span>${esc(a.name)} → ${esc(b.name)}</span></summary><div class="walk-mini-body"><div class="walk-route-result" aria-live="polite"><div class="walk-route-placeholder" role="status">正在加载高德步行路线……</div></div><div class="walk-mini-actions"><button type="button" class="small-button" data-walk-fetch hidden>重试</button><button type="button" class="small-button" data-walk-reset hidden>更换起终点位置</button><a href="${esc(walkingLink(a,b))}" target="_blank" rel="noopener noreferrer">其他地图导航 ↗</a></div></div></details>`;
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
   target.innerHTML=`<p class="walk-route-notice">找到同名地点，请确认起点和终点。</p><div class="walk-poi-choices">${[[a,'origin'],[b,'destination']].map(([place,key])=>`<label>${key==='origin'?'起点':'终点'} · ${esc(place.name)}<select data-walk-choice="${key}">${(data.candidates[place.id]??[]).length>1?'<option value="">请选择位置</option>':''}${(data.candidates[place.id]??[]).map(poi=>`<option value="${esc(poi.id)}">${esc(poi.name)} · ${esc(poi.address||poi.district||'地址未提供')}</option>`).join('')}</select></label>`).join('')}</div><details class="walk-map-notes"><summary>查看候选地点</summary><div class="walk-candidate-links">${Object.values(data.candidates).flat().map(poi=>`<a href="${esc(poi.map_url)}" target="_blank" rel="noopener noreferrer">${esc(poi.name)} · ${esc(poi.address||poi.district)} ↗</a>`).join('')}</div></details>`;
   button.textContent='查看路线';button.hidden=false;return;
  }
  if(data.mode==='invalid_selection'){selectedArgs=null;choiceData=null;cache.delete(JSON.stringify({origin_id:a.id,destination_id:b.id}));}
  if(data.mode!=='live'){
   const message={disabled:'高德地图尚未启用。',not_configured:'高德地图暂未配置。',invalid_selection:'所选位置已更新，请重新选择。',ambiguous_location:'暂时无法确认地点位置，请在地图中核对。'}[data.mode]||'路线暂时无法加载，请稍后重试。';
   reset.hidden=!selectedArgs;target.innerHTML=`<p class="walk-route-notice" role="status">${esc(message)}</p>`;button.textContent='重试';button.hidden=false;return;
  }
  reset.hidden=!selectedArgs;
  const image=routeImage(data.map_image),nav=navigationURL(data.navigation_url),leg=data.legs?.[0];
  target.innerHTML=`<div class="walk-live-heading"><strong>${esc(data.distance_m)} 米 · 约 ${Math.ceil(data.duration_s/60)} 分钟</strong>${nav?`<a href="${esc(nav)}" target="_blank" rel="noopener noreferrer">在高德中导航 ↗</a>`:''}</div>${image?`<button type="button" class="walk-image-zoom" aria-label="放大高德步行路线图"><img class="walk-route-image" src="${image}" alt="高德地图：${esc(a.name)}至${esc(b.name)}的步行路线，含地图署名"></button>`:'<p class="walk-route-notice">路线图片暂未加载，可在高德中查看路线。</p>'}<p class="walk-source">高德地图${image?' · 点击路线图可放大':''}</p><details class="walk-map-notes"><summary>路线信息</summary><p>起点：${esc(leg?.origin)}（图中 1） · 终点：${esc(leg?.destination)}（图中 2）。</p><p>查询时间：${esc(data.source?.fetched_at)}。道路和入口以现场通行为准。</p></details>`;
  button.hidden=true;
 }
 async function load(){
  if(button.disabled||item.disposed)return;
  const args=selectedArgs?{...selectedArgs}:{origin_id:a.id,destination_id:b.id};
  if(choiceData&&!selectedArgs){
   const origin=target.querySelector('[data-walk-choice="origin"]'),destination=target.querySelector('[data-walk-choice="destination"]');
   if(!origin?.value||!destination?.value){target.querySelector('.walk-route-notice').textContent='请选择起点和终点位置。';return;}
   args.origin_poi_id=origin.value;args.destination_poi_id=destination.value;selectedArgs={...args};
  }
  button.disabled=true;target.innerHTML='<div class="walk-route-placeholder" role="status">正在加载高德步行路线……</div>';
  try{show(await getRoute(JSON.stringify(args),args,api));}
  catch{if(!item.disposed&&wrapper.isConnected){target.innerHTML='<p class="walk-route-notice" role="status">路线暂时无法加载，请稍后重试。</p>';button.textContent='重试';button.hidden=false;}}
  finally{if(!item.disposed)button.disabled=false;}
 }
 target.addEventListener('change',event=>{if(!event.target.matches('[data-walk-choice]'))return;const choices=[...target.querySelectorAll('[data-walk-choice]')];if(choices.length===2&&choices.every(v=>v.value))load();});
 target.addEventListener('click',e=>{const zoom=e.target.closest('.walk-image-zoom');if(!zoom)return;const dialog=document.querySelector('#detail-dialog'),content=document.querySelector('#detail-content'),src=routeImage(zoom.querySelector('img').getAttribute('src'));if(!dialog||!content||!src)return;content.innerHTML=`<h2>${esc(a.name)} → ${esc(b.name)}</h2><img class="walk-full-image" src="${src}" alt="高德步行路线图，含地图署名"><p class="fine-print">高德地图</p>`;if(!dialog.open)dialog.showModal();});
 reset.addEventListener('click',()=>{selectedArgs=null;choiceData=null;reset.hidden=true;load();});
 button.addEventListener('click',load);
 load();
}
