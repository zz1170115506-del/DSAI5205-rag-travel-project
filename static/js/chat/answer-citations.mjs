import {displayText} from '../core/english.mjs?v=20261029-en';
const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

export function inlineAnswerHTML(answer,external,evidence=[]){
 const valid=new Set(answer.citations??[]);
 const documentSources=new Map((evidence??[]).map(row=>[row.id,row]));
 const mapSources=new Map(['amap','mixed'].includes(answer.retrieval_source)&&external?.provider==='amap'&&external.mode==='live'
  ?external.results.map(p=>[p.citation_id,p]):[]);
 const text=String(answer.text??'').split(/(\[[a-z0-9-]+\])/g).map(part=>/^\[[a-z0-9-]+\]$/.test(part)||(answer.retrieval_source==='documents'||answer.mode==='model')?part:displayText(part)).join('');
 return escapeHTML(text).replace(/\[([a-z0-9-]+)\]/g,(all,id)=>{
  if(!valid.has(id))return all;
  if(documentSources.has(id)){
   const source=documentSources.get(id);
   if(source.evidence_type==='current_itinerary')return '<button class="inline-citation" data-action="view-current-plan">Current itinerary ↑</button>';
   try{
    const url=new URL(source.source_url);
    if(url.protocol!=='https:'||url.username||url.password)return all;
    return `<a class="inline-citation" href="${escapeHTML(url.href)}" target="_blank" rel="noopener noreferrer" title="${escapeHTML(source.title??'Source')}">Source${source.page_number?' · PDF p. '+escapeHTML(source.page_number):''} ↗</a>`;
   }catch{return all;}
  }
  if(id.startsWith('map-')){
   const source=mapSources.get(id);if(!source)return all;
   try{
    const url=new URL(source.map_url);
    if(url.protocol!=='https:'||url.hostname!=='uri.amap.com'||url.username||url.password)return all;
    return `<a class="inline-citation" href="${escapeHTML(url.href)}" target="_blank" rel="noopener noreferrer" title="${escapeHTML(displayText(source.name))} · AMap">Map source ↗</a>`;
   }catch{return all;}
  }
  return `<button class="inline-citation" data-action="detail" data-id="${escapeHTML(id)}">Source ↗</button>`;
 });
}
