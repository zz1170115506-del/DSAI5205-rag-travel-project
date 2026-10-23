"""Civil travel dates; both endpoints count as travel days."""
import re
from datetime import date, timedelta

MAX_TRIP_DAYS = 366

def parse_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError('请使用 YYYY-MM-DD 格式的旅行日期。')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError('旅行日期无效，请重新选择。') from None

def resolve_dates(days=None, start_date=None, end_date=None):
    if (start_date is None) != (end_date is None):
        raise ValueError('请同时选择出发日期和结束日期。')
    if start_date is not None:
        start, end = parse_date(start_date), parse_date(end_date)
        count = (end-start).days+1
        if count < 1:
            raise ValueError('结束日期不能早于出发日期。')
        if count > MAX_TRIP_DAYS:
            raise ValueError('单次最多规划 366 天，请分段安排更长的旅程。')
        if days is not None and days != count:
            raise ValueError('旅行天数与所选日期不一致。')
        days = count
    if days is not None and (type(days) is not int or not 1 <= days <= MAX_TRIP_DAYS):
        raise ValueError('旅行天数须为 1–366 的整数。')
    return days

def date_for_day(start_date, offset):
    return (parse_date(start_date)+timedelta(days=offset)).isoformat()
