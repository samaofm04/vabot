# -*- coding: utf-8 -*-
"""Le salon 🔗・liens de You FR : par model, chaque VA en @, puis son lien.

POURQUOI (propriétaire, 10/11/2026)
    « Prépare-moi un message à envoyer à tout le monde avec les liens, ou un
    endroit avec écrit liens, et ça range par catégorie, et ça @ la personne
    et [le] lien après. » Maquette validée : un salon 🔗・liens dans 📣 ANNONCES
    ET SUIVI, un message par model, et les @ NOTIFIENT.

CE QUE PORTE LE SALON
    Un message par model des liens JB (guild_features.LIENS_JB : Amelia,
    Emma, Lola, Alicia), en texte simple — un @ ne notifie que dans le texte
    d'un message, jamais dans un embed :

        ### 🩷 AMELIA
        @dioplucky https://getmysocial.com/ameliabunny
        @eniassy_83352 https://getmysocial.com/ameliakitty

    Les VA sont ceux de liens_jb_fr.vas_du_serveur (un rôle de model au
    moins), leurs liens ceux de l'équipe VA JB FR (liens_jb_fr.lien_public).
    Aperçus de liens retirés : quarante cartes GetMySocial noieraient la liste.

LA NOTIFICATION, UNE FOIS
    Discord ne notifie qu'à l'ENVOI d'un message, jamais quand on le modifie.
    Les messages ne partent donc qu'une fois TOUS les liens créés
    (liens_jb_fr.manquants vide) : envoyés plus tôt, les VA ajoutés ensuite
    n'auraient jamais été notifiés. Après, le bot les tient à jour en les
    modifiant (nouveau VA, nouveau lien, départ), sans renotifier personne.

LE SALON ET LES MESSAGES
    Retrouvés par leur id (data/salon_liens.json), sinon par le nom du salon
    et l'en-tête de chaque message (« ### 🩷 AMELIA ») : jamais un second.
"""
from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from typing import Dict

import safe_json

ETAT = Path(__file__).resolve().parent / "data" / "salon_liens.json"
NOM = "🔗・liens"
#: Un message Discord : 2000 signes. La marge sert à « … +N ».
PLAFOND = 1900

_VERROUS: Dict[int, asyncio.Lock] = {}
_DITS: set = set()


def _dire_une_fois(cle: str, texte: str) -> None:
    if cle not in _DITS:
        _DITS.add(cle)
        print(texte, flush=True)


def models(guild) -> tuple:
    import liens_jb_fr as lj
    return tuple(lj.models_du_serveur(guild))


def en_tete(model: str) -> str:
    import repartition_va as rv
    return f"### {rv.EMOJIS.get(model, rv.EMOJI_AUTRE)} {model.upper()}"


def texte_model(guild, model: str) -> str:
    """Le message d'une model : son en-tête, puis « <@VA> lien » par VA qui
    en a un, triés par nom. Coupé en « … +N » avant 2000 signes."""
    import liens_jb_fr as lj
    lignes = [en_tete(model)]
    vas = [(uid, lj.lien_public(uid, model)) for uid, _nom in lj.vas_du_serveur(guild)]
    vas = [(uid, url) for uid, url in vas if url]
    for i, (uid, url) in enumerate(vas):
        ligne = f"<@{uid}> {url}"
        if len("\n".join(lignes + [ligne])) > PLAFOND:
            lignes.append(f"… +{len(vas) - i}")
            break
        lignes.append(ligne)
    if len(lignes) == 1:
        lignes.append("—")
    return "\n".join(lignes)


# ──────────────────────────────────────────────────────────────── l'état ──

def _etat() -> dict:
    d = safe_json.load(ETAT, default={})
    return d if isinstance(d, dict) else {}


def _noter(gid, valeurs: dict) -> None:
    d = copy.deepcopy(_etat())
    g = d.setdefault(str(gid), {})
    if all(g.get(k) == v for k, v in valeurs.items()):
        return
    g.update(valeurs)
    ETAT.parent.mkdir(parents=True, exist_ok=True)
    if not safe_json.write(ETAT, d, indent=1):
        print("[salon-liens] etat non ecrit : salon et messages relus au prochain passage",
              flush=True)


def _verrou(gid) -> asyncio.Lock:
    v = _VERROUS.get(gid)
    if v is None:
        v = _VERROUS[gid] = asyncio.Lock()
    return v


# ────────────────────────────────────────────────────────────── passage ──

async def assurer(guild) -> dict:
    """Le salon et ses messages. Rien avant que tous les liens existent ;
    ensuite, chaque message est réécrit s'il a changé. Rend le bilan."""
    import discord
    import liens_jb_fr as lj
    import repartition_va as rv
    bilan = {"attente": 0, "crees": [], "envoyes": [], "maj": [], "rates": []}
    ms = models(guild)
    if guild is None or not ms:
        return bilan
    async with _verrou(guild.id):
        g = _etat().get(str(guild.id)) or {}
        notes = dict(g.get("messages") or {})
        if not notes:
            # Le premier envoi notifie : il attend que tous aient leurs liens.
            reste = len(lj.manquants(guild))
            if reste:
                bilan["attente"] = reste
                _dire_une_fois(f"attente:{guild.id}:{reste}",
                               f"[salon-liens] {getattr(guild, 'name', '?')} : {reste} lien(s) JB "
                               "à créer avant le premier envoi (il notifie)")
                return bilan
        canal = rv.salon_nomme(guild, NOM, int(g.get("salon") or 0) or None)
        if canal is None:
            canal = await rv.creer_salon_annonces(guild, NOM, "Liens GetMySocial des VA par model",
                                                  bilan)
            if canal is None:
                return bilan
        _noter(guild.id, {"salon": canal.id})
        moi = getattr(getattr(guild, "me", None), "id", None)
        historique = None
        for model in ms:
            texte = texte_model(guild, model)
            try:
                msg = None
                mid = int(notes.get(model) or 0)
                if mid:
                    try:
                        msg = await canal.fetch_message(mid)
                    except discord.NotFound:
                        msg = None
                if msg is None:
                    if historique is None:
                        historique = [m async for m in canal.history(limit=50)
                                      if getattr(getattr(m, "author", None), "id", None) == moi]
                    poses = [m for m in historique
                             if str(getattr(m, "content", "") or "").split("\n", 1)[0] == en_tete(model)]
                    if poses:
                        msg = max(poses, key=lambda m: m.id)
                        for m in poses:
                            if m is not msg:
                                try:
                                    await m.delete()
                                except Exception as e:       # noqa: BLE001
                                    print(f"[salon-liens] {model} en double non retire : {e}", flush=True)
                if msg is None:
                    msg = await canal.send(
                        texte, suppress_embeds=True,
                        allowed_mentions=discord.AllowedMentions(users=True, roles=False,
                                                                 everyone=False))
                    bilan["envoyes"].append(model)
                    await asyncio.sleep(1.0)
                elif str(getattr(msg, "content", "") or "") != texte:
                    await msg.edit(content=texte, suppress=True)
                    bilan["maj"].append(model)
                notes[model] = msg.id
            except Exception as e:                           # noqa: BLE001
                bilan["rates"].append(f"{model} ({type(e).__name__}: {e})"[:200])
        _noter(guild.id, {"messages": notes})
    if bilan["crees"] or bilan["envoyes"] or bilan["maj"] or bilan["rates"]:
        print(f"[salon-liens] {getattr(guild, 'name', '?')} : salon cree {bilan['crees']}, envoyes "
              f"{bilan['envoyes']}, reecrits {bilan['maj']}, echecs {bilan['rates']}", flush=True)
    return bilan
