import test from 'node:test';
import assert from 'node:assert/strict';
import {sourceURL, requestId, eventParser, readWithTimeout, startPending, receiveToken} from '../ui-utils.mjs';

test('SSE handles split delimiters, CRLF, heartbeats and multiple events', () => {
  const parser = eventParser();
  assert.deepEqual(parser.push(': heartbeat\r\n\r\ndata: {"type":"token","text":"你'), []);
  assert.deepEqual(parser.push('好"}\r'), []);
  assert.deepEqual(parser.push('\n\r\ndata: {"type":"done"}\n\n'), [{type:'token',text:'你好'},{type:'done'}]);
});
test('SSE preserves Unicode when the transport splits bytes', () => {
  const bytes = new TextEncoder().encode('data: {"text":"香港旅行"}\n\n');
  const decoder = new TextDecoder(); const parser = eventParser(); const events=[];
  for (let i=0;i<bytes.length;i+=2) events.push(...parser.push(decoder.decode(bytes.slice(i,i+2),{stream:true})));
  events.push(...parser.push(decoder.decode(),true));
  assert.deepEqual(events,[{text:'香港旅行'}]);
});
test('SSE flushes a final event and reports corrupt data', () => {
  assert.deepEqual(eventParser().push('data: {"type":"done"}',true),[{type:'done'}]);
  assert.throws(()=>eventParser().push('data: broken\n\n'),/格式异常/);
});
test('synthetic citations open local evidence instead of broken external links', () => {
  assert.equal(sourceURL('https://example.invalid/evidence','synthetic'),null);
  assert.equal(sourceURL('https://example.invalid/evidence'),null);
  assert.equal(sourceURL('javascript:alert(1)'),null);
  assert.equal(sourceURL('https://user:password@example.com'),null);
  assert.equal(sourceURL('https://example.com/source','official'),'https://example.com/source');
});
test('request IDs work without crypto.randomUUID', () => {
  assert.equal(requestId({randomUUID:()=> 'uuid'}),'uuid');
  assert.equal(requestId({getRandomValues:bytes=>bytes.fill(5)}),'05'.repeat(16));
  assert.match(requestId({}),/^request-/);
});
test('a stalled stream is aborted and releases the read', async () => {
  const controller = new AbortController();
  await assert.rejects(readWithTimeout({read:()=>new Promise(()=>{})},controller,5),/等待过久/);
  assert.equal(controller.signal.aborted,true);
});
test('normal stream reads do not abort the connection', async () => {
  const controller=new AbortController();
  assert.deepEqual(await readWithTimeout({read:async()=>({done:true})},controller,50),{done:true});
  assert.equal(controller.signal.aborted,false);
});

test('the first answer token replaces the loading hint, later tokens append', () => {
  const classes=new Set();
  const row={received:true,text:{textContent:'发送中…'},wrapper:{classList:{add:c=>classes.add(c),remove:c=>classes.delete(c)}}};
  startPending(row,'正在理解你的问题');
  assert.equal(row.received,false);
  assert.equal(classes.has('pending'),true);
  receiveToken(row,'你好');receiveToken(row,'，香港');
  assert.equal(row.text.textContent,'你好，香港');
  assert.equal(classes.has('pending'),false);
});
