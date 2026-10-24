import test from 'node:test';
import assert from 'node:assert/strict';
import {walkingLink,walkingMapHTML} from '../static/walking-map.mjs';
const a={id:'avenue-stars',name:'星光大道'},b={id:'knutsford',name:'诺士佛台'};
test('compact map is available only for walking legs',()=>{
 assert.equal(walkingMapHTML(a,b,{transit_guide:{mode:'mtr'}}),'');
 assert.equal(walkingMapHTML(a,a,{transit_guide:{mode:'walk'}}),'');
 assert.match(walkingMapHTML(a,b,{transit_guide:{mode:'walk'}},true),/data-walk-origin="avenue-stars"/);
});
test('walking navigation uses place names and has no key',()=>{
 const link=new URL(walkingLink(a,b));
 assert.equal(link.origin,'https://www.google.com');
 assert.equal(link.searchParams.get('travelmode'),'walking');
 assert.equal(link.searchParams.get('origin'),'香港 星光大道');
 assert.equal(link.searchParams.get('api'),'1');
 assert.equal(link.searchParams.has('key'),false);
});
test('map labels and attributes escape hostile names',()=>{
 const html=walkingMapHTML({id:'x"<',name:'<img src=x onerror=1>'},b,{transit_guide:{mode:'walk'}});
 assert.ok(!html.includes('<img src=x'));
 assert.ok(html.includes('&lt;img'));
});

// Exercise the public mounting API: a visible panel must load without a click.
import {attachWalkingMaps,disposeWalkingMaps} from '../static/walking-map.mjs';
function panelFixture(origin,destination){
 const handlers={},button={disabled:false,hidden:true,addEventListener:(name,fn)=>handlers['button:'+name]=fn},reset={hidden:true,addEventListener:(name,fn)=>handlers['reset:'+name]=fn};
 const selections={origin:{value:''},destination:{value:''}};
 const wrapper={dataset:{walkOrigin:origin,walkDestination:destination},isConnected:true,querySelector:s=>s==='[data-walk-fetch]'?button:reset};
 const target={innerHTML:'loading',clientWidth:400,clientHeight:180,closest:()=>wrapper,addEventListener:(name,fn)=>handlers[name]=fn,querySelector:s=>s.includes('origin')?selections.origin:s.includes('destination')?selections.destination:{textContent:''},querySelectorAll:()=>Object.values(selections)};
 return {target,button,wrapper,selections,handlers,root:{querySelectorAll:()=>[target]}};
}
function observerFixture(){
 const original=globalThis.IntersectionObserver;let callback;
 globalThis.IntersectionObserver=class{constructor(cb){callback=cb}observe(){}unobserve(){}disconnect(){}};
 return {show:target=>callback([{target,isIntersecting:true}]),restore:()=>{disposeWalkingMaps();globalThis.IntersectionObserver=original}};
}
const nextTick=()=>new Promise(resolve=>setImmediate(resolve));
const liveRoute={mode:'live',distance_m:950,duration_s:720,map_image:'data:image/png;base64,AAAA',navigation_url:'https://uri.amap.com/direction?mode=walk',legs:[{origin:'A',destination:'B',steps:[{instruction:'沿街道右转',distance_m:200}]}],source:{fetched_at:'2026-10-23'}};

test('visible walking panel automatically requests and displays AMap route',async()=>{
 const observer=observerFixture(),p=panelFixture('auto-origin','auto-destination'),calls=[];
 try{
  attachWalkingMaps(p.root,[{id:'auto-origin'},{id:'auto-destination'}],async(path,args)=>{calls.push({path,args});return liveRoute});
  assert.equal(calls.length,0);observer.show(p.target);await nextTick();
  assert.equal(calls.length,1);assert.equal(calls[0].path,'/api/walking-map');
  assert.match(p.target.innerHTML,/walk-route-image/);assert.ok(!p.target.innerHTML.includes('沿街道右转'));assert.ok(!p.target.innerHTML.includes('walk-live-steps'));
  assert.ok(!p.target.innerHTML.includes('openstreetmap'));assert.equal(p.button.hidden,true);
 }finally{observer.restore()}
});

test('ambiguous positions require selection then automatically calculate route',async()=>{
 const observer=observerFixture(),p=panelFixture('choice-origin','choice-destination'),calls=[];
 try{
  const candidates={'choice-origin':[{id:'amap-a',name:'起点',address:'甲街',map_url:'https://uri.amap.com/marker'}],'choice-destination':[{id:'amap-b',name:'终点',address:'乙街',map_url:'https://uri.amap.com/marker'}]};
  attachWalkingMaps(p.root,[{id:'choice-origin',name:'起点'},{id:'choice-destination',name:'终点'}],async(path,args)=>{calls.push(args);return calls.length===1?{mode:'ambiguous_location',candidates}:liveRoute});
  observer.show(p.target);await nextTick();assert.equal(calls.length,1);assert.match(p.target.innerHTML,/请选择位置|确认起点和终点/);
  p.selections.origin.value='amap-a';p.handlers.change({target:{matches:()=>true}});await nextTick();assert.equal(calls.length,1);
  p.selections.destination.value='amap-b';p.handlers.change({target:{matches:()=>true}});await nextTick();
  assert.equal(calls.length,2);assert.equal(calls[1].origin_poi_id,'amap-a');assert.equal(calls[1].destination_poi_id,'amap-b');assert.match(p.target.innerHTML,/walk-route-image/);
 }finally{observer.restore()}
});

test('unavailable route shows retry without a substitute map',async()=>{
 const observer=observerFixture(),p=panelFixture('fail-origin','fail-destination');
 try{
  attachWalkingMaps(p.root,[{id:'fail-origin'},{id:'fail-destination'}],async()=>{throw Error('internal implementation details')});
  observer.show(p.target);await nextTick();assert.match(p.target.innerHTML,/路线暂时无法加载/);
  assert.ok(!p.target.innerHTML.includes('internal'));assert.ok(!p.target.innerHTML.includes('<img'));assert.equal(p.button.hidden,false);
 }finally{observer.restore()}
});

test('disposed panel ignores a late route response',async()=>{
 const observer=observerFixture(),p=panelFixture('late-origin','late-destination');let release;
 try{
  attachWalkingMaps(p.root,[{id:'late-origin'},{id:'late-destination'}],()=>new Promise(resolve=>release=resolve));
  observer.show(p.target);const before=p.target.innerHTML;disposeWalkingMaps();release(liveRoute);await nextTick();assert.equal(p.target.innerHTML,before);
 }finally{observer.restore()}
});


test('failed place lookup is not cached and retry reaches provider again',async()=>{
 const observer=observerFixture(),p=panelFixture('retry-origin','retry-destination');let calls=0;
 try{
  attachWalkingMaps(p.root,[{id:'retry-origin'},{id:'retry-destination'}],async()=>{calls++;return calls===1?{mode:'ambiguous_location'}:liveRoute});
  observer.show(p.target);await nextTick();assert.equal(calls,1);
  p.handlers['button:click']();await nextTick();assert.equal(calls,2);assert.match(p.target.innerHTML,/walk-route-image/);
 }finally{observer.restore()}
});
