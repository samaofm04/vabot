# -*- coding: utf-8 -*-
"""Le nom d'un ticket VA : « 🟢🔗⚙️-12-va-pseudo ».

Trois cogs le renomment : vaactivity (le rond d'activite), user (le 🔗 du
lien), clickrecap (le ⚙️ du lien a 0 clic). Chacun le reconstruisait en
entier -- un numero ajoute par l'un aurait ete efface par les deux autres
(serveur FR, 03/10/2026 : « le numero du VA a cote, synchro avec son lien »).
Ils passent tous par ici : chacun change SA marque et garde le reste.
"""
from __future__ import annotations

import re

_NUMERO = re.compile(r"(?:^|[^0-9a-z])(\d+)-va-[a-z0-9_.]+$")


def numero(nom) -> str:
    """« 🟢-12-va-bob » -> « 12 » ; "" sans numero."""
    m = _NUMERO.search(str(nom or "").lower())
    return m.group(1) if m else ""


def nom_ticket(rond: str, lien: str, gear: str, num, handle: str) -> str:
    """Le nom complet. Sans marque devant, pas de tiret de tete : Discord
    l'enleve, et la comparaison avec le nom en place bouclerait."""
    deco = f"{rond or ''}{lien or ''}{gear or ''}"
    milieu = f"{num}-" if num else ""
    return f"{deco}-{milieu}va-{handle}" if deco else f"{milieu}va-{handle}"
