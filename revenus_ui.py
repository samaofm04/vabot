"""Presentation of chatter revenue, using the existing data and payment forms.

This module does not write chatter metadata or crypto images. The browser moves
the existing controls into the expandable view, preserving their actions.
"""
import json
from pathlib import Path
from urllib.parse import quote
from revenus_dates import transaction_hour

_HERE = Path(__file__).resolve().parent
_CSS = (_HERE / 'revenus_ui.css').read_text(encoding='utf-8')
_JS = (_HERE / 'revenus_ui.js').read_text(encoding='utf-8')
_CHART_JS = (_HERE / 'revenus_chart.js').read_text(encoding='utf-8')


def render_revenus_ui(creators, segments=None, chatter_names=None):
    avatars = {str(name): '/mypuls/avatar/' + quote(str(cid), safe='')
               for name, cid in (creators or {}).items() if cid is not None}
    payload = (json.dumps(avatars, ensure_ascii=False)
               .replace('&', '\\u0026').replace('<', '\\u003c')
               .replace('>', '\\u003e').replace('\u2028', '\\u2028')
               .replace('\u2029', '\\u2029'))
    segment_payload = (json.dumps(segments or {}, ensure_ascii=False)
                       .replace('&', '\\u0026').replace('<', '\\u003c')
                       .replace('>', '\\u003e').replace('\u2028', '\\u2028')
                       .replace('\u2029', '\\u2029'))
    names_payload = (json.dumps(chatter_names or {}, ensure_ascii=False)
                     .replace('&', '\\u0026').replace('<', '\\u003c')
                     .replace('>', '\\u003e').replace('\u2028', '\\u2028')
                     .replace('\u2029', '\\u2029'))
    return ('<style>' + _CSS + '</style>'
            '<script>window.__mpCreatorAvatars=' + payload + ';</script>'
            '<script>window.__mpCreatorSegments=' + segment_payload + ';</script>'
            '<script>window.__mpChatterNames=' + names_payload + ';</script>'
            '<script>' + _JS + '</script>'
            '<script>' + _CHART_JS + '</script>')
