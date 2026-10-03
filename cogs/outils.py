# -*- coding: utf-8 -*-
"""La categorie « 🧰 Outils » du serveur FR : un salon par outil, commun a tous.

POURQUOI (demande du proprietaire, 03/10/2026)
    Les outils des dossiers US (spoofer, telechargement, numeros) sur Va IG. Un
    dossier par VA y coute 6 salons : 160 VA = 960 salons, Discord plafonne
    a 500 par serveur. Le proprietaire : « le meme channel pour tout le
    monde [...] chacun ne voit pas ce qu'il fait a l'interieur ».

CE QUI RESTE PRIVE
    Le panneau est commun. Un clic recoit sa reponse en ephemere (seul le VA
    la voit) et les FICHIERS partent dans SON salon va- (users.json) : un
    ephemere disparait au rechargement de Discord, le VA perdrait ce qu'il
    vient de demander. Sans salon a lui sur ce serveur, l'outil refuse :
    livrer dans le salon commun montrerait ses fichiers a tout le monde.

CE QUI N'EST PAS ICI
    Aucune commande slash : le bot principal en a 100 sur 100. Les panneaux
    et leurs boutons restent ceux de cogs/spoofer.py et cogs/telechargement.py,
    qui demandent a ce module ou livrer (salon_perso).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import safe_json

import discord
from discord.ext import commands, tasks

#: Les serveurs qui ont la categorie Outils : Va IG (marche FR). Le serveur
#: US garde ses dossiers par VA.
SERVEURS = frozenset({1505418484052394004})

CATEGORIE = "🧰 Outils"
#: Les salons communs (categorie Outils) : plus crees ni entretenus depuis que
#: les outils sont sur la ligne du ticket (proprietaire, 03/10/2026 : « ca du
#: coup pas besoin d'avoir »). Faux : le bot ne recree plus rien ; des salons
#: deja la continuent de marcher tant qu'on ne les supprime pas.
SALONS_COMMUNS = False
#: (cle, nom a la creation). La cle est le nom sans decor : le proprietaire
#: renomme les salons a la main (« ⬇️・all-download »), un salon renomme doit
#: rester reconnu.
#: « ・ » et pas « - » dans le nom du salon des numeros : « 📱-numero-mail »
#: finirait par « -numero-mail », le suffixe des salons PRIVES d'un VA US, et
#: /panelnumeroall le cacherait a tout le monde.
SALONS = (("spoofer", "📤・spoofer"), ("download", "⬇️・download"),
          ("numero-mail", "📱・numero-mail"))


def _norm(nom) -> str:
    try:
        from cogs.welcome import nom_sans_decor
        return nom_sans_decor(nom)
    except Exception:
        return str(nom or "").strip().lower()


def _serveur_outils(guilde) -> bool:
    return int(getattr(guilde, "id", 0) or 0) in SERVEURS


#: Le nom public : les cogs spoofer, telechargement, numeros et user s'en servent.
serveur_outils = _serveur_outils


def est_categorie_outils(cat) -> bool:
    return (cat is not None and _serveur_outils(getattr(cat, "guild", None))
            and _norm(getattr(cat, "name", "")) == _norm(CATEGORIE))


def est_salon_outils(canal, outil: str = None) -> bool:
    """Un salon commun de la categorie Outils (de cet outil, si precise)."""
    if canal is None or not est_categorie_outils(getattr(canal, "category", None)):
        return False
    return outil is None or _norm(getattr(canal, "name", "")) == outil


def salon_perso(guilde, membre):
    """Le salon va- du membre sur ce serveur (users.json), ou None.

    Jamais un salon de la categorie Outils : y livrer rendrait public ce que
    le VA vient de demander."""
    if guilde is None or membre is None:
        return None
    try:
        from cogs.welcome import load_users
        entree = (load_users() or {}).get(str(getattr(membre, "id", "")))
        cid = int((entree or {}).get("channel_id") or 0)
    except Exception as e:                                   # noqa: BLE001
        print(f"[outils] users.json illisible : {type(e).__name__}: {e}")
        return None
    canal = guilde.get_channel(cid) if cid else None
    if not isinstance(canal, discord.TextChannel) or est_salon_outils(canal):
        return None
    return canal


def _tickets() -> set:
    """Les salons va- des VA (users.json), toutes guildes confondues."""
    try:
        from cogs.welcome import load_users
        return {int((e or {}).get("channel_id") or 0)
                for e in (load_users() or {}).values() if isinstance(e, dict)}
    except Exception as e:                                   # noqa: BLE001
        print(f"[outils] users.json illisible : {type(e).__name__}: {e}")
        return set()


def ou_livrer(canal, membre):
    """Ou livrer un outil lance sur le serveur FR -- LA regle des trois outils.

    Depuis le ticket d'un VA (les boutons de son menu) : ce ticket, meme
    clique par un manager qui l'aide. Ailleurs -- le salon commun, un menu
    central, un salon public : le ticket du membre, ou None s'il n'en a pas.
    Jamais un salon que d'autres voient."""
    cible = _ticket_vise(canal, membre)
    if cible is not None and not _ticket_permis(cible):
        return None
    return cible


def _ticket_vise(canal, membre):
    """Le ticket ou livrer, identite non regardee (ou_livrer, refus)."""
    if (canal is not None and not est_salon_outils(canal)
            and int(getattr(canal, "id", 0) or 0) in _tickets()):
        return canal
    return salon_perso(getattr(canal, "guild", None), membre)


#: Les MODELS dont les VA ont les outils. Proprietaire, 03/10/2026 : « les
#: meufs de OF Julia, Amelia, Lola [...] uniquement, on fait par demande » ;
#: « c'est uniquement models, pas d'identite » -- Emma, Sarah et Alicia, les
#: identites du serveur FR, n'en ont pas. Dans le code, une model est une
#: identite (users.json « identity », sa categorie de tickets).
MODELS_OUTILS = frozenset({"julia", "amelia", "lola"})


def identite_permise(identite) -> bool:
    return str(identite or "").strip().lower() in MODELS_OUTILS


def identite_du_ticket(canal) -> str:
    """L'identite du VA a qui est ce ticket (users.json), ou ""."""
    try:
        from cogs.welcome import load_users
        cid = int(getattr(canal, "id", 0) or 0)
        for e in (load_users() or {}).values():
            if isinstance(e, dict) and int(e.get("channel_id") or 0) == cid:
                return str(e.get("identity") or "")
    except Exception as e:                                   # noqa: BLE001
        print(f"[outils] users.json illisible : {type(e).__name__}: {e}")
    return ""


#: La phrase du refus, la meme pour tous les outils.
SANS_SALON = "Tu n'as pas de salon VA sur ce serveur : rien ne peut t'être livré."
PAS_ENCORE = "🔒 Les outils ne sont pas encore ouverts pour ta model."


def models_du_ticket(canal) -> list:
    """Les models du VA a qui est ce ticket : celle de sa fiche, plus celles
    de ses roles (serveur FR, plusieurs roles = plusieurs models)."""
    out = []
    ident = identite_du_ticket(canal)
    try:
        from cogs.welcome import load_users, models_du_membre
        cid = int(getattr(canal, "id", 0) or 0)
        uid = next((u for u, e in (load_users() or {}).items()
                    if isinstance(e, dict) and int(e.get("channel_id") or 0) == cid), None)
        g = getattr(canal, "guild", None)
        m = g.get_member(int(uid)) if (g is not None and uid) else None
        if m is not None:
            # serveur FR : les roles font foi (sans role, plus d'outils)
            return models_du_membre(m)
    except Exception as e:                                   # noqa: BLE001
        print(f"[outils] models du ticket : {type(e).__name__}: {e}")
    if ident:
        out.append(ident.strip().lower())
    return out


def _ticket_permis(cible) -> bool:
    return any(identite_permise(m) for m in models_du_ticket(cible))


def refus(canal, membre) -> str:
    """"" si l'outil peut servir ce clic, sinon la phrase a dire au VA.
    Chaque outil la dit AVANT de travailler : un spoof ou un numero ne se
    paie pas pour etre refuse a la livraison."""
    cible = _ticket_vise(canal, membre)
    if cible is None:
        return SANS_SALON
    if not _ticket_permis(cible):
        return PAS_ENCORE
    return ""


def _role_verifie(guilde):
    """✅ Verifie si le serveur exige la verification (verif_discord, « porte »)."""
    try:
        import verif_discord as vd
        c = vd.serveur(str(guilde.id)) or {}
        if c.get("porte") and c.get("role_verifie"):
            return guilde.get_role(int(c["role_verifie"]))
    except Exception as e:                                   # noqa: BLE001
        print(f"[outils] verification illisible : {type(e).__name__}: {e}")
    return None


def _droits(guilde, moi):
    """Tout le monde voit, personne n'ecrit ; le bot pose ses panneaux. Sur
    un serveur a verification, « tout le monde » = ✅ Verifie : un nouveau
    non verifie ne voit que le salon de verification."""
    voir = discord.PermissionOverwrite(
        view_channel=True, read_message_history=True, send_messages=False,
        add_reactions=False, create_public_threads=False,
        create_private_threads=False, send_messages_in_threads=False)
    verifie = _role_verifie(guilde)
    if verifie is not None:
        droits = {guilde.default_role: discord.PermissionOverwrite(view_channel=False),
                  verifie: voir}
    else:
        droits = {guilde.default_role: voir}
    if moi is not None:
        droits[moi] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            manage_messages=True, embed_links=True, attach_files=True)
    return droits


#: Les categories d'information du serveur FR, copiees de Twitter le
#: 03/10/2026 (« |<<<<< ACCUEIL >>>>>| », « <<<🔔NOTIFICATION >>> ») : leurs
#: salons sont pour tous les VA (✅ Verifie).
CATEGORIES_INFO = ("accueil", "notification")


def salons_info(guilde) -> list:
    return [c for c in (getattr(guilde, "text_channels", None) or [])
            if getattr(c, "category", None) is not None
            and any(k in str(c.category.name).lower() for k in CATEGORIES_INFO)]


#: Le reglage du site « identites scrapees » (web_upload.SCRAPE_IDENTS_FILE) et
#: la trace de l'activation des models FR, faite UNE fois : si le proprietaire
#: en coupe une ensuite depuis le site, le bot ne la rallume pas.
_SCRAPE_IDENTS = Path(__file__).resolve().parent.parent / "data" / "scrape_identites.json"
_SCRAPE_FR_FAIT = Path(__file__).resolve().parent.parent / "data" / "scrape_models_fr.json"


def activer_scrape_models_fr(models) -> list:
    """Ajoute les models FR aux identites scrapees (proprietaire, 03/10/2026 :
    bangers FR, « oui, les 6 models »). Sans fichier de reglage, tout est deja
    scrape : rien a faire. Rend les models ajoutees."""
    if (safe_json.load(_SCRAPE_FR_FAIT, default={}) or {}).get("fait"):
        return []
    d = safe_json.load(_SCRAPE_IDENTS, default=None)
    ajoutees = []
    if isinstance(d, dict) and isinstance(d.get("actives"), list):
        actives = [str(x).strip().lower() for x in d["actives"]]
        if "*" not in actives:
            ajoutees = [m for m in models if m and m not in actives]
            if ajoutees:
                d["actives"] = actives + ajoutees
                if not safe_json.write(_SCRAPE_IDENTS, d, indent=1):
                    print("[outils] identites scrapees non ecrites : on reessaiera", flush=True)
                    return []
    safe_json.write(_SCRAPE_FR_FAIT, {"fait": int(__import__("time").time()),
                                      "ajoutees": ajoutees}, indent=1)
    if ajoutees:
        print(f"[outils] scrape Instagram active pour {ajoutees}", flush=True)
    return ajoutees


def _rendre_visible_aux_futurs_va(ids) -> None:
    """Les salons s'ajoutent aux « salons d'aide » de l'isolation : sinon un
    VA qui arrive est masque de TOUS les salons (anonymat) et ne verrait
    jamais les outils."""
    try:
        from cogs.welcome import load_welcome_config, save_welcome_config
        cfg = load_welcome_config()
        deja = [int(x) for x in cfg.get("extra_visible_channel_ids", []) or []]
        manquants = [i for i in ids if i not in deja]
        if manquants:
            cfg["extra_visible_channel_ids"] = deja + manquants
            save_welcome_config(cfg)
            print(f"[outils] {len(manquants)} salon(s) ajoute(s) aux salons visibles des VA")
    except Exception as e:                                   # noqa: BLE001
        print(f"[outils] salons non ajoutes a l'isolation : {type(e).__name__}: {e}")


#: Reset des tickets du serveur FR demande au bot (proprietaire, 03/10/2026 :
#: « reset », « oui, lance-le » -- il ne peut pas taper /resettickets a ma
#: place). Fait UNE fois : la trace est ecrite AVANT de commencer. Coupe par
#: un redemarrage (chaque push en provoque un), il REPREND la ou il en etait
#: au lieu de tout refaire -- trois reprises au plus, pour qu'un reset qui
#: plante a chaque fois ne tourne pas indefiniment.
RESET_DEMANDE = "2026-10-03"
_RESET_FAIT = Path(__file__).resolve().parent.parent / "data" / "reset_tickets_fr.json"

#: Essai de lien demande au bot (proprietaire, 03/10/2026 : « essaie avec
#: Emma, je crois que je n'ai plus l'abo MyPuls des autres, vas-y teste ») :
#: le tracking MYM d'Amelia revenait HTTP 400. UNE fois, trace ecrite avant ;
#: le resultat, et les createrices que MyPuls donne au compte, vont dans le
#: ticket de Mario, ou le proprietaire teste.
ESSAI_LIEN = {"id": "2026-10-03-emma", "uid": 479005370438778891,
              "pseudo": "marioofm", "model": "emma"}
_ESSAI_FAIT = Path(__file__).resolve().parent.parent / "data" / "essai_liens_fr.json"

#: Nettoyage des tickets demande au bot (proprietaire, 03/10/2026 : « clean
#: toutes les conv, supprime tout meme le menu, je refais l'onboarding ; juste
#: le menu, garde l'epingle »). Chaque ticket VA : tout efface, puis sa ligne
#: de menu (une par model) postee et epinglee, sans l'avis « a epingle ».
#: UNE fois, trace ecrite avant ; coupe par un redemarrage (un push d'une
#: autre session, 12:26 le 03/10), il REPREND aux tickets pas encore faits --
#: trois reprises au plus.
CLEAN_DEMANDE = "2026-10-03"
_CLEAN_FAIT = Path(__file__).resolve().parent.parent / "data" / "clean_tickets_fr.json"


def _createrices_mypuls() -> list:
    """Pour l'essai de lien : les createrices des models FR que MyPuls donne
    au compte (page /creators = celles qu'il gere encore) et leur etat dans
    l'API. Le proprietaire croyait ne plus avoir l'abonnement de certaines."""
    import liens_fr
    import mypuls
    out = []
    try:
        page = mypuls.list_creators(force_refresh=True)
        gerees = {int(v): k for k, v in (page.get("creators") or {}).items()}
        if not page.get("ok"):
            out.append(f"⚠️ page MyPuls /creators : {page.get('error')}")
    except Exception as e:                                   # noqa: BLE001
        gerees = {}
        out.append(f"⚠️ page MyPuls /creators : {type(e).__name__}: {e}")
    try:
        api = {int(c["id"]): c for c in mypuls.api_creators_parsed() if c.get("id")}
    except Exception as e:                                   # noqa: BLE001
        api = {}
        out.append(f"⚠️ API MyPuls /creators : {type(e).__name__}: {e}")
    for m, cfg in liens_fr.MODELS.items():
        morceaux = []
        for p in ("of", "mym"):
            cid = cfg.get(p)
            if not cid:
                continue
            nom = gerees.get(int(cid))
            etat = api.get(int(cid))
            morceaux.append(f"{p.upper()} {cid} " + (f"✅ {nom}" if nom else "❌ absente de la page")
                            + (f" (API : {'active' if etat.get('active') else 'INACTIVE'})" if etat
                               else " (absente de l'API)"))
        out.append(f"**{cfg['nom']}** : " + " · ".join(morceaux))
    return out


class Outils(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self._entretien.start()
        self._numeros.start()

    async def cog_unload(self):
        self._entretien.cancel()
        self._numeros.cancel()

    @tasks.loop(minutes=10)
    async def _numeros(self):
        """Le numero du VA dans le nom de son salon (« 🟢-12-va-bob »), le meme
        que celui de son lien (liens_fr.numero_va). Un nouveau ticket, ou un
        ticket change de categorie, a le sien dans les dix minutes."""
        for guilde in list(getattr(self.bot, "guilds", []) or []):
            if not _serveur_outils(guilde):
                continue
            try:
                await self.numeroter(guilde)
            except Exception as e:                           # noqa: BLE001
                print(f"[outils] numeros des VA : {type(e).__name__}: {e}", flush=True)

    @_numeros.before_loop
    async def _avant_numeros(self):
        await self.bot.wait_until_ready()

    async def numeroter(self, guilde) -> dict:
        import liens_fr
        from cogs.welcome import load_users, models_du_serveur
        from nom_ticket import nom_ticket, numero
        bilan = {"renommes": 0, "deja": 0, "sans_va": [], "rates": []}
        par_salon = {int(e.get("channel_id") or 0): uid for uid, e in (load_users() or {}).items()
                     if isinstance(e, dict) and str(uid).isdigit()}
        models = set(models_du_serveur(guilde))
        for cat in guilde.categories:
            model = str(cat.name or "").strip().lower()
            if model not in models:
                continue
            for ch in sorted(cat.text_channels, key=lambda c: c.position):
                import re as _re
                m = _re.search(r"(?:^|[^a-z0-9])va-([a-z0-9_.]+)$", (ch.name or "").lower())
                if not m:
                    continue
                uid = par_salon.get(ch.id)
                if uid is None:
                    bilan["sans_va"].append(ch.name)     # ticket sans fiche : compte, pas numerote
                    continue
                n = await asyncio.to_thread(liens_fr.numero_va, uid, model)
                cur = ch.name or ""
                rond = cur[0] if cur[:1] in ("🟢", "🟠", "🔴") else ""
                cible = nom_ticket(rond, "🔗" if "🔗" in cur else "", "⚙️" if "⚙" in cur else "",
                                   n, m.group(1))
                if numero(cur) == str(n):
                    bilan["deja"] += 1
                    continue
                try:
                    await ch.edit(name=cible, reason=f"Numero du VA ({model} {n})")
                    bilan["renommes"] += 1
                    await asyncio.sleep(1.5)
                except Exception as e:                       # noqa: BLE001
                    bilan["rates"].append(f"{ch.name} ({type(e).__name__})")
        if bilan["renommes"] or bilan["sans_va"] or bilan["rates"]:
            print(f"[outils] numeros des VA : {bilan['renommes']} renomme(s), {bilan['deja']} deja bons, "
                  f"sans fiche {bilan['sans_va'][:10]}, rates {bilan['rates'][:10]}", flush=True)
        return bilan

    @tasks.loop(hours=24)
    async def _entretien(self):
        for guilde in list(getattr(self.bot, "guilds", []) or []):
            if not _serveur_outils(guilde):
                continue
            if SALONS_COMMUNS:
                try:
                    await self.assurer(guilde)
                except Exception as e:                       # noqa: BLE001
                    print(f"[outils] {getattr(guilde, 'name', '?')} : {type(e).__name__}: {e}")
            try:
                await self._reset_demande(guilde)
            except Exception as e:                           # noqa: BLE001
                print(f"[outils] reset des tickets : {type(e).__name__}: {e}")
            try:
                await self._essai_lien(guilde)
            except Exception as e:                           # noqa: BLE001
                print(f"[outils] essai de lien : {type(e).__name__}: {e}")
            try:
                await self._clean_demande(guilde)
            except Exception as e:                           # noqa: BLE001
                print(f"[outils] nettoyage des tickets : {type(e).__name__}: {e}")
            # les salons d'information : l'isolation d'un VA qui arrive les
            # lui cacherait (un refus par salon), sauf ceux de cette liste
            try:
                _rendre_visible_aux_futurs_va([c.id for c in salons_info(guilde)])
            except Exception as e:                           # noqa: BLE001
                print(f"[outils] salons d'information : {type(e).__name__}: {e}")
            try:
                from cogs.welcome import models_du_serveur
                activer_scrape_models_fr(models_du_serveur(guilde))
            except Exception as e:                           # noqa: BLE001
                print(f"[outils] scrape des models FR : {type(e).__name__}: {e}")
            # Les photos en emojis (PP des models, reserves du ✨ General,
            # icones des boutons) : le panneau 📋 Menu les lit au clic, sans
            # le temps d'en creer. Va IG n'en avait aucun (03/10/2026).
            try:
                from cogs.user import (ensure_action_emojis, ensure_identity_emojis,
                                       ensure_reserve_emojis)
                from cogs.welcome import models_du_serveur
                await ensure_identity_emojis(guilde, models_du_serveur(guilde))
                await ensure_reserve_emojis(guilde)
                await ensure_action_emojis(guilde)
            except Exception as e:                           # noqa: BLE001
                print(f"[outils] emojis du serveur FR : {type(e).__name__}: {e}")
            # un role de model a chaque VA qui a une fiche et aucun role
            # (fiches faites par /adduser, VA d'avant les roles)
            try:
                await self._roles_models(guilde)
            except Exception as e:                           # noqa: BLE001
                print(f"[outils] roles de model : {type(e).__name__}: {e}")
            # le message « Se vérifier » : pose par le bot de la verification
            # (Luigi), pas par celui-ci -- le clic irait a la mauvaise application
            try:
                import verif_discord as vd
                etat = await asyncio.to_thread(vd.assurer_message_verif, str(guilde.id))
                if etat not in ("deja", "pas de salon de verification"):
                    print(f"[outils] message de verification de {guilde.name} : {etat}")
            except Exception as e:                           # noqa: BLE001
                print(f"[outils] message de verification : {type(e).__name__}: {e}")

    @_entretien.before_loop
    async def _avant(self):
        await self.bot.wait_until_ready()

    async def _clean_demande(self, guilde) -> bool:
        fait = safe_json.load(_CLEAN_FAIT, default={}) or {}
        etat = fait.get(CLEAN_DEMANDE)
        if etat and (etat.get("fin") or etat.get("reprises", 0) >= 3):
            return False
        if etat:
            etat["reprises"] = etat.get("reprises", 0) + 1
        else:
            etat = fait[CLEAN_DEMANDE] = {"debut": int(__import__("time").time()), "faits": []}
        deja_faits = {int(i) for i in etat.get("faits") or []}
        if not safe_json.write(_CLEAN_FAIT, fait, indent=1):
            print("[outils] trace du nettoyage non ecrite : nettoyage NON lance", flush=True)
            return False
        ucog = self.bot.get_cog("UserCog")
        if ucog is None:
            print("[outils] nettoyage des tickets : UserCog absent, rien fait", flush=True)
            return False
        salon_staff = discord.utils.find(lambda c: "entrées" in c.name or "entrees" in c.name,
                                         guilde.text_channels)

        async def signaler(texte):
            print(f"[outils] nettoyage : {texte}", flush=True)
            if salon_staff is not None:
                try:
                    await salon_staff.send(texte)
                except Exception:                            # noqa: BLE001
                    pass

        async def _tache():
            import re as _re
            from cogs.user import _menu_a_poster, _une_ligne_par_model
            from cogs.welcome import _salon_archive, load_users
            # TOUS les tickets, meme sans role de model (_va_targets les saute :
            # ils seraient restes pleins) ; leurs lignes de menu a part
            fiches = {int(e.get("channel_id") or 0): (uid, e.get("identity"))
                      for uid, e in (load_users() or {}).items()
                      if isinstance(e, dict) and str(uid).isdigit()}
            tous = []
            for ch in guilde.text_channels:
                if _salon_archive(ch) or not _re.search(r"(?:^|[^a-z0-9])va-[a-z0-9_.]+$",
                                                        (ch.name or "").lower()):
                    continue
                uid, ident = fiches.get(ch.id, (None, None))
                lignes = [(u, i) for _c, u, i in _une_ligne_par_model([(ch, uid, ident)])] if uid else []
                tous.append((ch, lignes))
            vieux_faits = {int(i) for i in (etat.get("vieux_faits") or [])}
            # Discord n'efface EN LOT que les messages de moins de 14 jours ; les
            # plus vieux partent un par un. Le 03/10 un seul vieux ticket a
            # bloque tous les autres pendant de longues minutes -- d'ou DEUX
            # passes : tous les tickets d'abord (recent + menu), le vieux apres.
            limite = discord.utils.utcnow() - __import__("datetime").timedelta(days=13, hours=12)

            def _noter(**k):
                trace = safe_json.load(_CLEAN_FAIT, default={}) or {}
                trace.setdefault(CLEAN_DEMANDE, {}).update(k)
                safe_json.write(_CLEAN_FAIT, trace, indent=1)

            a_faire = [(ch, l) for ch, l in tous if ch.id not in deja_faits]
            await signaler(f"🧹 Nettoyage de {len(a_faire)} ticket(s)…"
                           + (f" (reprise : {len(deja_faits)} déjà faits)" if deja_faits else ""))
            faits_ids = set(deja_faits)
            faits, sans_menu, rates = 0, [], []
            for i, (ch, lignes) in enumerate(a_faire, 1):
                try:
                    await ch.purge(limit=None, after=limite, bulk=True, reason="Nettoyage des tickets")
                    poses = 0
                    for uid, ident in lignes:
                        if uid is None:
                            continue
                        vue = _menu_a_poster(ucog, ident, guilde, va=int(uid))
                        if not vue.a_des_elements():
                            continue
                        msg = await ch.send(view=vue)
                        await msg.pin(reason="Menu permanent VA (h24)")
                        poses += 1
                    # l'avis « … a epingle un message » : seul le menu reste
                    async for m in ch.history(limit=6):
                        if m.type == discord.MessageType.pins_add:
                            await m.delete()
                    faits += 1
                    faits_ids.add(ch.id)
                    if not poses:
                        sans_menu.append(ch.name)
                except Exception as e:                       # noqa: BLE001
                    rates.append(f"{ch.name} ({type(e).__name__})")
                if i % 10 == 0:
                    _noter(faits=sorted(faits_ids))          # pour reprendre apres un redemarrage
                if i % 25 == 0:
                    await signaler(f"🧹 {i}/{len(a_faire)}…")
                await asyncio.sleep(1)
            _noter(faits=sorted(faits_ids))
            await signaler(f"✅ Tickets nettoyés : {faits}, menu épinglé seul"
                           + (f" · SANS menu (pas de fiche ou de rôle) : {', '.join(sans_menu[:15])}"
                              if sans_menu else "")
                           + (f" · ratés : {', '.join(rates[:15])}" if rates else "")
                           + " — reste les messages de plus de 14 jours, un par un.")
            vieux, vieux_rates = 0, []
            for ch, _l in tous:
                if ch.id in vieux_faits:
                    continue
                try:
                    partis = await ch.purge(limit=None, before=limite, bulk=False,
                                            reason="Nettoyage des tickets (vieux messages)")
                    if partis:
                        vieux += 1
                        print(f"[outils] nettoyage : {len(partis)} vieux message(s) de #{ch.name}", flush=True)
                    vieux_faits.add(ch.id)
                    _noter(vieux_faits=sorted(vieux_faits))
                except Exception as e:                       # noqa: BLE001
                    vieux_rates.append(f"{ch.name} ({type(e).__name__})")
            _noter(fin=int(__import__("time").time()))
            await signaler(f"✅ Nettoyage fini : vieux messages retirés de {vieux} ticket(s)"
                           + (f" · ratés : {', '.join(vieux_rates[:15])}" if vieux_rates else ""))
        self.bot.loop.create_task(_tache())
        return True

    async def _essai_lien(self, guilde) -> bool:
        fait = safe_json.load(_ESSAI_FAIT, default={}) or {}
        if fait.get(ESSAI_LIEN["id"]):
            return False
        fait[ESSAI_LIEN["id"]] = {"debut": int(__import__("time").time())}
        if not safe_json.write(_ESSAI_FAIT, fait, indent=1):
            print("[outils] trace de l'essai de lien non ecrite : essai NON lance", flush=True)
            return False
        uid, model = ESSAI_LIEN["uid"], ESSAI_LIEN["model"]

        async def _tache():
            lignes = [f"🧪 **Essai de lien {model.capitalize()}** (demandé par le propriétaire)"]
            try:
                import liens_fr
                lignes += await asyncio.to_thread(_createrices_mypuls)
                res = await asyncio.to_thread(liens_fr.generer, uid, ESSAI_LIEN["pseudo"], model,
                                              "essai du proprietaire")
                if res.get("ok"):
                    lignes.append(f"✅ **{res.get('display_name')}** → {res.get('public_url')}")
                else:
                    lignes.append(f"❌ {res.get('erreur')}")
                lignes += [f"• tracking {k.upper()} : {v}" for k, v in (res.get("trackings") or {}).items()]
                lignes += [f"⚠️ {s}" for s in res.get("soucis") or []]
            except Exception as e:                           # noqa: BLE001
                lignes.append(f"❌ essai interrompu : {type(e).__name__}: {e}")
            texte = "\n".join(lignes)[:1900]
            print(f"[outils] essai de lien :\n{texte}", flush=True)
            fin = safe_json.load(_ESSAI_FAIT, default={}) or {}
            fin.setdefault(ESSAI_LIEN["id"], {})["resultat"] = texte
            safe_json.write(_ESSAI_FAIT, fin, indent=1)
            try:
                from cogs.welcome import load_users
                fiche = (load_users() or {}).get(str(uid)) or {}
                salon = guilde.get_channel(int(fiche.get("channel_id") or 0)) or discord.utils.find(
                    lambda c: "demande" in c.name and "lien" in c.name, guilde.text_channels)
                if salon is not None:
                    await salon.send(texte)
            except Exception as e:                           # noqa: BLE001
                print(f"[outils] essai de lien non poste : {e}", flush=True)
        self.bot.loop.create_task(_tache())
        return True

    async def _reset_demande(self, guilde) -> bool:
        fait = safe_json.load(_RESET_FAIT, default={}) or {}
        etat = fait.get(RESET_DEMANDE)
        if etat and (etat.get("fin") or etat.get("reprises", 0) >= 3):
            return False
        depuis = None
        if etat:
            depuis = etat.get("debut")
            etat["reprises"] = etat.get("reprises", 0) + 1
        else:
            etat = fait[RESET_DEMANDE] = {"debut": int(__import__("time").time())}
        if not safe_json.write(_RESET_FAIT, fait, indent=1):
            print("[outils] trace du reset non ecrite : reset NON lance (il pourrait "
                  "se refaire a chaque demarrage)", flush=True)
            return False
        from cogs.welcome import reset_tickets
        salon = discord.utils.find(lambda c: "entrées" in c.name or "entrees" in c.name,
                                   guilde.text_channels)

        async def signaler(texte):
            print(f"[outils] reset : {texte}", flush=True)
            if salon is not None:
                try:
                    await salon.send(texte)
                except Exception:                            # noqa: BLE001
                    pass

        async def _tache():
            try:
                if depuis:
                    await signaler("🔄 Reset coupe par un redemarrage : reprise")
                b = await reset_tickets(guilde, self.bot, signaler, depuis=depuis)
                fin = safe_json.load(_RESET_FAIT, default={}) or {}
                fin.setdefault(RESET_DEMANDE, {})["fin"] = int(__import__("time").time())
                safe_json.write(_RESET_FAIT, fin, indent=1)
                await signaler(f"✅ Reset des tickets fini : {b['faits']} ticket(s) neuf(s)"
                               + (f" · non archives : {', '.join(b['archives_ratees'][:15])}"
                                  if b["archives_ratees"] else "")
                               + (f" · archives SANS ticket neuf : {', '.join(b['tickets_rates'][:15])}"
                                  if b["tickets_rates"] else ""))
            except Exception as e:                           # noqa: BLE001
                await signaler(f"❌ Reset interrompu : {type(e).__name__}: {e}")
        self.bot.loop.create_task(_tache())
        return True

    async def _roles_models(self, guilde) -> int:
        wcog = self.bot.get_cog("Welcome")
        if wcog is None or not hasattr(wcog, "donner_role_model"):
            return 0
        from cogs.welcome import load_users
        n = 0
        for uid, e in (load_users() or {}).items():
            if not isinstance(e, dict) or not e.get("identity"):
                continue
            m = guilde.get_member(int(uid)) if str(uid).isdigit() else None
            if m is not None and not m.bot and await wcog.donner_role_model(m, e["identity"]):
                n += 1
                await asyncio.sleep(0.5)
        if n:
            print(f"[outils] {guilde.name} : {n} role(s) de model pose(s)")
        return n

    async def assurer(self, guilde) -> dict:
        """La categorie, ses salons et leurs panneaux. Idempotent : ce qui
        existe et est a jour n'est pas touche. Rend un bilan."""
        bilan = {"crees": [], "panneaux": 0}
        moi = guilde.me
        cat = discord.utils.find(est_categorie_outils, guilde.categories)
        if cat is None:
            cat = await guilde.create_category(
                CATEGORIE, overwrites=_droits(guilde, moi),
                reason="Outils communs des VA (spoofer, telechargement)")
            bilan["crees"].append(cat.name)
        salons = {}
        for cle, nom in SALONS:
            canal = discord.utils.find(
                lambda c, k=cle: _norm(c.name) == k, cat.text_channels)
            if canal is None:
                canal = await guilde.create_text_channel(
                    nom, category=cat, overwrites=_droits(guilde, moi),
                    reason="Outils communs des VA")
                bilan["crees"].append(canal.name)
                await asyncio.sleep(1.0)
            salons[cle] = canal
        _rendre_visible_aux_futurs_va([c.id for c in salons.values()])

        spf = self.bot.get_cog("Spoofer")
        if spf is not None:
            bilan["panneaux"] += await spf.assurer_panneau(salons["spoofer"])
        else:
            print("[outils] cog Spoofer absent : panneau du spoofer non pose")
        dl = self.bot.get_cog("Telechargement")
        if dl is not None:
            from cogs import telechargement as tl
            canal = salons["download"]
            moi_id = getattr(getattr(self.bot, "user", None), "id", 0)
            du_bot = [m async for m in canal.history(limit=25) if m.author.id == moi_id]
            if not (len(du_bot) == 1 and tl.panneau_a_jour(du_bot[0], moi_id)):
                bilan["panneaux"] += await tl.poser_panneaux(dl, canal)
        else:
            print("[outils] cog Telechargement absent : panneau du download non pose")
        # Le panneau des numeros est pose par le bot ADMIN (cogs/numeros.py,
        # _panneau_commun) : c'est lui qui porte le module des numeros.
        if bilan["crees"] or bilan["panneaux"]:
            print(f"[outils] {guilde.name} : crees {bilan['crees']}, "
                  f"{bilan['panneaux']} panneau(x) pose(s)")
        return bilan


async def setup(bot):
    await bot.add_cog(Outils(bot))
