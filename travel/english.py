"""English presentation helpers; canonical records and tool values stay intact."""
import json
from functools import lru_cache

from .config import ROOT


@lru_cache(maxsize=1)
def place_texts():
    return json.loads((ROOT / 'data/places.en.json').read_text(encoding='utf-8'))


def english_answer(state, reason):
    """A grounded local fallback, never presented as a successful model answer."""
    if reason == 'clarify_days':
        days = state['trip'].get('days')
        return ('Please tell me the original trip length before adding or removing days.' if days is None else
                'The adjusted trip must contain 1–366 days. Your previous conditions are unchanged.')
    if reason == 'clarify':
        return 'Please choose a start and end date, or tell me how many days you would like to travel.'
    failures = {
        'live_guard': 'The available sources cannot confirm live opening hours, fares or weather. Please check the official source.',
        'map_needed': 'There are not enough matching places in the curated collection. A map lookup is needed.',
        'repeat': 'Repeated tool calls were stopped. Please refine the request and try again.',
        'limit': 'The tool-call limit was reached. Your confirmed preferences are retained.',
        'timeout': 'This turn timed out. Please retry or simplify the request; confirmed preferences are retained.',
        'model_error': 'The model request or answer validation failed. Please retry or use the local knowledge demo.',
        'tool_error': 'The tools could not satisfy the current constraints. Adjust the area, duration or selected places.',
    }
    if reason in failures:
        return failures[reason]
    if state.get('plan'):
        plan = state['plan']
        free = plan.get('coverage', {}).get('flex_days', 0)
        text = f"Your {plan['days_requested']}-day itinerary draft is ready below."
        if free:
            text += f' {free} day(s) remain free for rest or your own activities because of the selected places or limited source coverage.'
        return text + ' Times and transfers are estimates; check official arrangements before travelling.'
    hits = state.get('hits', [])
    if hits:
        rows = ['Based on the curated sources, consider:']
        for index, place in enumerate(hits[:4], 1):
            text = place_texts()[place['id']]
            rows.append(f"{index}. {text['name']} ({text['area']}): {text['summary']} [{place['id']}]")
        rows.append('You can select places and ask for an itinerary, or refine your travel preferences.')
        return '\n\n'.join(rows)
    return 'There is not enough source evidence for this request. Try a specific Hong Kong place or adjust your preferences.'
