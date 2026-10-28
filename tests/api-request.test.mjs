import test from 'node:test';
import assert from 'node:assert/strict';
import {postAPI} from '../static/api-request.mjs';
import {readAPIResponse} from '../static/api-response.mjs';

class FakeXHR {
  constructor(){FakeXHR.last=this;this.headers={};this.sends=0;}
  open(method,path){this.method=method;this.path=path;}
  setRequestHeader(k,v){this.headers[k]=v;}
  getResponseHeader(){return 'application/x-ndjson';}
  send(body){this.body=body;this.sends++;}
  abort(){this.onabort();}
}
test('credentialed POST sends one request and reads a streamed final answer',async()=>{
  const promise=postAPI('/api/chat',{question:'大馆'},new AbortController().signal,FakeXHR);
  const xhr=FakeXHR.last;
  assert.equal(xhr.withCredentials,true);
  assert.equal(xhr.method,'POST');assert.equal(xhr.path,'/api/chat');
  assert.equal(xhr.headers.Accept,'application/x-ndjson');
  assert.deepEqual(JSON.parse(xhr.body),{question:'大馆'});
  xhr.status=200;xhr.responseText='\n'+JSON.stringify({type:'result',status:200,data:{answer:{text:'大馆'}}});xhr.onload();
  assert.deepEqual(await readAPIResponse(await promise),{answer:{text:'大馆'}});
  assert.equal(xhr.sends,1);
});
test('aborting cancels the actual request and never retries',async()=>{
  const controller=new AbortController();const promise=postAPI('/api/chat',{},controller.signal,FakeXHR);
  controller.abort();await assert.rejects(promise,{name:'AbortError'});
  assert.equal(FakeXHR.last.sends,1);
});
test('network errors reject without a duplicate model submission',async()=>{
  const promise=postAPI('/api/chat',{},null,FakeXHR);FakeXHR.last.onerror();
  await assert.rejects(promise,TypeError);assert.equal(FakeXHR.last.sends,1);
});
test('an already aborted request is never sent',async()=>{
  const controller=new AbortController();controller.abort();
  await assert.rejects(postAPI('/api/history/read',{},controller.signal,FakeXHR),{name:'AbortError'});
  assert.equal(FakeXHR.last.sends,0);
});
