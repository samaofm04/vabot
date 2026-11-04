# -*- coding: utf-8 -*-
"""🔓 VA JAILBREAK de MARCHE FR : le nombre de VA Jailbreak FR, dans le nom
d'un salon vocal, recompté chaque heure.

POURQUOI (propriétaire, 04/11/2026)
    MARCHE FR est le serveur du staff du marché FR (guild 1566803396319649913,
    monté par Meyzah). Pour l'espace VA JAILBREAK : « tu mets juste nombre de
    VA jailbreak », compté sur le rôle « Jailbreak FR » de Youl4b (choisi
    devant « Jailbreak FR (12) » et « FR + US (62) »). Le salon vocal
    « 🔓 VA Jailbreak : 12 » est le compteur ; les deux salons texte de
    l'espace ont été retirés à sa demande.

COMMENT
    Tout en REST, dans un fil (le clic du cog ne bloque rien) :
      - les membres de Youl4b lus par Revel (Wario), présent sur Youl4b, page
        par page (1 000 au plus par page) ;
      - le salon renommé par Meyzah, le seul bot de MARCHE FR — seulement si
        le nombre a changé : Discord ne laisse renommer un salon que deux fois
        par dix minutes.
    Une lecture ratée (Discord, rôle introuvable) ne touche pas au salon : un
    faux « 0 » vaut moins qu'un nombre d'une heure. Un salon supprimé à la
    main n'est jamais refait (dit une fois au journal).

AUCUNE commande slash : le bot principal est à 100 sur 100.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from discord.ext import commands, tasks

log = logging.getLogger("vabot.compteurjailbreak")

MARCHE_FR_ID = "1566803396319649913"
#: Le salon vocal compteur (ex « 🔊 Jailbreak », créé le 04/11/2026).
SALON_ID = "1567527773256552530"
YOUL4B_ID = "1535758943324999711"
ROLE_NOM = "Jailbreak FR"
GABARIT = "🔓 VA Jailbreak : {n}"
APP_REVEL = "1552785601051365516"      # lit Youl4b
APP_MEYZAH = "1552789379574145126"     # écrit sur MARCHE FR
PAGE = 1000
PAGES_MAX = 50

_DITS: set = set()


def _dire_une_fois(cle: str, texte: str) -> None:
    if cle not in _DITS:
        _DITS.add(cle)
        print(f"[compteur-jailbreak] {texte}", flush=True)


def _bot(app_id: str) -> Optional[Dict[str, Any]]:
    import verif_discord as vd
    return next((b for b in vd.bots() if str(b.get("app_id")) == app_id), None)


def _http(bot: Dict[str, Any], methode: str, chemin: str, **kw):
    import verif_discord as vd
    return vd._http(bot, methode, chemin, **kw)


def compter() -> Optional[int]:
    """Les membres de Youl4b qui ont le rôle Jailbreak FR ; None si la lecture
    rate (jamais un zéro inventé)."""
    revel = _bot(APP_REVEL)
    if revel is None:
        _dire_une_fois("revel", "Revel introuvable dans les bots : rien compté")
        return None
    code, roles = _http(revel, "GET", f"/guilds/{YOUL4B_ID}/roles")
    if code != 200 or not isinstance(roles, list):
        print(f"[compteur-jailbreak] rôles de Youl4b illisibles (HTTP {code})", flush=True)
        return None
    rid = next((str(r["id"]) for r in roles
                if isinstance(r, dict) and str(r.get("name") or "").strip() == ROLE_NOM), "")
    if not rid:
        _dire_une_fois("role", f"rôle « {ROLE_NOM} » introuvable sur Youl4b : rien compté")
        return None
    n, apres = 0, "0"
    for _p in range(PAGES_MAX):
        code, ms = _http(revel, "GET", f"/guilds/{YOUL4B_ID}/members?limit={PAGE}&after={apres}")
        if code != 200 or not isinstance(ms, list):
            print(f"[compteur-jailbreak] membres de Youl4b illisibles (HTTP {code})", flush=True)
            return None
        n += sum(1 for m in ms if isinstance(m, dict) and rid in [str(x) for x in m.get("roles") or []])
        if len(ms) < PAGE:
            return n
        apres = str(ms[-1]["user"]["id"])
    print(f"[compteur-jailbreak] plus de {PAGES_MAX * PAGE} membres : rien affiché", flush=True)
    return None


def mettre_a_jour() -> str:
    """Le salon renommé si le nombre a changé. Rend ce qui a été fait
    (« pose », « deja », « rate », « supprime »). Ne lève pas."""
    try:
        n = compter()
        if n is None:
            return "rate"
        meyzah = _bot(APP_MEYZAH)
        if meyzah is None:
            _dire_une_fois("meyzah", "Meyzah introuvable dans les bots : salon non renommé")
            return "rate"
        code, salon = _http(meyzah, "GET", f"/channels/{SALON_ID}")
        if code == 404 or (isinstance(salon, dict) and salon.get("code") == 10003):
            _dire_une_fois("supprime", "salon compteur supprimé à la main : jamais refait")
            return "supprime"
        if code != 200 or not isinstance(salon, dict):
            print(f"[compteur-jailbreak] salon illisible (HTTP {code})", flush=True)
            return "rate"
        nom = GABARIT.format(n=n)
        if salon.get("name") == nom:
            return "deja"
        code, rep = _http(meyzah, "PATCH", f"/channels/{SALON_ID}", json={"name": nom})
        if code != 200:
            print(f"[compteur-jailbreak] renommage refusé (HTTP {code}) {str(rep)[:120]}", flush=True)
            return "rate"
        print(f"[compteur-jailbreak] {salon.get('name')} → {nom}", flush=True)
        return "pose"
    except Exception as e:                                   # noqa: BLE001
        print(f"[compteur-jailbreak] {type(e).__name__}: {e}", flush=True)
        return "rate"


class CompteurJailbreak(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tour.start()

    def cog_unload(self):
        self.tour.cancel()

    @tasks.loop(hours=1)
    async def tour(self):
        await asyncio.to_thread(mettre_a_jour)

    @tour.before_loop
    async def _avant(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(CompteurJailbreak(bot))
