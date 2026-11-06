"""Read-only admission references; prices never filter or optimize an itinerary."""
from datetime import date
from decimal import Decimal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class AdmissionPrice(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    min_hkd: float = Field(ge=0, allow_inf_nan=False, multiple_of=0.01)
    max_hkd: float = Field(ge=0, allow_inf_nan=False, multiple_of=0.01)
    source_url: str
    checked: str
    scope: str = Field(min_length=1, max_length=200)

    @field_validator('source_url')
    @classmethod
    def source(cls, value):
        url = urlparse(value)
        if url.scheme != 'https' or not url.hostname or url.username or url.password:
            raise ValueError('Admission price requires an HTTPS source URL')
        return value

    @field_validator('checked')
    @classmethod
    def check_date(cls, value):
        if date.fromisoformat(value) > date.today():
            raise ValueError('Price verification date cannot be in the future')
        return value

    @model_validator(mode='after')
    def ordered_range(self):
        if self.min_hkd > self.max_hkd:
            raise ValueError('Admission price range is reversed')
        return self


def with_price_summary(plan):
    """Sum one admission per scheduled visit; unknowns remain explicitly unknown."""
    low, high, items, unknown = Decimal(0), Decimal(0), [], []
    for day in plan.get('days', []):
        for stop in day.get('stops', []):
            place = stop['place']
            if place.get('kind') == 'food':
                continue
            reference = {'place_id': place['id'], 'name': place['name'], 'day': day['day']}
            try:
                price = AdmissionPrice.model_validate(place.get('admission_price'))
            except ValidationError:
                unknown.append(reference)
                continue
            low += Decimal(str(price.min_hkd))
            high += Decimal(str(price.max_hkd))
            items.append({**reference, **price.model_dump()})
    return {**plan, 'price_summary': {
        'currency': 'HKD', 'basis': 'one_admission_per_person_per_scheduled_visit',
        'known_min_hkd': float(low) if items else None,
        'known_max_hkd': float(high) if items else None,
        'known_items': items, 'unknown_items': unknown,
        'admission_prices_complete': not unknown,
        'excluded_categories': ['transport', 'dining', 'accommodation', 'flights'],
        'trip_total_hkd': None,
    }}
