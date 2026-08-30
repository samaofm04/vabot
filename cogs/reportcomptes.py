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

**Aucune commande slash, et c'est contraint.** Discord plafonne une
APPLICATION a 100 commandes globales, et ce bot y est deja : quatre cogs
(vaactivity, vasort, tgrouter, numeros) ne se chargent plus depuis un
moment, en silence, pour cette raison — leurs commandes n'existent plus sur
Discord. En ajouter trois faisait echouer celui-ci exactement pareil.

Le report n'en a pas besoin : il tourne seul apres minuit. Le salon se
trouve par CONVENTION DE NOM — tout salon dont le nom commence par
« report-compte ». On cree le salon, il est servi. Le declenchement manuel
vit sur le tableau de bord, bouton « Report des comptes ».

Trois autres choses valent d'etre dites, parce qu'elles ne se devinent pas :

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
         f"{marque} Comptes qui tournent : **{e['actifs']} / {e['objectif']}** ({pct} %) "
         f"{_barre(e['actifs'], e['objectif'])}"]
    if e["warmup"]:
        t.append(f"_dont {e['warmup']} en warm-up (créé il y a peu, compté "
                 f"même sans publication)_")
    if not e["atteint"]:
        manque = max(0, e["seuil"] - e["actifs"])
        t.append(f"_Objectif du jour non tenu — il manque {manque} compte(s) "
                 f"qui tourne(nt) pour atteindre {e['seuil']} (80 % de {e['objectif']})._")
    return "\n".join(t)


def bloc_quinzaine(lignes: list, debut: str, fin: str, identite: str = "") -> str:
    """Le message épinglé : une ligne par fiche, triée du pire au meilleur.

    Du pire au meilleur à dessein : ce message sert à voir qui décroche, pas à
    féliciter. Ce qui compte est en haut, lisible sans dérouler.
    """
    def _d(j):
        try:
            return datetime.date.fromisoformat(j).strftime("%d/%m")
        except Exception:
            return j
    portee = f" · `@{identite}`" if identite else ""
    t = [f"📌 **Bilan de la quinzaine — du {_d(debut)} au {_d(fin)}**{portee}",
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

def identite_du_salon(nom: str, identites) -> str:
    """L'identite que ce salon suit, d'apres son NOM. '' = toutes.

    « report-compte » suit tout le monde ; « report-compte-jessye » ne suit
    que jessye. Le nom porte deja la convention qui designe ces salons, il
    peut aussi en porter la portee : on lit le salon et on sait ce qu'il
    contient, sans aller chercher un reglage ailleurs.

    Un suffixe qui ne correspond a AUCUNE identite connue est traite comme une
    simple etiquette (« report-comptes-equipe-1 ») et ne filtre rien. Le
    contraire serait pire : un salon nomme un peu de travers deviendrait vide
    sans que personne comprenne pourquoi.
    """
    n = str(nom or "").lower().replace("_", "-").strip()
    for prefixe in ("report-comptes-", "report-compte-"):
        if n.startswith(prefixe):
            suffixe = n[len(prefixe):].strip("-")
            for ident in (identites or []):
                if str(ident).lower() == suffixe:
                    return str(ident).lower()
            return ""
    return ""


def etats_du_jour(jour: str = "", identite_voulue: str = "") -> list:
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
    voulue = str(identite_voulue or "").strip().lower()
    for identite, entree in (jb.list_all() or {}).items():
        if not isinstance(entree, dict):
            continue
        if voulue and str(identite).lower() != voulue:
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

            # PREMIER PASSAGE. Un salon « report-compte » qui vient d'etre cree
            # n'a aucune raison d'attendre minuit pour montrer quelque chose :
            # on l'a cree justement pour voir. Un salon est « neuf » tant qu'il
            # n'a pas de message epingle enregistre — donc une seule fois.
            cfg = _load_cfg()
            neufs = [(cle, ch) for cle, ch in self.salons_report()
                     if not (cfg.get(cle) or {}).get("pin_id")]
            if neufs:
                noms = ", ".join(str(getattr(c, "name", "?")) for _k, c in neufs)
                print(f"[report-comptes] premier passage : {noms}", flush=True)
                await self.publier(jour, cibles=neufs)

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
    async def publier(self, jour: str, salon_force=None, cibles=None) -> dict:
        """Poste le report de `jour` dans tous les salons configures.

        `salon_force` sert au declenchement manuel : on publie la, et nulle
        part ailleurs.
        """
        import jb_objectifs as ob
        if cibles is None:
            if salon_force is not None:
                cibles = [(_cle(getattr(salon_force.guild, "id", 0), salon_force.id),
                           salon_force)]
            else:
                cibles = self.salons_report()

        # La MESURE est faite une fois, sur tout le monde, et elle est gravee
        # une fois. Elle ne depend pas de qui la regarde : un salon qui ne
        # suit que jessye ne doit pas empecher les autres fiches d'etre
        # comptees dans leur bilan de quinzaine.
        #
        # On grave AVANT de poster : si Discord refuse (permission, panne), la
        # journee reste comptee. L'inverse aurait perdu la mesure a cause d'un
        # probleme d'affichage.
        tous = await asyncio.to_thread(etats_du_jour, jour)
        await asyncio.to_thread(ob.enregistrer_jour, tous, jour)

        bilans = {}
        for e in tous:
            bilans[(e["identite"].lower(), e["va"].lower())] = await asyncio.to_thread(
                ob.bilan_quinzaine, e["identite"], e["va"], jour)

        try:
            import jailbreak as _jb_id
            identites = list((_jb_id.list_all() or {}).keys())
        except Exception:
            identites = []

        n_msg = 0
        for cle, ch in cibles:
            # Chaque salon ne recoit QUE ce qu'il annonce suivre.
            voulue = identite_du_salon(getattr(ch, "name", ""), identites)
            etats = [e for e in tous
                     if not voulue or e["identite"].lower() == voulue]
            lignes_bilan = [{"e": e, "bilan": bilans.get(
                (e["identite"].lower(), e["va"].lower())) or {}} for e in etats]
            try:
                for e in etats:
                    await ch.send(_tronquer(ligne_fiche(e)))
                    n_msg += 1
                    await asyncio.sleep(0.6)     # on ne bouscule pas Discord
                debut, fin = ob.quinzaine(jour)
                await self._poser_epingle(ch, cle, _tronquer(
                    bloc_quinzaine(lignes_bilan, debut, fin, voulue)))
            except discord.Forbidden:
                print(f"[report-comptes] pas le droit d'écrire dans {ch}", flush=True)
            except Exception as e:
                print(f"[report-comptes] envoi : {e}", flush=True)
        return {"fiches": len(etats), "messages": n_msg, "salons": len(cibles)}

    def salons_report(self) -> list:
        """[(cle, salon)] ou publier : par convention de nom, et par config.

        Convention : tout salon dont le nom commence par « report-compte »
        (« report-compte », « report-comptes », « report-comptes-fr »...). Le
        proprietaire cree le salon, il est servi — pas de commande a lancer,
        et rien a reparametrer apres un changement de serveur.

        La configuration par identifiant reste lue si elle existe : elle sert
        aux salons qui ne suivent pas la convention.
        """
        vus, out = set(), []
        for c in getattr(self.bot, "get_all_channels", lambda: [])():
            nom = str(getattr(c, "name", "") or "").lower().replace("_", "-")
            if not nom.startswith("report-compte"):
                continue
            if not hasattr(c, "send"):
                continue
            vus.add(c.id)
            out.append((_cle(getattr(c.guild, "id", 0), c.id), c))
        for cle, cfg in _reports_configures(_load_cfg()):
            try:
                ch = self.bot.get_channel(int(cfg.get("channel_id") or 0))
            except Exception:
                ch = None
            if ch is not None and ch.id not in vus:
                vus.add(ch.id)
                out.append((cle, ch))
        return out

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
            # L'entree est CREEE si elle n'existait pas : un salon trouve par
            # son nom n'en a pas. Sans ca, pin_id n'etait jamais enregistre,
            # le salon restait « jamais servi » — et le premier passage se
            # serait rejoue toutes les vingt minutes, indefiniment.
            if cle:
                c = c if isinstance(c, dict) else {
                    "guild_id": getattr(getattr(ch, "guild", None), "id", 0),
                    "channel_id": ch.id, "auto": True}
                c["pin_id"] = msg.id
                cfg[cle] = c
                _save_cfg(cfg)
        except Exception as e:
            print(f"[report-comptes] épingle : {e}", flush=True)

    # ---- pas de commande slash, et c'est un choix contraint -------------
    #
    # Discord plafonne une APPLICATION a 100 commandes slash globales. Ce bot
    # y est deja : quatre cogs (vaactivity, vasort, tgrouter, numeros) ne se
    # chargent plus depuis un moment, en silence, pour cette raison. En
    # ajouter trois de plus faisait echouer celui-ci exactement pareil.
    #
    # Ce report n'a de toute facon pas besoin d'une commande : il tourne tout
    # seul apres minuit. Ne restait que la configuration du salon — remplacee
    # par une convention : le report va dans TOUT salon dont le nom commence
    # par « report-compte ». Le proprietaire cree le salon, il est servi.
    # Un declenchement manuel existe depuis le tableau de bord.


async def setup(bot):
    await bot.add_cog(ReportComptes(bot))
