// Current itinerary is independent from messages: questions never replace it.
export function restoreJourney(saved){
 const checkpoint=saved.checkpoint??{};
 const plan=checkpoint.journey_plan??[...(saved.turns??[])].reverse().find(t=>t.result?.plan)?.result.plan??null;
 return {plan,version:checkpoint.plan_version??(plan?1:0)};
}

export function acceptJourneyResult(state,result){
 if(result.plan_changed!==true||!result.plan||!Number.isInteger(result.plan_version)||result.plan_version<=state.planVersion)return false;
 state.plan=result.plan;state.planVersion=result.plan_version;return true;
}
