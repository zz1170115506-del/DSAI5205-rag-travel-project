// Pending messages keep the connection active; only the final result reaches UI.
export async function readAPIResponse(response) {
  if (!response.ok) {
    let obj = {}; try { obj = await response.json(); } catch {}
    throw Error(typeof obj.detail === 'string' ? obj.detail : '服务暂不可用，请重试。');
  }
  if (!response.headers.get('content-type')?.includes('application/x-ndjson')) return response.json();
  const lines = (await response.text()).trim().split('\n');
  let event;
  try { event = JSON.parse(lines.at(-1)); } catch {}
  if (event?.type !== 'result' || !Number.isInteger(event.status)) {
    throw Error('回答连接中断，请重试；也可在“我的旅程”查看是否已保存。');
  }
  if (event.status >= 400) throw Error(typeof event.detail === 'string' ? event.detail : '服务暂不可用，请重试。');
  if (event.status !== 200 || !event.data || typeof event.data !== 'object' || Array.isArray(event.data)) {
    throw Error('回答格式不完整，请重试。');
  }
  return event.data;
}
