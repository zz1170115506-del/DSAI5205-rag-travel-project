from copy import deepcopy

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from app import app
from travel.itinerary.preferences import Trip
from travel.itinerary.pricing import AdmissionPrice, with_price_summary


def price(low=10, high=20, **changes):
    return {**dict(min_hkd=low,max_hkd=high,source_url='https://example.org/admission',
                   checked='2026-11-06',scope='Standard adult admission'),**changes}


def itinerary(*places):
    return {'days':[{'day':1,'stops':[{'place':p} for p in places]}]}


def test_price_summary_preserves_stops_and_unknowns_without_claiming_full_total():
    plan=itinerary({'id':'a','name':'A','admission_price':price()},
                   {'id':'b','name':'B','cost':'public'},
                   {'id':'c','name':'C','kind':'food'})
    before=deepcopy(plan)
    result=with_price_summary(plan)
    assert plan==before and result['days']==before['days']
    summary=result['price_summary']
    assert (summary['known_min_hkd'],summary['known_max_hkd'])==(10,20)
    assert [x['place_id'] for x in summary['unknown_items']]==['b']
    assert summary['trip_total_hkd'] is None and not summary['admission_prices_complete']
    assert summary['known_items'][0]['source_url']=='https://example.org/admission'


def test_missing_prices_do_not_become_zero_but_sourced_free_entry_can_be_zero():
    unknown=with_price_summary(itinerary({'id':'a','name':'A','cost':'public'}))['price_summary']
    assert unknown['known_min_hkd'] is None
    free=with_price_summary(itinerary({'id':'a','name':'A','admission_price':price(0,0)}))['price_summary']
    assert free['known_min_hkd']==free['known_max_hkd']==0
    assert free['admission_prices_complete']


@pytest.mark.parametrize('reference',[price(-1,2),price(3,2),price(source_url='javascript:alert(1)'),
                                      price(checked='2999-01-01'),price(scope=''),price(float('nan'),2)])
def test_invalid_price_references_are_rejected(reference):
    with pytest.raises(ValidationError):
        AdmissionPrice.model_validate(reference)


def test_money_constraints_are_not_part_of_trip_or_planning_api():
    for field in ['budget','budget_hkd','max_price']:
        with pytest.raises(ValidationError):
            Trip.model_validate({'days':1,field:100})
        with TestClient(app) as client:
            assert client.post('/api/plan',json={'days':1,field:100}).status_code==422
