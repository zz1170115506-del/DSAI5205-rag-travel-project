import {displayText} from '../core/english.mjs?v=20261029-en';

const esc=value=>displayText(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=value=>Number(value).toLocaleString('en-HK',{minimumFractionDigits:0,maximumFractionDigits:2});
const note='Admission references per person only. Transport, dining, accommodation and flights are not included. Check the applicable ticket type and current price before travelling.';
function range(summary){
 const low=summary?.known_min_hkd,high=summary?.known_max_hkd;
 if(!Number.isFinite(low)||!Number.isFinite(high)||low<0||high<low)return null;
 return `HK$ ${money(low)}${high===low?'':'–'+money(high)}`;
}
function sourceURL(value){
 try{const url=new URL(value);return url.protocol==='https:'&&!url.username&&!url.password?url.href:null;}catch{return null;}
}

export function priceSummaryHTML(plan){
 const summary=plan.price_summary,amount=range(summary);
 const known=summary?.known_items??[],unknown=summary?.unknown_items??[];
 return `<section class="plan-price" aria-label="Trip price"><h4>Trip price · ${amount?'Known admission subtotal: '+esc(amount)+' per person':'To verify'}</h4><p>${note}</p>${unknown.length?`<p>${unknown.length} scheduled admission price(s) still need verification.</p>`:''}${known.length?`<details><summary>Price references and sources</summary>${known.map(item=>{const url=sourceURL(item.source_url);return `<p>${esc(item.name)} · ${esc(item.scope)} · Checked ${esc(item.checked)}${url?` · <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Price source ↗</a>`:''}</p>`;}).join('')}</details>`:''}</section>`;
}

export function priceSummaryText(plan){
 const summary=plan.price_summary,amount=range(summary);
 return [`Trip price: ${amount?'Known admission subtotal '+amount+' per person':'To verify'}`,note,
  ...(summary?.known_items??[]).map(item=>`${displayText(item.name)}: ${item.scope}; checked ${item.checked}; ${item.source_url}`),
  ...(summary?.unknown_items??[]).map(item=>`${displayText(item.name)}: price to verify`)].join('\n');
}
