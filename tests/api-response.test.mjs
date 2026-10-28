import test from 'node:test';
import assert from 'node:assert/strict';
import {readAPIResponse} from '../static/api-response.mjs';

const response = (text, status=200, type='application/x-ndjson') => new Response(text,{status,headers:{'content-type':type}});
test('chat heartbeats never appear in the final answer',async()=>{
  const body='\n\n'+JSON.stringify({type:'result',status:200,data:{answer:{text:'大馆'}}})+'\n';
  assert.deepEqual(await readAPIResponse(response(body)),{answer:{text:'大馆'}});
});
test('normal JSON API responses stay compatible',async()=>{
  assert.deepEqual(await readAPIResponse(response('{"places":[]}',200,'application/json')),{places:[]});
  await assert.rejects(readAPIResponse(response('{"detail":"请登录"}',401,'application/json')),/请登录/);
});
test('in-stream errors preserve the message instead of becoming answers',async()=>{
  await assert.rejects(readAPIResponse(response('{"type":"result","status":409,"detail":"当前对话仍在处理"}\n')),/当前对话仍在处理/);
});
test('truncated, malformed and incomplete streams fail clearly',async()=>{
  for (const body of ['', '\n\n', '{broken', '{"type":"result","status":200}']) {
    await assert.rejects(readAPIResponse(response(body)),/中断|不完整/);
  }
});
