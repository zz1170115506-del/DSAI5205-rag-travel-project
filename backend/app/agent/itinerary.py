from app.models import Attraction
from app.rag.retrieval.search import distance_m


def arrange(factory, evidence, constraints):
    """Greedy demo itinerary. Budgets cover known visit duration/admission, not transit."""
    ids = list(dict.fromkeys(r['attraction_id'] for r in evidence if r['attraction_id']))
    with factory() as db:
        remaining = [db.get(Attraction, key) for key in ids]
        remaining = [a for a in remaining if a]
        selected, minutes, cost, last = [], 0, 0., None
        while remaining:
            if last:
                remaining.sort(key=lambda a: distance_m(float(last.latitude), float(last.longitude), float(a.latitude), float(a.longitude)))
            item = remaining.pop(0)
            if constraints.get('max_minutes') is not None and (item.visit_minutes is None or minutes + item.visit_minutes > constraints['max_minutes']):
                continue
            if constraints.get('max_price') is not None and (item.ticket_price_max_hkd is None or cost + float(item.ticket_price_max_hkd) > constraints['max_price']):
                continue
            selected.append(item.entity_id)
            minutes += item.visit_minutes or 0
            cost += float(item.ticket_price_max_hkd or 0)
            last = item
        return {'attraction_ids': selected, 'known_visit_minutes': minutes,
            'known_admission_hkd': cost,
            'limitation': '仅合计已知游玩时长和门票参考价，不含交通、餐饮、排队；未知费用和营业时间仍需核对。'}
