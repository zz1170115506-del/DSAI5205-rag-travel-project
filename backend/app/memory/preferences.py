import re

from sqlalchemy import select

from app.models import Preference, now
from app.rag.text import normalize

KEYS = {'interests', 'avoidances', 'budget_hkd', 'walking_minutes', 'language'}


def validate_preference(key, value):
    if key not in KEYS:
        raise ValueError('Unknown preference key')
    if key in {'interests', 'avoidances'}:
        if not isinstance(value, list) or len(value) > 20 or any(not isinstance(x, str) or not 1 <= len(x) <= 80 for x in value):
            raise ValueError('Preference requires up to 20 short strings')
    elif key in {'budget_hkd', 'walking_minutes'}:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100000:
            raise ValueError('Preference requires a non-negative number')
    elif value not in {'zh-Hans', 'zh-Hant', 'en'}:
        raise ValueError('Invalid language')


def read_profile(db, user):
    if not user.memory_enabled:
        return {}
    return {p.preference_key: p.value for p in db.scalars(select(Preference).where(
        Preference.user_id == user.user_id, Preference.status == 'active'))}


def save_preference(db, user_id, key, value, source_message_id=None):
    validate_preference(key, value)
    pref = db.scalar(select(Preference).where(Preference.user_id == user_id, Preference.preference_key == key))
    if pref is None:
        pref = Preference(user_id=user_id, preference_key=key)
        db.add(pref)
    pref.value, pref.status, pref.deleted_at = value, 'active', None
    pref.source_message_id = source_message_id
    pref.origin = 'explicit_message' if source_message_id else 'user_edit'
    pref.confirmed_at = now()


def explicit_preferences(text):
    """Only explicit opt-in instructions. No speculative profile inference."""
    q = normalize(text)
    if not any(x in q for x in ['记住', 'remember']):
        return {}
    values = {}
    like = re.search(r'(?:喜欢|偏好|like|prefer)\s*([^，。；!！\n]{1,80})', q)
    negative = re.search(r'(?:不喜欢|避免|讨厌|avoid|dislike)\s*([^，。；!！\n]{1,80})', q)
    if negative:
        values['avoidances'] = [negative.group(1).strip()]
    elif like:
        values['interests'] = [like.group(1).strip()]
    budget = re.search(r'(?:预算|budget)\D{0,6}(\d+(?:\.\d+)?)', q)
    if budget:
        values['budget_hkd'] = float(budget.group(1))
    return values
