"""Civil travel dates; both endpoints count as travel days."""
import re
from dataclasses import dataclass
from datetime import date, timedelta

MAX_TRIP_DAYS = 366


class DayChangeError(ValueError):
    """A day edit needs clarification; do not overwrite the existing trip."""


@dataclass(frozen=True)
class DayChange:
    operation: str
    amount: int

    def apply(self, current_days):
        if self.operation == 'set':
            result = self.amount
        else:
            if current_days is None:
                raise DayChangeError('还不知道原来的旅行天数，请先告诉我原本玩几天，再增加或减少天数。')
            result = current_days + (self.amount if self.operation == 'increase' else -self.amount)
        if not 1 <= result <= MAX_TRIP_DAYS:
            raise DayChangeError('调整后旅行天数须为 1–366 天；已保留原行程，请调整增加或减少的天数。')
        return result


def parse_day_change(question):
    """Separate an absolute duration from a relative edit; skip 第N天 references."""
    q = question.translate(str.maketrans('兩減長縮', '两减长缩'))
    matches = re.finditer(r'(?<![0-9.零〇一二三四五六七八九十百千万亿两])(-?[0-9]+(?:\.[0-9]+)?|[零〇一二三四五六七八九十百千万亿两]+)\s*天', q)
    match = next((m for m in matches if not re.search(r'第\s*$', q[:m.start()])), None)
    if not match:
        return None
    raw = match[1]
    if raw.isascii() and raw.isdigit():
        amount = int(raw)
    elif re.fullmatch(r'[零〇一二三四五六七八九十百千两]+', raw):
        digits = dict(zip('零〇一二三四五六七八九两', [0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 2]))
        amount, digit = 0, 0
        for char in raw:
            if char in digits:
                digit = digits[char]
            else:
                amount += (digit or 1) * {'十': 10, '百': 100, '千': 1000}[char]
                digit = 0
        amount += digit
    else:
        raise DayChangeError('请使用有效的整数旅行天数；已保留原行程。')
    if not 1 <= amount <= MAX_TRIP_DAYS:
        raise DayChangeError('旅行天数或增减量须为 1–366 的整数；已保留原行程。')
    prefix = q[:match.start()].rstrip()
    operation = 'set'
    if re.search(r'(?:增加|延长|追加|多玩|多留|多待|多住|再玩|再留|加|多)(?:上|了|多)?$', prefix):
        operation = 'increase'
    elif re.search(r'(?:减少|缩短|少玩|少留|少待|少住|减去|减|少)(?:了|掉)?$', prefix):
        operation = 'decrease'
    return DayChange(operation, amount)

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
