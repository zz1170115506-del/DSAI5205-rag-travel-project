const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

export function inlineAnswerHTML(answer,external){
 const valid=new Set(answer.citations??[]);
 const mapSources=new Map(answer.retrieval_source==='amap'&&external?.provider==='amap'&&external.mode==='live'
  ?external.results.map(p=>[p.citation_id,p]):[]);
 return escapeHTML(answer.text).replace(/\[([a-z0-9-]+)\]/g,(all,id)=>{
  if(!valid.has(id))return all;
  if(id.startsWith('map-')){
   const source=mapSources.get(id);if(!source)return all;
   try{
    const url=new URL(source.map_url);
    if(url.protocol!=='https:'||url.hostname!=='uri.amap.com'||url.username||url.password)return all;
    return `<a class="inline-citation" href="${escapeHTML(url.href)}" target="_blank" rel="noopener noreferrer" title="${escapeHTML(source.name)} · 高德地图">地图出处 ↗</a>`;
   }catch{return all;}
  }
  return `<button class="inline-citation" data-action="detail" data-id="${escapeHTML(id)}">出处 ↗</button>`;
 });
}
