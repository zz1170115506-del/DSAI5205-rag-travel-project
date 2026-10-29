import test from 'node:test';
import assert from 'node:assert/strict';
import {inlineAnswerHTML} from '../static/answer-citations.mjs';

const answer={text:'Test mall [map-1]',citations:['map-1'],retrieval_source:'amap'};
const evidence={provider:'amap',mode:'live',results:[
 {citation_id:'map-1',name:'Test mall',map_url:'https://uri.amap.com/marker?name=test'}]};

test('map citations open the provider source instead of a local detail ID',()=>{
 const html=inlineAnswerHTML(answer,evidence);
 assert.match(html,/href="https:\/\/uri\.amap\.com/);
 assert.match(html,/Map source/);
 assert.doesNotMatch(html,/data-action="detail"/);
 assert.match(html,/rel="noopener noreferrer"/);
});
test('local citations retain the local detail action',()=>{
 assert.match(inlineAnswerHTML({text:'Tai Kwun [tai-kwun]',citations:['tai-kwun']}),/data-id="tai-kwun"/);
});
test('unretrieved or invalid map citations remain plain text',()=>{
 assert.equal(inlineAnswerHTML({...answer,text:'Test [map-2]'} ,evidence),'Test [map-2]');
 assert.equal(inlineAnswerHTML(answer,{...evidence,mode:'unavailable'}),'Test mall [map-1]');
 assert.equal(inlineAnswerHTML(answer),'Test mall [map-1]');
});
test('untrusted source URLs never become executable or third-party links',()=>{
 for(const url of ['javascript:alert(1)','http://uri.amap.com/marker','https://evil.fixture',
                   'https://uri.amap.com.evil.fixture','https://user@uri.amap.com/marker']){
  const data={...evidence,results:[{...evidence.results[0],map_url:url}]};
  assert.equal(inlineAnswerHTML(answer,data),'Test mall [map-1]');
 }
});
test('model prose and source labels are HTML escaped',()=>{
 const html=inlineAnswerHTML({...answer,text:'<img src=x> [map-1]'},
  {...evidence,results:[{...evidence.results[0],name:'" onfocus="attack'}]});
 assert.match(html,/&lt;img src=x&gt;/);
 assert.doesNotMatch(html,/<img|title="" onfocus/);
});
