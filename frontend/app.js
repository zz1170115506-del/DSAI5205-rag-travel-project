import {sourceURL, requestId, eventParser, readWithTimeout, startPending, receiveToken} from './ui-utils.mjs';

const $ = id => document.getElementById(id);
const state = {session:null,active:null,cards:[],creating:false,switching:false,ready:false};
const API = '/api/v1';
const statuses = {queued:'排队中',planning:'正在理解问题',retrieving:'正在检索资料',generating:'正在生成回答'};
let toastTimer;
async function api(path, options={}) {
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),20000);
  try {
    const response=await fetch(API+path,{credentials:'same-origin',...options,signal:controller.signal,
      headers:{'Content-Type':'application/json',...options.headers}});
    let data;
    try {data=await response.json();} catch {throw new Error('服务返回了无效响应，请稍后重试。');}
    if(!response.ok) {
      const message=response.status===401?'访客会话已过期，请刷新页面重新连接。':response.status===404?'会话或资料不存在，请新建会话后重试。':data.message||`请求失败 (${response.status})`;
      throw new Error(message);
    }
    return data;
  } catch(error) {
    if(error.name==='AbortError')throw new Error('请求超时，请检查服务连接后重试。');
    if(error instanceof TypeError)throw new Error('无法连接服务，请检查网络后重试。');
    throw error;
  } finally {clearTimeout(timer);}
}
function toast(text) {clearTimeout(toastTimer);$('toast').textContent=text;$('toast').hidden=false;toastTimer=setTimeout(()=>$('toast').hidden=true,6500);}
function el(tag,text,cls) {const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;}
function busy() {
  const locked=state.creating||state.switching;
  $('send').disabled=!state.ready||locked;
  $('send').textContent=state.creating?'发送中…':state.active?'补充并重新回答 ↗':'发送 ↗';
  $('new-chat').disabled=locked;
  $('sessions').disabled=locked;
  $('stop').disabled=!state.active;
  for(const node of document.querySelectorAll('.prompt'))node.disabled=!state.ready||locked;
}
function focusChat() {$('chat').scrollIntoView({behavior:'smooth',block:'start'});$('question').focus({preventScroll:true});}
function setQuestion(question,submit=true) {
  if(state.creating||state.switching){toast('正在处理上一次操作，请稍候。');return;}
  $('question').value=question;focusChat();
  if(submit) {
    if(!state.ready){toast('服务连接尚未就绪，请点击重新连接。');return;}
    $('chat-form').requestSubmit();
  }
}
function renderCards(items) {
  $('cards').replaceChildren();state.cards=items;
  for(const item of items) {
    const card=el('article',undefined,'card');card.tabIndex=0;card.setAttribute('role','button');card.setAttribute('aria-label',`查看${item.name_zh}详情`);card.dataset.id=item.entity_id;
    const image=el('div',undefined,'card-image');
    image.append(el('span',({museum:'▥',park:'♧',heritage:'⌂',market:'▦',viewpoint:'◉'})[item.category]||'◇'),el('small',item.setting==='indoor'?'INDOOR / 探索':'DISCOVER / 漫游'));
    const photo=item.images?.[0];
    if(photo) {
      const url=photo.url?.startsWith('/api/')?photo.url:sourceURL(photo.url);
      if(url){const img=document.createElement('img');img.src=url;img.alt=photo.caption;img.loading='lazy';img.onerror=()=>img.remove();image.prepend(img);}
    }
    const body=el('div',undefined,'card-body');body.append(el('h3',item.name_zh),el('p',item.summary));
    const meta=el('div',undefined,'card-meta');
    meta.append(el('span',item.relations.find(r=>r.predicate==='LOCATED_IN')?.name||'地区待补充'),el('span',item.visit_minutes?`约 ${item.visit_minutes} 分钟`:'时长待核对'));
    body.append(meta);card.append(image,body);
    card.onclick=()=>selectAttraction(item);
    card.onkeydown=e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();selectAttraction(item);}};
    $('cards').append(card);
  }
  if(!items.length)$('cards').append(el('p','没有符合条件的景点，请调整筛选。'));
  renderPins(items);
}
function renderPins(items) {
  $('pins').replaceChildren();const ns='http://www.w3.org/2000/svg';
  for(const item of items) {
    const circle=document.createElementNS(ns,'circle');
    circle.setAttribute('cx',String(Math.max(15,Math.min(385,20+(Number(item.longitude)-114.13)/.07*360))));
    circle.setAttribute('cy',String(Math.max(15,Math.min(245,240-(Number(item.latitude)-22.26)/.06*220))));
    circle.setAttribute('r','6');circle.dataset.id=item.entity_id;circle.setAttribute('tabindex','0');circle.setAttribute('role','button');circle.setAttribute('aria-label',`地图：${item.name_zh}`);
    const title=document.createElementNS(ns,'title');title.textContent=item.name_zh;circle.append(title);
    circle.onclick=()=>selectAttraction(item);circle.onkeydown=e=>{if(e.key==='Enter')selectAttraction(item);};$('pins').append(circle);
  }
}
function selectAttraction(item) {
  for(const node of document.querySelectorAll('.card,#pins circle'))node.classList.toggle('selected',node.dataset.id===item.entity_id);
  $('map-name').textContent=`已选择 · ${item.name_zh}`;
  const lat=Number(item.latitude),lon=Number(item.longitude);
  $('map-frame').src=`https://www.openstreetmap.org/export/embed.html?bbox=${lon-.012},${lat-.008},${lon+.012},${lat+.008}&layer=mapnik&marker=${lat},${lon}`;
  $('map-frame').hidden=false;
  $('detail').replaceChildren(el('h3',item.name_zh),el('p',item.summary),el('p',`地址：${item.address_zh}`),el('p',`参考票价：${item.ticket_price_min_hkd==null?'未知':'HK$ '+item.ticket_price_min_hkd} · ${item.ticket_note||'请核对官方信息'}`));
  const ask=el('button','询问这个景点 ↗');ask.type='button';ask.onclick=()=>setQuestion(`介绍一下${item.name_zh}`);$('detail').append(ask);
  if(window.matchMedia('(max-width: 900px)').matches)document.querySelector('.map-panel').scrollIntoView({behavior:'smooth',block:'start'});
}
async function browse() {
  const q=new URLSearchParams();if($('setting').value)q.set('setting',$('setting').value);
  renderCards((await api('/attractions?'+q)).items);
}
async function search() {
  $('search-button').disabled=true;$('search-button').textContent='检索中…';$('setting').disabled=true;$('cards').inert=true;$('cards').setAttribute('aria-busy','true');
  try {
    const query=$('search-input').value.trim();
    if(!query)await browse();
    else {
      const result=await api('/search',{method:'POST',body:JSON.stringify({query,setting:$('setting').value||null})});
      const ids=[...new Set(result.results.map(x=>x.attraction_id).filter(Boolean))];
      renderCards(await Promise.all(ids.map(id=>api('/attractions/'+encodeURIComponent(id)))));
    }
    toast(`找到 ${state.cards.length} 个景点`);
  } catch(error){toast(error.message);}
  finally {$('search-button').disabled=false;$('search-button').textContent='检索';$('setting').disabled=false;$('cards').inert=false;$('cards').removeAttribute('aria-busy');}
}
function message(role,content='',citations=[]) {
  if($('messages').querySelector('.welcome'))$('messages').replaceChildren();
  const wrapper=el('div',undefined,`message ${role}`);wrapper.append(el('span',role==='user'?'YOU':'TRAVEL LAB','label'));
  const text=el('div',content,'message-text');const sourceBox=el('div',undefined,'citations');wrapper.append(text,sourceBox);$('messages').append(wrapper);
  citations.forEach((c,i)=>citation(sourceBox,c,i+1));
  $('messages').scrollTop=$('messages').scrollHeight;return {wrapper,text,sourceBox,received:!!content};
}
function showEvidence(data,number) {
  $('evidence-title').textContent=`[${number}] ${data.name||'回答依据'}`;
  $('evidence-content').textContent=data.text||'暂无片段正文。';
  $('evidence-meta').textContent=`定位：${data.locator||'未提供'} · 核对时间：${data.verified_at||'未知'}`;
  const url=sourceURL(data.source_url,data.source_type);
  $('evidence-source').hidden=!url;if(url)$('evidence-source').href=url;else $('evidence-source').removeAttribute('href');
  $('evidence-note').textContent=url?'你可以查看完整片段，或打开原始来源。':'这是演示资料，没有可访问的外部来源页；下方展示实际检索证据。';
  $('evidence-paths').textContent=data.relation_paths?.length?`本回答使用了 ${data.relation_paths.length} 条景点关联路径。`:'';
  $('evidence-dialog').showModal();
}
function citation(box,data,number) {
  const button=el('button',`[${number}] ${data.name||'查看依据'}`);button.type='button';button.title='查看回答依据与来源';button.onclick=()=>showEvidence(data,number);box.append(button);
  if(data.relation_paths?.length){const button=el('button','查看关联依据');button.type='button';button.onclick=()=>showEvidence(data,number);box.append(button);}
}
async function sessions() {
  const list=await api('/sessions');$('sessions').replaceChildren();
  list.forEach((s,i)=>{const opt=el('option',s.title||`新会话 ${list.length-i}`);opt.value=s.session_id;$('sessions').append(opt);});$('sessions').value=state.session||'';
}
function finishActive(active,status) {
  clearInterval(active.timer);
  active.row.wrapper.classList.remove('pending');
  if(state.active===active){state.active=null;$('chat-status').textContent=status;busy();}
}
async function stop() {
  const active=state.active;if(!active)return;
  $('chat-status').textContent='正在停止…';
  try {await api(`/runs/${active.id}/cancel`,{method:'POST',body:'{}'});}
  finally {
    active.controller.abort();
    if(!active.row.received)active.row.text.textContent='已停止。可以继续提问或补充条件。';
    finishActive(active,'已停止');
  }
}
async function ensureSession() {
  if(!state.session)state.session=(await api('/sessions',{method:'POST',body:'{}'})).session_id;
}
async function newSession({announce=true}={}) {
  if(state.creating||state.switching)return;
  state.switching=true;busy();$('chat-status').textContent='正在创建新会话…';
  try {
    await stop();state.session=(await api('/sessions',{method:'POST',body:'{}'})).session_id;
    $('messages').replaceChildren(el('div','新会话已创建，输入问题或点击左侧示例即可开始。','welcome'));
    $('constraints').textContent='';$('chat-status').textContent='新会话已就绪';await sessions();
    if(announce){toast('已创建新会话');$('question').focus({preventScroll:true});}
  } finally {state.switching=false;busy();}
}
async function loadSession(id) {
  if(state.creating||state.switching||!id)return;
  state.switching=true;busy();
  try {
    await stop();const s=await api('/sessions/'+encodeURIComponent(id));state.session=id;$('messages').replaceChildren();
    for(const m of s.messages){const row=message(m.role,m.content,m.citations);if(m.status!=='completed'&&m.role==='assistant')row.wrapper.append(el('small','（上次回答未完成，可继续提问）'));}
    if(!s.messages.length)$('messages').append(el('div','这个会话还没有消息，输入问题即可开始。','welcome'));
    $('chat-status').textContent='会话已恢复';
    if(s.active_run_id){const row=message('assistant');followRun(s.active_run_id,row,s.messages.filter(m=>m.role==='user').at(-1)?.content||'').catch(error=>toast(error.message));}
  } finally {state.switching=false;busy();}
}
function showFailure(row,error,question) {
  row.wrapper.classList.remove('pending');
  if(!row.received)row.text.textContent='这次未能完成回答。';
  const errorNode=el('div',error.message,'message-error');errorNode.setAttribute('role','alert');
  const retry=el('button','重新提问');retry.type='button';retry.onclick=()=>setQuestion(question);errorNode.append(retry);row.wrapper.append(errorNode);
  if(!$('question').value.trim())$('question').value=question;
}
async function restoreResult(id,row) {
  const result=await api('/runs/'+id);
  if(result.answer){row.text.textContent=result.answer;row.received=true;}
  if(!row.sourceBox.children.length)result.citations.forEach((c,i)=>citation(row.sourceBox,c,i+1));
  return result;
}
async function followRun(id,row,question) {
  const active={id,row,controller:new AbortController(),phase:'准备回答',started:Date.now()};state.active=active;busy();
  startPending(row,'正在理解你的问题，请稍候…');
  const showProgress=()=>{if(state.active!==active)return;const seconds=Math.floor((Date.now()-active.started)/1000);$('chat-status').textContent=`${active.phase} · ${seconds}秒`;if(!row.received)row.text.textContent=`${active.phase}…${seconds>=8?' 模型仍在处理，可以随时停止或补充条件。':''}`;};
  active.timer=setInterval(showProgress,1000);showProgress();
  let terminal=false;
  try {
    const response=await fetch(`${API}/runs/${id}/events`,{credentials:'same-origin',signal:active.controller.signal});
    if(!response.ok||!response.body)throw new Error('无法连接回答流，请重新提问。');
    const reader=response.body.getReader(),decoder=new TextDecoder(),parser=eventParser();
    function process(events) {
      for(const data of events){
        if(state.active!==active||data.run_id!==id)continue;
        if(data.type==='status'){active.phase=statuses[data.status]||'正在处理';showProgress();}
        else if(data.type==='token'){receiveToken(row,data.text);$('messages').scrollTop=$('messages').scrollHeight;}
        else if(data.type==='citation')citation(row.sourceBox,data.citation,data.number);
        else if(data.type==='error')throw new Error(data.message||'回答流已中断，请重新提问。');
        else if(data.type==='done'||data.type==='cancelled'){terminal=true;active.phase=data.status==='completed'?'已完成':data.status==='cancelled'?'已停止':'回答已中断';}
      }
    }
    while(state.active===active){const result=await readWithTimeout(reader,active.controller);if(result.done){process(parser.push(decoder.decode(),true));break;}process(parser.push(decoder.decode(result.value,{stream:true})));}
    if(state.active!==active)return;
    if(!terminal||!row.received){const result=await restoreResult(id,row);if(result.status==='completed'){terminal=true;active.phase='已完成';}else if(result.status==='cancelled'){terminal=true;active.phase='已停止';}else throw new Error('回答未完成，可以重新提问。');}
    if(!row.received)row.text.textContent=active.phase==='已停止'?'已停止，可以继续提问。':'模型没有返回文本，请重新提问。';
    finishActive(active,active.phase);await sessions();
  } catch(error) {
    if(state.active!==active)return;
    if(error.name!=='AbortError'){showFailure(row,error,question);toast(error.message);}
    try{await api(`/runs/${id}/cancel`,{method:'POST',body:'{}'});}catch{}
    active.controller.abort();finishActive(active,'回答未完成');
  } finally {clearInterval(active.timer);}
}
async function send(e) {
  e.preventDefault();const question=$('question').value.trim();
  if(!question||state.creating||state.switching)return;
  if(!state.ready){toast('服务未就绪，请点击重新连接。');return;}
  const submission=Symbol('submission');state.submission=submission;state.creating=true;busy();let row;
  try {
    await stop();await ensureSession();
    message('user',question);row=message('assistant');startPending(row,'正在发送问题…');$('question').value='';$('chat-status').textContent='正在发送问题…';
    const result=await api(`/sessions/${state.session}/runs`,{method:'POST',body:JSON.stringify({message:question,request_id:requestId()})});
    state.creating=false;busy();await followRun(result.run_id,row,question);
  } catch(error) {if(row)showFailure(row,error,question);toast(error.message);$('chat-status').textContent='发送未完成';}
  finally {if(state.submission===submission)state.creating=false;busy();}
}
async function showMemory() {
  const profile=await api('/me/preferences');$('memory-enabled').checked=profile.enabled;
  $('interest-input').value=(profile.values.interests||[]).join('，');$('preference-json').value=JSON.stringify(profile.values,null,2);$('memory-error').textContent='';$('memory-list').replaceChildren();
  for(const [key,value] of Object.entries(profile.values)) {
    const row=el('div');row.append(el('span',`${key}: ${JSON.stringify(value)}`));const remove=el('button','删除');remove.type='button';
    remove.onclick=async()=>{try{remove.disabled=true;await stop();await api('/me/preferences/'+encodeURIComponent(key),{method:'DELETE',body:'{}'});await showMemory();toast('偏好已删除');}catch(error){toast(error.message);remove.disabled=false;}};row.append(remove);$('memory-list').append(row);
  }
  if(!$('memory-dialog').open)$('memory-dialog').showModal();
}
$('memory-form').onsubmit=async e=>{
  e.preventDefault();const button=e.submitter||$('memory-form').querySelector('[type=submit]');button.disabled=true;button.textContent='保存中…';
  try {
    const values=JSON.parse($('preference-json').value||'{}');if(!values||Array.isArray(values)||typeof values!=='object')throw new Error('请填写 JSON 对象');
    const interests=$('interest-input').value.split(/[,，]/).map(s=>s.trim()).filter(Boolean);if(interests.length||'interests' in values)values.interests=interests;
    await stop();await api('/me/preferences',{method:'PATCH',body:JSON.stringify({enabled:$('memory-enabled').checked,values})});$('memory-dialog').close();toast('偏好已保存');
  } catch(error){$('memory-error').textContent=error.message;}
  finally{button.disabled=false;button.textContent='保存偏好';}
};
$('chat-form').onsubmit=send;$('question').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('chat-form').requestSubmit();}};
$('stop').onclick=()=>stop().catch(error=>toast(error.message));$('new-chat').onclick=()=>newSession().catch(error=>toast(error.message));
$('sessions').onchange=()=>loadSession($('sessions').value).catch(error=>toast(error.message));
$('search-button').onclick=search;$('search-input').onkeydown=e=>{if(e.key==='Enter')search();};$('setting').onchange=search;
$('memory-open').onclick=()=>showMemory().catch(error=>toast(error.message));$('memory-close').onclick=()=>$('memory-dialog').close();
$('evidence-close').onclick=()=>$('evidence-dialog').close();
for(const node of document.querySelectorAll('.prompt'))node.onclick=()=>setQuestion(node.dataset.prompt);
for(const node of document.querySelectorAll('a[href="#chat"]'))node.addEventListener('click',()=>setTimeout(()=>$('question').focus({preventScroll:true}),100));
async function init() {
  state.ready=false;busy();$('notice').textContent='正在连接服务…';
  try {
    const user=await api('/auth/guest',{method:'POST',body:'{}'});$('mode').textContent=user.model_mode==='mock'?'模拟模式':'真实模型';
    const health=await api('/health/ready');
    $('notice').textContent=(health.synthetic_data?'知识库已就绪，其中包含虚构演示数据，坐标、票价、故事仅用于流程检查。':'知识库已就绪，请核对回答来源与资料更新时间。')+(user.model_mode==='mock'?' 当前使用模拟模式。':'');
    await browse();const list=await api('/sessions');state.ready=true;
    if(list.length)await loadSession(list[0].session_id);else await newSession({announce:false});await sessions();
  } catch(error) {
    $('notice').replaceChildren(el('span',`服务连接未完成：${error.message} `));const retry=el('button','重新连接');retry.type='button';retry.onclick=init;$('notice').append(retry);toast(error.message);
  } finally {busy();}
}
init();
