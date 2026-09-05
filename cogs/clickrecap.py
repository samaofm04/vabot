"""Récap quotidien des clics GetMySocial, posté chaque nuit dans le salon
va-<handle> de CHAQUE VA QUI A UN LIEN — avec SES clics (aujourd'hui / hier /
la quinzaine de paie en cours : 1–15 ou 16–fin de mois). En auto, les salons
sans lien sont ignorés (pas de spam). En test manuel sur un salon précis, on
affiche quand même le message « pas de lien » pour voir l'état.

Timing robuste sans zoneinfo : on poll toutes les 30 min et on calcule l'heure
de Paris à la main (DST inclus), pour lancer une seule fois après minuit Paris.
"""
import asyncio
import calendar
import datetime
import json
import pathlib
import re
import time

import discord
import safe_json


def _tag_call(_fn, *a, **kw):
    """Exécute un appel gms.* sous l'étiquette 'report' (instrumentation api_usage) :
    le tag doit être posé DANS le thread exécutant, pas dans la boucle asyncio."""
    try:
        import gms as _g
        with _g.api_tag("report"):
            return _fn(*a, **kw)
    except AttributeError:          # vieux gms sans api_tag
        return _fn(*a, **kw)


def _analytics_reparti(gms, lid, a, b):
    """analytics_for_link sur une clé du POOL, en rotation.

    Le quota GetMySocial est PAR CLE. Le report d'un workspace de 20 liens fait
    80 appels d'un coup : sur une seule clé, la moitie repartait en echec et le
    tableau se remplissait de « — ». En les repartissant sur les 5 clés
    dediees, chacune ne voit qu'un cinquieme du trafic.

    La cle DOIT etre posee dans le thread qui appelle : use_key travaille sur un
    thread-local. La poser dans la boucle asyncio n'aurait servi a rien — meme
    raison que pour api_tag, cf. _tag_call.

    Sans pool configure, next_dash_key rend '' et use_key est un no-op : on
    retombe sur la cle principale, comme avant.
    """
    try:
        with gms.use_key(gms.next_dash_key()):
            return _tagged_analytics(gms, lid, a, b)
    except AttributeError:          # vieux gms sans pool de cles
        return _tagged_analytics(gms, lid, a, b)


def _tagged_analytics(gms, lid, a, b):
    """analytics_for_link étiqueté 'report' (instrumentation gms.api_usage)."""
    try:
        with gms.api_tag("report"):
            return gms.analytics_for_link(lid, a, b)
    except AttributeError:                       # vieux gms sans api_tag
        return gms.analytics_for_link(lid, a, b)

from discord import app_commands
from discord.ext import commands, tasks

# Flag persistant (data/ gitignore -> état runtime VPS). Cron ON par défaut
# (opt-out) : le récap auto ne poste QUE dans les salons qui ont un lien, donc
# pas de spam « pas de lien ». On peut le couper via /recapclics_auto actif:false.
_CFG_FILE = pathlib.Path(__file__).resolve().parent.parent / "data" / "clickrecap.json"


def _auto_enabled() -> bool:
    try:
        return bool(json.loads(_CFG_FILE.read_text(encoding="utf-8")).get("auto", True))
    except Exception:
        return True


def _set_auto(v: bool):
    try:
        _CFG_FILE.parent.mkdir(parents=True, exist_ok=True)
        safe_json.write_text(_CFG_FILE, json.dumps({"auto": bool(v)}))
    except Exception:
        pass


# Détection auto du lien d'un VA en scannant l'historique de son salon va-<handle>
# (cherche une URL getmysocial.com/<shortcode> postée par le bot/manager/boss).
_GMS_LINK_RE = re.compile(r"getmysocial\.com/([A-Za-z0-9_\-]+)", re.I)
# Détection robuste d'un salon VA, tolérante à un rond 🟢/🟠/🔴 en préfixe
_VA_CH_RE = re.compile(r"(?:^|[^a-z0-9])va-([a-z0-9_.]+)$")


def _ch_handle(name):
    m = _VA_CH_RE.search((name or "").lower())
    return m.group(1) if m else None


# Marqueur ⚙️ : le lien du VA a fait 0 clic sur 3 jours (lien qui tourne à vide).
# ADDITIF : se pose APRÈS le rond d'activité (🟢🟠🔴) et le 🔗. Ordre canonique du
# nom de salon : {rond}{🔗}{⚙️}-va-handle.
GEAR_MARK = "⚙️"


def _va_name_set_gear(name, has_gear):
    """Pose/retire le ⚙️ en PRÉSERVANT le rond d'activité (🟢🟠🔴) et le 🔗.
    None si ce n'est pas un salon va-."""
    h = _ch_handle(name)
    if not h:
        return None
    n = name or ""
    dot = n[0] if n[:1] in ("🟢", "🟠", "🔴") else ""
    link = "🔗" if "🔗" in n else ""
    gear = GEAR_MARK if has_gear else ""
    return f"{dot}{link}{gear}-va-{h}"


_LINKCACHE_FILE = pathlib.Path(__file__).resolve().parent.parent / "data" / "clickrecap_links.json"


def _load_linkcache() -> dict:
    try:
        return json.loads(_LINKCACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_linkcache(d: dict):
    try:
        _LINKCACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        safe_json.write_text(_LINKCACHE_FILE, json.dumps(d, ensure_ascii=False))
    except Exception:
        pass


# ---- Report des clics d'un GROUPE GMS (ex: Hybride) dans un salon dedie ----
# data/ est gitignore -> config runtime VPS. {guild_id: {channel_id, team_id,
# group_id, group_name, marche, message_id}}. La cle est « serveur:salon » —
# un report par SALON, pour tenir un click-fr et un click-us cote a cote.
# message_id = le message live, edite toutes les 30 minutes.
_REPORT_CFG_FILE = pathlib.Path(__file__).resolve().parent.parent / "data" / "report_click.json"


def _load_report_cfg() -> dict:
    try:
        d = json.loads(_REPORT_CFG_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_report_cfg(d: dict):
    try:
        _REPORT_CFG_FILE.parent.mkdir(parents=True, exist_ok=True)
        safe_json.write_text(_REPORT_CFG_FILE, json.dumps(d, ensure_ascii=False, indent=2))
    except Exception:
        pass


def _match_shortcode(sc, links):
    sc = (sc or "").lower()
    if not sc:
        return None
    for l in links:
        if (l.get("shortcode") or "").lower() == sc:
            return l
    return None

GMS_DOMAIN = "https://getmysocial.com"
# Cache court des clics calculés pour le bouton 'Mes clics' : évite de re-taper
# GetMySocial si un VA reclique rapidement (clé = (link_id, date du jour)).
_CLICKS_CACHE: dict = {}
_CLICKS_TTL = 60  # secondes
FR_MONTHS = ["", "janv.", "févr.", "mars", "avr.", "mai", "juin",
             "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def _last_sunday(year: int, month: int) -> int:
    for week in reversed(calendar.monthcalendar(year, month)):
        if week[6]:  # dimanche
            return week[6]
    return 28


def _paris_now() -> datetime.datetime:
    """Heure locale de Paris calculée depuis l'UTC (CET=+1, CEST=+2).
    DST UE : dernier dimanche de mars 01:00 UTC → dernier dimanche d'octobre 01:00 UTC."""
    u = datetime.datetime.utcnow()
    y = u.year
    dst_start = datetime.datetime(y, 3, _last_sunday(y, 3), 1)
    dst_end = datetime.datetime(y, 10, _last_sunday(y, 10), 1)
    offset = 2 if (dst_start <= u < dst_end) else 1
    return u + datetime.timedelta(hours=offset)


def _pay_period(d: datetime.date):
    """Quinzaine de paie contenant la date d : (debut, fin)."""
    if d.day <= 15:
        return d.replace(day=1), d.replace(day=15)
    last = calendar.monthrange(d.year, d.month)[1]
    return d.replace(day=16), d.replace(day=last)


def _quinzaine_precedente(d: datetime.date):
    """La quinzaine qui precede celle de d : (debut, fin).

    Le 1er-15 est precede du 16-fin du mois d'avant ; le 16-fin est precede
    du 1er-15 du meme mois. Passer par « la veille du debut » evite d'avoir a
    traiter janvier a part : le mois d'avant se deduit tout seul.
    """
    debut, _fin = _pay_period(d)
    return _pay_period(debut - datetime.timedelta(days=1))


#: Marches proposes au report. La cle est ce qu'on ecrit dans la config ; la
#: valeur est (libelle, drapeau, pays comptes). Un ensemble vide = « tout », on
#: n'affiche alors que le total.
MARCHES = {
    "fr": ("FR", "🇫🇷", frozenset({"FR", "BE", "CH", "LU", "MC"})),
    # « US » au sens du proprietaire : les pays anglophones ou le public a de
    # l'argent, pas les seuls Etats-Unis. Un clic canadien ou britannique vaut
    # un clic americain ; les compter a part n'aurait servi a rien.
    # Pour en ajouter un (NZ, IE...), il suffit de l'ecrire ici.
    "us": ("US", "🇺🇸", frozenset({"US", "CA", "AU", "GB"})),
    "tout": ("tous pays", "🌍", frozenset()),
}

#: Ce que « US » recouvre, dit en toutes lettres sous le titre du report :
#: sans ca, un chiffre plus gros que le nombre de clics americains passerait
#: pour une erreur.
MARCHE_DETAIL = {
    "us": "🇺🇸 🇨🇦 🇦🇺 🇬🇧",
    "fr": "🇫🇷 🇧🇪 🇨🇭 🇱🇺 🇲🇨",
}


def _marche_de(c: dict) -> tuple:
    """(cle, libelle, drapeau, pays) du marche d'un report. Defaut : tout."""
    cle = str((c or {}).get("marche") or "tout").lower()
    if cle not in MARCHES:
        cle = "tout"
    lib, dra, pays = MARCHES[cle]
    return cle, lib, dra, pays


def _cle_report(guild_id, channel_id) -> str:
    """La cle d'un report dans la config : un par SALON, pas un par serveur.

    Le proprietaire veut un salon « click-fr » et un salon « click-us » sur le
    meme serveur. L'ancienne cle (l'identifiant du serveur seul) n'en autorisait
    qu'un ; les anciennes entrees restent lues telles quelles, voir
    _reports_configures.
    """
    return "%s:%s" % (guild_id, channel_id)


def _reports_configures(cfg: dict) -> list:
    """[(cle, config)] de tous les reports, anciens formats compris.

    Une entree ecrite avant le passage au multi-salon est rangee sous le seul
    identifiant du serveur. On la rend telle quelle : elle continue de marcher,
    personne n'a a refaire sa configuration.
    """
    out = []
    for cle, c in (cfg or {}).items():
        if isinstance(c, dict) and c.get("channel_id"):
            out.append((str(cle), c))
    return out


def _code_suivi(destination) -> str:
    """Le code de suivi MyPuls au bout d'une destination, ou ''.

    Les liens GetMySocial pointent vers onlyfans.com/<pseudo>/c85 : « c85 » est
    le code du lien de suivi cote MyPuls. C'est par LUI qu'on rattache les
    abonnes aux clics — jamais par le nom, qui s'ecrit « Bo07 » d'un cote et
    « BO7 » de l'autre, « Pam Pam » ici et « PAMPAM » la.
    """
    m = re.search(r"/([A-Za-z]+\d+)/?$", str(destination or "").strip())
    return m.group(1) if m else ""


def _cle_adresse(url) -> str:
    """« onlyfans.com/jessyewdiference/c88 » -> « jessyewdiference/c88 ».

    LE CODE SEUL NE SUFFIT PAS. Il n'est unique que dans une creatrice :
    « c47 » designe cinq liens differents selon la modele — « VA 4 JB » chez
    Jessye, « peaky » ailleurs, une campagne SFS ailleurs encore. Rapprocher
    sur le code seul prenait le premier venu, d'ou des campagnes SFS collees
    aux VA et les memes abonnes affiches a six personnes.

    L'adresse, elle, porte le pseudo ET le code, des deux cotes : la
    destination d'un lien GetMySocial et l'URL d'un lien de suivi MyPuls ont
    la meme forme. Le rapprochement devient exact.

    Rend '' si l'adresse n'a pas cette forme — mieux vaut ne rien rattacher
    que rattacher au hasard.
    """
    m = re.search(r"([^/]+)/([A-Za-z]+\d+)/?$", str(url or "").strip())
    return ("%s/%s" % (m.group(1), m.group(2))).lower() if m else ""


# _cle_nom a ete RETIRE avec _suivi_de : il servait a rapprocher « BO7 » de
# « Bo07 ». On ne rapproche plus par le nom du tout — l'adresse complete
# (pseudo + code) ne peut pas se tromper de personne, la ou un prenom ramenait
# des campagnes SFS.


async def _liens_suivi_periode(debut, fin) -> list:
    """Les liens de suivi sur UNE periode. [] si l'API ne repond pas.

    `subscribers_period` est le differentiel GAGNE sur la fenetre demandee —
    c'est ce qu'on veut dire par « aujourd'hui » ou « cette quinzaine », et
    non le cumul depuis toujours.
    """
    try:
        import mypuls
        return await asyncio.to_thread(
            mypuls.api_tracking_links, False,
            debut.isoformat(), fin.isoformat()) or []
    except Exception as e:
        print(f"[reportclick] liens de suivi {debut}..{fin} : {e}")
        return []


# _liens_suivi et _abonnes_par_code ont ete RETIRES : plus aucun appelant.
# Le report demande desormais une PERIODE precise (_liens_suivi_periode),
# parce que le cumul depuis toujours ne dit rien de ce qui vient de se
# passer -- un lien a 4 000 abonnes depuis un an ressemble a un lien qui
# marche, meme sans rien avoir rapporte depuis trois semaines.


def _personne_du_lien(nom) -> str:
    """La PERSONNE derriere un nom de lien, ou '' si on ne peut pas la nommer.

    Une meme personne tient plusieurs telephones, et chacun a son lien :
    « ( BO7 ) 1 », « ( BO7 ) 2 »… Sans regroupement, ses lignes se retrouvent
    dispersees dans le tableau et on ne voit jamais ce qu'elle rapporte.

    La personne est TOUT ce qui est entre parentheses ; seul le nombre qui SUIT
    la parenthese est le numero du telephone.

    Piege corrige le 23/08 : on retirait un prefixe « VA n » a l'interieur des
    parentheses, en le prenant pour un numero. C'etait faux — « VA 1 Noum »,
    « VA 2 Noum » et « VA 3 Noum » sont TROIS personnes differentes. Seuls
    « (VA 1 Noum) 1 » et « (VA 1 Noum) 2 » sont les deux telephones d'une meme.

    Les espaces sont normalises : le meme compte s'ecrit « ( BO7 ) 1 » ici et
    « (BO7) 2 » la, ce qui en ferait deux personnes.

    Rend '' quand il n'y a pas de parentheses (« VA 1 », « TEMPLATE ») : mieux
    vaut ne pas regrouper que regrouper a tort. Dans certains workspaces, cinq
    liens s'appellent tous « VA 1 » sans etre la meme personne.
    """
    m = re.search(r"\((.*?)\)", str(nom or ""))
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()


def _nom_propre(nom) -> str:
    """Le nom d'un lien, espaces normalises : « ( BO7 )  1 » -> « (BO7) 1 ».

    Les noms sont saisis a la main et l'espacement varie d'un lien a l'autre ;
    en chasse fixe, ces espaces en trop se voient et decalent la lecture.
    """
    n = re.sub(r"\s+", " ", str(nom or "")).strip()
    n = re.sub(r"\(\s+", "(", n)
    n = re.sub(r"\s+\)", ")", n)
    return n


def _creneau_30(d: datetime.datetime) -> tuple:
    """Le creneau de 30 minutes auquel appartient cet instant : (heure, 0|30).

    Sert de repere au rafraichissement : on compare le creneau courant au
    dernier traite. Aligne sur l'horloge (h:00 et h:30) plutot que sur un
    compteur interne, pour que la cadence survive a un redemarrage — sinon
    chaque relance du bot decalait le rythme.
    """
    return (d.hour, 0 if d.minute < 30 else 30)


def _next_demi_heure_unix() -> int:
    """Timestamp Unix (UTC) du prochain h:00 ou h:30 — pour le timer Discord
    dynamique <t:…:R> (« dans X min »). Les demi-heures Paris et UTC coincident
    (decalage en heures pleines), donc on calcule direct en UTC."""
    u = datetime.datetime.utcnow().replace(second=0, microsecond=0)
    nxt = (u.replace(minute=30) if u.minute < 30
           else u.replace(minute=0) + datetime.timedelta(hours=1))
    return int(calendar.timegm(nxt.timetuple()))


#: Mois en anglais : le report est en anglais, les VA du marche US le lisent.
EN_MONTHS = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _en(d: datetime.date) -> str:
    """« Aug » — le mois d'une date, en anglais abrege."""
    return EN_MONTHS[d.month]


def _fr(d: datetime.date) -> str:
    return f"{d.day} {FR_MONTHS[d.month]}"


NO_LINK_MSG = (
    "🔗 **Pas encore de lien GetMySocial.**\n"
    "Demande ton lien à un **manager** ou au **boss** "
    "(bouton « Demander un lien » dans tes commandes, ou `/lien`)."
)


#: Dernier rafraichissement manuel, par salon. Le bouton est ouvert a TOUT le
#: monde : sans ce frein, dix personnes qui cliquent d'affilee lanceraient dix
#: series d'appels GetMySocial, et le quota est partage avec le rapport de paie
#: — un 429 la-bas coute bien plus cher qu'un report en retard de trente
#: secondes.
_REFRESH_DERNIER = {}
_REFRESH_ATTENTE_S = 60


#: Noms de groupes GMS, pour l'autocompletion. Un cache est OBLIGATOIRE :
#: Discord coupe une autocompletion qui n'a pas repondu en 3 secondes, et
#: list_team_groups interroge le board prive (cookie, ~1 s par workspace).
#: Sans cache, la liste serait vide une fois sur deux.
_ESPACES_CACHE = {"ts": 0.0, "espaces": [], "tache": None}
_ESPACES_TTL = 600


async def _charger_espaces_gms() -> list:
    """Les workspaces du compte, par la CLE API. [{id, name, link_count}].

    Par la cle et non par le cookie de session : le cookie expire, et la
    fonction qui l'utilise rend alors une liste vide sans le dire — c'est ce
    qui affichait « aucune option ne correspond ».

    Et par teams_via_api plutot que par la constante KNOWN_TEAMS, qui n'en
    liste que deux en dur alors que le compte en compte sept.
    """
    import gms
    teams = await asyncio.to_thread(gms.teams_via_api)
    out = [{"id": t["id"], "name": t.get("name") or t["id"],
            "link_count": t.get("link_count") or 0}
           for t in (teams or []) if t.get("id")]
    # Les plus fournis d'abord : c'est presque toujours celui-la qu'on cherche.
    out.sort(key=lambda e: (-(e["link_count"] or 0), e["name"].lower()))
    return out


def _rafraichir_espaces(bot=None):
    """Lance (ou retrouve) le chargement des groupes EN FOND. Rend la tache.

    Rendre la tache compte : l'autocompletion l'ATTEND avec un delai, au lieu
    d'envelopper le chargement dans un wait_for. La difference n'est pas un
    detail — wait_for ANNULE la coroutine quand le delai expire, si bien que le
    travail etait jete a chaque frappe et n'aboutissait jamais. Le cache
    restait vide indefiniment, et l'autocompletion echouait a chaque fois.
    """
    tache = _ESPACES_CACHE.get("tache")
    if tache is not None and not tache.done():
        return tache

    async def _travail():
        try:
            liste = await _charger_espaces_gms()
            if liste:
                _ESPACES_CACHE.update({"ts": time.time(), "espaces": liste})
            return liste
        except Exception as e:
            print(f"[reportclick] chargement des groupes echoue : {e}")
            return []

    try:
        tache = asyncio.get_running_loop().create_task(_travail())
    except RuntimeError:
        return None                    # pas de boucle : rien a lancer
    _ESPACES_CACHE["tache"] = tache
    return tache


async def _espaces_gms(budget_s: float = 2.2) -> list:
    """Les groupes connus. Rend la liste PERIMEE plutot que rien.

    Si le cache est encore VIDE — juste apres un redemarrage, par exemple — on
    accepte d'attendre un court instant plutot que de rendre une liste vide :
    une autocompletion vide se lit comme « ce groupe n'existe pas ». Le budget
    reste sous les 3 secondes au-dela desquelles Discord abandonne.

    Si le cache contient deja quelque chose, on ne bloque jamais : le
    rafraichissement part en fond et la frappe suivante en profitera.
    """
    vieux = (time.time() - _ESPACES_CACHE.get("ts", 0)) >= _ESPACES_TTL
    deja = _ESPACES_CACHE.get("espaces") or []
    if deja:
        if vieux:
            _rafraichir_espaces()      # en fond, on ne fait attendre personne
        return deja
    tache = _rafraichir_espaces()
    if tache is not None:
        # asyncio.wait — et NON wait_for : le delai expire sans annuler la
        # tache. Elle continue, et la frappe suivante trouvera le cache rempli.
        # wait_for l'aurait tuee, et le cache ne se serait jamais rempli.
        try:
            await asyncio.wait({tache}, timeout=budget_s)
        except Exception as e:
            print(f"[reportclick] attente des groupes : {e}")
    return _ESPACES_CACHE.get("espaces") or []


class ReportRefreshView(discord.ui.View):
    """Bouton « Rafraichir » sous le report de clics. Ouvert a tout le monde.

    Persistant (timeout=None + custom_id fixe) : le bouton doit continuer de
    repondre apres un redemarrage du bot, sinon le message epingle deviendrait
    un decor mort.
    """

    def __init__(self, cog=None):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Rafraîchir", emoji="🔄",
                       style=discord.ButtonStyle.secondary,
                       custom_id="reportclick:refresh")
    async def b_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.cog or interaction.client.get_cog("ClickRecap")
        if cog is None:
            await interaction.response.send_message("⚠️ Module indispo.", ephemeral=True)
            return
        cid = getattr(interaction.channel, "id", None)
        cfg = _load_report_cfg()
        vises = [cle for cle, c in _reports_configures(cfg)
                 if str(c.get("channel_id")) == str(cid)]
        if not vises:
            await interaction.response.send_message(
                "ℹ️ Aucun report configuré dans ce salon.", ephemeral=True)
            return
        reste = _REFRESH_ATTENTE_S - (time.time() - _REFRESH_DERNIER.get(cid, 0))
        if reste > 0:
            # On le DIT au lieu de faire semblant : un bouton qui ne repond
            # rien passe pour casse, et la personne reclique.
            await interaction.response.send_message(
                f"⏳ Déjà rafraîchi il y a moins d'une minute. Réessaie dans "
                f"{int(reste)} s — les chiffres viennent de GetMySocial, "
                f"qui a un quota.", ephemeral=True)
            return
        _REFRESH_DERNIER[cid] = time.time()
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            for cle in vises:
                await cog._post_or_update_report(cle)
            await interaction.followup.send("🔄 Report mis à jour.", ephemeral=True)
        except Exception as e:
            # Le compteur est relache : l'essai n'a rien coute en quota, la
            # personne ne doit pas attendre une minute pour retenter.
            _REFRESH_DERNIER.pop(cid, None)
            await interaction.followup.send(
                f"⚠️ Mise à jour impossible : {str(e)[:120]}", ephemeral=True)


class MyClicksView(discord.ui.View):
    """Bouton persistant '📊 Mes clics' posé dans chaque salon va-.
    Au clic, le VA voit EN DIRECT ses clics (aujourd'hui / hier / semaine /
    quinzaine) pour le lien de CE salon. Réponse éphémère (privée)."""

    def __init__(self, cog=None):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Mes clics", emoji="📊",
                       style=discord.ButtonStyle.primary, custom_id="myclicks:show")
    async def b_clicks(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.cog or interaction.client.get_cog("ClickRecap")
        if cog is None:
            await interaction.response.send_message("⚠️ Module indispo.", ephemeral=True)
            return
        await cog._handle_myclicks(interaction)


class ClickRecap(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._owner_id = None
        self._last_run = None  # date ISO du dernier récap auto (anti-doublon)
        self._report_creneau = None  # dernier creneau de 30 min deja publie
        if _auto_enabled():
            self.daily_recap.start()
        self.hourly_report.start()

    async def cog_load(self):
        # Vue persistante : le bouton 'Mes clics' marche même après un restart.
        try:
            self.bot.add_view(MyClicksView(self))
            self.bot.add_view(ReportRefreshView(self))
        except Exception as e:
            print(f"[clickrecap] add_view échoué : {e}")
        # Cache des groupes rempli dès le démarrage : sans ça la première
        # autocomplétion tombe sur un cache vide et n'affiche rien, ce qui se
        # lit comme « ce groupe n'existe pas » alors qu'il existe.
        _rafraichir_espaces()

    def cog_unload(self):
        if self.daily_recap.is_running():
            self.daily_recap.cancel()
        if self.hourly_report.is_running():
            self.hourly_report.cancel()

    async def _ac_groupe(self, interaction: discord.Interaction, current: str):
        """Propose les groupes GMS a la frappe.

        Discord plafonne a 25 propositions et coupe au-dela de 3 secondes :
        _espaces_gms travaille sur cache et rend une liste perimee plutot que
        rien. Une autocompletion vide passerait pour un bug alors que le
        groupe existe.
        """
        # TOUT est sous garde : une exception ici fait afficher « Échec des
        # options de chargement » a Discord, sans la moindre trace cote bot.
        # Mieux vaut une liste incomplete qu'un message d'echec.
        try:
            return await self._ac_groupe_reel(current)
        except Exception as e:
            print(f"[reportclick] autocompletion groupes : {type(e).__name__} {e}")
            return []

    async def _ac_groupe_reel(self, current: str):
        """Propose les WORKSPACES, pas les groupes.

        Le proprietaire suit ses clics par workspace (« marche francais »,
        « JESSY LE RETOUR »…), pas groupe par groupe : proposer les 54 groupes
        noyait le choix. Six lignes valent mieux que cinquante-quatre.
        """
        espaces = await _espaces_gms()
        cur = (current or "").strip().lower()
        if cur:
            debut = [e for e in espaces if e["name"].lower().startswith(cur)]
            dedans = [e for e in espaces
                      if cur in e["name"].lower() and e not in debut]
            espaces = debut + dedans
        choix = []
        for e in espaces[:25]:
            lib = f"{e['name']} ({e.get('link_count') or 0} lien(s))"
            choix.append(app_commands.Choice(name=lib[:100],
                                             value=str(e["id"])[:100]))
        return choix

    async def _is_owner(self, uid):
        if self._owner_id is None:
            app = await self.bot.application_info()
            self._owner_id = app.owner.id
        return uid == self._owner_id

    # ---------- Loop : poll 30 min, déclenche 1×/jour après minuit Paris ----------
    @tasks.loop(minutes=30)
    async def daily_recap(self):
        now = _paris_now()
        dstr = now.date().isoformat()
        if now.hour == 0 and self._last_run != dstr:
            self._last_run = dstr
            try:
                await self._run_all()
            except Exception as e:
                print(f"[clickrecap] erreur loop : {e}")

    @daily_recap.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    # ---------- Report HORAIRE des clics d'un groupe (ex: Hybride) ----------
    @tasks.loop(minutes=5)
    async def hourly_report(self):
        """Met a jour (edite) le message de report de chaque serveur configure,
        toutes les 30 minutes (aligne sur h:00 et h:30, survit aux redemarrages).

        La boucle tourne toutes les 5 minutes mais ne fait rien tant que le
        creneau n'a pas change : c'est ce qui garde la cadence alignee sur
        l'horloge meme apres un redemarrage du bot.
        """
        now = _paris_now()
        creneau = _creneau_30(now)
        if self._report_creneau == creneau:
            return
        self._report_creneau = creneau
        cfg = _load_report_cfg()
        for cle, _c in _reports_configures(cfg):
            try:
                await self._post_or_update_report(cle)
            except Exception as e:
                print(f"[reportclick] update {cle} echoue : {e}")
            await asyncio.sleep(1)

    @hourly_report.before_loop
    async def _before_report(self):
        await self.bot.wait_until_ready()

    async def _build_group_report(self, c: dict, permettre_vide: bool = True):
        """Construit l'embed du report d'un groupe : aujourd'hui / hier / semaine
        / période 1–15 / période 16–fin. None si le module GMS est indispo."""
        import gms
        team_id = c.get("team_id")
        group_id = c.get("group_id")
        identity = c.get("identity")  # si défini -> énumération par suffixe (clé API)
        name = c.get("group_name") or "Groupe"
        _cle_m, libelle, drapeau, pays_marche = _marche_de(c)
        tout_le_ws = bool(c.get("tout"))
        metas = await asyncio.to_thread(_tag_call, gms.report_links_meta,
                                        team_id, identity, group_id, tout_le_ws)
        # None = board GMS injoignable (cookie expiré, HTTP KO…). On NE réécrit
        # PAS le report avec un faux « 0 clic » : on skip et on garde le dernier
        # message valide (l'appelant voit None -> ne touche pas au message).
        if metas is None:
            return None
        ids = [m["id"] for m in metas if m.get("id")]
        today = _paris_now().date()
        yest = today - datetime.timedelta(days=1)
        week_start = today - datetime.timedelta(days=today.weekday())  # lundi
        last = calendar.monthrange(today.year, today.month)[1]
        p1s, p1e = today.replace(day=1), today.replace(day=15)
        p2s, p2e = today.replace(day=16), today.replace(day=last)
        ranges = [
            (today, today),        # aujourd'hui
            (yest, yest),          # hier
            (week_start, today),   # cette semaine
            (p1s, p1e),            # période 1–15
            (p2s, p2e),            # période 16–fin
        ]
        vals = await asyncio.gather(*[
            asyncio.to_thread(_tag_call, gms.clicks_for_ids, ids, s.isoformat(), e.isoformat())
            for (s, e) in ranges
        ])
        c_today, c_yest, c_week, c_p1, c_p2 = vals
        all_none = all(v is None for v in vals)
        # Tout a echoue ET un message existe deja : on rend None pour que
        # l'appelant garde l'ancien. Ecraser des chiffres justes par « No data »
        # est pire que de laisser un report d'une heure : le lecteur croit que
        # personne n'a clique, alors qu'on n'a simplement pas su lire.
        # A la premiere pose, en revanche, on affiche l'echec — sinon rien
        # n'apparaitrait et le report passerait pour non configure.
        if all_none and not permettre_vide:
            return None

        # ---- Detail par lien, calcule AVANT l'embed --------------------------
        # Il faut les clics du marche par lien pour pouvoir en faire le cumul
        # affiche dans le resume : clicks_for_ids ne rend aucun detail pays.
        _MAX_PER_LIEN = 60
        cyc_s, cyc_e = _pay_period(today)
        rows, cumul, detail_ok = [], [None, None, None, None], False
        # Le nom affiche ne porte pas la destination : on la garde a part pour
        # en tirer le code de suivi MyPuls (…/c85) plus bas.
        _dest_par_nom = {}
        if ids and not all_none and len(ids) <= _MAX_PER_LIEN:
            # analytics_for_link plutot que clicks_for_link : MEME appel reseau,
            # mais il rend aussi le detail par pays. Les clics du marche sortent
            # donc gratuitement — les demander a part aurait double la facture.
            _plages = [
                (today, today),          # today
                (yest, yest),            # yesterday
                (week_start, today),     # this week
                (cyc_s, cyc_e),          # current pay period
            ]
            # Concurrence BORNEE. Sans elle, 20 liens x 4 periodes partaient en
            # 80 appels simultanes : GetMySocial en laissait tomber la moitie,
            # et le tableau se remplissait de « — » alors que les memes appels,
            # passes en file, reussissent tous (mesure : 12/12 en 3,7 s).
            # Meme borne que _fetch_daily_stats, qui a deja tranche la question.
            _sem = asyncio.Semaphore(6)

            async def _un(lid, s, e):
                async with _sem:
                    return await asyncio.to_thread(_analytics_reparti, gms, lid,
                                                   s.isoformat(), e.isoformat())

            per = await asyncio.gather(*[
                asyncio.gather(*[_un(m["id"], s, e) for (s, e) in _plages])
                for m in metas if m.get("id")
            ])

            def _duo_de(couple):
                """(clics du marche, total). (None, None) si l'appel a echoue.

                Surtout pas (0, 0), qui se lirait « personne n'a clique » alors
                qu'on n'a rien su lire.
                """
                total, pays = couple if isinstance(couple, tuple) else (None, None)
                if total is None:
                    return None, None
                if not pays_marche:
                    return None, total
                return sum(v for k, v in (pays or {}).items() if k in pays_marche), total

            cumul = [0, 0, 0, 0]
            for m, quatre in zip([m for m in metas if m.get("id")], per):
                label = m.get("display_name") or m.get("shortcode") or "?"
                paires = [_duo_de(c) for c in quatre]
                for i, (u, _t) in enumerate(paires):
                    if u is not None:
                        cumul[i] += u
                rows.append((label, paires))
                _dest_par_nom[str(label)] = m.get("destination") or ""
            rows.sort(key=lambda r: (-((r[1][0][1]) or 0), -((r[1][2][1]) or 0),
                                     -((r[1][3][1]) or 0), str(r[0])))
            detail_ok = True

        # ---- L'embed ---------------------------------------------------------
        if all_none:
            color = discord.Color.orange()
        elif (c_today or 0) > 0 or (c_week or 0) > 0:
            color = discord.Color.green()
        else:
            color = discord.Color.dark_grey()

        emb = discord.Embed(
            title=f"{drapeau} Clicks — {name}",
            description=(
                f"**{len(ids)}** link(s) tracked."
                + (f"  ·  {libelle} = {MARCHE_DETAIL[_cle_m]}"
                   if _cle_m in MARCHE_DETAIL else "")),
            color=color,
        )

        def _n(v):
            return "—" if v is None else f"{v:,}".replace(",", " ")

        # Resume : une seule zone, alignee. Cinq champs separes rendaient la
        # lecture impossible sur telephone (une colonne par periode).
        # Le detail par lien ne mesure que la quinzaine EN COURS : on l'attribue
        # a la bonne moitie du mois. L'autre n'affiche que le total — dire un
        # chiffre US qu'on n'a pas mesure serait pire que de ne rien dire.
        _premiere_moitie = cyc_s.day == 1
        lignes_resume = []
        # LES MEMES CHIFFRES, EN BRUT. La page web ne peut pas relire un
        # tableau a chasse fixe sans le reanalyser ; on lui donne les valeurs
        # telles qu'elles sortent du calcul, et personne ne recalcule rien.
        _donnees = {"marche": libelle if pays_marche else "",
                    "drapeau": drapeau if pays_marche else "🌍",
                    "resume": [], "abonnes": [], "par_lien": []}
        for etiquette, marche_v, total_v in (
                ("Today", cumul[0], c_today),
                ("Yesterday", cumul[1], c_yest),
                ("This week", cumul[2], c_week),
                (f"{_en(p1s)} 1–15",
                 cumul[3] if _premiere_moitie else None, c_p1),
                (f"{_en(p2s)} 16–{p2e.day}",
                 None if _premiere_moitie else cumul[3], c_p2)):
            _donnees["resume"].append(
                {"quand": etiquette,
                 "marche": marche_v if (pays_marche and marche_v is not None) else None,
                 "total": total_v})
            if pays_marche and marche_v is not None:
                lignes_resume.append(
                    f"`{etiquette:<12}` {drapeau} **{_n(marche_v)}**"
                    f"   🌍 **{_n(total_v)}**")
            else:
                lignes_resume.append(f"`{etiquette:<12}` 🌍 **{_n(total_v)}**")
        emb.add_field(name="​", value="\n".join(lignes_resume), inline=False)

        if all_none:
            emb.add_field(name="⚠️ No data",
                          value="GetMySocial is not responding right now.",
                          inline=False)
        elif not ids:
            # board OK mais 0 lien : groupe reellement vide OU config perimee.
            # On le signale, sinon « 0 clic » serait trompeur.
            emb.color = discord.Color.orange()
            emb.add_field(
                name="⚠️ No links here",
                value="Empty workspace, or stale config. "
                      "Run `/setreportclick` again if that's unexpected.",
                inline=False)

        if detail_ok and rows:
            # DEUX tableaux, pas un : « 10/17 » dans une seule colonne laissait
            # se demander lequel des deux chiffres etait le US. Chaque tableau
            # porte son drapeau dans son titre, il n'y a plus a deviner.
            #
            # Bloc de code : c'est la seule mise en forme que Discord aligne.
            # Les drapeaux, eux, ne s'alignent pas en chasse fixe — d'ou leur
            # place dans le titre plutot que dans le tableau.
            # UN seul tableau, deux colonnes par periode : le marche et le
            # total, cote a cote sur la meme ligne. Deux tableaux separes
            # obligeaient a chercher la meme personne deux fois pour comparer.
            _m = libelle if pays_marche else ""
            entete = (
                f"{'':<18}{'TODAY':^12}{'YESTERDAY':^12}{'PERIOD':^12}\n"
                f"{'LINK':<18}"
                + (f"{_m:>5}{'GLOB':>7}" * 3 if pays_marche
                   else f"{'GLOB':>12}" * 3))

            def _c(v):
                # « — » veut dire « pas su lire », JAMAIS « zero ». Ecrire 0
                # a la place d'un echec serait un mensonge qu'on ne verrait pas.
                return "—" if v is None else str(v)

            def _duo_col(paire):
                """« marche  total » d'une periode, en deux colonnes alignees."""
                u, t = paire
                if not pays_marche:
                    return f"{_c(t):>12}"
                return f"{_c(u):>5}{_c(t):>7}"

            # LE REGROUPEMENT PAR PERSONNE A ETE RETIRE, avec ses sous-totaux
            # et son classement par chiffres. Une ligne par lien, par ordre
            # alphabetique : c'est ce que le proprietaire lit tous les jours,
            # et un tableau qui se reordonne a chaque heure ne se parcourt pas
            # du regard. Les sous-totaux, eux, additionnaient des lignes qu'il
            # veut voir separement -- « c'est deux trucs differents ».

            # (« classer sur le marche ou sur le total » n'a plus lieu
            #  d'etre : on classe par NOM.)

            def _tableau():
                # AUCUN REGROUPEMENT. Une ligne par lien, dans l'ordre
                # alphabetique, un point c'est tout.
                #
                # On empilait les telephones d'une meme personne sous un
                # sous-total, et on classait par nombre de clics. Deux defauts
                # pour le prix d'un : le sous-total additionnait des lignes que
                # le proprietaire veut voir separement (« c'est deux trucs
                # differents »), et un classement par chiffres change d'ordre a
                # chaque heure -- on cherche quelqu'un et il a bouge de six
                # lignes.
                #
                # La parenthese de tete est ignoree au tri : « (ANDRY) 1 » se
                # range a A. Le numero de telephone suit le nom, donc
                # « (BO7) 1 » precede « (BO7) 2 » sans rien de special.
                _cle_tri = lambda t: re.sub(r"^[^0-9A-Za-z]+", "", str(t)).lower()
                _donnees["par_lien"] = [
                    {"lien": _nom_propre(lab),
                     "periodes": [{"marche": p[i][0], "total": p[i][1]}
                                  for i in (0, 1, 3)]}
                    for lab, p in sorted(rows, key=lambda x: _cle_tri(x[0]))]
                lignes_plates = [
                    f"{_nom_propre(lab)[:17]:<18}"
                    + "".join(_duo_col(p[i]) for i in (0, 1, 3))
                    for lab, p in sorted(rows, key=lambda x: _cle_tri(x[0]))
                ]

                # Un champ Discord plafonne a 1024 signes ; on garde de la
                # marge pour l'en-tete, repete dans CHAQUE bloc — sans lui, le
                # second n'a plus de titres de colonnes et ses chiffres ne
                # veulent plus rien dire.
                blocs, courant, taille = [], [], 0
                for ligne in lignes_plates:
                    if courant and taille + len(ligne) + 1 > 820:
                        blocs.append("\n".join(courant))
                        courant, taille = [], 0
                    courant.append(ligne)
                    taille += len(ligne) + 1
                if courant:
                    blocs.append("\n".join(courant))
                return blocs

            # ---- Abonnes MyPuls, par personne ------------------------------
            # Les clics disent qui envoie du trafic ; les abonnes disent qui le
            # convertit. Un VA a 500 clics et 0 abonne ne se voyait nulle part.
            # ---- Abonnes MyPuls, par lien ---------------------------------
            #
            # DEUX INFORMATIONS, PAS PLUS : ce qui est arrive aujourd'hui, et
            # les deux dernieres quinzaines. Le cumul depuis toujours ne dit
            # rien de ce qui vient de se passer -- un lien a 4 000 abonnes
            # depuis un an ressemble a un lien qui marche, meme s'il n'a rien
            # rapporte depuis trois semaines.
            #
            # `subscribers_period` est le differentiel GAGNE sur la fenetre
            # demandee, d'ou trois appels : le jour, la quinzaine en cours,
            # celle d'avant. C'est trois requetes sur les soixante du quota,
            # et le trousseau en couvre largement le cout.
            _q_deb, _q_fin = _pay_period(today)
            _p_deb, _p_fin = _quinzaine_precedente(today)
            _jour, _quinz, _prec = await asyncio.gather(
                _liens_suivi_periode(today, today),
                _liens_suivi_periode(_q_deb, _q_fin),
                _liens_suivi_periode(_p_deb, _p_fin))

            if _jour or _quinz or _prec:
                def _index(liste):
                    """{adresse: lien}, l'adresse portant le pseudo ET le code.

                    Le code n'est unique QUE dans une creatrice : « c47 »
                    designe cinq liens differents selon la modele. Indexer sur
                    le code seul collait des campagnes SFS aux VA.
                    """
                    d = {}
                    for _t in liste or []:
                        _a = _cle_adresse(_t.get("url"))
                        if _a:
                            d.setdefault(_a, _t)
                    return d

                _iJ, _iQ, _iP = _index(_jour), _index(_quinz), _index(_prec)

                def _n(idx, adr):
                    _t = idx.get(adr)
                    return (_t or {}).get("abonnes_periode") or 0

                _assoc = []
                for lab, _p in rows:
                    _adr = _cle_adresse(_dest_par_nom.get(str(lab), ""))
                    if not _adr:
                        continue
                    if _adr not in _iJ and _adr not in _iQ and _adr not in _iP:
                        continue
                    _assoc.append((_nom_propre(lab), _adr,
                                   _n(_iJ, _adr), _n(_iQ, _adr), _n(_iP, _adr)))

                # PAR ORDRE ALPHABETIQUE. Un classement par chiffres change
                # d'ordre a chaque heure : on cherche quelqu'un et il a
                # bouge de six lignes. Un tableau qu'on lit tous les jours se
                # parcourt du regard, et pour ca il faut que chacun soit
                # TOUJOURS au meme endroit.
                #
                # La parenthese de tete est ignoree : « (ANDRY) 1 » se range a
                # A, pas avant tout le monde. Le numero de telephone suit le
                # nom, donc « (BO7) 1 » precede « (BO7) 2 » naturellement.
                _assoc.sort(key=lambda x: re.sub(r"^[^0-9A-Za-z]+", "", x[0]).lower())
                _donnees["abonnes"] = [
                    {"lien": _n2, "auj": _a1, "quinz": _a2, "prec": _a3}
                    for _n2, _adr2, _a1, _a2, _a3 in _assoc]
                _donnees["quinzaine"] = "%s→%s" % (_fr(_q_deb), _fr(_q_fin))
                _donnees["precedente"] = "%s→%s" % (_fr(_p_deb), _fr(_p_fin))
                _e = (f"{'LINK':<18}{'AUJ':>5}{'QUINZ':>7}{'PRÉC':>7}")

                # UN CHAMP DISCORD TIENT 1024 CARACTERES, et on ne tronque
                # pas : on DECOUPE. Un plafond en LIGNES est un pari sur la
                # longueur des noms — 22 lignes faisaient 1199 caracteres le
                # 05/09, et Discord refuse alors le MESSAGE ENTIER.
                _PLAFOND = 1024 - 10
                _pages, _cour, _taille = [], [], len(_e)
                for _nom, _adr, _a1, _a2, _a3 in _assoc:
                    _ligne = (f"{str(_nom)[:17]:<18}{_a1:>5}{_a2:>7}{_a3:>7}")
                    if _cour and _taille + 1 + len(_ligne) > _PLAFOND:
                        _pages.append(_cour)
                        _cour, _taille = [], len(_e)
                    _cour.append(_ligne)
                    _taille += 1 + len(_ligne)
                if _cour:
                    _pages.append(_cour)

                _restant = sum(len(x) for x in _pages[3:])
                for _i, _pg in enumerate(_pages[:3]):
                    if _i == 2 and _restant:
                        _pg = list(_pg) + [f"… +{_restant} de plus"]
                    _nb = min(len(_pages), 3)
                    _t1 = (f"👥 Subscribers — {_fr(_q_deb)}→{_fr(_q_fin)} "
                           f"vs {_fr(_p_deb)}→{_fr(_p_fin)}")
                    emb.add_field(
                        name=(_t1 if _i == 0 else f"👥 Subscribers ({_i + 1}/{_nb})"),
                        value="```\n" + _e + "\n" + "\n".join(_pg) + "\n```",
                        inline=False)

            # ACCROCHE A L'EMBED. Discord ignore les attributs qu'il ne
            # connait pas ; la page web y trouve de quoi faire de vraies
            # tables sans reanalyser du texte a chasse fixe.
            try:
                emb.donnees_clics = _donnees
            except Exception:
                pass

            _titre = (f"📋 Per link — {drapeau} {libelle} vs 🌍 global"
                      if pays_marche else "📋 Per link — 🌍 global")
            _blocs = _tableau()
            for i, b in enumerate(_blocs):
                # L'en-tete est repete partout : un bloc de suite sans titres
                # de colonnes n'est qu'une grille de chiffres.
                nom_champ = (_titre if i == 0
                             else f"{_titre} ({i + 1}/{len(_blocs)})")
                emb.add_field(name=nom_champ,
                              value=f"```\n{entete}\n{b}\n```",
                              inline=False)
        elif ids and not all_none and len(ids) > _MAX_PER_LIEN:
            emb.add_field(
                name="📋 Per link",
                value=f"_({len(ids)} links — too many to detail, totals above.)_",
                inline=False)

        # Pas de drapeau dans le PIED de page : Discord y rend les emoji en
        # toutes petites lettres, « 🇺🇸 US » se lisait « us US ».
        _quoi = (f"{libelle} vs global" if pays_marche else "all countries")
        emb.set_footer(
            text=f"Updated {_paris_now().strftime('%H:%M')} · every 30 min · "
                 f"{_quoi} · GetMySocial")
        return emb

    async def _post_or_update_report(self, guild_id: str):
        """Édite le message live de report du serveur, ou le poste (1re fois)."""
        cfg = _load_report_cfg()
        c = cfg.get(guild_id)
        if not c:
            return
        ch = self.bot.get_channel(int(c["channel_id"]))
        if ch is None:
            try:
                ch = await self.bot.fetch_channel(int(c["channel_id"]))
            except Exception:
                return
        # Un message existe deja -> on refuse un report vide, pour ne pas
        # remplacer de bons chiffres par « No data ».
        emb = await self._build_group_report(
            c, permettre_vide=not c.get("message_id"))
        if emb is None:
            return
        # Timer dynamique : Discord rend <t:…:R> en « dans X min » qui décompte
        # tout seul côté client (pas besoin d'éditer pour le voir bouger).
        ts = _next_demi_heure_unix()
        content = f"⏱️ **Prochaine mise à jour** <t:{ts}:R> (à <t:{ts}:t>)"
        mid = c.get("message_id")
        msg = None
        if mid:
            try:
                msg = await ch.fetch_message(int(mid))
            except discord.NotFound:
                msg = None  # message vraiment supprimé -> on en reposte un
            except Exception:
                return  # erreur transitoire (5xx/perm) -> on garde l'ancien
        if msg is not None:
            try:
                await msg.edit(content=content, embed=emb,
                               view=ReportRefreshView(self))
                return
            except discord.NotFound:
                pass  # supprimé entre fetch et edit -> repost ci-dessous
            except Exception as e:
                # 5xx / perte de perm / 429 : on NE reposte PAS (sinon doublons
                # de messages épinglés qui s'accumulent) -> on garde l'ancien.
                print(f"[reportclick] edit transitoire échoué, ancien gardé : {e}")
                return
        try:
            m = await ch.send(content=content, embed=emb,
                              view=ReportRefreshView(self))
            try:
                await m.pin()
            except Exception:
                pass
            # Re-load juste avant d'écrire : un /reportclick_off ou un autre
            # /setreportclick a pu modifier le fichier pendant le ch.send().
            # On ne touche QUE le message_id de CE serveur (pas d'écrasement
            # du snapshot complet, pas de résurrection d'un guild supprimé).
            fresh = _load_report_cfg()
            if guild_id in fresh:
                fresh[guild_id]["message_id"] = m.id
                _save_report_cfg(fresh)
        except Exception as e:
            print(f"[reportclick] post initial échoué : {e}")

    # ---------- Coeur ----------
    async def _links(self):
        import gms
        res = await asyncio.to_thread(_tag_call, gms.list_all_links)
        return (res.get("links") or []) if res.get("ok") else []

    async def _resolve_link(self, ch, links):
        """Trouve le lien GMS d'un VA pour son salon va-<handle> :
        1) cache  2) nom du lien va_@handle  3) SCAN de l'historique du salon
        (1re URL getmysocial.com/<shortcode> qui correspond à un vrai lien)."""
        import gms
        handle = _ch_handle(getattr(ch, "name", ""))
        if not handle:
            return None
        cache = _load_linkcache()
        # 1) cache
        sc = cache.get(handle)
        if sc:
            l = _match_shortcode(sc, links)
            if l:
                return l
        # 2) nom du lien va_@handle
        l = gms.find_link_for_handle(handle, links)
        if l:
            cache[handle] = (l.get("shortcode") or "").lower()
            _save_linkcache(cache)
            return l
        # 3) scan de l'historique du salon
        try:
            async for msg in ch.history(limit=400):
                blobs = [msg.content or ""]
                for emb in msg.embeds:
                    blobs += [emb.title or "", emb.description or "", emb.url or ""]
                    for f in emb.fields:
                        blobs.append(f.value or "")
                for b in blobs:
                    for m in _GMS_LINK_RE.finditer(b or ""):
                        hit = _match_shortcode(m.group(1), links)
                        if hit:
                            cache[handle] = (hit.get("shortcode") or "").lower()
                            _save_linkcache(cache)
                            return hit
        except Exception as e:
            print(f"[clickrecap] scan historique #{getattr(ch, 'name', '?')} : {e}")
        return None

    def _build_message(self, link, gms, ref_yesterday, today):
        """(content, embed) pour un VA. link=None -> message 'pas de lien' (sans réseau)."""
        if not link:
            return (NO_LINK_MSG, None)
        lid = link.get("id")
        shortcode = link.get("shortcode") or ""
        p_start, p_end = _pay_period(ref_yesterday)
        c_today = gms.clicks_for_link(lid, today.isoformat(), today.isoformat())
        c_yest = gms.clicks_for_link(lid, ref_yesterday.isoformat(), ref_yesterday.isoformat())
        c_period = gms.clicks_for_link(lid, p_start.isoformat(), ref_yesterday.isoformat())

        def fmt(v):
            return "—" if v is None else f"**{v}**"

        emb = discord.Embed(
            title="📊 Tes clics — getmysocial.com",
            description=f"🔗 {GMS_DOMAIN}/{shortcode}",
            color=discord.Color.green() if (c_yest or 0) > 0 else discord.Color.dark_grey(),
        )
        emb.add_field(name="📅 Hier", value=f"{fmt(c_yest)} clic(s)", inline=True)
        emb.add_field(name="🟢 Aujourd'hui", value=f"{fmt(c_today)} clic(s)", inline=True)
        emb.add_field(
            name=f"🗓️ Quinzaine ({_fr(p_start)}–{_fr(p_end)})",
            value=f"{fmt(c_period)} clic(s)",
            inline=False,
        )
        emb.set_footer(text="Récap automatique chaque nuit · GetMySocial")
        return (None, emb)

    async def _fetch_myclicks(self, lid, gms, today):
        """Récupère les 4 compteurs (aujourd'hui/hier/semaine/quinzaine) EN
        PARALLÈLE (au lieu de 4 appels réseau en série) + cache court.
        Retourne (c_today, c_yest, c_week, c_period) — chaque valeur int ou None."""
        ck = (lid, today.isoformat())
        cached = _CLICKS_CACHE.get(ck)
        if cached and (time.time() - cached[0]) < _CLICKS_TTL:
            return cached[1]
        yest = today - datetime.timedelta(days=1)
        week_start = today - datetime.timedelta(days=today.weekday())  # lundi
        p_start, _p_end = _pay_period(today)
        ranges = [
            (today, today),            # aujourd'hui
            (yest, yest),              # hier
            (week_start, today),       # cette semaine
            (p_start, today),          # quinzaine en cours
        ]
        vals = await asyncio.gather(*[
            asyncio.to_thread(_tag_call, gms.clicks_for_link, lid, s.isoformat(), e.isoformat())
            for (s, e) in ranges
        ])
        vals = tuple(vals)
        # On ne met en cache que les résultats exploitables (pas un échec total).
        if not all(v is None for v in vals):
            _CLICKS_CACHE[ck] = (time.time(), vals)
        return vals

    def _myclicks_embed(self, link, today, counts):
        """Construit l'embed à partir des compteurs déjà récupérés."""
        shortcode = link.get("shortcode") or ""
        week_start = today - datetime.timedelta(days=today.weekday())
        p_start, p_end = _pay_period(today)
        c_today, c_yest, c_week, c_period = counts
        all_none = all(v is None for v in counts)

        def fmt(v):
            return "—" if v is None else f"**{v}**"

        if all_none:
            color = discord.Color.orange()
        elif (c_today or 0) > 0 or (c_week or 0) > 0:
            color = discord.Color.green()
        else:
            color = discord.Color.dark_grey()
        emb = discord.Embed(
            title="📊 Tes clics — en direct",
            description=f"🔗 {GMS_DOMAIN}/{shortcode}",
            color=color,
        )
        emb.add_field(name="🟢 Aujourd'hui", value=f"{fmt(c_today)} clic(s)", inline=True)
        emb.add_field(name="📅 Hier", value=f"{fmt(c_yest)} clic(s)", inline=True)
        emb.add_field(name=f"🗓️ Cette semaine (depuis {_fr(week_start)})",
                      value=f"{fmt(c_week)} clic(s)", inline=False)
        emb.add_field(name=f"💰 Quinzaine ({_fr(p_start)}–{_fr(p_end)})",
                      value=f"{fmt(c_period)} clic(s)", inline=False)
        if all_none:
            emb.add_field(name="⚠️ Données indisponibles",
                          value="GetMySocial ne répond pas pour l'instant — réessaie dans un instant.",
                          inline=False)
        emb.set_footer(text="Mis à jour à l'instant · GetMySocial")
        return emb

    # ---------- Argent (paliers JOURNALIERS, taux unique par jour) ----------
    # 0-50 clics/jour -> 0.05$/clic | 51-100 -> 0.06$/clic | >100 -> 0.07$/clic.
    @staticmethod
    def _rate_for_clicks(clicks):
        c = clicks or 0
        if c <= 50:
            return 0.05
        if c <= 100:
            return 0.06
        return 0.07

    @classmethod
    def _money_for_clicks(cls, clicks):
        c = clicks or 0
        if c <= 0:
            return 0.0
        return c * cls._rate_for_clicks(c)

    def _tier_breakdown(self, dstats, s, e):
        """Repartit les jours de s..e par palier (selon les clics ELIGIBLES/jour) :
        {'deb':[jours,$], 'moy':[jours,$], 'exp':[jours,$]}. Ignore les jours a 0 elig."""
        out = {"deb": [0, 0.0], "moy": [0, 0.0], "exp": [0, 0.0]}
        d = s
        while d <= e:
            v = dstats.get(d.isoformat())
            d += datetime.timedelta(days=1)
            if v is None:
                continue
            elig = v[1] or 0
            if elig <= 0:
                continue
            money = self._money_for_clicks(elig)
            if elig <= 50:
                out["deb"][0] += 1
                out["deb"][1] += money
            elif elig <= 100:
                out["moy"][0] += 1
                out["moy"][1] += money
            else:
                out["exp"][0] += 1
                out["exp"][1] += money
        return out

    # Pays "eligibles" (qui paient bien) : l'argent se calcule sur CES clics.
    _ELIGIBLE_COUNTRIES = {"FR", "BE", "CH", "LU", "MC"}  # UE francophone

    async def _fetch_daily_stats(self, lid, gms, start, end):
        """Par JOUR de start..end -> {iso: (total, eligible)|None}. 'eligible' = clics
        des pays qui paient bien (FR/BE/CH/LU/MC). Meme appel API que le total
        (analytics_for_link) -> 0 cout reseau en plus. Cache PAR JOUR (partage entre
        'Mes clics' et le rapport de paie -> ne refetch que les jours manquants) +
        concurrence limitee a 6."""
        now = time.time()
        days, d = [], start
        while d <= end:
            days.append(d)
            d += datetime.timedelta(days=1)
        out, missing = {}, []
        for dd in days:
            c = _CLICKS_CACHE.get(("dstat1", lid, dd.isoformat()))
            if c and (now - c[0]) < _CLICKS_TTL:
                out[dd.isoformat()] = c[1]
            else:
                missing.append(dd)
        if missing:
            sem = asyncio.Semaphore(6)

            async def _one(dd):
                async with sem:
                    t, ctry = await asyncio.to_thread(
                        _tagged_analytics, gms, lid, dd.isoformat(), dd.isoformat())
                    return dd, t, ctry

            for dd, total, countries in await asyncio.gather(*[_one(x) for x in missing]):
                if total is None:
                    out[dd.isoformat()] = None
                    continue
                elig = sum(v for k, v in (countries or {}).items()
                           if k in self._ELIGIBLE_COUNTRIES)
                val = (total, elig)
                out[dd.isoformat()] = val
                _CLICKS_CACHE[("dstat1", lid, dd.isoformat())] = (now, val)
        return out

    def _myclicks_money_embed(self, link, today, dstats):
        """Embed clics + ARGENT. dstats[iso] = (total, eligible). L'argent est calcule
        sur les clics ELIGIBLES (FR/BE/CH/LU/MC), JOUR PAR JOUR (palier journalier)
        puis somme. On affiche aussi le total (tous pays)."""
        shortcode = link.get("shortcode") or ""
        week_start = today - datetime.timedelta(days=today.weekday())
        p_start, p_end = _pay_period(today)
        yest = today - datetime.timedelta(days=1)

        def _sum(s, e, idx):
            vals, d = [], s
            while d <= e:
                v = dstats.get(d.isoformat())
                vals.append(v[idx] if v is not None else None)
                d += datetime.timedelta(days=1)
            known = [x for x in vals if x is not None]
            return sum(known) if known else None

        def _money(s, e):
            total, d = 0.0, s
            while d <= e:
                v = dstats.get(d.isoformat())
                if v is not None:
                    total += self._money_for_clicks(v[1])  # v[1] = clics eligibles
                d += datetime.timedelta(days=1)
            return total

        vt = dstats.get(today.isoformat())
        vy = dstats.get(yest.isoformat())
        t_today, e_today = (vt if vt is not None else (None, None))
        t_yest, e_yest = (vy if vy is not None else (None, None))
        t_week, e_week = _sum(week_start, today, 0), _sum(week_start, today, 1)
        t_period, e_period = _sum(p_start, today, 0), _sum(p_start, today, 1)
        all_none = (not dstats) or all(v is None for v in dstats.values())

        m_today = self._money_for_clicks(e_today or 0)
        m_yest = self._money_for_clicks(e_yest or 0)
        m_week = _money(week_start, today)
        m_period = _money(p_start, today)

        if all_none:
            color = discord.Color.orange()
        elif (t_today or 0) > 0 or (t_period or 0) > 0:
            color = discord.Color.green()
        else:
            color = discord.Color.dark_grey()

        def fmt(v):
            return "—" if v is None else f"**{v}**"

        emb = discord.Embed(
            title="📊 Tes clics & ton argent — en direct",
            description=f"🔗 {GMS_DOMAIN}/{shortcode}\n"
                        "_L'argent est payé sur les **clics éligibles** "
                        "(🇫🇷 France · 🇨🇭 Suisse · 🇧🇪 Belgique · 🇱🇺 · 🇲🇨)._",
            color=color,
        )
        emb.add_field(
            name="🟢 Aujourd'hui",
            value=f"{fmt(t_today)} clic(s) · {fmt(e_today)} élig. → 💵 **${m_today:.2f}**",
            inline=True)
        emb.add_field(
            name="📅 Hier",
            value=f"{fmt(t_yest)} clic(s) · {fmt(e_yest)} élig. → 💵 **${m_yest:.2f}**",
            inline=True)
        emb.add_field(
            name=f"🗓️ Cette semaine (depuis {_fr(week_start)})",
            value=f"{fmt(t_week)} clic(s) · {fmt(e_week)} élig. → 💵 **${m_week:.2f}**",
            inline=False)
        emb.add_field(
            name=f"💰 Quinzaine EN COURS ({_fr(p_start)}–{_fr(p_end)})",
            value=f"{fmt(t_period)} clic(s) · {fmt(e_period)} élig. → 💵 **${m_period:.2f} gagnés**",
            inline=False)

        # Quinzaine PRECEDENTE (celle qu'on paie le jour de paie) + detail par palier.
        prev_end = p_start - datetime.timedelta(days=1)
        prev_start, _ = _pay_period(prev_end)
        n_prev = (prev_end - prev_start).days + 1
        prev_has = any(dstats.get((prev_start + datetime.timedelta(days=i)).isoformat()) is not None
                       for i in range(n_prev))
        if prev_has:
            pt = _sum(prev_start, prev_end, 0)
            pe = _sum(prev_start, prev_end, 1)
            pm = _money(prev_start, prev_end)
            emb.add_field(
                name=f"📅 Quinzaine PRÉCÉDENTE ({_fr(prev_start)}–{_fr(prev_end)})",
                value=f"{fmt(pt)} clic(s) · {fmt(pe)} élig. → 💵 **${pm:.2f}**",
                inline=False)
            tb = self._tier_breakdown(dstats, prev_start, prev_end)
            emb.add_field(
                name="💵 Détail paiement (période précédente)",
                value=(f"🥉 Débutant (≤50/j, $0.05) : **{tb['deb'][0]}** j → ${tb['deb'][1]:.2f}\n"
                       f"🥈 Moyen (51-100/j, $0.06) : **{tb['moy'][0]}** j → ${tb['moy'][1]:.2f}\n"
                       f"🥇 Expert (>100/j, $0.07) : **{tb['exp'][0]}** j → ${tb['exp'][1]:.2f}"),
                inline=False)

        et = e_today or 0
        if not all_none:
            if et <= 50:
                emb.add_field(name="🚀 Astuce",
                              value=f"Encore **{51 - et}** clic(s) **éligibles** aujourd'hui → **$0.06/clic** !",
                              inline=False)
            elif et <= 100:
                emb.add_field(name="🚀 Astuce",
                              value=f"Encore **{101 - et}** clic(s) **éligibles** aujourd'hui → **$0.07/clic** !",
                              inline=False)
            else:
                emb.add_field(name="🔥 Palier max",
                              value="Tu es au **meilleur taux : $0.07/clic éligible** aujourd'hui 💪",
                              inline=False)

        if all_none:
            emb.add_field(name="⚠️ Données indisponibles",
                          value="GetMySocial ne répond pas pour l'instant — réessaie dans un instant.",
                          inline=False)
        emb.set_footer(
            text="Payé sur clics éligibles/jour : ≤50 → $0.05 · 51-100 → $0.06 · >100 → $0.07 · GetMySocial")
        return emb

    async def _handle_myclicks(self, interaction: discord.Interaction):
        """Clic sur le bouton 'Mes clics' : calcule et montre en privé les clics
        du lien de CE salon va-, en temps réel."""
        await interaction.response.defer(ephemeral=True, thinking=True)
        import guild_features as gf
        if not gf.enabled(interaction.guild, "clics"):
            await interaction.followup.send("⚠️ Fonction désactivée sur ce serveur.", ephemeral=True)
            return
        try:
            import gms
        except Exception as e:
            await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
            return
        ch = interaction.channel
        if not _ch_handle(getattr(ch, "name", "")):
            await interaction.followup.send(
                "⚠️ Ce bouton fonctionne dans ton salon `va-…`.", ephemeral=True)
            return
        links = await self._links()
        link = await self._resolve_link(ch, links)
        if not link:
            await interaction.followup.send(NO_LINK_MSG, ephemeral=True)
            return
        today = _paris_now().date()
        p_start, _p_end = _pay_period(today)
        prev_end = p_start - datetime.timedelta(days=1)
        prev_start, _ = _pay_period(prev_end)
        week_start = today - datetime.timedelta(days=today.weekday())
        yest = today - datetime.timedelta(days=1)
        # On remonte jusqu'a la quinzaine PRECEDENTE (visible le jour de paie).
        start = min(prev_start, week_start, yest)
        dstats = await self._fetch_daily_stats(link.get("id"), gms, start, today)
        emb = self._myclicks_money_embed(link, today, dstats)
        try:
            await interaction.followup.send(embed=emb, ephemeral=True)
        except Exception as e:
            print(f"[clickrecap] followup myclicks échoué : {e}")

    async def _recap_channel(self, ch, links, gms, today, yest, skip_if_no_link=False):
        """Poste le récap dans un salon va-<handle>. Retourne 'sent'|'nolink'|'skip'.
        skip_if_no_link=True -> on ne poste RIEN si le salon n'a pas de lien
        (utilisé par le cron auto : on ne reporte que là où il y a un lien)."""
        handle = _ch_handle(ch.name) or ""
        if not handle:
            return "skip"
        link = await self._resolve_link(ch, links)  # nom va_@ OU scan historique du salon
        if link is None and skip_if_no_link:
            return "skip"  # pas de lien -> pas de message (anti-spam)
        content, emb = await asyncio.to_thread(_tag_call, self._build_message, link, gms, yest, today)
        try:
            if emb is not None:
                await ch.send(content=content, embed=emb)
            else:
                await ch.send(content)
            return "sent" if link else "nolink"
        except discord.Forbidden:
            return "skip"
        except Exception as e:
            print(f"[clickrecap] envoi #{ch.name} échoué : {e}")
            return "skip"

    async def _run_all(self):
        import gms
        links = await self._links()
        today = _paris_now().date()
        yest = today - datetime.timedelta(days=1)
        sent = nolink = 0
        import guild_features as gf
        for guild in self.bot.guilds:
            if not gf.enabled(guild, "clics"):
                continue  # serveur bridé sans la fonction clics
            for ch in guild.text_channels:
                if not _ch_handle(ch.name):
                    continue
                # Auto : on ne poste QUE dans les salons qui ont un lien (pas de spam).
                r = await self._recap_channel(ch, links, gms, today, yest, skip_if_no_link=True)
                if r == "sent":
                    sent += 1
                elif r == "nolink":
                    nolink += 1
                await asyncio.sleep(1.2)  # rate-limit friendly (Discord + GMS API)
            # MAJ auto des ⚙️ (lien 0 clic 3j) pour ce serveur
            try:
                await self._apply_gear_marks(guild)
            except Exception as e:
                print(f"[clickrecap] gear marks: {e}")
        print(f"[clickrecap] récap posté : {sent} avec lien, {nolink} sans lien")
        return sent, nolink

    async def _apply_gear_marks(self, guild):
        """Pose ⚙️ sur les salons va- dont le LIEN a fait 0 clic sur 3 jours
        (J-2..J), le retire sinon. Préserve le rond d'activité + le 🔗.
        Best-effort. Retourne un dict de compteurs, ou None si GMS indispo."""
        import gms
        try:
            lr = await asyncio.to_thread(_tag_call, gms.list_all_links)
        except Exception:
            return None
        if not isinstance(lr, dict) or not lr.get("ok"):
            return None
        link_list = lr.get("links") or []
        try:
            from cogs.user import _gms_exact_link
        except Exception:
            return None
        today = _paris_now().date()
        start3 = today - datetime.timedelta(days=2)  # 3 jours inclus : J-2, J-1, J
        st = {"gear": 0, "ungear": 0, "skip": 0, "fail": 0}
        for ch in guild.text_channels:
            h = _ch_handle(ch.name)
            if not h:
                continue
            link = _gms_exact_link(h, link_list)
            has_gear = False
            if link:
                c3 = await asyncio.to_thread(
                    _tag_call, gms.clicks_for_link, link.get("id"),
                    start3.isoformat(), today.isoformat())
                # 0 EXACT -> ⚙️. None = API indispo -> on ne marque PAS (évite un faux ⚙️).
                if c3 == 0:
                    has_gear = True
            target = _va_name_set_gear(ch.name, has_gear)
            cur = ch.name or ""
            # comparaison insensible au sélecteur de variante (évite une boucle)
            if not target or target.replace("️", "") == cur.replace("️", ""):
                st["skip"] += 1
                continue
            try:
                await ch.edit(name=target, reason="VA lien 0 clic 3j")
                st["gear" if has_gear else "ungear"] += 1
                await asyncio.sleep(2)  # anti rate-limit (rename de salon)
            except Exception:
                st["fail"] += 1
        return st

    # ---------- Commandes ----------
    @app_commands.command(
        name="marquerinactifs",
        description="[OWNER] Met ⚙️ sur les salons VA dont le lien a fait 0 clic en 3 jours",
    )
    async def marquerinactifs(self, interaction: discord.Interaction):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        await interaction.response.send_message(
            "🔄 Analyse des clics (3 derniers jours) en arrière-plan — je pose ⚙️ sur les liens "
            "à 0 clic, sans toucher au rond d'activité ni au 🔗. Je préviens ici à la fin.",
            ephemeral=True)
        _chan = interaction.channel
        _uid = interaction.user.id

        async def _run():
            st = await self._apply_gear_marks(guild)
            try:
                if st is None:
                    await _chan.send(
                        f"<@{_uid}> ⚠️ GetMySocial indisponible — réessaie dans un instant.")
                else:
                    await _chan.send(
                        f"✅ <@{_uid}> ⚙️ terminé : posé sur **{st['gear']}** salon(s) "
                        f"(lien + 0 clic/3j), retiré de {st['ungear']}, {st['skip']} inchangé(s)"
                        + (f", {st['fail']} échec(s)" if st['fail'] else "") + ".")
            except Exception:
                pass
        interaction.client.loop.create_task(_run())

    async def _pay_report(self, guild, gms, p_start, p_end):
        """Paie (clics ELIGIBLES) par VA sur p_start..p_end. Retourne une liste de
        (categorie, handle, eligibles, money) pour les VA a payer ($>0). Detection du
        lien par nom (va_@handle) pour rester rapide sur bcp de salons."""
        try:
            from cogs.user import _gms_exact_link
        except Exception:
            return []
        links = await self._links()
        rows = []
        for ch in guild.text_channels:
            h = _ch_handle(ch.name)
            if not h:
                continue
            link = _gms_exact_link(h, links)
            if not link:
                continue
            dstats = await self._fetch_daily_stats(link.get("id"), gms, p_start, p_end)
            elig = sum(v[1] for v in dstats.values() if v is not None)
            money = sum(self._money_for_clicks(v[1]) for v in dstats.values() if v is not None)
            # Jours dont la lecture GetMySocial a ECHOUE (429/timeout) : ils
            # etaient purement ignores -> montant sous-evalue SANS aucun signal.
            missing = sum(1 for v in dstats.values() if v is None)
            if money <= 0 and not missing:
                continue
            cat = ch.category.name if getattr(ch, "category", None) else "Sans catégorie"
            rows.append((cat, h, elig, money, missing))
        return rows

    @staticmethod
    def _format_pay_report(rows, title):
        """Groupe par categorie (triees par sous-total desc), VA tries par $ desc.
        Retourne une liste de lignes."""
        from collections import defaultdict
        by_cat = defaultdict(list)
        for _r in rows:
            cat, h, elig, money = _r[0], _r[1], _r[2], _r[3]
            miss = _r[4] if len(_r) > 4 else 0
            by_cat[cat].append((h, elig, money, miss))
        cat_total = {c: sum(m for _, _, m, _m in v) for c, v in by_cat.items()}
        grand = sum(cat_total.values())
        lines = [f"💸 **{title}**",
                 "_clics éligibles uniquement · triés du + payé au - payé_", ""]
        for c in sorted(by_cat.keys(), key=lambda x: -cat_total[x]):
            lines.append(f"📁 **{c}** — sous-total **${cat_total[c]:.2f}**")
            for h, elig, money, miss in sorted(by_cat[c], key=lambda x: -x[2]):
                warn = f"  ⚠️ {miss} j illisible(s) — montant INCOMPLET" if miss else ""
                lines.append(f"  • `va-{h}` — {elig} élig. → **${money:.2f}**{warn}")
            lines.append("")
        n_miss = sum((r[4] if len(r) > 4 else 0) for r in rows)
        lines.append(f"💰 **TOTAL À PAYER : ${grand:.2f}**  ·  {len(rows)} VA")
        if n_miss:
            lines.append(f"⚠️ **{n_miss} jour(s) non lus** (quota GMS) : le total est un MINIMUM. "
                         f"Relance la commande dans quelques minutes avant de payer.")
        return lines

    async def _run_pay_report(self, interaction, which):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        import gms
        today = _paris_now().date()
        p_start, p_end = _pay_period(today)
        if which == "previous":
            pe = p_start - datetime.timedelta(days=1)
            p_start, p_end = _pay_period(pe)
            title = f"RAPPORT DE PAIE — quinzaine PRÉCÉDENTE ({_fr(p_start)}–{_fr(p_end)})"
        else:
            p_end = today
            title = f"RAPPORT DE PAIE — quinzaine EN COURS ({_fr(p_start)}–{_fr(p_end)})"
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            rows = await self._pay_report(guild, gms, p_start, p_end)
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur rapport : {e}", ephemeral=True)
            return
        if not rows:
            await interaction.followup.send(
                f"💸 **{title}**\nAucun VA à payer (0 clic éligible sur la période).",
                ephemeral=True)
            return
        lines = self._format_pay_report(rows, title)
        buf = ""
        for ln in lines:
            if len(buf) + len(ln) + 1 > 1900:
                await interaction.followup.send(buf, ephemeral=True)
                buf = ""
            buf += ln + "\n"
        if buf.strip():
            await interaction.followup.send(buf, ephemeral=True)

    @app_commands.command(
        name="rapportpaie",
        description="[OWNER] Qui payer — quinzaine EN COURS (clics éligibles, par catégorie, trié par $)",
    )
    async def rapportpaie(self, interaction: discord.Interaction):
        await self._run_pay_report(interaction, "current")

    @app_commands.command(
        name="rapportpaieavant",
        description="[OWNER] Qui payer — quinzaine PRÉCÉDENTE (clics éligibles, par catégorie, trié par $)",
    )
    async def rapportpaieavant(self, interaction: discord.Interaction):
        await self._run_pay_report(interaction, "previous")

    @app_commands.command(
        name="recapclics",
        description="[OWNER] Poste le récap des clics dans CE salon (test), ou partout",
    )
    @app_commands.describe(
        salon="Salon va-… du VA → APERÇU privé de son récap (recommandé : choisis le salon directement)",
        va="OU le pseudo exact (ce qui suit « va- » dans le nom du salon — PAS le nom affiché Discord)",
        partout="true = lance le récap dans TOUS les salons va- (comme le cron de minuit)",
    )
    async def recapclics(self, interaction: discord.Interaction,
                          salon: discord.TextChannel = None, va: str = None, partout: bool = False):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            import gms
        except Exception as e:
            await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
            return
        # Aperçu CIBLÉ (par salon précis, ou pseudo) — montré en privé, rien posté chez le VA
        target_handle = None
        if salon is not None and _ch_handle(getattr(salon, "name", "")):
            target_handle = _ch_handle(salon.name)
        elif va:
            h = va.strip().lstrip("@")
            if h.lower().startswith("va-"):
                h = h[3:]
            target_handle = h
        if target_handle:
            links = await self._links()
            # retrouve le salon va-<handle> pour pouvoir scanner son historique
            tch = salon
            if tch is None:
                for g in self.bot.guilds:
                    tch = discord.utils.find(lambda c: _ch_handle(c.name) == target_handle, g.text_channels)
                    if tch is not None:
                        break
            if tch is not None:
                link = await self._resolve_link(tch, links)
            else:
                link = gms.find_link_for_handle(target_handle, links)
            today = _paris_now().date()
            yest = today - datetime.timedelta(days=1)
            if link:
                _c, emb = await asyncio.to_thread(self._build_message, link, gms, yest, today)
                via = " · 🔎 lien détecté dans l'historique du salon" if not gms.find_link_for_handle(target_handle, links) else ""
                await interaction.followup.send(
                    content=f"👁️ Aperçu — **va-{target_handle}** (test, non posté chez le VA){via} :",
                    embed=emb, ephemeral=True)
            else:
                va_names = sorted({(l.get("display_name") or "") for l in links
                                   if (l.get("display_name") or "").lower().startswith("va_@")})
                hint = ("\n\n**Liens `va_@…` existants sur GMS :**\n" + "\n".join("• `" + n + "`" for n in va_names[:25])) \
                    if va_names else "\n\n(aucun lien nommé `va_@…` sur GMS pour l'instant)"
                await interaction.followup.send(
                    f"👁️ **va-{target_handle}** : ❌ aucun lien `va_@{target_handle}` trouvé sur GMS.\n"
                    f"💡 Le récap relie le VA à son lien par le **nom du lien** `va_@<pseudo>` "
                    f"(le pseudo = ce qui suit `va-` dans le salon, **pas** le nom affiché Discord). "
                    f"Si son lien existe sous un autre nom, régénère-le via `/gmslink` **dans son salon** pour qu'il soit renommé `va_@{target_handle}`.{hint}",
                    ephemeral=True)
            return
        if partout:
            sent, nolink = await self._run_all()
            await interaction.followup.send(
                f"✅ Récap envoyé : **{sent}** salon(s) avec lien · **{nolink}** sans lien.",
                ephemeral=True,
            )
            return
        ch = interaction.channel
        if not _ch_handle(getattr(ch, "name", "")):
            await interaction.followup.send(
                "Lance cette commande dans un salon `va-<pseudo>` (ou `/recapclics partout:true`).",
                ephemeral=True,
            )
            return
        links = await self._links()
        today = _paris_now().date()
        yest = today - datetime.timedelta(days=1)
        r = await self._recap_channel(ch, links, gms, today, yest)
        msg = {"sent": "✅ Récap posté ici.", "nolink": "✅ Posté (ce VA n'a pas de lien).",
               "skip": "⚠️ Impossible de poster ici."}.get(r, "?")
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(
        name="clicsbouton",
        description="[OWNER] Pose le bouton '📊 Mes clics' dans CE salon",
    )
    async def clicsbouton(self, interaction: discord.Interaction):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        ch = interaction.channel
        if not _ch_handle(getattr(ch, "name", "")):
            await interaction.followup.send(
                "Lance ça dans un salon `va-<pseudo>` (ou `/clicsboutontous` pour tous).",
                ephemeral=True)
            return
        try:
            msg = await ch.send(
                "📊 **Tes clics en direct** — clique pour voir tes clics "
                "(aujourd'hui, hier, cette semaine, quinzaine).",
                view=MyClicksView(self),
            )
            try:
                await msg.pin()
            except Exception:
                pass
            await interaction.followup.send("✅ Bouton « Mes clics » posé ici.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Échec : {e}", ephemeral=True)

    @app_commands.command(
        name="clicsboutontous",
        description="[OWNER] Pose le bouton '📊 Mes clics' dans TOUS les salons va- (sans rien à remplir)",
    )
    async def clicsboutontous(self, interaction: discord.Interaction):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        n = 0
        fails = []
        for guild in self.bot.guilds:
            for ch in guild.text_channels:
                if not _ch_handle(ch.name):
                    continue
                try:
                    msg = await ch.send(
                        "📊 **Tes clics en direct** — clique pour voir tes clics "
                        "(aujourd'hui, hier, cette semaine, quinzaine).",
                        view=MyClicksView(self),
                    )
                    try:
                        await msg.pin()
                    except Exception:
                        pass
                    n += 1
                except discord.Forbidden:
                    fails.append(f"{ch.name} (pas la permission)")
                except Exception as e:
                    fails.append(f"{ch.name} ({type(e).__name__})")
                    print(f"[clickrecap] bouton #{getattr(ch, 'name', '?')} : {e}")
                await asyncio.sleep(1.0)  # rate-limit friendly (succès ET échec)
        msg = f"✅ Bouton « Mes clics » posé dans **{n}** salon(s) va-."
        if fails:
            msg += f"\n⚠️ **{len(fails)}** échec(s) : " + ", ".join(fails[:10])
            if len(fails) > 10:
                msg += f" … (+{len(fails) - 10})"
        await interaction.followup.send(msg[:1900], ephemeral=True)

    @app_commands.command(
        name="recapclicstous",
        description="[OWNER] Envoie MAINTENANT le récap des clics dans TOUS les salons va- (sans rien à remplir)",
    )
    async def recapclicstous(self, interaction: discord.Interaction):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            import gms  # noqa: F401  (vérifie juste que le module est dispo)
        except Exception as e:
            await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
            return
        sent, nolink = await self._run_all()
        await interaction.followup.send(
            f"✅ Récap des clics envoyé dans **{sent}** salon(s) (ceux qui ont un lien). "
            f"Les salons sans lien sont ignorés.",
            ephemeral=True,
        )

    @app_commands.command(
        name="recapclics_auto",
        description="[OWNER] Active/désactive le récap clics AUTOMATIQUE de chaque nuit",
    )
    @app_commands.describe(actif="true = récap auto chaque nuit dans tous les salons va- · false = manuel seulement")
    async def recapclics_auto(self, interaction: discord.Interaction, actif: bool):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        _set_auto(actif)
        if actif and not self.daily_recap.is_running():
            self.daily_recap.start()
        elif not actif and self.daily_recap.is_running():
            self.daily_recap.cancel()
        await interaction.response.send_message(
            ("✅ Récap clics **automatique activé** (chaque nuit ~minuit, dans chaque salon va- **qui a un lien** — les autres sont ignorés)."
             if actif else
             "🛑 Récap clics automatique **désactivé**. Utilise `/recapclics` pour tester à la main."),
            ephemeral=True,
        )


    @app_commands.command(
        name="setreportclick",
        description="[OWNER] Report des clics d'un groupe GMS dans CE salon (maj 30 min)",
    )
    @app_commands.describe(
        groupe="Workspace GetMySocial a suivre (choisis dans la liste)",
        marche="Quels clics mettre en avant : fr, us, ou tout (défaut : tout)",
    )
    @app_commands.choices(marche=[
        app_commands.Choice(name="🇫🇷 France (FR/BE/CH/LU/MC)", value="fr"),
        app_commands.Choice(name="🇺🇸 États-Unis", value="us"),
        app_commands.Choice(name="🌍 Tous pays", value="tout"),
    ])
    @app_commands.autocomplete(groupe=_ac_groupe)
    async def setreportclick(self, interaction: discord.Interaction,
                             groupe: str = None, marche: str = None):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            import gms
        except Exception as e:
            await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
            return
        data, err = await self._resolve_report_group(interaction.guild, groupe)
        if err:
            await interaction.followup.send(err, ephemeral=True)
            return
        gid = str(interaction.guild.id)
        cid = interaction.channel.id
        cfg = _load_report_cfg()
        cle = _cle_report(gid, cid)
        marche_cle = (marche or "tout").strip().lower()
        if marche_cle not in MARCHES:
            marche_cle = "tout"
        new_c = {
            "channel_id": cid, "team_id": data["team_id"],
            "group_id": data["group_id"], "identity": data["identity"],
            "group_name": data["group_name"], "marche": marche_cle,
            # Sans ce drapeau, un report de workspace repartirait chercher un
            # groupe au premier rafraichissement et ne trouverait plus rien.
            "tout": bool(data.get("tout")),
        }
        # Re-lancer dans le MÊME salon : on réutilise le message existant (sinon
        # on poste un doublon). On regarde AUSSI l'ancienne clé, rangée sous le
        # seul identifiant du serveur — sans ça, une config d'avant le
        # multi-salon repartirait sur un second message dans le même salon.
        for ancienne in (cle, gid):
            old = cfg.get(ancienne)
            if (isinstance(old, dict) and str(old.get("channel_id")) == str(cid)
                    and old.get("message_id")):
                new_c["message_id"] = old["message_id"]
                if ancienne != cle:
                    cfg.pop(ancienne, None)   # migrée vers la clé par salon
                break
        cfg[cle] = new_c
        _save_report_cfg(cfg)
        gid = cle          # tout ce qui suit publie ce report-là
        self._report_creneau = _creneau_30(_paris_now())  # evite un double post immediat par la boucle
        await self._post_or_update_report(gid)
        await interaction.followup.send(
            f"✅ Report des clics **{data['group_name']}** {_marche_de(new_c)[2]} "
            f"(workspace **{data['ws']}**, "
            f"{data['n']} lien(s)) activé dans {interaction.channel.mention}.\n"
            f"Message **édité toutes les 30 min** (aujourd'hui / hier / semaine / période 1–15 / 16–fin), "
            f"et un bouton **Rafraîchir** que n'importe qui peut cliquer. "
            f"Snapshot à la demande : `/reportclicknow`. Désactive : `/reportclick_off`.{data['ambig']}",
            ephemeral=True)

    @app_commands.command(
        name="reportclick_off",
        description="[OWNER] Désactive le report horaire des clics sur CE serveur",
    )
    async def reportclick_off(self, interaction: discord.Interaction):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        cfg = _load_report_cfg()
        gid = str(interaction.guild.id)
        cid = getattr(interaction.channel, "id", None)
        # On coupe le report DE CE SALON. Deux reports peuvent coexister sur un
        # meme serveur (un FR, un US) : couper le serveur entier en tuerait un
        # que personne n aurait demande a arreter.
        vises = [cle for cle, c in _reports_configures(cfg)
                 if str(c.get("channel_id")) == str(cid)]
        if not vises and gid in cfg:
            vises = [gid]        # ancienne config, rangee sous le serveur seul
        if vises:
            for cle in vises:
                cfg.pop(cle, None)
            _save_report_cfg(cfg)
            await interaction.response.send_message(
                "🛑 Report des clics désactivé dans ce salon.", ephemeral=True)
        else:
            restants = len(_reports_configures(cfg))
            await interaction.response.send_message(
                "ℹ️ Aucun report configuré dans ce salon."
                + (f" ({restants} ailleurs sur ce serveur.)" if restants else ""),
                ephemeral=True)

    async def _resolve_report_group(self, guild, groupe):
        """Résout la cible d'un report de clics. Retourne (data, None) si OK —
        data = {team_id, identity, group_id, group_name, ws, ambig, n} —, sinon
        (None, message_erreur). Partagé par /setreportclick et /reportclicknow."""
        import gms
        import guild_features as gf
        name = (groupe or gf.get_server_identity(guild) or "").strip()
        if not name:
            return None, ("⚠️ Précise le groupe : `groupe:Hybride` — ou définis l'identité "
                          "du serveur (`/setidentite`).")

        # Valeur venue de l'autocomplétion : un identifiant de WORKSPACE
        # (« tm_… »). Le report couvre alors TOUS ses liens, sans regarder les
        # groupes — c'est ce que veut le propriétaire : un salon par workspace,
        # pas un par groupe (il y en a 54).
        if name.startswith("tm_") and "|" not in name:
            tid = name.strip()
            libelle = tid
            for e in (_ESPACES_CACHE.get("espaces") or []):
                if str(e.get("id")) == tid:
                    libelle = e.get("name") or tid
                    break
            ids = await asyncio.to_thread(gms.report_link_ids, tid, None, None,
                                          True)
            if ids is None:
                return None, ("❌ Impossible de lister les liens de ce workspace "
                              "(GetMySocial injoignable). Réessaie dans un instant.")
            return {"team_id": tid, "identity": None, "group_id": None,
                    "tout": True, "group_name": libelle, "ws": libelle,
                    "ambig": "", "n": len(ids)}, None

        # Le NOM d'un workspace, tape a la main plutot que choisi dans la liste.
        # Sans ce repli, « marche francais » partait chercher un GROUPE de ce
        # nom — qui n'existe pas, c'est un workspace — et repondait
        # « introuvable » alors que la liste le proposait juste au-dessus.
        _espaces = await _espaces_gms()
        _cherche = name.strip().lower()
        for e in _espaces:
            if str(e.get("name") or "").strip().lower() == _cherche:
                tid = str(e["id"])
                ids = await asyncio.to_thread(gms.report_link_ids, tid, None,
                                              None, True)
                if ids is None:
                    return None, ("❌ Impossible de lister les liens de "
                                  f"**{e['name']}** (GetMySocial injoignable). "
                                  "Réessaie dans un instant.")
                return {"team_id": tid, "identity": None, "group_id": None,
                        "tout": True, "group_name": e["name"], "ws": e["name"],
                        "ambig": "", "n": len(ids)}, None
        ident = name.lower()
        group_name = name[0].upper() + name[1:]  # hybride -> Hybride (groupes capitalisés)

        def _ws_label(tid):
            if tid == getattr(gms, "THREADS_US_TID", None):
                return "Threads US"
            if tid == getattr(gms, "MARCHE_FRANCAIS_TID", None):
                return "marché FR"
            return str(tid)

        team_id = group_id = identity = None
        ambig = ""
        suffix = getattr(gms, "_SHORTCODE_SUFFIX", {}).get(ident)
        pref_team = getattr(gms, "IDENTITY_TEAM", {}).get(ident)
        if suffix and pref_team:
            # Identité connue (ex: hybride) -> workspace préféré + énumération par
            # suffixe `…secret` via la CLÉ API (insensible à l'expiration du cookie).
            team_id, identity = pref_team, ident
        else:
            # Groupe arbitraire -> résolution par nom de groupe (cookie de session).
            order = list(getattr(gms, "KNOWN_TEAMS", ()))
            if pref_team and pref_team in order:
                order.remove(pref_team)
                order.insert(0, pref_team)
            matches = []
            for tid in order:
                g = await asyncio.to_thread(gms.group_id_by_name, tid, group_name)
                if g:
                    matches.append((tid, g))
            if not matches:
                # On NOMME ce qui existe au lieu de laisser chercher : un
                # « introuvable » sec envoie soupçonner le cookie alors que le
                # nom tapé n'est simplement pas celui d'un groupe.
                _dispo = ", ".join(f"**{e['name']}**" for e in _espaces[:8])
                return None, (
                    f"❌ « **{group_name}** » ne correspond à aucun groupe.\n"
                    + (f"Workspaces disponibles : {_dispo}.\n" if _dispo else "")
                    + "Choisis-en un **dans la liste** du champ `groupe` plutôt "
                      "que de le taper.\n"
                      "_(Si tu visais bien un groupe et non un workspace, le "
                      "cookie de session GMS du VPS est peut-être expiré.)_")
            team_id, group_id = matches[0]
            if len(matches) > 1:
                ambig = (f"\n⚠️ Un groupe « {group_name} » existe dans **{len(matches)}** workspaces "
                         f"— j'ai pris **{_ws_label(team_id)}**.")
        ids = await asyncio.to_thread(gms.report_link_ids, team_id, identity, group_id)
        if ids is None:
            return None, ("❌ Impossible de lister les liens (API/cookie GMS injoignable). "
                          "Réessaie dans un instant.")
        return {"team_id": team_id, "identity": identity, "group_id": group_id,
                "group_name": group_name, "ws": _ws_label(team_id),
                "ambig": ambig, "n": len(ids)}, None

    @app_commands.command(
        name="reportclicknow",
        description="[OWNER] Poste MAINTENANT un report complet des clics (snapshot)",
    )
    @app_commands.describe(groupe="Workspace GetMySocial a suivre (choisis dans la liste)")
    @app_commands.autocomplete(groupe=_ac_groupe)
    async def reportclicknow(self, interaction: discord.Interaction, groupe: str = None):
        if not await self._is_owner(interaction.user.id):
            await interaction.response.send_message("Owner only.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            import gms  # noqa: F401 (vérifie juste que le module est dispo)
        except Exception as e:
            await interaction.followup.send(f"❌ Module GMS indispo : {e}", ephemeral=True)
            return
        data, err = await self._resolve_report_group(interaction.guild, groupe)
        if err:
            await interaction.followup.send(err, ephemeral=True)
            return
        emb = await self._build_group_report({
            "team_id": data["team_id"], "group_id": data["group_id"],
            "identity": data["identity"], "group_name": data["group_name"],
        })
        if emb is None:
            await interaction.followup.send(
                "❌ GMS injoignable pour l'instant — réessaie dans un instant.", ephemeral=True)
            return
        try:
            await interaction.channel.send(embed=emb)
        except Exception as e:
            await interaction.followup.send(f"❌ Envoi impossible ici : {e}", ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Report complet **{data['group_name']}** posté ici ({data['n']} lien(s)).{data['ambig']}",
            ephemeral=True)


async def setup(bot):
    await bot.add_cog(ClickRecap(bot))
