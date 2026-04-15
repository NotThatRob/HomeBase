"""Shared input validation helpers.

Raise ``ValueError`` on failure; routes already convert these to 400 responses.
"""

from datetime import date, timedelta
from decimal import Decimal

MAX_SHORT_TEXT = 200
MAX_LONG_TEXT = 5000
MIN_YEAR = 1900
MAX_MILEAGE = 10_000_000
MAX_MONEY = Decimal("10000000")
MAX_GALLONS = Decimal("1000")
MAX_PRICE_PER_GALLON = Decimal("100")
MAX_SEARCH_QUERY = 200


def current_max_year() -> int:
    return date.today().year + 1


def ensure_short_text(value, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    if len(value) > MAX_SHORT_TEXT:
        raise ValueError(f"{field} must be {MAX_SHORT_TEXT} characters or fewer")


def ensure_long_text(value, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    if len(value) > MAX_LONG_TEXT:
        raise ValueError(f"{field} must be {MAX_LONG_TEXT} characters or fewer")


def ensure_nonnegative_int(value, field: str, upper: int | None = None) -> None:
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be a whole number")
    if value < 0:
        raise ValueError(f"{field} must be zero or greater")
    if upper is not None and value > upper:
        raise ValueError(f"{field} must be {upper:,} or less")


def ensure_positive_money(value, field: str, allow_zero: bool = False) -> None:
    if value is None:
        return
    if not isinstance(value, Decimal):
        raise ValueError(f"{field} must be a number")
    if allow_zero:
        if value < 0:
            raise ValueError(f"{field} must be zero or greater")
    elif value <= 0:
        raise ValueError(f"{field} must be greater than zero")
    if value > MAX_MONEY:
        raise ValueError(f"{field} is unreasonably large")


def ensure_money_upper(value, field: str, upper: Decimal) -> None:
    if value is None:
        return
    if not isinstance(value, Decimal):
        raise ValueError(f"{field} must be a number")
    if value > upper:
        raise ValueError(f"{field} must be {upper} or less")


def ensure_date_not_future(value, field: str, slack_days: int = 1) -> None:
    if value is None:
        return
    if not isinstance(value, date):
        raise ValueError(f"{field} must be a date")
    if value > date.today() + timedelta(days=slack_days):
        raise ValueError(f"{field} cannot be in the future")


def ensure_year_in_range(value, field: str = "year") -> None:
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be a whole number")
    if not (MIN_YEAR <= value <= current_max_year()):
        raise ValueError(f"{field} must be between {MIN_YEAR} and {current_max_year()}")


def ensure_date_in_range(value, field: str, max_years_ahead: int = 50) -> None:
    if value is None:
        return
    if not isinstance(value, date):
        raise ValueError(f"{field} must be a date")
    today = date.today()
    if value.year < MIN_YEAR:
        raise ValueError(f"{field} is too far in the past")
    if value.year > today.year + max_years_ahead:
        raise ValueError(f"{field} is too far in the future")


def escape_like(term: str) -> str:
    """Escape LIKE/ILIKE metacharacters. Use with ``.ilike(pattern, escape='\\\\')``."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
