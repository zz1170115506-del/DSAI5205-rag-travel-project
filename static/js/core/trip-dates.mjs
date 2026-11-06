export const MAX_TRIP_DAYS=366;
// Calendar days are counted inclusively and independently of browser timezone.
export function addDays(value, offset) {
  const date=parseDate(value);date.setUTCDate(date.getUTCDate()+offset);
  return date.toISOString().slice(0,10);
}
function parseDate(value){
  if(!/^\d{4}-\d{2}-\d{2}$/.test(value??''))throw Error('Choose both the start and end date.');
  const date=new Date(value+'T00:00:00Z');
  if(!Number.isFinite(date.getTime())||date.toISOString().slice(0,10)!==value||value.startsWith('0000'))throw Error('The travel date is invalid. Please choose again.');
  return date;
}
export function travelDates(start,end){
  const first=parseDate(start),last=parseDate(end),days=Math.round((last-first)/86400000)+1;
  if(days<1)throw Error('The end date cannot precede the start date.');
  if(days>MAX_TRIP_DAYS)throw Error('A trip can contain up to 366 days. Split a longer journey into separate plans.');
  return {start_date:start,end_date:end,days};
}
export function dateLabel(value){return value?value.replaceAll('-',' / '):'';}
