import {displayText} from './english.mjs?v=20261029-en';
const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

export function inlineAnswerHTML(answer,external){
 const valid=new Set(answer.citations??[]);
 const mapSources=new Map(answer.retrieval_source==='amap'&&external?.provider==='amap'&&external.mode==='live'
  ?external.results.map(p=>[p.citation_id,p]):[]);
 const text=String(answer.text??'').split(/(\[[a-z0-9-]+\])/g).map(part=>/^\[[a-z0-9-]+\]$/.test(part)?part:displayText(part)).join('');
 return escapeHTML(text).replace(/\[([a-z0-9-]+)\]/g,(all,id)=>{
  if(!valid.has(id))return all;
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
