import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {displayText,displayJSON,setEnglishCatalog,englishGuide,loadEnglish} from '../static/english.mjs?v=20261029-en';
import {inlineAnswerHTML} from '../static/answer-citations.mjs';

const catalog=JSON.parse(readFileSync(new URL('../static/english-catalog.json',import.meta.url),'utf8'));
const original=JSON.parse(readFileSync(new URL('../data/places.json',import.meta.url),'utf8')).places;
const translated=JSON.parse(readFileSync(new URL('../data/places.en.json',import.meta.url),'utf8'));
setEnglishCatalog(catalog);

test('all curated place descriptions have English display text without changing the originals',()=>{
 for(const place of original)for(const field of ['name','area','summary','tip']){
  assert.equal(displayText(place[field]),translated[place.id][field]);
  assert.doesNotMatch(displayText(place[field]),/[\u3400-\u9fff]/);
 }
 assert.equal(original.find(p=>p.id==='tai-kwun').name,'大馆');
});

test('displaying canonical enums and traces does not mutate request values',()=>{
 const input={region:'九龙',pace:'轻松',must_visit:['tai-kwun'],source:'https://example.com/香港'};
 const snapshot=JSON.stringify(input);
 const shown=JSON.parse(displayJSON(input));
 assert.equal(shown.region,'Kowloon');assert.equal(shown.pace,'Relaxed');
 assert.deepEqual(shown.must_visit,['tai-kwun']);assert.doesNotMatch(shown.source,/[\u3400-\u9fff]/);
 assert.equal(JSON.stringify(input),snapshot);
});

test('English transport directions retain stations, line, direction and stop count',()=>{
 const guide={steps:[{kind:'ride',from:'中环',to:'尖沙咀',line_name:'荃湾线',color_name:'红色',direction:'荃湾',stop_count:2}]};
 const text=englishGuide(guide).steps[0].text;
 for(const part of ['Central','Tsim Sha Tsui','Tsuen Wan Line','Red','2 stop'])assert.ok(text.includes(part));
 assert.doesNotMatch(text,/[\u3400-\u9fff]/);
});

test('unknown provider prose keeps its citation and working source link',()=>{
 const output=inlineAnswerHTML({text:'未收录的外部地点 [map-1]',citations:['map-1'],retrieval_source:'amap'},
  {provider:'amap',mode:'live',results:[{citation_id:'map-1',name:'未收录的外部地点',map_url:'https://uri.amap.com/marker?name=source'}]});
 assert.match(output,/href="https:\/\/uri\.amap\.com\/marker/);
 assert.match(output,/Map source/);assert.doesNotMatch(output,/[\u3400-\u9fff]/);
});

test('dynamic free-day notes retain their actual duration in English',()=>{
 const shown=displayText('按你只安排已选地点的偏好，3 天保留为休息／自由活动日，未额外添加其他地点。');
 assert.match(shown,/3 day/);assert.doesNotMatch(shown,/[\u3400-\u9fff]/);
});

test('a failed English catalogue request can be retried',async()=>{
 const originalFetch=globalThis.fetch;let calls=0;
 globalThis.fetch=async()=>{calls++;if(calls===1)throw Error('temporary connection failure');return {ok:true,json:async()=>catalog};};
 try{await assert.rejects(loadEnglish(),/temporary/);await loadEnglish();assert.equal(calls,2);assert.equal(displayText('九龙'),'Kowloon');}
 finally{globalThis.fetch=originalFetch;}
});
