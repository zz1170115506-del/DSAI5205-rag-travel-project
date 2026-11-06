import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createPlanRenderer} from '../static/js/itinerary/render.mjs';
import {mapHTML} from '../static/js/itinerary/itinerary-map.js';
import {priceSummaryHTML} from '../static/js/itinerary/pricing.mjs';
import {displayText,englishGuide,setEnglishCatalog} from '../static/js/core/english.mjs?v=20261029-en';

setEnglishCatalog(JSON.parse(readFileSync(new URL('../static/locales/en.json',import.meta.url),'utf8')));
const render=createPlanRenderer({getStatus:()=>({amap_configured:true})});
function fixture(){
 const local={id:'pmq',name:'PMQ',summary:'Creative spaces in Central.',lat:22.28,lon:114.15};
 const external={id:'amap-K11',provider:'amap',name:'K11 MUSEA',summary:'Map-sourced stop.',lat:null,lon:null,
  map_url:'https://uri.amap.com/marker?position=114.17%2C22.3'};
 return {days_requested:1,append_workflow:true,only_selected:true,warnings:['Times are assumptions.'],days:[{
  day:1,kind:'sightseeing',title:'Your evolving Hong Kong itinerary',end:'14:00',transfer_minutes:35,
  meal_note:'Arrange meals separately.',stops:[local,external].map(place=>({place,start:'10:00',end:'11:30',minutes:90})),
  legs:[{minutes:35,transit_guide:{mode:'unverified',title:'Check this connection',estimated_minutes:35,
   checked:'Not route-verified',sources:[],steps:[{kind:'note',text:'A planning allowance, not a computed route.'}],notice:'Unverified.'}}]}]};
}

test('a mixed itinerary renders provider links and never routes external IDs through local-only actions',()=>{
 const html=render.planHTML(fixture());
 assert.match(html,/data-action="detail" data-id="pmq"/);
 assert.match(html,/AMap · Provisional stop/);
 assert.match(html,/href="https:\/\/uri\.amap\.com\/marker/);
 assert.doesNotMatch(html,/data-action="detail" data-id="amap-/);
 assert.doesNotMatch(html,/data-action="route"/);
 assert.doesNotMatch(html,/[\u3400-\u9fff]/);
});

test('an external-only itinerary has provider links and no misplaced WGS84 overview',()=>{
 const plan=fixture();plan.days[0].stops.shift();plan.days[0].legs=[];
 const html=render.planHTML(plan);
 assert.match(html,/K11 MUSEA/);
 assert.doesNotMatch(html,/class="itinerary-map"/);
 assert.doesNotMatch(html,/data-action="route"/);
});

test('the compact plan scrolls separately and omits the removed summary panels',()=>{
 const html=render.planHTML(fixture());
 assert.match(html,/aria-label="Scrollable itinerary"/);
 assert.doesNotMatch(html,/class="plan-price"|class="plan-notes"|class="plan-coverage"|class="map-panel"/);
 const map=mapHTML(fixture());
 assert.doesNotMatch(map,/map-stop-list|Your journey across Hong Kong|OpenStreetMap basemap/);
 assert.match(map,/Interactive Hong Kong itinerary map/);
});
