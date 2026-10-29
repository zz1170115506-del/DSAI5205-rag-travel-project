import {displayText} from './english.mjs?v=20261029-en';
// Real OSM basemap; local points remain approximate and lines show visit order only.
const escapeHTML=v=>displayText(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const colors=['#217460','#be6947','#5b6fa2'];
const liveMaps=new Set();
let visibility;

export function mapHTML(plan){
  if(!plan.days.some(d=>d.stops.length))return '';
  const days=plan.days.map((d,i)=>({...d,index:i})).filter(d=>d.stops.length);
  const filters=days.length>7?`<label class="map-day-label">Map date<select data-map-select aria-label="Map date (days with planned stops)"><option value="all">All days</option>${days.map(d=>`<option value="${d.index}">Day ${d.day}${d.date?' · '+escapeHTML(d.date):''}</option>`).join('')}</select></label>`:`<button class="small-button active" data-map-day="all" aria-pressed="true">All days</button>${days.map(d=>`<button class="small-button day-${d.index%3+1}" data-map-day="${d.index}" aria-pressed="false">${d.date?escapeHTML(d.date.slice(5))+' · ':''}Day ${escapeHTML(d.day)}</button>`).join('')}`;
  return `<section class="map-panel itinerary-panel"><div class="map-title"><div><span class="eyebrow">YOUR HONG KONG, ON THE MAP</span><h3>Your journey across Hong Kong</h3></div><span class="badge">OpenStreetMap basemap</span></div><div class="map-toolbar" aria-label="Choose a day on the map">${filters}<button class="small-button map-fit" data-map-fit>Fit all stops ↗</button></div><div class="itinerary-map" role="region" aria-label="Interactive Hong Kong itinerary map"><p class="map-placeholder">The map loads when visible...</p></div><p class="map-load-status fine-print" role="status">Drag to explore, zoom in, or select a numbered stop.</p><div class="map-stop-list"></div><details class="fine-print map-caption"><summary>About this map</summary><p>Basemap: © OpenStreetMap contributors. Markers are approximate; connecting lines show visit order. Use walking references or transport guides for directions.</p><a href="https://www.openstreetmap.org/fixthemap" target="_blank" rel="noopener noreferrer">Report a map issue ↗</a></details></section>`;
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
  if(!window.L){status.textContent='The map component could not load. Refresh, or open a place using its map link.';return;}
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
    status.textContent=loaded?(failed?'Some tiles could not load. Try zooming, or use the place links.':'Map loaded · Drag to explore and select numbered stops.'):'Map tiles are unavailable. Check your connection or use the place links below.';
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
        const popup=`<span class="popup-day">Day ${escapeHTML(p.day)} · Stop ${number}</span><h4>${escapeHTML(p.name)}</h4><p>Curated source · Approximate position</p><button class="text-button" data-action="detail" data-id="${escapeHTML(p.id)}">Place details ↗</button> <a href="https://uri.amap.com/search?keyword=${encodeURIComponent('Hong Kong '+p.name)}&city=${encodeURIComponent('Hong Kong')}&view=map&src=hk-travel-assistant" target="_blank" rel="noopener noreferrer">Search AMap ↗</a>`;
        L.marker([p.lat,p.lon],{icon,title:`${number} ${displayText(p.name)}`,alt:`${number} ${displayText(p.name)}`,keyboard:true}).bindPopup(popup,{maxWidth:250}).addTo(group);
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
