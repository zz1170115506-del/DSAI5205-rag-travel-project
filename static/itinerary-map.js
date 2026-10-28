// Real OSM basemap; local points remain approximate and lines show visit order only.
const escapeHTML=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const colors=['#217460','#be6947','#5b6fa2'];
const liveMaps=new Set();
let visibility;

export function mapHTML(plan){
  if(!plan.days.some(d=>d.stops.length))return '';
  const days=plan.days.map((d,i)=>({...d,index:i})).filter(d=>d.stops.length);
  const filters=days.length>7?`<label class="map-day-label">地图日期<select data-map-select aria-label="地图日期（仅含已安排地点的日期）"><option value="all">全程</option>${days.map(d=>`<option value="${d.index}">第 ${d.day} 天${d.date?' · '+escapeHTML(d.date):''}</option>`).join('')}</select></label>`:`<button class="small-button active" data-map-day="all" aria-pressed="true">全程</button>${days.map(d=>`<button class="small-button day-${d.index%3+1}" data-map-day="${d.index}" aria-pressed="false">${d.date?escapeHTML(d.date.slice(5))+' · ':''}第 ${escapeHTML(d.day)} 天</button>`).join('')}`;
  return `<section class="map-panel itinerary-panel"><div class="map-title"><div><span class="eyebrow">YOUR HONG KONG, ON THE MAP</span><h3>这一程，在香港的哪里</h3></div><span class="badge">真实地图 · OpenStreetMap</span></div><div class="map-toolbar" aria-label="选择地图中的行程日期">${filters}<button class="small-button map-fit" data-map-fit>查看全貌 ↗</button></div><div class="itinerary-map" role="region" aria-label="香港行程互动地图"><p class="map-placeholder">地图在显示时加载……</p></div><p class="map-load-status fine-print" role="status">支持拖动、缩放，点击编号查看地点。</p><div class="map-stop-list"></div><details class="fine-print map-caption"><summary>地图说明</summary><p>底图：© OpenStreetMap contributors。编号为地点近似位置，连线表示游览顺序；具体走法请查看步行小地图或交通指引。</p><a href="https://www.openstreetmap.org/fixthemap" target="_blank" rel="noopener noreferrer">反馈地图问题 ↗</a></details></section>`;
}

export function disposeMaps(){
  visibility?.disconnect();
  for(const controller of liveMaps){controller.resize.disconnect();clearTimeout(controller.timer);controller.map.remove();}
  liveMaps.clear();
}

export function attachPlanMaps(root,turns){
  const pending=new Map();
  visibility=new IntersectionObserver(entries=>{
    for(const entry of entries){
      if(!entry.target.isConnected||!entry.isIntersecting||!entry.target.clientWidth)continue;
      visibility.unobserve(entry.target);
      const plan=pending.get(entry.target);pending.delete(entry.target);
      if(plan)mountMap(entry.target,plan);
    }
  },{threshold:0.05});
  for(const turn of root.querySelectorAll('[data-turn]')){
    const host=turn.querySelector('.itinerary-map'),plan=turns[Number(turn.dataset.turn)]?.result.plan;
    if(host&&plan){pending.set(host,plan);visibility.observe(host);}
  }
}

function mountMap(host,plan){
  const panel=host.closest('.itinerary-panel'),status=panel.querySelector('.map-load-status');
  if(!window.L){status.textContent='地图组件未能加载，请刷新页面；仍可通过地点列表打开外部地图。';return;}
  host.replaceChildren();
  const L=window.L,map=L.map(host,{scrollWheelZoom:false,minZoom:9,maxZoom:18});
  const tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{
    maxZoom:19,updateWhenIdle:true,keepBuffer:1,referrerPolicy:'origin',
    attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'
  });
  const controller={map,resize:new ResizeObserver(()=>{if(host.clientWidth&&host.clientHeight)map.invalidateSize({pan:false});}),timer:null};
  liveMaps.add(controller);controller.resize.observe(host);
  let loaded=0,failed=0;
  const updateStatus=()=>{
    host.dataset.tilesLoaded=String(loaded);
    status.textContent=loaded?(failed?'部分底图未加载，可缩放或通过地点链接打开地图。':'真实地图已加载 · 拖动浏览，点击编号查看地点。'):'地图底图暂不可用，请检查网络；可通过下方地点链接打开地图。';
  };
  tiles.on('tileload',()=>{loaded++;clearTimeout(controller.timer);updateStatus();});
  tiles.on('tileerror',()=>{failed++;updateStatus();});
  controller.timer=setTimeout(updateStatus,10000);
  tiles.addTo(map);
  const group=L.featureGroup().addTo(map);
  let active='all',selected=[];
  const numbered=plan.days.flatMap((d,dayIndex)=>d.stops.map(stop=>({...stop.place,day:d.day,dayIndex})));
  const valid=p=>Number.isFinite(p.lat)&&Number.isFinite(p.lon)&&p.lat>22.1&&p.lat<22.65&&p.lon>113.8&&p.lon<114.5;
  const fit=()=>{if(selected.length)map.fitBounds(selected.map(p=>[p.lat,p.lon]),{padding:[38,38],maxZoom:15});else map.setView([22.3,114.17],12);};
  const draw=()=>{
    group.clearLayers();selected=[];
    plan.days.forEach((day,dayIndex)=>{
      if(active!=='all'&&Number(active)!==dayIndex)return;
      const points=numbered.filter(p=>p.dayIndex===dayIndex&&valid(p));selected.push(...points);
      if(points.length>1)L.polyline(points.map(p=>[p.lat,p.lon]),{color:colors[dayIndex%3],weight:3,opacity:.75,dashArray:'5 8',interactive:false}).addTo(group);
      points.forEach(p=>{
        const number=numbered.indexOf(p)+1;
        const icon=L.divIcon({className:`trip-marker day-${dayIndex%3+1}`,html:`<span>${number}</span>`,iconSize:[32,32],iconAnchor:[16,16]});
        const popup=`<span class="popup-day">第 ${escapeHTML(p.day)} 天 · 第 ${number} 站</span><h4>${escapeHTML(p.name)}</h4><p>本地资料近似定位</p><button class="text-button" data-action="detail" data-id="${escapeHTML(p.id)}">地点详情 ↗</button> <a href="https://uri.amap.com/search?keyword=${encodeURIComponent('香港 '+p.name)}&city=${encodeURIComponent('香港')}&view=map&src=hk-travel-assistant" target="_blank" rel="noopener noreferrer">高德中查找 ↗</a>`;
        L.marker([p.lat,p.lon],{icon,title:`${number} ${p.name}`,alt:`${number} ${p.name}`,keyboard:true}).bindPopup(popup,{maxWidth:250}).addTo(group);
      });
    });
    panel.querySelector('.map-stop-list').innerHTML=selected.map(p=>`<button class="map-stop day-${p.dayIndex%3+1}" data-map-stop="${numbered.indexOf(p)}"><b>${numbered.indexOf(p)+1}</b>${escapeHTML(p.name)}</button>`).join('');
    panel.querySelectorAll('[data-map-day]').forEach(b=>{b.classList.toggle('active',b.dataset.mapDay===active);b.setAttribute('aria-pressed',String(b.dataset.mapDay===active));});
    const select=panel.querySelector('[data-map-select]');if(select)select.value=active;
    fit();
  };
  panel.addEventListener('change',e=>{if(e.target.matches('[data-map-select]')){active=e.target.value;draw();}});
  panel.addEventListener('click',e=>{
    const day=e.target.closest('[data-map-day]');if(day){active=day.dataset.mapDay;draw();return;}
    if(e.target.closest('[data-map-fit]')){fit();return;}
    const stop=e.target.closest('[data-map-stop]');if(stop){const p=numbered[Number(stop.dataset.mapStop)];for(const layer of group.getLayers())if(layer instanceof L.Marker&&layer.options.title===`${numbered.indexOf(p)+1} ${p.name}`){map.setView(layer.getLatLng(),Math.max(map.getZoom(),15));layer.openPopup();break;}}
  });
  draw();
}
