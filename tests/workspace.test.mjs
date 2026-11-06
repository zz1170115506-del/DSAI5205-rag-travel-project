import test from 'node:test';
import assert from 'node:assert/strict';
import {restoreJourney,acceptJourneyResult} from '../static/js/itinerary/workspace.mjs';
import {inlineAnswerHTML} from '../static/js/chat/answer-citations.mjs';

test('read-only turns and late responses never replace the current itinerary',()=>{
 const state={plan:{id:'current'},planVersion:2};
 assert.equal(acceptJourneyResult(state,{plan_changed:false,plan:null,plan_version:2}),false);
 assert.equal(acceptJourneyResult(state,{plan_changed:true,plan:{id:'late'},plan_version:1}),false);
 assert.equal(state.plan.id,'current');
 assert.equal(acceptJourneyResult(state,{plan_changed:true,plan:{id:'new'},plan_version:3}),true);
 assert.equal(state.plan.id,'new');
});

test('history restores checkpoint itinerary even when the last message has no plan',()=>{
 const restored=restoreJourney({checkpoint:{journey_plan:{id:'saved'},plan_version:3},
  turns:[{result:{plan:{id:'older'}}},{result:{plan:null}}]});
 assert.deepEqual(restored,{plan:{id:'saved'},version:3});
});

test('paragraph citations link to actual sources and retain physical page numbers',()=>{
 const html=inlineAnswerHTML({text:'A historic building [paragraph-1]',citations:['paragraph-1'],retrieval_source:'documents'},null,
  [{id:'paragraph-1',source_url:'https://example.org/document.pdf',title:'Document',page_number:4}]);
 assert.match(html,/href="https:\/\/example.org\/document.pdf"/);
 assert.match(html,/PDF p. 4/);
 assert.doesNotMatch(html,/data-action="detail"/);
});
