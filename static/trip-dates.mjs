export const MAX_TRIP_DAYS=366;
// Calendar days are counted inclusively and independently of browser timezone.
export function addDays(value, offset) {
  const date=parseDate(value);date.setUTCDate(date.getUTCDate()+offset);
  return date.toISOString().slice(0,10);
}
function parseDate(value){
  if(!/^\d{4}-\d{2}-\d{2}$/.test(value??''))throw Error('请选择完整的出发日期和结束日期。');
  const date=new Date(value+'T00:00:00Z');
  if(!Number.isFinite(date.getTime())||date.toISOString().slice(0,10)!==value||value.startsWith('0000'))throw Error('旅行日期无效，请重新选择。');
  return date;
}
export function travelDates(start,end){
  const first=parseDate(start),last=parseDate(end),days=Math.round((last-first)/86400000)+1;
  if(days<1)throw Error('结束日期不能早于出发日期。');
  if(days>MAX_TRIP_DAYS)throw Error('单次最多规划 366 天，请分段安排更长的旅程。');
  return {start_date:start,end_date:end,days};
}
export function dateLabel(value){return value?value.replaceAll('-',' / '):'';}
