# -*- coding: utf-8 -*-
"""Report de fin de journee, par fiche VA : ou en est son telephone.

Chaque nuit, une fois passe minuit a Paris, ce cog poste dans le salon
configure un message par fiche VA :

    VA NOUM 1X1 · @jessye
    Comptes : 39   dont 5 ajoutes aujourd hui
    Ont publie aujourd hui : 12      Oublies (>48 h) : 3
    Actifs : 24 / 30  (80 %)  -- objectif tenu

Puis il tient a jour UN message epingle, le bilan de la quinzaine : une ligne
par fiche, avec sa pastille. C'est celui-la que tout le monde regarde.

Trois choses valent d'etre dites, parce qu'elles ne se devinent pas :

**Le calcul n'est pas ici.** Il vit dans `jb_objectifs`, et le tableau de bord
appelle la meme fonction. Deux facons de compter « les comptes actifs »
finiraient par se contredire, et ce desaccord ne se remarque que le jour ou
quelqu'un conteste une retenue de paie.

**Un report manque n'est pas une journee ratee.** Le bilan de quinzaine
compte les journees TENUES sur les journees NOTEES : si le bot etait a
l'arret a minuit, la journee n'existe pas, elle ne compte ni en bien ni en
mal. Sans ca, la premiere coupure de service transformait un bon VA en
mauvais.

**Le message epingle est reecrit, jamais reposte.** Un bilan qui s'empile
chaque nuit devient illisible en une semaine, et l'epingle ne designe plus
rien.
"""
import asyncio
import calendar
import datetime
import json
import pathlib
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

import safe_json

_CFG_FILE = pathlib.Path(__file__).resolve().parent.parent / "data" / "report_comptes.json"

#: Longueur maxi d'un message Discord, avec de la marge pour le pied.
_MAX_MSG = 1900


# ==============================================================================
# Heure de Paris — recopiee de clickrecap : meme besoin, meme methode, et le
# projet tourne sans zoneinfo garanti sur toutes les machines.
# ==============================================================================

def _last_sunday(year: int, month: int) -> int:
    return max(d for d in range(25, 32)
               if datetime.date(year, month, d).weekday() == 6)


def _paris_now() -> datetime.datetime:
    """Heure locale de Paris calculee depuis l'UTC (CET=+1, CEST=+2)."""
    u = datetime.datetime.utcnow()
    y = u.year
    debut = datetime.datetime(y, 3, _last_sunday(y, 3), 1)
    fin = datetime.datetime(y, 10, _last_sunday(y, 10), 1)
    return u + datetime.timedelta(hours=2 if (debut <= u < fin) else 1)


# ==============================================================================
# Configuration : quel salon, sur quel serveur
# ==============================================================================

def _cle(guild_id, channel_id) -> str:
    """Un report par SALON, pas un par serveur.

    Meme choix que le report de clics : le proprietaire peut vouloir un salon
    par marche ou par equipe sur un meme serveur.
    """
    return "%s:%s" % (guild_id, channel_id)


def _load_cfg() -> dict:
    d = safe_json.load(_CFG_FILE, default={})
    return d if isinstance(d, dict) else {}


def _save_cfg(d: dict) -> bool:
    try:
        _CFG_FILE.parent.mkdir(parents=True, exist_ok=True)
        return bool(safe_json.write(_CFG_FILE, d))
    except Exception:
        return False


def _reports_configures(cfg: dict) -> list:
    return [(str(k), c) for k, c in (cfg or {}).items()
            if isinstance(c, dict) and c.get("channel_id")]


# ==============================================================================
# Mise en forme
# ==============================================================================

def _barre(actifs: int, objectif: int, largeur: int = 10) -> str:
    """Une barre de progression en carres. Plafonnee a l'objectif : depasser
    n'allonge pas la barre, ca se lit sur le chiffre."""
    if objectif <= 0:
        return ""
    plein = max(0, min(largeur, round(largeur * actifs / objectif)))
    return "▰" * plein + "▱" * (largeur - plein)


def ligne_fiche(e: dict) -> str:
    """Le bloc d'une fiche pour le report du jour."""
    marque = "✅" if e["atteint"] else "🔴"
    pct = int(round(e["pct"]))
    t = [f"**{e['va']}** · `@{e['identite']}`",
         f"Comptes : **{e['total']}**"
         + (f"   ·   dont **{e['ajoutes']}** ajouté(s) aujourd'hui" if e["ajoutes"] else ""),
         f"Ont publié aujourd'hui : **{e['publie']}**"
         f"   ·   Oubliés (>48 h) : **{e['oublies']}**"
         + (f"   ·   Bannis : {e['bannis']}" if e["bannis"] else ""),
         f"{marque} Actifs : **{e['actifs']} / {e['objectif']}** ({pct} %) "
         f"{_barre(e['actifs'], e['objectif'])}"]
    if e["warmup"]:
        t.append(f"_dont {e['warmup']} en warm-up (créé il y a moins de 5 j, "
                 f"compté actif même sans publication)_")
    if not e["atteint"]:
        manque = max(0, e["seuil"] - e["actifs"])
        t.append(f"_Objectif du jour non tenu — il manque {manque} compte(s) "
                 f"actif(s) pour atteindre {e['seuil']} (80 % de {e['objectif']})._")
    return "\n".join(t)


def bloc_quinzaine(lignes: list, debut: str, fin: str) -> str:
    """Le message épinglé : une ligne par fiche, triée du pire au meilleur.

    Du pire au meilleur à dessein : ce message sert à voir qui décroche, pas à
    féliciter. Ce qui compte est en haut, lisible sans dérouler.
    """
    def _d(j):
        try:
            return datetime.date.fromisoformat(j).strftime("%d/%m")
        except Exception:
            return j
    t = [f"📌 **Bilan de la quinzaine — du {_d(debut)} au {_d(fin)}**",
         "_Une journée est tenue quand la fiche atteint 80 % de son objectif. "
         "Les journées sans report ne comptent ni en bien ni en mal._", ""]
    if not lignes:
        t.append("_Aucune fiche suivie pour l'instant._")
        return "\n".join(t)
    ordre = sorted(lignes, key=lambda x: (x["bilan"]["pct"], x["e"]["actifs"]))
    for x in ordre:
        b, e = x["bilan"], x["e"]
        if b["jours_notes"]:
            detail = f"{b['jours_tenus']}/{b['jours_notes']} j tenus"
        else:
            detail = "pas encore de journée notée"
        t.append(f"{b['pastille']} **{e['va']}** `@{e['identite']}` — {detail} "
                 f"· aujourd'hui {e['actifs']}/{e['objectif']}")
    return "\n".join(t)


def _tronquer(txt: str) -> str:
    if len(txt) <= _MAX_MSG:
        return txt
    coupe = txt[:_MAX_MSG].rsplit("\n", 1)[0]
    return coupe + "\n…_(liste tronquée — Discord limite la taille d'un message)_"


# ==============================================================================
# Collecte
# ==============================================================================

def etats_du_jour(jour: str = "") -> list:
    """L'etat de CHAQUE fiche VA aujourd'hui, dans l'ordre identite puis VA.

    Une fiche sans le moindre compte est ecartee : elle n'a rien a dire, et
    poster « 0 / 30 » pour un telephone qui n'existe pas encore ne ferait que
    du bruit.
    """
    import jailbreak as jb
    import jb_objectifs as ob
    try:
        import web_upload as w
        stats = w._load_insta_3_stats_cache() or {}
    except Exception:
        stats = {}
    maintenant = time.time()
    jour = jour or ob.aujourdhui()
    out = []
    for identite, entree in (jb.list_all() or {}).items():
        if not isinstance(entree, dict):
            continue
        comptes = [a for a in (entree.get("accounts") or []) if isinstance(a, dict)]
        # Les fiches DECLAREES, plus celles que seuls leurs comptes designent :
        # une fiche implicite s'affiche sur le dashboard, elle doit compter ici.
        noms, vus = [], set()
        for v in (entree.get("vas") or []):
            nom = (v.get("name") if isinstance(v, dict) else v) or ""
            nom = str(nom).strip()
            if nom and nom.lower() not in vus:
                vus.add(nom.lower())
                noms.append(nom)
        for a in comptes:
            nom = str(a.get("va") or "").strip()
            if nom and nom.lower() not in vus:
                vus.add(nom.lower())
                noms.append(nom)
        for nom in noms:
            siens = [a for a in comptes
                     if str(a.get("va") or "").strip().lower() == nom.lower()]
            if not siens:
                continue
            out.append(ob.etat_fiche(identite, nom, siens, stats, maintenant, jour))
    out.sort(key=lambda e: (e["identite"].lower(), e["va"].lower()))
    return out


# ==============================================================================
# Le cog
# ==============================================================================

class ReportComptes(commands.Cog):
    """Report de minuit par fiche VA + bilan de quinzaine epingle."""

    def __init__(self, bot):
        self.bot = bot
        self._dernier_jour = ""
        self.boucle.start()

    def cog_unload(self):
        self.boucle.cancel()

    # ---- la boucle -------------------------------------------------------
    @tasks.loop(minutes=20)
    async def boucle(self):
        """Poste une fois par jour, apres minuit a Paris.

        On scrute toutes les vingt minutes au lieu de programmer un reveil a
        minuit pile : un redemarrage a 00 h 03 ne doit pas faire sauter la
        journee. Le garde-fou est la date deja traitee, pas l'heure.
        """
        try:
            maintenant = _paris_now()
            jour = maintenant.date().isoformat()
            if maintenant.hour != 0 or self._dernier_jour == jour:
                return
            # La journee qu'on cloture est CELLE QUI VIENT DE FINIR.
            veille = (maintenant.date() - datetime.timedelta(days=1)).isoformat()
            self._dernier_jour = jour
            await self.publier(veille)
        except Exception as e:
            print(f"[report-comptes] boucle : {e}", flush=True)

    @boucle.before_loop
    async def avant(self):
        await self.bot.wait_until_ready()

    # ---- publication -----------------------------------------------------
    async def publier(self, jour: str, salon_force=None) -> dict:
        """Poste le report de `jour` dans tous les salons configures.

        `salon_force` sert au declenchement manuel : on publie la, et nulle
        part ailleurs.
        """
        import jb_objectifs as ob
        etats = await asyncio.to_thread(etats_du_jour, jour)
        # On grave AVANT de poster : si Discord refuse (permission, panne), la
        # journee reste comptee dans le bilan de quinzaine. L'inverse aurait
        # perdu la mesure a cause d'un probleme d'affichage.
        await asyncio.to_thread(ob.enregistrer_jour, etats, jour)

        bilans = []
        for e in etats:
            bilans.append({"e": e, "bilan": await asyncio.to_thread(
                ob.bilan_quinzaine, e["identite"], e["va"], jour)})

        cibles = []
        if salon_force is not None:
            cibles = [(None, salon_force)]
        else:
            for cle, c in _reports_configures(_load_cfg()):
                ch = self.bot.get_channel(int(c.get("channel_id") or 0))
                if ch is not None:
                    cibles.append((cle, ch))

        n_msg = 0
        for cle, ch in cibles:
            try:
                for e in etats:
                    await ch.send(_tronquer(ligne_fiche(e)))
                    n_msg += 1
                    await asyncio.sleep(0.6)     # on ne bouscule pas Discord
                debut, fin = ob.quinzaine(jour)
                await self._poser_epingle(ch, cle, _tronquer(
                    bloc_quinzaine(bilans, debut, fin)))
            except discord.Forbidden:
                print(f"[report-comptes] pas le droit d'écrire dans {ch}", flush=True)
            except Exception as e:
                print(f"[report-comptes] envoi : {e}", flush=True)
        return {"fiches": len(etats), "messages": n_msg, "salons": len(cibles)}

    async def _poser_epingle(self, ch, cle, texte: str):
        """Reecrit le message epingle du bilan, ou le cree la premiere fois."""
        cfg = _load_cfg()
        c = cfg.get(cle) if cle else None
        mid = int((c or {}).get("pin_id") or 0)
        if mid:
            try:
                msg = await ch.fetch_message(mid)
                await msg.edit(content=texte)
                return
            except Exception:
                pass                    # supprime a la main : on en refait un
        try:
            msg = await ch.send(texte)
            try:
                await msg.pin()
            except Exception:
                pass                    # pas le droit d'epingler : tant pis
            if cle and isinstance(c, dict):
                c["pin_id"] = msg.id
                cfg[cle] = c
                _save_cfg(cfg)
        except Exception as e:
            print(f"[report-comptes] épingle : {e}", flush=True)

    # ---- commandes -------------------------------------------------------
    @app_commands.command(
        name="setreportcomptes",
        description="Poser ici le report quotidien des comptes par VA (minuit)")
    async def setreportcomptes(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Réservé aux administrateurs.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        cfg = _load_cfg()
        cle = _cle(interaction.guild_id, interaction.channel_id)
        cfg[cle] = {"guild_id": interaction.guild_id,
                    "channel_id": interaction.channel_id,
                    "pose": int(time.time())}
        _save_cfg(cfg)
        res = await self.publier(_paris_now().date().isoformat(),
                                 salon_force=interaction.channel)
        await interaction.followup.send(
            f"✅ Report des comptes posé ici. {res['fiches']} fiche(s) suivie(s), "
            f"republication chaque nuit après minuit.", ephemeral=True)

    @app_commands.command(
        name="reportcomptesnow",
        description="Publier tout de suite le report des comptes (test)")
    async def reportcomptesnow(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Réservé aux administrateurs.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        res = await self.publier(_paris_now().date().isoformat(),
                                 salon_force=interaction.channel)
        await interaction.followup.send(
            f"✅ {res['messages']} message(s) pour {res['fiches']} fiche(s).",
            ephemeral=True)

    @app_commands.command(
        name="objectifva",
        description="Fixer l'objectif de comptes actifs d'une fiche VA")
    @app_commands.describe(identite="L'identité (ex : jessye)",
                           va="Le nom de la fiche (ex : VA NOUM 1X1)",
                           objectif="Nombre de comptes actifs visés (0 = défaut)")
    async def objectifva(self, interaction: discord.Interaction,
                         identite: str, va: str, objectif: int):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Réservé aux administrateurs.", ephemeral=True)
            return
        import jb_objectifs as ob
        n = await asyncio.to_thread(ob.fixer_objectif, identite, va, objectif)
        await interaction.response.send_message(
            f"✅ Objectif de **{va}** (`@{identite.lower()}`) : **{n}** comptes "
            f"actifs — journée tenue à partir de {ob._seuil(n)}.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(ReportComptes(bot))
