// Explicit browser credentials for protected, same-origin API submissions.
// A single XHR request avoids retrying a potentially completed model call.
export function postAPI(path, body, signal, XHR = XMLHttpRequest) {
  return new Promise((resolve, reject) => {
    const xhr = new XHR();
    const cleanup = () => signal?.removeEventListener('abort', abort);
    const abort = () => xhr.abort();
    xhr.open('POST', path);
    xhr.withCredentials = true;
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.setRequestHeader('Accept', path === '/api/chat' ? 'application/x-ndjson' : 'application/json');
    xhr.onload = () => {
      cleanup();
      if (!xhr.status) { reject(new TypeError('请求连接中断')); return; }
      resolve(new Response(xhr.status === 204 ? null : xhr.responseText, {
        status: xhr.status,
        headers: {'content-type': xhr.getResponseHeader('Content-Type') || 'application/json'}
      }));
    };
    xhr.onerror = () => { cleanup(); reject(new TypeError('请求连接中断')); };
    xhr.onabort = () => { cleanup(); reject(new DOMException('请求已取消', 'AbortError')); };
    if (signal?.aborted) { reject(new DOMException('请求已取消', 'AbortError')); return; }
    signal?.addEventListener('abort', abort, {once: true});
    xhr.send(JSON.stringify(body));
  });
}
