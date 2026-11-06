import test from 'node:test';
import assert from 'node:assert/strict';
import {priceSummaryHTML,priceSummaryText} from '../static/js/itinerary/pricing.mjs';

test('missing price information never becomes a zero-priced trip',()=>{
 const html=priceSummaryHTML({});
 assert.match(html,/To verify/);
 assert.doesNotMatch(html,/HK\$ 0/);
});

test('a known zero admission retains its source and is only a subtotal',()=>{
 const plan={price_summary:{known_min_hkd:0,known_max_hkd:0,unknown_items:[{name:'Another place'}],
  known_items:[{name:'A place',scope:'Standard entry',checked:'2026-11-06',source_url:'https://example.org/ticket'}]}};
 assert.match(priceSummaryHTML(plan),/Known admission subtotal: HK\$ 0/);
 assert.match(priceSummaryHTML(plan),/1 scheduled admission price/);
 assert.match(priceSummaryText(plan),/Another place: price to verify/);
 assert.match(priceSummaryText(plan),/https:\/\/example.org\/ticket/);
});

test('price sources and labels are escaped and unsafe links are not rendered',()=>{
 const html=priceSummaryHTML({price_summary:{known_min_hkd:10,known_max_hkd:20,unknown_items:[],
  known_items:[{name:'<img src=x onerror=alert(1)>',scope:'<script>x</script>',checked:'2026-11-06',source_url:'javascript:alert(1)'}]}});
 assert.match(html,/HK\$ 10–20/);
 assert.doesNotMatch(html,/<script>|<img|href="javascript:/);
});
