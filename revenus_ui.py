"""Presentation of chatter revenue, using the existing data and payment forms.

This module does not write chatter metadata or crypto images. The browser moves
the existing controls into the expandable view, preserving their actions.
"""
import json
from datetime import date
from pathlib import Path
from urllib.parse import quote
from revenus_dates import transaction_hour

_HERE = Path(__file__).resolve().parent
_CSS = (_HERE / 'revenus_ui.css').read_text(encoding='utf-8')
_JS = (_HERE / 'revenus_ui.js').read_text(encoding='utf-8')
_CHART_JS = (_HERE / 'revenus_chart.js').read_text(encoding='utf-8')
# Onglets Managers et Mini-boss : le script ne pose rien tant que la route
# /mypuls/managers.json ne lui a pas repondu (acces complets seulement).
_MGR_CSS = (_HERE / 'revenus_managers.css').read_text(encoding='utf-8')
_MGR_JS = (_HERE / 'revenus_managers.js').read_text(encoding='utf-8')


def render_revenus_ui(creators, segments=None, chatter_names=None):
    # « ?j=<jour> » : l'adresse change chaque jour. La route gardait 24 h dans
    # le navigateur meme une reponse cassee (page de connexion servie comme une
    # image, le 18/11/2026) ; sans ce jeton, les photos des models seraient
    # restees en initiales un jour entier apres le retour du cookie.
    jour = date.today().isoformat()
    avatars = {str(name): '/mypuls/avatar/' + quote(str(cid), safe='') + '?j=' + jour
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
    return ('<style>' + _CSS + _MGR_CSS + '</style>'
            '<script>window.__mpCreatorAvatars=' + payload + ';</script>'
            '<script>window.__mpCreatorSegments=' + segment_payload + ';</script>'
            '<script>window.__mpChatterNames=' + names_payload + ';</script>'
            '<script>' + _JS + '</script>'
            '<script>' + _CHART_JS + '</script>'
            '<script>' + _MGR_JS + '</script>')
