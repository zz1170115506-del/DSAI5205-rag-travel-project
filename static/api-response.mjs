// Pending messages keep the connection active; only the final result reaches UI.
export async function readAPIResponse(response) {
  if (!response.ok) {
    let obj = {}; try { obj = await response.json(); } catch {}
    throw Error(typeof obj.detail === 'string' ? obj.detail : 'The service is temporarily unavailable. Please try again.');
  }
  if (!response.headers.get('content-type')?.includes('application/x-ndjson')) return response.json();
  const lines = (await response.text()).trim().split('\n');
  let event;
  try { event = JSON.parse(lines.at(-1)); } catch {}
  if (event?.type !== 'result' || !Number.isInteger(event.status)) {
    throw Error('The answer connection was interrupted. Retry or check My Journey for a saved result.');
  }
  if (event.status >= 400) throw Error(typeof event.detail === 'string' ? event.detail : 'The service is temporarily unavailable. Please try again.');
  if (event.status !== 200 || !event.data || typeof event.data !== 'object' || Array.isArray(event.data)) {
    throw Error('The answer was incomplete. Please try again.');
  }
  return event.data;
}
