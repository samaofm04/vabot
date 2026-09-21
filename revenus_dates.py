"""Transaction dates shared by revenue charts and shift filters (Paris time)."""
from datetime import datetime
from zoneinfo import ZoneInfo


def transaction_datetime(value):
    value = str(value or '').strip()
    try:
        if 'T' in value or (len(value) > 10 and value[4] == '-'):
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return dt.astimezone(ZoneInfo('Europe/Paris')) if dt.tzinfo else dt
        for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M'):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                pass
    except (ValueError, TypeError):
        pass
    return None


def transaction_day(value):
    dt = transaction_datetime(value)
    return dt.date().isoformat() if dt else ''


def transaction_hour(value):
    dt = transaction_datetime(value)
    return dt.hour if dt else -1
