import test from 'node:test';
import assert from 'node:assert/strict';
import {travelDates,addDays,dateLabel} from '../static/trip-dates.mjs';
test('inclusive same-day and three-day ranges',()=>{
 assert.equal(travelDates('2026-10-24','2026-10-24').days,1);
 assert.deepEqual(travelDates('2026-10-24','2026-10-26'),{days:3,start_date:'2026-10-24',end_date:'2026-10-26'});
});
test('calendar boundaries are timezone independent',()=>{
 assert.equal(addDays('2026-12-31',1),'2027-01-01');
 assert.equal(travelDates('2028-02-28','2028-03-01').days,3);
 assert.equal(travelDates('2026-10-31','2026-11-01').days,2);
 assert.equal(dateLabel('2026-10-24'),'2026 / 10 / 24');
});
test('reject partial, nonexistent, reversed and unsupported ranges',()=>{
 for(const [a,b] of [['','2026-10-24'],['2026-10-24',''],['2026-02-30','2026-03-01'],['2026-10-25','2026-10-24'],['2026-10-24','2027-10-25']])assert.throws(()=>travelDates(a,b));
});

test('long ranges derive complete inclusive calendar lengths',()=>{
 assert.equal(travelDates('2026-10-24','2026-11-06').days,14);
 assert.equal(travelDates('2026-12-28','2027-01-06').days,10);
 assert.equal(travelDates('2028-01-01','2028-12-31').days,366);
});
