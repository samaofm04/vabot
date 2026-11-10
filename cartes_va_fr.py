# -*- coding: utf-8 -*-
"""Les liens d'un VA de You FR, model par model : une carte dans son -content.

POURQUOI (propriétaire, 10/11/2026)
    « Tu peux leur donner leurs liens GMS pour leurs models et le lien pour
    qu'ils ajoutent des comptes pour leurs models », maquette validée le même
    jour : une carte par model, son lien GMS, un bouton 📷 Ajouter mes
    comptes. Pour les VA qui n'ont pas encore de lien : « donne-moi déjà les
    trucs et on fixe » — leur carte part avec le seul bouton, et le lien s'y
    ajoute de lui-même le jour où il existe.

CE QUE PORTE UNE CARTE
    - le cœur et le nom de la model (repartition_va.EMOJIS), le liseré à la
      couleur de son rôle ;
    - 🔗 le lien GetMySocial du VA pour cette model : celui du registre des
      liens FR (liens_fr.lien_de, data/liens_va_fr.json), et seulement s'il
      est en service chez GetMySocial (liste de l'équipe, gardée 10 min) — un
      lien coupé ne part pas, la carte attend sans lui ;
    - 📷 Ajouter mes comptes : au clic, en éphémère, le lien de SA page de
      comptes (comptes_tickets.page_du_va, le portail /mes-comptes de TRUST
      INSTAGRAM). Les comptes arrivent sur la page Virtual Assistants, sous la
      model, dans sa fiche : celle qui porte déjà son pseudo Discord, sinon
      une neuve à son nom. La page n'est préparée qu'au clic : aucune fiche
      n'est créée pour un VA qui ne s'en sert pas — le propriétaire ajoute
      les VA à la main.

LES RÔLES : CEUX DU PSEUDO
    Une carte par model dont le VA porte le rôle, d'après
    pseudo_model.models_du_membre : la même reconnaissance que le pseudo
    « (AMELIA) » et que la répartition. Rôle retiré : sa carte est retirée.

QUAND
    cogs/pseudomodel demande un passage quelques secondes après chaque rôle
    donné ou retiré, et repasse toutes les trente minutes. Chaque carte est
    posée une fois (id gardé dans data/cartes_va_fr.json), réécrite si son
    lien change, retirée avec le rôle. Un VA sans -content est compté et dit,
    jamais sauté en silence.
"""
from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import discord

import safe_json

ETAT = Path(__file__).resolve().parent / "data" / "cartes_va_fr.json"

#: custom_id du bouton : « cvf:<model>:<id du VA> ». Le VA est dans le
#: bouton : un manager qui clique dans son salon ouvre la page de CE VA.
PREFIXE = "cvf"
MOTIF = rf"{PREFIXE}:(?P<model>[a-z0-9_-]+):(?P<uid>\d+)"

LIBELLE = "Ajouter mes comptes"
TEXTE_PAS_A_TOI = "❌ Ce bouton est celui de <@{uid}>."
TEXTE_PANNE = "❌ Ta page n'a pas pu être préparée. Réessaie dans un instant."
DELAI_SEC = 5.0

_PLANIFIES: Dict[int, "asyncio.Task"] = {}
_ENCORE: set = set()
_VERROUS: Dict[int, asyncio.Lock] = {}
_DITS: set = set()


def _dire_une_fois(cle: str, texte: str) -> None:
    if cle not in _DITS:
        _DITS.add(cle)
        print(texte, flush=True)


def serveur(guild) -> bool:
    """Ce serveur donne-t-il leurs cartes aux VA ? (guild_features.CARTES_VA)"""
    try:
        import guild_features as gf
        return bool(gf.cartes_va(guild))
    except Exception:                                        # noqa: BLE001
        return False


# ──────────────────────────────────────────────────────── le lien GMS ──

def _statuts_gms() -> Dict[str, bool]:
    """{id de lien: en service ?} d'après la liste de l'équipe (gardée 10 min
    par liens_fr). Illisible : {} — on ne sait pas, le lien reste montré."""
    try:
        import liens_fr
        out = {}
        for l in liens_fr._liens_equipe(force=False) or []:
            lid = str(l.get("id") or "")
            actif = liens_fr._actif_gms(l)
            if lid and actif is not None:
                out[lid] = actif
        return out
    except Exception as e:                                   # noqa: BLE001
        _dire_une_fois(f"gms:{type(e).__name__}", f"[cartes-va-fr] liste GetMySocial illisible "
                       f"({type(e).__name__}: {e}) : liens montrés sans vérifier")
        return {}


def lien_gms(uid, model: str, statuts: Optional[Dict[str, bool]] = None) -> str:
    """Le lien GetMySocial du VA pour cette model, ou "" (aucun, ou coupé)."""
    try:
        import liens_fr
        e = liens_fr.lien_de(uid, model) or {}
    except Exception as ex:                                  # noqa: BLE001
        _dire_une_fois(f"registre:{type(ex).__name__}", f"[cartes-va-fr] registre des liens "
                       f"illisible ({type(ex).__name__}: {ex})")
        return ""
    url = str(e.get("public_url") or "").strip()
    if not url:
        return ""
    lid = str(e.get("link_id") or "")
    if statuts is not None and statuts.get(lid) is False:
        _dire_une_fois(f"coupe:{uid}:{model}:{lid}", f"[cartes-va-fr] {e.get('display_name') or lid} "
                       "est coupé chez GetMySocial : pas montré sur la carte")
        return ""
    return url


# ──────────────────────────────────────────────────────────── la carte ──

def couleur_du_role(guild, model: str) -> Optional[int]:
    import pseudo_model as pm
    for r in list(getattr(guild, "roles", None) or []):
        if pm.cle(getattr(r, "name", "")) == model:
            v = getattr(getattr(r, "colour", None), "value", None)
            return int(v) if v else None
    return None


def titre(model: str) -> str:
    import repartition_va as rv
    return f"### {rv.EMOJIS.get(model, rv.EMOJI_AUTRE)} {model.upper()}"


class BoutonComptes(discord.ui.DynamicItem[discord.ui.Button], template=MOTIF):
    """📷 Ajouter mes comptes. Persistant (DynamicItem, enregistré par
    cogs/pseudomodel) : il répond après un redémarrage, la model et le VA
    arrivent avec le clic."""

    def __init__(self, model: str, uid: int):
        self.model, self.uid = str(model), int(uid)
        super().__init__(discord.ui.Button(
            label=LIBELLE, emoji="📷", style=discord.ButtonStyle.secondary,
            custom_id=f"{PREFIXE}:{self.model}:{self.uid}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["model"], int(match["uid"]))

    async def callback(self, interaction: discord.Interaction):
        await repondre_clic(interaction, self.model, self.uid)


def vue(model: str, uid: int, url_gms: str, couleur: Optional[int]):
    """La carte : titre, lien GMS s'il y en a un, bouton 📷."""
    enfants = [discord.ui.TextDisplay(titre(model))]
    if url_gms:
        enfants.append(discord.ui.TextDisplay(f"🔗 {url_gms}"))
    enfants.append(discord.ui.ActionRow(BoutonComptes(model, uid)))
    v = discord.ui.LayoutView(timeout=None)
    v.add_item(discord.ui.Container(*enfants, accent_colour=couleur))
    return v


def signature(model: str, url_gms: str, couleur: Optional[int]) -> str:
    """Ce qui, s'il change, fait réécrire la carte."""
    return f"{model}|{url_gms}|{couleur or 0}"


# ─────────────────────────────────────────────────────────────── le clic ──

def _peut_ouvrir_pour(membre, uid: int) -> bool:
    """Le VA lui-même, ou quelqu'un qui gère le serveur (son salon est privé :
    seul le staff y voit la carte)."""
    if getattr(membre, "id", None) == uid:
        return True
    p = getattr(membre, "guild_permissions", None)
    return bool(p and (p.administrator or p.manage_guild or p.manage_channels))


async def repondre_clic(interaction: discord.Interaction, model: str, uid: int):
    membre, guild = interaction.user, interaction.guild
    if guild is None or not _peut_ouvrir_pour(membre, uid):
        await interaction.response.send_message(TEXTE_PAS_A_TOI.format(uid=uid), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    va = guild.get_member(uid)
    nom_actuel = str(getattr(va, "name", "") or "")
    try:
        import comptes_tickets as ct
        url, nom, refus = await asyncio.to_thread(ct.page_du_va, str(guild.id), str(uid),
                                                  nom_actuel, model)
    except Exception as e:                                   # noqa: BLE001
        print(f"[cartes-va-fr] page de {uid}/{model} : {type(e).__name__}: {e}", flush=True)
        url, nom, refus = "", "", TEXTE_PANNE
    if refus or not url:
        await interaction.followup.send(refus or TEXTE_PANNE, ephemeral=True)
        return
    a_lui = getattr(membre, "id", None) == uid
    texte = (f"📷 **Mes comptes · {model.capitalize()}**" if a_lui
             else f"📷 **Comptes de @{nom} · {model.capitalize()}**")
    bouton = discord.ui.View()
    bouton.add_item(discord.ui.Button(label="Ouvrir ma page" if a_lui else "Ouvrir sa page",
                                      url=url))
    await interaction.followup.send(texte, view=bouton, ephemeral=True)


# ──────────────────────────────────────────────────────────────── l'état ──

def _etat() -> dict:
    d = safe_json.load(ETAT, default={})
    return d if isinstance(d, dict) else {}


def _ecrire(d: dict) -> bool:
    ETAT.parent.mkdir(parents=True, exist_ok=True)
    if not safe_json.write(ETAT, d, indent=1):
        print("[cartes-va-fr] etat non ecrit : les cartes seront relues au prochain passage",
              flush=True)
        return False
    return True


# ─────────────────────────────────────────────────────────────── le passage ──

def voulues(guild) -> Dict[int, List[str]]:
    """{id du VA: [ses models, dans l'ordre]} : les membres (ni bots) qui
    portent au moins un rôle de model."""
    import pseudo_model as pm
    models = pm.models_du_serveur(guild)
    out = {}
    for m in list(getattr(guild, "members", None) or []):
        if getattr(m, "bot", False):
            continue
        siennes = pm.models_du_membre(m, models)
        if siennes:
            out[int(m.id)] = siennes
    return out


def _verrou(gid) -> asyncio.Lock:
    v = _VERROUS.get(gid)
    if v is None:
        v = _VERROUS[gid] = asyncio.Lock()
    return v


async def _supprimer(guild, entree) -> bool:
    """Retire une carte posée. Rend True si elle n'est plus là."""
    canal = guild.get_channel(int(entree.get("salon") or 0)) if entree.get("salon") else None
    if canal is None:
        return True
    try:
        msg = await canal.fetch_message(int(entree.get("mid") or 0))
        await msg.delete()
    except discord.NotFound:
        pass
    return True


async def assurer(guild) -> dict:
    """Pose, réécrit ou retire les cartes du serveur. Rend le bilan ; chaque
    échec et chaque VA sans salon y sont comptés et imprimés."""
    bilan = {"posees": 0, "maj": 0, "retirees": 0, "sans_salon": [], "rates": []}
    if guild is None or not serveur(guild):
        return bilan
    import outils_communs as oc
    gid = str(guild.id)
    async with _verrou(guild.id):
        voulu = voulues(guild)
        statuts = await asyncio.to_thread(_statuts_gms) if voulu else {}
        d = copy.deepcopy(_etat())
        g = d.setdefault(gid, {})
        change = False
        # 1) Les cartes dont le rôle est parti (ou le VA avec lui).
        for uid_s in list(g):
            gardes = set(voulu.get(int(uid_s), []))
            for model in list(g[uid_s]):
                if model in gardes:
                    continue
                try:
                    await _supprimer(guild, g[uid_s][model])
                    del g[uid_s][model]
                    bilan["retirees"] += 1
                    change = True
                except Exception as e:                       # noqa: BLE001
                    bilan["rates"].append(f"retrait {uid_s}/{model} ({type(e).__name__}: {e})"[:200])
            if not g[uid_s]:
                del g[uid_s]
                change = True
        # 2) Les cartes voulues : posées, ou réécrites si elles ont changé.
        for uid, models in voulu.items():
            membre = guild.get_member(uid)
            salon = oc.content_de(guild, membre)
            if salon is None:
                bilan["sans_salon"].append(str(getattr(membre, "name", uid)))
                continue
            a_lui = g.setdefault(str(uid), {})
            for model in models:
                url = await asyncio.to_thread(lien_gms, uid, model, statuts)
                couleur = couleur_du_role(guild, model)
                sig = signature(model, url, couleur)
                deja = a_lui.get(model) or {}
                try:
                    msg = None
                    if deja.get("mid") and int(deja.get("salon") or 0) == salon.id:
                        try:
                            msg = await salon.fetch_message(int(deja["mid"]))
                        except discord.NotFound:
                            msg = None
                    elif deja.get("mid"):
                        # Le VA a changé de salon : l'ancienne carte part.
                        await _supprimer(guild, deja)
                    if msg is None:
                        msg = await salon.send(view=vue(model, uid, url, couleur))
                        bilan["posees"] += 1
                    elif deja.get("sig") != sig:
                        await msg.edit(view=vue(model, uid, url, couleur))
                        bilan["maj"] += 1
                    else:
                        continue
                    a_lui[model] = {"mid": msg.id, "salon": salon.id, "sig": sig}
                    change = True
                    await asyncio.sleep(0.5)                 # on ménage l'API
                except Exception as e:                       # noqa: BLE001
                    bilan["rates"].append(f"{uid}/{model} ({type(e).__name__}: {e})"[:200])
            if not a_lui:
                g.pop(str(uid), None)
        if change:
            _ecrire(d)
    if bilan["sans_salon"]:
        _dire_une_fois(f"sans:{gid}:{','.join(sorted(bilan['sans_salon']))}",
                       f"[cartes-va-fr] {getattr(guild, 'name', '?')} : sans salon -content, pas de "
                       f"carte pour {', '.join(sorted(bilan['sans_salon']))}")
    if bilan["posees"] or bilan["maj"] or bilan["retirees"] or bilan["rates"]:
        print(f"[cartes-va-fr] {getattr(guild, 'name', '?')} : posees {bilan['posees']}, "
              f"reecrites {bilan['maj']}, retirees {bilan['retirees']}, echecs {bilan['rates']}",
              flush=True)
    return bilan


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
        print(f"[cartes-va-fr] passage rate ({type(e).__name__}: {e})", flush=True)
    finally:
        _PLANIFIES.pop(gid, None)


def planifier(guild, delai: float = DELAI_SEC) -> bool:
    """Un passage dans `delai` secondes ; une demande pendant l'attente ou le
    passage en vaut une de plus, pas deux."""
    if guild is None or not serveur(guild):
        return False
    t = _PLANIFIES.get(guild.id)
    if t is not None and not t.done():
        _ENCORE.add(guild.id)
        return True
    _PLANIFIES[guild.id] = asyncio.get_running_loop().create_task(_plus_tard(guild, delai))
    return True
