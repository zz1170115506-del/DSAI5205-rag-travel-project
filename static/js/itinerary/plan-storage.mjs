// 只恢复当前资料版本的有效草案。存储不可用时，当前页面仍能正常使用。
export const PLAN_KEY = 'hkslow-plan-v2';
const regions = new Set(['全部', '香港岛', '九龙', '大屿山']);
const clock = value => typeof value === 'string' && /^([01]\d|2[0-3]):[0-5]\d$/.test(value);
const strings = value => Array.isArray(value) && value.every(v => typeof v === 'string');

export function readSavedPlan(storage, knowledgeVersion, places, interests) {
  try {
    const raw = storage.getItem(PLAN_KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw), plan = saved?.plan, input = saved?.input;
    const known = new Set(places.map(p => p.id));
    if (saved.schema !== 2 || saved.knowledge_version !== knowledgeVersion || !plan || !input) return null;
    if (![1, 2, 3].includes(input.days) || !regions.has(input.region) || !['轻松', '充实'].includes(input.pace)) return null;
    if (typeof input.rain !== 'boolean' || typeof input.public_only !== 'boolean' || !strings(input.interests) || !input.interests.every(t => interests.includes(t))) return null;
    if (!strings(input.must_visit) || input.must_visit.length > 3 || !input.must_visit.every(id => known.has(id))) return null;
    if (!Array.isArray(plan.days) || !plan.days.length || plan.days.length > input.days || !strings(plan.warnings) || typeof plan.algorithm !== 'string') return null;
    if (!Array.isArray(plan.trace) || !plan.trace.every(t => strings(t.steps))) return null;
    const used = new Set();
    for (const day of plan.days) {
      if (!Array.isArray(day.stops) || !day.stops.length || !Array.isArray(day.legs) || day.legs.length !== day.stops.length - 1 || !clock(day.end)) return null;
      for (const stop of day.stops) {
        if (!stop.place || !known.has(stop.place.id) || used.has(stop.place.id) || !clock(stop.start) || !clock(stop.end) || stop.start >= stop.end) return null;
        if (!strings(stop.place.tags) || typeof stop.place.summary !== 'string' || !Number.isFinite(stop.place.lat) || !Number.isFinite(stop.place.lon)) return null;
        used.add(stop.place.id);
      }
    }
    if (!input.must_visit.every(id => used.has(id))) return null;
    return saved;
  } catch { return null; }
}

export function savePlan(storage, knowledgeVersion, plan, input) {
  try {
    storage.setItem(PLAN_KEY, JSON.stringify({schema: 2, knowledge_version: knowledgeVersion, plan, input}));
    return true;
  } catch { return false; }
}

export function clearPlan(storage) {
  try {
    storage.removeItem(PLAN_KEY);
    storage.removeItem('hkslow-plan-v1');
  } catch { /* 关闭浏览器存储也不妨碍当前页面清除。 */ }
}
