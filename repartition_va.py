# -*- coding: utf-8 -*-
"""La répartition des VA par model : un salon, une colonne par model.

POURQUOI (propriétaire, 10/11/2026, devant You FR)
    « Je peux avoir un emploi du temps avec les VA par model stp, répartition
    VA, crée le channel et tu drop un [message] qui dépend des rôles sur le
    serveur », puis « fais un salon et y a les différentes [models], genre une
    colonne Amelia, une colonne Emma etc. ». Maquette validée le même jour :
    🗓️・répartition-va dans 📣 ANNONCES ET SUIVI, six colonnes et une case
    « Sans model ».

CE QUE LE SALON MONTRE
    Un seul message du bot, un embed : une colonne par model (champs
    « inline », trois par rangée), dans l'ordre des models du serveur, et
    sous chacune les VA qui portent son rôle, par nom d'utilisateur Discord
    — celui de leur salon perso « <pseudo>-content ». Un VA à deux models est
    dans les deux colonnes. Dessous, « Sans model » : les membres sans aucun
    rôle de model, ni bot ni propriétaire du serveur. Aucun texte d'aide (le
    propriétaire retire toutes les notices), aucun montant.

LES RÔLES : CEUX DU PSEUDO, PAS UNE SECONDE LISTE
    Un membre est sous une model quand pseudo_model dit qu'il en porte le
    rôle (models_du_serveur, models_du_membre). Une seconde reconnaissance
    aurait fini par diverger : un VA « (AMELIA) » dans son pseudo absent de
    la colonne Amelia (CLAUDE.md, « deux mappings valent deux comportements »).

QUAND LE MESSAGE CHANGE
    cogs/pseudomodel appelle planifier() à chaque rôle donné ou retiré, à
    chaque arrivée ou départ, à chaque rôle renommé : quelques secondes plus
    tard (un rôle donné par trois clics fait un seul envoi), le message est
    réécrit s'il a changé. Toutes les trente minutes, et au démarrage, il
    repasse (assurer) : un rôle donné pendant un redémarrage n'arrive jamais
    comme événement. Le message est retrouvé par son id gardé dans
    data/repartition_va.json, sinon dans le salon : jamais un second.

LE SALON
    Retrouvé par son id gardé, sinon par son nom (sans décor ni accent,
    outils_communs._cle) partout sur le serveur : renommé ou déplacé à la
    main, il reste le sien. Absent : créé dans 📣 ANNONCES ET SUIVI, dont il
    prend les droits (tout le monde lit, personne n'écrit) ; sans cette
    catégorie, en lecture seule à son propre compte (outils_communs.droits_outil).
"""
from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import safe_json

ETAT = Path(__file__).resolve().parent / "data" / "repartition_va.json"

CATEGORIE = "📣 ANNONCES ET SUIVI"
NOM = "🗓️・répartition-va"
TITRE = "🗓️ Répartition VA"

#: La couleur du rôle de chaque model sur You FR (celles de Va IG), en cœur :
#: un embed n'a qu'une couleur, ses colonnes aucune.
EMOJIS = {"amelia": "🩷", "emma": "💜", "sarah": "💙",
          "julia": "🩵", "lola": "🧡", "alicia": "💛"}
EMOJI_AUTRE = "▫️"
SANS_MODEL = "⚪ SANS MODEL"
VIDE = "—"

#: Discord : 1024 signes par champ, 6000 par embed. 7 champs × 800 tiennent.
PLAFOND_CHAMP = 800
#: Un rôle donné en trois clics : un seul envoi.
DELAI_SEC = 5.0

_PLANIFIES: Dict[int, "asyncio.Task"] = {}
_ENCORE: set = set()
_VERROUS: Dict[int, asyncio.Lock] = {}
#: gid -> (id du message, empreinte posée) : rien à relire si rien n'a changé.
_POSE: Dict[int, Tuple[int, tuple]] = {}
_DITS: set = set()


def _dire_une_fois(cle: str, texte: str) -> None:
    if cle not in _DITS:
        _DITS.add(cle)
        print(texte, flush=True)


# ─────────────────────────────────────────────────────────── la règle ──

def serveur(guild) -> bool:
    """Ce serveur a-t-il le salon de répartition ? (guild_features.REPARTITION_VA)"""
    try:
        import guild_features as gf
        return bool(gf.repartition_va(guild))
    except Exception:                                        # noqa: BLE001
        return False


def _nom(membre) -> str:
    return str(getattr(membre, "name", "") or "").strip() or str(getattr(membre, "id", "?"))


def repartition(guild) -> Tuple[List[Tuple[str, List[str]]], List[str]]:
    """([(model, [noms des VA])...] dans l'ordre des models, [noms sans model]).

    Les noms sont triés sans tenir compte de la casse. Les bots ne comptent
    pas ; le propriétaire du serveur n'est sous une model que s'il en porte
    le rôle, et jamais dans « Sans model »."""
    import pseudo_model as pm
    models = pm.models_du_serveur(guild)
    colonnes: Dict[str, List[str]] = {m: [] for m in models}
    sans: List[str] = []
    proprio = getattr(guild, "owner_id", None)
    for membre in list(getattr(guild, "members", None) or []):
        if getattr(membre, "bot", False):
            continue
        siennes = pm.models_du_membre(membre, models)
        for m in siennes:
            colonnes[m].append(_nom(membre))
        if not siennes and getattr(membre, "id", None) != proprio:
            sans.append(_nom(membre))
    tri = lambda noms: sorted(noms, key=lambda n: (n.casefold(), n))   # noqa: E731
    return [(m, tri(colonnes[m])) for m in models], tri(sans)


def _valeur(noms: List[str]) -> str:
    """Les noms, un par ligne, échappés (« a_b_c » ne doit pas passer en
    italique), coupés en « … +N » au-delà de PLAFOND_CHAMP."""
    if not noms:
        return VIDE
    import discord
    lignes: List[str] = []
    for i, n in enumerate(noms):
        ligne = discord.utils.escape_markdown(n)
        # 12 signes de côté : la place de « … +N ».
        if len("\n".join(lignes + [ligne])) > PLAFOND_CHAMP - 12:
            lignes.append(f"… +{len(noms) - i}")
            break
        lignes.append(ligne)
    return "\n".join(lignes)


def champs(guild) -> List[Tuple[str, str, bool]]:
    """Les champs de l'embed : (nom, valeur, inline)."""
    colonnes, sans = repartition(guild)
    out = [(f"{EMOJIS.get(m, EMOJI_AUTRE)} {m.upper()} · {len(noms)}", _valeur(noms), True)
           for m, noms in colonnes]
    out.append((f"{SANS_MODEL} · {len(sans)}", _valeur(sans), False))
    return out


def empreinte_champs(titre, liste) -> tuple:
    return (str(titre or ""), tuple((str(n), str(v), bool(i)) for n, v, i in liste))


def empreinte_message(message) -> Optional[tuple]:
    """L'empreinte de l'embed posé, ou None s'il n'en porte pas."""
    embeds = list(getattr(message, "embeds", None) or [])
    if not embeds:
        return None
    e = embeds[0]
    return empreinte_champs(getattr(e, "title", ""),
                            [(f.name, f.value, f.inline) for f in (getattr(e, "fields", None) or [])])


def embed(guild):
    import discord
    e = discord.Embed(title=TITRE)
    for n, v, i in champs(guild):
        e.add_field(name=n, value=v, inline=i)
    return e


# ──────────────────────────────────────────────────────────── l'état ──

def _etat() -> dict:
    d = safe_json.load(ETAT, default={})
    return d if isinstance(d, dict) else {}


def _noter(gid, **valeurs) -> None:
    d = copy.deepcopy(_etat())
    g = d.setdefault(str(gid), {})
    if all(g.get(k) == v for k, v in valeurs.items()):
        return
    g.update(valeurs)
    ETAT.parent.mkdir(parents=True, exist_ok=True)
    if not safe_json.write(ETAT, d, indent=1):
        print("[repartition-va] etat non ecrit : salon et message relus au prochain passage",
              flush=True)


def _note(gid, cle) -> Optional[int]:
    try:
        v = (_etat().get(str(gid)) or {}).get(cle)
        return int(v) if v else None
    except (TypeError, ValueError):
        return None


# ──────────────────────────────────────────────────────── le salon ──

def _cle(nom) -> str:
    import outils_communs as oc
    return oc._cle(nom)


def salon(guild):
    """Le salon de répartition (par son id gardé, sinon par son nom), ou None."""
    import discord
    textes = list(getattr(guild, "text_channels", None) or [])
    sid = _note(guild.id, "salon")
    if sid:
        c = discord.utils.get(textes, id=sid)
        if c is not None:
            return c
    return discord.utils.find(lambda c: _cle(c.name) == _cle(NOM), textes)


async def _creer_salon(guild, bilan):
    cat = next((c for c in (getattr(guild, "categories", None) or [])
                if _cle(c.name) == _cle(CATEGORIE)), None)
    try:
        if cat is not None:
            # Dans la catégorie, sans droits à soi : il prend les siens
            # (tout le monde lit, personne n'écrit, Ryuk écrit).
            c = await guild.create_text_channel(NOM, category=cat,
                                                reason="Répartition des VA par model")
        else:
            import outils_communs as oc
            c = await guild.create_text_channel(
                NOM, overwrites=oc.droits_outil(guild, (getattr(guild, "me", None),)),
                reason="Répartition des VA par model")
            bilan["rates"].append(f"{CATEGORIE} introuvable : salon cree hors categorie")
    except Exception as e:                                   # noqa: BLE001
        bilan["rates"].append(f"{NOM} non cree ({type(e).__name__}: {e})"[:200])
        return None
    bilan["crees"].append(c.name)
    return c


async def _message(canal, bot_id):
    """Le message de répartition du salon (id gardé, sinon relu), doublons
    retirés ; None s'il n'y en a pas. Lève si Discord est injoignable : rien
    n'est alors reposté — un second message vaut moins qu'un passage raté."""
    import discord
    gid = canal.guild.id
    mid = _note(gid, "message")
    if mid:
        try:
            return await canal.fetch_message(mid)
        except discord.NotFound:
            pass
    poses = [m async for m in canal.history(limit=30)
             if getattr(getattr(m, "author", None), "id", None) == bot_id
             and (empreinte_message(m) or ("",))[0] == TITRE]
    if not poses:
        return None
    garde = max(poses, key=lambda m: m.id)
    for m in poses:
        if m is not garde:
            try:
                await m.delete()
            except Exception as e:                           # noqa: BLE001
                print(f"[repartition-va] message en double non retire : {e}", flush=True)
    return garde


def _verrou(gid) -> asyncio.Lock:
    v = _VERROUS.get(gid)
    if v is None:
        v = _VERROUS[gid] = asyncio.Lock()
    return v


async def assurer(guild, forcer: bool = False) -> dict:
    """Le salon et son message, à jour. Idempotent : rien n'est recréé ni
    reposté, le message n'est réécrit que s'il a changé. Sans `forcer`, un
    contenu identique au dernier posé ne relit même pas le message ; le
    passage des trente minutes force, pour revoir un message supprimé à la
    main. Rend le bilan ; chaque échec y est compté et imprimé, aucun n'est tu."""
    bilan = {"crees": [], "pose": False, "maj": False, "rates": []}
    if guild is None or not serveur(guild):
        return bilan
    import pseudo_model as pm
    if not pm.models_du_serveur(guild):
        _dire_une_fois(f"models:{guild.id}", f"[repartition-va] {getattr(guild, 'name', '?')} : "
                       "aucune model pour ce serveur, salon non tenu")
        return bilan
    async with _verrou(guild.id):
        canal = salon(guild)
        if canal is None:
            canal = await _creer_salon(guild, bilan)
        if canal is not None:
            _noter(guild.id, salon=canal.id)
            e = embed(guild)
            voulu = empreinte_champs(e.title, [(f.name, f.value, f.inline) for f in e.fields])
            deja = _POSE.get(guild.id)
            if forcer or not (deja and deja[1] == voulu and deja[0] == _note(guild.id, "message")):
                bot_id = getattr(getattr(guild, "me", None), "id", None)
                try:
                    msg = await _message(canal, bot_id)
                    if msg is None:
                        msg = await canal.send(embed=e)
                        bilan["pose"] = True
                    elif empreinte_message(msg) != voulu:
                        await msg.edit(content=None, embed=e)
                        bilan["maj"] = True
                    _noter(guild.id, message=msg.id)
                    _POSE[guild.id] = (msg.id, voulu)
                except Exception as ex:                      # noqa: BLE001
                    bilan["rates"].append(f"message ({type(ex).__name__}: {ex})"[:200])
    if bilan["crees"] or bilan["pose"] or bilan["maj"] or bilan["rates"]:
        print(f"[repartition-va] {getattr(guild, 'name', '?')} : crees {bilan['crees']}, "
              f"pose {bilan['pose']}, mis a jour {bilan['maj']}, echecs {bilan['rates']}",
              flush=True)
    return bilan


# ──────────────────────────────────────────────────────── l'envoi ──

async def _plus_tard(guild, delai) -> None:
    gid = guild.id
    try:
        while True:
            _ENCORE.discard(gid)
            await asyncio.sleep(delai)
            await assurer(guild)
            if gid not in _ENCORE:
                return
    except Exception as e:                                   # noqa: BLE001
        print(f"[repartition-va] passage rate ({type(e).__name__}: {e})", flush=True)
    finally:
        _PLANIFIES.pop(gid, None)


def planifier(guild, delai: float = DELAI_SEC) -> bool:
    """Demande une mise à jour dans `delai` secondes. Une demande pendant
    l'attente ou l'envoi en vaut une de plus, pas deux. Rend True si une
    attente est (déjà) en cours."""
    if guild is None or not serveur(guild):
        return False
    t = _PLANIFIES.get(guild.id)
    if t is not None and not t.done():
        _ENCORE.add(guild.id)
        return True
    _PLANIFIES[guild.id] = asyncio.get_running_loop().create_task(_plus_tard(guild, delai))
    return True
