"""Calendar shortcuts scoped to Chatter earnings (Paris calendar days)."""
from datetime import date, timedelta
from html import escape
from urllib.parse import urlencode

ALL_HISTORY_START = '1970-01-01'


def period_ranges(today):
    month = today.replace(day=1)
    previous_end = month - timedelta(days=1)
    return [
        ('today', "Aujourd’hui", today.isoformat(), today.isoformat()),
        ('yesterday', 'Hier', (today-timedelta(days=1)).isoformat(), (today-timedelta(days=1)).isoformat()),
        ('7d', '7 j', (today-timedelta(days=6)).isoformat(), today.isoformat()),
        ('30d', '30 j', (today-timedelta(days=29)).isoformat(), today.isoformat()),
        ('month', 'Mois', month.isoformat(), today.isoformat()),
        ('previous_month', 'M-1', previous_end.replace(day=1).isoformat(), previous_end.isoformat()),
        ('year', 'Année', today.replace(month=1, day=1).isoformat(), today.isoformat()),
        ('all', 'Tout', ALL_HISTORY_START, today.isoformat()),
    ]


def render_period_presets(today, start, end, selected=''):
    ranges = period_ranges(today)
    matches = [key for key, _, first, last in ranges if (first, last) == (start, end)]
    active = selected if selected in matches else (matches[0] if matches else '')
    items = []
    for key, label, first, last in ranges:
        params = urlencode(dict(tab='revenus', mp_start=first, mp_end=last, mp_period=key))
        current = ' aria-current="date"' if key == active else ''
        divider = ' mp-period-divider' if key in ('7d', 'month', 'year') else ''
        items.append(
            f'<a class="mypuls-period-btn mp-period-preset{divider}" '
            f'href="?{escape(params, quote=True)}" data-period="{key}"{current} '
            f'onclick="mpShowPeriodLoader()">{escape(label)}</a>'
        )
    return '<nav class="mp-revenue-period-presets" aria-label="Période des revenus">' + ''.join(items) + '</nav>'
