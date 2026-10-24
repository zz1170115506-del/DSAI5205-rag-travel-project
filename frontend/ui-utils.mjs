export function sourceURL(value, type) {
  if (!value || type === 'synthetic') return null;
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.hostname.endsWith('.invalid')) return null;
    return url.href;
  } catch { return null; }
}

export function requestId(cryptoApi = globalThis.crypto) {
  if (typeof cryptoApi?.randomUUID === 'function') return cryptoApi.randomUUID();
  if (typeof cryptoApi?.getRandomValues === 'function') {
    const bytes = cryptoApi.getRandomValues(new Uint8Array(16));
    return [...bytes].map(x => x.toString(16).padStart(2, '0')).join('');
  }
  // This is an idempotency identifier, never an authentication credential.
  return `request-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function eventParser() {
  let pending = '';
  return {
    push(chunk, finished = false) {
      pending += chunk;
      const output = [];
      let match;
      const parse = block => {
        const data = block.split(/\r?\n/).filter(l => l.startsWith('data:')).map(l => l.slice(5).trimStart()).join('\n');
        if (!data) return;
        try { output.push(JSON.parse(data)); }
        catch { throw new Error('回答数据格式异常，请重新提问。'); }
      };
      while ((match = /\r?\n\r?\n/.exec(pending))) {
        parse(pending.slice(0, match.index));
        pending = pending.slice(match.index + match[0].length);
      }
      if (finished && pending.trim()) { parse(pending); pending = ''; }
      return output;
    }
  };
}

export async function readWithTimeout(reader, controller, milliseconds = 45000) {
  let timer;
  try {
    return await Promise.race([
      reader.read(),
      new Promise((_, reject) => {
        timer = setTimeout(() => {
          reject(new Error('回答连接等待过久，请重试。'));
          controller.abort();
        }, milliseconds);
      })
    ]);
  } finally { clearTimeout(timer); }
}

export function startPending(row, text) {
  row.received = false;
  row.text.textContent = text;
  row.wrapper.classList.add('pending');
}

export function receiveToken(row, text) {
  if (!row.received) {
    row.text.textContent = '';
    row.received = true;
    row.wrapper.classList.remove('pending');
  }
  row.text.textContent += text;
}
