from decimal import Decimal, InvalidOperation


def currency(value) -> str:
    """Format a number as USD with thousands separators."""
    if value is None:
        return "$0.00"
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        amount = Decimal("0")
    return f"${amount:,.2f}"


def compact_date(value) -> str:
    """Format a date as abbreviated month and non-padded day."""
    if not value:
        return ""
    return f"{value.strftime('%b')} {value.day}"


def short_date(value) -> str:
    """Format a date as abbreviated month, non-padded day, and year."""
    if not value:
        return ""
    return f"{compact_date(value)}, {value.year}"


def long_date(value) -> str:
    """Format a date as full month, non-padded day, and year."""
    if not value:
        return ""
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def file_size(value) -> str:
    """Format a byte count as KB or MB."""
    try:
        size = int(value or 0)
    except (TypeError, ValueError):
        size = 0
    kb = size / 1024
    if kb < 1024:
        return f"{kb:.0f} KB"
    return f"{kb / 1024:.1f} MB"
