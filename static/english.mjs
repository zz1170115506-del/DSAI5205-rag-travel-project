// Presentation translations never replace canonical values sent to the API.
const CJK=/[\u3400-\u9fff]/;
let catalog={}, ordered=[], loading;
export function setEnglishCatalog(value){
 catalog={...value};ordered=Object.keys(catalog).sort((a,b)=>b.length-a.length);
}
export function loadEnglish(){
 return loading??=fetch('/static/english-catalog.json?v=20261029-en').then(async response=>{
  if(!response.ok)throw Error('English presentation resources could not load. Please refresh.');
  setEnglishCatalog(await response.json());
 }).catch(error=>{loading=undefined;throw error;});
}
export function displayText(value){
 let text=String(value??'');
 if(/^(?:https?:|data:)/.test(text)){try{return new URL(text).href;}catch{return text;}}
 if(!CJK.test(text))return text;
 if(catalog[text])return catalog[text];
 if(text.includes('\n'))return text.split('\n').map(displayText).join('\n');
 text=text.replace(/步行预留约 (\d+) 分钟（项目估算）。/g,'Allow approximately $1 minutes on foot (project estimate).')
  .replace(/两地可从(.+?)站周边街区衔接。由(.+?)按街道地图步行至(.+?)，无需进出站绕行；步行方案仍需现场确认。/g,(_,station,a,b)=>`Both places are near ${displayText(station)} station. Walk from ${displayText(a)} to ${displayText(b)} using a street map; entering the station is unnecessary. Confirm the route on site.`)
  .replace(/由(.+?)步行至(.+?)站 (.+?) 入口，预留约 (\d+) 分钟（估算），按站区图核对入口。/g,(_,place,station,exit,minutes)=>`Walk from ${displayText(place)} to ${displayText(station)} station Entrance ${exit}. Allow about ${minutes} minutes (estimate); check the entrance on the station map.`)
  .replace(/从(.+?)按街道地图步行至花园道山顶缆车中环总站，预留约 20–30 分钟及上坡时间（项目估算）。/g,(_,place)=>`Walk from ${displayText(place)} to the Peak Tram Garden Road Central Terminus using a street map. Allow about 20–30 minutes and extra time uphill (project estimate).`)
  .replace(/从(.+?)按路牌步行至(.+?)巴士总站。/g,(_,place,area)=>`Follow signs from ${displayText(place)} to ${displayText(area)} bus terminus.`)
  .replace(/下车后按(.+?)标识步行，山路不可按地图直线穿行。/g,(_,place)=>`After alighting, follow signs to ${displayText(place)}. Do not infer a mountain path from a straight line on the map.`)
  .replace(/乘新大屿山巴士 (\d+) 号往(.+?)，于(.+?)总站下车；先查当日班次与尾班。/g,(_,number,target)=>`Take New Lantao Bus ${number} to ${displayText(target)} terminus. Check the day's departures and last bus first.`)
  .replace(/在东涌达东路巴士总站乘新大屿山巴士 (\d+) 号往(.+?)，于(.+?)总站下车，再按(.+?)路牌步行。/g,(_,number,target,_terminus,place)=>`At Tung Chung Tat Tung Road Bus Terminus, take New Lantao Bus ${number} to ${displayText(target)} terminus, then follow signs to ${displayText(place)}.`)
  .replace(/在(.+?)站从 (.+?) 出口出站。/g,(_,station,exit)=>`Leave ${displayText(station)} station via Exit ${exit}.`)
  .replace(/从(.+?)步行至(.+?)。/g,(_,a,b)=>`Walk from ${displayText(a)} to ${displayText(b)}.`)
  .replace(/^从(.+?)站出发$/,(_,station)=>`Start from ${displayText(station)} station`)
  .replace(/按你只安排已选地点的偏好，(\d+) 天保留为休息／自由活动日，未额外添加其他地点。/g,'With only your selected places scheduled, $1 day(s) remain free. No extra places were added.')
  .replace(/资料覆盖有限，(\d+) 天列为休息／自由活动日并保留完整日期；未重复安排相同地点，也未声称已核实自由活动的地点或交通。/g,'Source coverage is limited. $1 day(s) remain free, without repeating stops or claiming unverified activities or transport.');
 for(const key of ordered)text=text.replaceAll(key,catalog[key]);
 // Untranslated provider prose is never disguised as a verified English translation.
 // Its original place page remains available through the provider/source link.
 if(CJK.test(text))return 'Additional source details are available through the original source link.';
 return text.replaceAll('。','. ').replaceAll('，',', ').replaceAll('；','; ').replaceAll('：',': ')
  .replaceAll('（',' (').replaceAll('）',')').replaceAll('、',', ').replaceAll('／','/');
}
export function displayJSON(value){
 return JSON.stringify(value,(_key,item)=>typeof item==='string'?displayText(item):item,2);
}
export function englishGuide(guide){
 if(!guide)return guide;
 return {...guide,steps:guide.steps.map(step=>{
  let text=step.text;
  if(step.kind==='ride')text=`At ${displayText(step.from)}, take the ${displayText(step.line_name)} (${displayText(step.color_name)}) towards ${displayText(step.direction)} for ${step.stop_count} stop(s), then alight at ${displayText(step.to)}.`;
  else if(step.kind==='transfer')text=`At ${displayText(step.station)}, change to the ${({TWL:'Tsuen Wan Line',ISL:'Island Line',KTL:'Kwun Tong Line',TCL:'Tung Chung Line',TML:'Tuen Ma Line',EAL:'East Rail Line'})[step.to_line]??step.to_line} and follow interchange signs.`;
  else if(step.kind==='station_walk')text=`Follow the pedestrian connection from ${displayText(step.from)} to ${displayText(step.to)}. Check MTR signs and current ticketing arrangements.`;
  return {...step,text};
 })};
}
