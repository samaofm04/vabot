# -*- coding: utf-8 -*-
"""Qui est present aux sessions vocales des VA.

CE QUE FAIT CE COG, ET RIEN D'AUTRE

Chaque minute, il regarde qui se trouve dans les salons vocaux suivis et le
dit a `sessions_voc`. Tout le raisonnement -- a quelle session cette minute
appartient, a partir de combien de temps on est « present », qui manquait --
vit dans `sessions_voc.py`, qui se teste sans bot et sans reseau. Ici il n'y
a que la lecture de Discord et l'envoi du resume.

AUCUNE COMMANDE SLASH, ET C'EST OBLIGATOIRE

Le bot principal est a 100 commandes sur 100, le plafond d'une application
Discord. Un cog qui en declare une seule echoue ENTIEREMENT, en silence :
quatre cogs du projet sont deja morts ainsi (`vaactivity`, `vasort`,
`tgrouter`, `numeros`). On suit donc le modele de `reportcomptes` : zero
commande, les salons trouves par convention de nom, et le declenchement
manuel depuis le tableau de bord.

POURQUOI ON SONDE AU LIEU D'ECOUTER LES ENTREES ET SORTIES

`on_voice_state_update` ne survit pas a un redemarrage : ceux qui etaient
deja connectes n'existent plus pour le bot, et un evenement perdu laisse
quelqu'un « present » indefiniment. Relever la liste chaque minute mesure du
temps reellement passe, et se repare tout seul au tour suivant.
"""
import asyncio
import datetime as _dt
import io
import json
from pathlib import Path
import time as _t

import discord
from discord.ext import commands, tasks

import sessions_voc as sv


# Une seule definition du nettoyage de nom, dans sessions_voc : deux copies,
# c'est deux comportements le jour ou l'une des deux change.
_sans_accent = sv.sans_accent

FICHIER_APERCUS = Path("data") / "sessions_apercus.json"


# ==============================================================================
# Le bilan en IMAGE (demande du proprietaire du 28/09 : « plus beau, avec la
# PP »). Fonctions de module, pas methodes : /demosessions, sur le bot ADMIN,
# doit produire EXACTEMENT le meme message avec le bot PRINCIPAL -- une
# seconde construction aurait fini par montrer autre chose que le vrai.
# ==============================================================================

#: Le nom de la piece jointe. Il sert aussi a reconnaitre un bilan deja poste
#: (anti-doublon) ; [a-zA-Z0-9_.-] seulement, sinon Discord le reecrit et la
#: galerie « attachment://... » pointe dans le vide.
NOM_IMAGE = "bilan_sessions_%s.png"

#: Photos deja lues, par cle d'avatar Discord (elle change quand la photo
#: change) : le bilan quotidien et les essais ne retelechargent pas tout.
_AVATARS: dict = {}
_AVATARS_MAX = 400


def titre_bilan(jour: str) -> str:
    """« Sessions du 2026-09-27 » : le repere de l'anti-doublon, ancien et nouveau format."""
    return "Sessions du %s" % jour


def attendus_et_etat(bot) -> tuple:
    """(attendus, raison si la liste est inconnue).

    La raison est dite par /demosessions : « liste inconnue » sans cause
    laissait croire a un bug du bilan quand le bot n'etait simplement pas
    encore connecte.
    """
    if bot is None:
        return [], "bot principal introuvable dans ce processus"
    if not bot.is_ready():
        return [], "bot principal pas encore connecté"
    guilde = bot.get_guild(sv.SUIVI_GUILD_ID)
    if guilde is None:
        return [], "le bot principal ne voit pas le serveur Youl4b (US)"
    if not guilde.chunked:
        # Ne pas établir une liste avec un cache incomplet.
        return [], "liste des membres de Youl4b (US) pas encore complète"
    return sv.attendus_jessye(guilde.members), ""


def textes_composants(composants):
    """Tous les textes d'un message en composants (V2), a toute profondeur."""
    for c in composants or []:
        t = getattr(c, "content", None)
        if isinstance(t, str):
            yield t
        yield from textes_composants(getattr(c, "children", None))
        acc = getattr(c, "accessory", None)
        if acc is not None:
            yield from textes_composants([acc])


def est_bilan_du(msg, jour: str, moi_id) -> bool:
    """Ce message est-il le bilan de `jour` poste par ce bot ? Ancien OU nouveau format.

    Ancien : un embed titre « Sessions du AAAA-MM-JJ ». Nouveau : un message
    en composants dont le premier texte est ce titre, avec l'image
    bilan_sessions_AAAA-MM-JJ.png. Ne reconnaitre que l'un des deux, c'etait
    reposter le bilan apres chaque redemarrage pendant l'heure du bilan.
    """
    if getattr(getattr(msg, "author", None), "id", None) != moi_id:
        return False
    titre = titre_bilan(jour)
    if any(getattr(e, "title", None) == titre for e in (getattr(msg, "embeds", None) or [])):
        return True
    if any(getattr(a, "filename", None) == NOM_IMAGE % jour
           for a in (getattr(msg, "attachments", None) or [])):
        return True
    for t in textes_composants(getattr(msg, "components", None)):
        premiere = (t.strip().splitlines() or [""])[0]
        if premiere.lstrip("#").strip() == titre:
            return True
    return False


def ligne_courte(resume_fuseau: str, att) -> str:
    """La ligne sous le titre : fuseau et nombre d'attendus, ou l'avertissement."""
    if att:
        return "Jessye US · Youl4b · heures en %s · %d VA attendu%s" % (
            resume_fuseau, len(att), "s" if len(att) > 1 else "")
    return ("Heures en %s. Liste des VA attendus inconnue : seuls les présents "
            "sont fiables." % resume_fuseau)


#: Photos en echec recemment (cle -> heure) : un CDN en panne n'est pas
#: rattendu pour le salon suivant ni pour un second clic. Retentees ensuite.
_AVATARS_KO: dict = {}
_AVATARS_KO_DUREE = 600


async def photos_avatars(bot, ids, taille: int = 128, paralleles: int = 6,
                         delai_total: float = 8.0) -> tuple:
    """({id: octets PNG}, compte) — les photos de profil, via le serveur suivi.

    En parallele mais limite (six a la fois) ; chaque echec donne des
    initiales dans l'image et est COMPTE, jamais avale.

    UN DELAI TOTAL, pas seulement par photo. Avec 15 s par photo et six a la
    fois, un CDN muet faisait attendre ceil(18/6) x 15 = 45 s le vrai 27/09 :
    le bouton du site (/sessions/resume_now attend 25 s) repondait « echec »,
    le bilan partait quand meme a 45 s, et le clic suivant -- naturel apres
    un « echec » -- en postait un second. Passe `delai_total`, les photos
    manquantes sont des initiales, comptees en « delai ».
    """
    compte = {"lues": 0, "cache": 0, "introuvables": 0, "echecs": 0, "delai": 0}
    guilde = None
    try:
        if bot is not None and bot.is_ready():
            guilde = bot.get_guild(sv.SUIVI_GUILD_ID)
    except Exception:                                 # noqa: BLE001
        guilde = None
    if guilde is None:
        compte["introuvables"] = len(ids)
        return {}, compte
    verrou = asyncio.Semaphore(paralleles)

    async def une(uid):
        try:
            membre = guilde.get_member(int(uid))
        except (TypeError, ValueError):
            membre = None
        if membre is None:
            compte["introuvables"] += 1
            return uid, None
        cle = None
        try:
            asset = membre.display_avatar.replace(size=taille, format="png")
            cle = "%s:%d" % (getattr(asset, "key", "") or asset.url, taille)
            if cle in _AVATARS:
                compte["cache"] += 1
                return uid, _AVATARS[cle]
            if _t.time() - _AVATARS_KO.get(cle, 0) < _AVATARS_KO_DUREE:
                compte["echecs"] += 1
                return uid, None
            async with verrou:
                octets = await asyncio.wait_for(asset.read(), timeout=delai_total)
            if len(_AVATARS) >= _AVATARS_MAX:
                _AVATARS.pop(next(iter(_AVATARS)))
            _AVATARS[cle] = octets
            _AVATARS_KO.pop(cle, None)
            compte["lues"] += 1
            return uid, octets
        except asyncio.CancelledError:
            # Annulee par le delai total : comptee plus bas, en « delai ».
            if cle:
                _AVATARS_KO[cle] = _t.time()
            raise
        except Exception as e:                        # noqa: BLE001
            compte["echecs"] += 1
            if cle:
                _AVATARS_KO[cle] = _t.time()
            print("[sessions] photo de %s illisible (%s) : initiales à la place"
                  % (uid, type(e).__name__), flush=True)
            return uid, None

    taches = [asyncio.ensure_future(une(u)) for u in ids]
    if not taches:
        return {}, compte
    faites, en_attente = await asyncio.wait(taches, timeout=delai_total)
    for tache in en_attente:
        tache.cancel()
    if en_attente:
        await asyncio.gather(*en_attente, return_exceptions=True)
        compte["delai"] = len(en_attente)
        print("[sessions] %d photo(s) pas arrivée(s) en %.0f s : initiales à la place"
              % (len(en_attente), delai_total), flush=True)
    res = [tache.result() for tache in faites if not tache.cancelled()]
    if len(_AVATARS_KO) > _AVATARS_MAX:
        _AVATARS_KO.clear()
    return {u: o for u, o in res if o}, compte


def message_bilan_image(jour: str, png: bytes, ligne: str, alt: str = ""):
    """(vue Components V2, fichier) : le titre, la ligne courte, l'image en grand.

    Pourquoi une galerie V2 et pas un embed : une image d'embed est affichee
    a ~400 px de large, une galerie a une seule image prend toute la largeur
    du message (~550 px) -- et c'est ce qui rend le tableau lisible sans
    l'ouvrir. Pas de conteneur autour : il retirerait sa marge a l'image.
    """
    ui = discord.ui
    if not (hasattr(ui, "LayoutView") and hasattr(ui, "MediaGallery")):
        raise RuntimeError("discord.py %s ne sait pas envoyer de galerie (V2)"
                           % discord.__version__)
    nom = NOM_IMAGE % jour
    vue = ui.LayoutView(timeout=None)
    vue.add_item(ui.TextDisplay("## %s\n-# %s" % (titre_bilan(jour), ligne)))
    vue.add_item(ui.MediaGallery(discord.MediaGalleryItem(
        "attachment://" + nom, description=(alt or titre_bilan(jour))[:1024])))
    return vue, discord.File(io.BytesIO(png), filename=nom)


def embed_resume_texte(jour: str, att, maintenant: float = None) -> discord.Embed:
    """Le bilan TEXTE (l'ancien format) : le repli quand l'image est impossible.

    LE PREMIER BILAN ETAIT ILLISIBLE. Les absents arrivaient en une seule
    phrase separee par des virgules -- cent soixante-dix-neuf noms colles,
    qu'on ne pouvait ni parcourir ni compter. Le proprietaire a demande
    des retours a la ligne et des pastilles ; c'est la bonne forme, parce
    qu'on lit une liste de gens en la balayant, pas en la lisant.

    Vert = present. Rouge = absent. Orange = passe sans rester.
    """
    r = sv.resume_jour(jour, attendus=att, limiter_aux_attendus=True, maintenant=maintenant)
    description = ("Jessye US · Youl4b. Heures en %s. %d VA attendu(s)." % (r["fuseau"], len(att))
                   if att else
                   "Heures en %s. Liste des VA attendus inconnue : seuls "
                   "les presents sont fiables." % r["fuseau"])
    if not all(s2.get("terminee", True) for s2 in r["sessions"]):
        # Le bilan du jour en cours (repli texte du message tenu a jour) :
        # l'heure du releve, comme sur l'image.
        import sessions_image as _siT
        description += " Relevé à %s." % _siT._hhmm(
            _t.time() if maintenant is None else maintenant, r["fuseau"])
    e = discord.Embed(title=titre_bilan(jour), description=description, color=0x5865F2)
    for s2 in r["sessions"]:
        hl = s2.get("heures_locales") or {}
        entete = "%s — %s" % (s2["nom"], s2["heure"])
        if hl.get("MG"):
            entete += "  (BJ %s · MG %s)" % (hl.get("BJ", "?"), hl["MG"])
        SessionsVoc._ajouter_lignes(e, entete, SessionsVoc._corps_session(s2, complet=True).splitlines())
    return e


async def contenu_bilan(bot, jour: str, maintenant: float = None) -> tuple:
    """(arguments de send, infos) : le bilan en image, ou le texte si l'image echoue.

    Un bilan ne doit JAMAIS etre perdu : toute erreur du dessin (police,
    Pillow, photo...) retombe sur l'embed texte, avec la cause au journal.
    Le dessin tourne hors de la boucle d'evenements (asyncio.to_thread) :
    une image de soixante lignes ne doit pas figer le bot.

    `maintenant` : l'instant du releve (le bilan du jour tenu a jour, et
    /demosessions qui le montre). Une journee pas finie porte « relevé à ».
    `infos["png"]`, `["ligne"]`, `["alt"]` gardent de quoi refaire le
    message : un discord.File ne se lit qu'une fois, et deux salons « bilan »
    en veulent chacun un -- sans redessiner ni relire les photos.
    """
    maintenant = _t.time() if maintenant is None else float(maintenant)
    att, raison = attendus_et_etat(bot)
    infos = {"mode": "image", "raison": raison, "attendus": att, "photos": {}, "erreur": "",
             "png": None, "ligne": "", "alt": "", "maintenant": maintenant}
    try:
        import sessions_image as _si
        r = sv.resume_jour(jour, attendus=att, limiter_aux_attendus=False, maintenant=maintenant)
        ids = _si.ids_dessines(r, att, maintenant)
        photos, compte = await photos_avatars(bot, ids)
        infos["photos"] = compte
        png = await asyncio.to_thread(_si.dessiner_bilan, r, att, photos, jour, maintenant)
        t = _si.tableau(r, att, maintenant)
        vus = t["attendus_vus"] if att else len(t["lignes"])
        alt = (("Bilan des sessions du %s : %d VA présent%s sur %d"
                % (jour, vus, "s" if vus > 1 else "", t["attendus"])) if att else
               "Bilan des sessions du %s : %d VA vu%s" % (jour, vus, "s" if vus > 1 else ""))
        if not t["journee_finie"]:
            alt += " (journée en cours, relevé à %s)" % t["releve"]
        ligne = ligne_courte(r["fuseau"], att)
        vue, fichier = message_bilan_image(jour, png, ligne, alt)
        infos.update(png=png, ligne=ligne, alt=alt)
        print("[sessions] bilan %s dessiné%s : %d ligne(s), %d absent(s), photos %s"
              % (jour, "" if t["journee_finie"] else " (relevé à %s)" % t["releve"],
                 len(t["lignes"]), len(t["absents"]), compte), flush=True)
        return {"view": vue, "file": fichier}, infos
    except Exception as e:                            # noqa: BLE001
        infos.update(mode="texte", erreur="%s: %s" % (type(e).__name__, str(e)[:200]))
        print("[sessions] bilan %s : image impossible (%s) — repli sur le bilan texte"
              % (jour, infos["erreur"]), flush=True)
        return {"embed": embed_resume_texte(jour, att, maintenant)}, infos


# ==============================================================================
# Le message EN DIRECT en image (demande du proprietaire du 28/09 : « la meme
# chose » que le bilan pour le message qui suit la session en cours). Fonctions
# de module pour la meme raison que le bilan : /demosessions (bot admin) doit
# montrer EXACTEMENT ce que le bot principal pose dans le salon.
# ==============================================================================

#: La piece jointe du direct : une par session, remplacee a chaque
#: reecriture. [a-zA-Z0-9_.-] seulement (sinon Discord renomme le fichier et
#: la galerie « attachment://... » pointe dans le vide).
NOM_DIRECT = "direct_%s_%s.png"

#: Un gel qui echoue est retente a la minute suivante, GEL_ESSAIS_MAX fois ;
#: ensuite toutes les GEL_ESPACEMENT secondes. Abandonner apres dix minutes
#: laissait le message sur « En cours » pour toujours des qu'une panne Discord
#: durait un peu : le gel doit avoir lieu, fige ne passe a True qu'apres une
#: reecriture reussie.
GEL_ESSAIS_MAX = 10
GEL_ESPACEMENT = 15 * 60
#: Seule limite : sept jours apres la fin de la session (un week-end de panne
#: est couvert). Au-dela -- acces au salon retire pour de bon --, on arrete de
#: relire en le disant (gel_rate) ; direct_purger n'est appele nulle part, le
#: registre ne s'en chargerait pas.
GEL_ABANDON = 7 * 24 * 3600

#: Discord plafonne le texte d'un message en composants (V2) a 4000
#: caracteres, tous blocs confondus.
TEXTE_V2_MAX = 3900


def titre_direct(session: dict) -> str:
    """« Session 1 · 10:00 » : le titre court au-dessus de l'image."""
    return "%s · %02d:%02d" % (session.get("nom") or session.get("id") or "Session",
                               int(session.get("heure") or 0), int(session.get("minute") or 0))


def est_v2(msg) -> bool:
    """Ce message est-il deja en composants V2 ? Le drapeau ne s'enleve jamais :
    un message V2 ne peut plus porter d'embed, seulement des composants."""
    return bool(getattr(getattr(msg, "flags", None), "components_v2", False))


def _session_du_resume(session: dict, att) -> tuple:
    """(entree de resume_jour pour cette session, fuseau) -- TOUS les vus, hors liste compris."""
    r = sv.resume_jour(session["jour"], attendus=att, limiter_aux_attendus=False)
    entree = next((x for x in r["sessions"] if x["id"] == session["id"]), None)
    if entree is None:
        raise LookupError("session %s absente de la configuration du %s"
                          % (session.get("id"), session.get("jour")))
    return entree, r["fuseau"]


def embed_direct_texte(session: dict, att, fige: bool = False, maintenant: float = None) -> discord.Embed:
    """Le direct en TEXTE (l'ancien format) : le repli quand l'image est impossible.

    Le MEME message sert pendant la session et apres : tant qu'elle tourne il
    est reecrit, et au dernier passage il devient le compte rendu definitif.
    Deux messages -- un « en cours » puis un « bilan » -- auraient laisse le
    premier mentir pour toujours dans l'historique du salon.

    Les personnes hors de la liste des attendus y figurent, marquees : le
    filtre `if k in noms` les faisait disparaitre sans un mot.
    """
    maintenant = _t.time() if maintenant is None else float(maintenant)
    jour, sid = session["jour"], session["id"]
    brut = sv.presences(jour, sid)
    noms = {str(a["id"]): a["nom"] for a in (att or [])}
    gens = sorted(
        ({"id": k, "nom": noms.get(k) or v.get("nom") or k,
          "hors_liste": bool(noms) and k not in noms,
          "secondes": int(v.get("secondes") or 0),
          "premiere": v.get("premiere"), "derniere": v.get("derniere")}
         for k, v in brut.items() if isinstance(v, dict)),
        key=lambda g: -g["secondes"])
    seuil = sv.config()["presence_min_secondes"]
    presents = [g for g in gens if g["secondes"] >= seuil]
    partiels = [g for g in gens if g["secondes"] < seuil]
    hl = sv.heures_locales(session)
    e = discord.Embed(
        title="%s — %02d:%02d" % (session["nom"], session["heure"], session["minute"]),
        color=0x9AA0A6 if fige else 0x22C55E)
    e.description = ("Terminée." if fige else "En cours…") + \
        "  ·  BJ %s · MG %s" % (hl.get("BJ", "?"), hl.get("MG", "?"))
    if presents:
        SessionsVoc._ajouter_lignes(e, "Présents (%d)" % len(presents),
                                   [SessionsVoc._ligne_presence(g, maintenant, fige) for g in presents])
    else:
        e.add_field(name="Présents (0)", value="*personne pour l'instant*", inline=False)
    if partiels:
        # LE TEMPS AUSSI, ICI. Une liste de noms nus laisse croire que tous
        # ont fait la meme chose : deux minutes et quarante secondes ne se
        # valent pas, et c'est ce chiffre qui dit s'il faut leur en parler.
        SessionsVoc._ajouter_lignes(e, "Passés vite (%d)" % len(partiels),
                                   ["%s (%d min)%s" % (SessionsVoc._personne(g), g["secondes"] // 60,
                                                        " · hors liste" if g["hors_liste"] else "")
                                    for g in partiels])
    if fige:
        if att:
            vus = {g["id"] for g in gens}
            absents = [a for a in att if str(a["id"]) not in vus]
            SessionsVoc._ajouter_lignes(e, "Absents (%d)" % len(absents),
                                       [SessionsVoc._personne(a) for a in absents] or ["aucun"])
        e.set_footer(text="Compte définitif — ce message ne bouge plus.")
    else:
        e.set_footer(text="Mis à jour toutes les %d min." % sv.config()["maj_minutes"])
    return e


def texte_embed(e: discord.Embed, limite: int = TEXTE_V2_MAX) -> str:
    """Un embed mis en texte, pour un bloc V2 : titre, description, champs, pied.

    Coupe entre deux lignes et DIT combien il en manque : une liste tronquee
    en silence se lit comme une liste complete.
    """
    lignes = ["## %s" % (e.title or "")]
    if e.description:
        lignes.append(str(e.description))
    for f in e.fields:
        lignes.append("**%s**" % f.name)
        lignes.extend(str(f.value or "").splitlines())
    if e.footer and e.footer.text:
        lignes.append("-# %s" % e.footer.text)
    out, total = [], 0
    for i, l in enumerate(lignes):
        if total + len(l) + 1 > limite - 60:
            out.append("*… et %d ligne(s) de plus (voir la page Sessions)*" % (len(lignes) - i))
            break
        out.append(l)
        total += len(l) + 1
    return "\n".join(out)


def vue_texte_v2(texte: str):
    """Un message V2 fait d'un seul bloc de texte (le repli d'un direct deja en V2)."""
    vue = discord.ui.LayoutView(timeout=None)
    vue.add_item(discord.ui.TextDisplay(texte[:4000]))
    return vue


def message_direct_image(session: dict, png: bytes, alt: str = ""):
    """(vue Components V2, fichier) : le titre court, puis l'image en grand.

    Galerie a une image, comme le bilan : affichee a ~550 px, contre ~400
    pour une image d'embed. Le nom du fichier ne change pas d'une reecriture
    a l'autre ; la piece jointe, elle, est REMPLACEE (attachments=[fichier]).
    """
    ui = discord.ui
    if not (hasattr(ui, "LayoutView") and hasattr(ui, "MediaGallery")):
        raise RuntimeError("discord.py %s ne sait pas envoyer de galerie (V2)"
                           % discord.__version__)
    nom = NOM_DIRECT % (session["jour"], session["id"])
    vue = ui.LayoutView(timeout=None)
    vue.add_item(ui.TextDisplay("## %s" % titre_direct(session)))
    vue.add_item(ui.MediaGallery(discord.MediaGalleryItem(
        "attachment://" + nom, description=(alt or titre_direct(session))[:1024])))
    return vue, discord.File(io.BytesIO(png), filename=nom)


async def contenu_direct(bot, session: dict, fige: bool = False, maintenant: float = None) -> tuple:
    """(arguments d'envoi, infos) : le direct en image, ou l'embed texte si l'image echoue.

    `infos["png"]` garde l'image : un fichier discord.File ne se lit qu'une
    fois, et un second salon (ou un second essai) en veut un neuf.
    Le dessin tourne hors de la boucle d'evenements (asyncio.to_thread). Les
    photos passent par photos_avatars et son cache par cle d'avatar : un
    redessin toutes les quatre minutes ne retelecharge pas les photos.
    """
    maintenant = _t.time() if maintenant is None else float(maintenant)
    att, raison = attendus_et_etat(bot)
    infos = {"mode": "image", "raison": raison, "attendus": att, "photos": {},
             "erreur": "", "png": None, "alt": ""}
    try:
        import sessions_image as _si
        entree, fuseau = _session_du_resume(session, att)
        ids = _si.ids_direct(entree, att, fige=fige)
        photos, compte = await photos_avatars(bot, ids)
        infos["photos"] = compte
        png = await asyncio.to_thread(_si.dessiner_direct, entree, att, photos, maintenant,
                                      fige, fuseau, session["jour"])
        d = _si.direct(entree, att, maintenant, fige, fuseau, session["jour"])
        vus = d["attendus_vus"] if att else d["vus"]
        alt = "%s — %s : %d VA %s%s" % (
            titre_direct(session), "terminée" if fige else "en cours, relevé à %s" % d["releve"],
            vus, ("présent%s" % ("s" if vus > 1 else "")) if att else ("vu%s" % ("s" if vus > 1 else "")),
            (" sur %d" % d["attendus"]) if att else "")
        infos.update(png=png, alt=alt)
        vue, fichier = message_direct_image(session, png, alt)
        print("[sessions] direct %s dessiné%s : %d présent(s), %d passage(s) court(s), photos %s"
              % (sv.direct_cle(session), " (figé)" if fige else "", len(d["presents"]),
                 len(d["partiels"]), compte), flush=True)
        return {"view": vue, "file": fichier}, infos
    except Exception as e:                            # noqa: BLE001
        infos.update(mode="texte", erreur="%s: %s" % (type(e).__name__, str(e)[:200]))
        print("[sessions] direct %s : image impossible (%s) — repli sur le texte"
              % (sv.direct_cle(session), infos["erreur"]), flush=True)
        return {"embed": embed_direct_texte(session, att, fige, maintenant)}, infos


def session_pour_demo(jour: str = "", maintenant: float = None) -> tuple:
    """(session, figee) pour /demosessions vue « direct », ou (None, False).

    Sans jour : la session EN COURS s'il y en a une, sinon la derniere
    terminee (aujourd'hui ou hier). Avec un jour : sa derniere session
    terminee, ou celle qui tourne si aucune ne l'est encore.
    """
    maintenant = _t.time() if maintenant is None else float(maintenant)
    if not jour:
        s = sv.session_a(maintenant)
        if s is not None:
            return s, False
        aujourd = sv.jour_de(maintenant)
        jours = [aujourd, (_dt.date.fromisoformat(aujourd) - _dt.timedelta(days=1)).isoformat()]
    else:
        jours = [jour]
    finies = [s for j in jours for s in sv.sessions_du_jour(j) if float(s["fin"]) <= maintenant]
    if finies:
        return max(finies, key=lambda s: float(s["fin"])), True
    if jour:
        s = sv.session_a(maintenant)
        if s is not None and s.get("jour") == jour:
            return s, False
    return None, False


class SessionAbsentsView(discord.ui.View):
    """Bouton persistant des essais de mise en page, liés à un message précis.

    Les identifiants sont figés avec le bilan : un clic ne recalcule jamais
    les absences historiques avec la liste des VA du jour.
    """

    def __init__(self, count=None):
        super().__init__(timeout=None)
        if count is not None:
            self.absents.label = "Voir les %d absents" % count

    @discord.ui.button(label="Voir les absents", style=discord.ButtonStyle.secondary,
                       custom_id="sessions:absents:v1")
    async def absents(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            data = json.loads(FICHIER_APERCUS.read_text(encoding="utf-8"))
            message = interaction.message
            record = data["messages"][str(message.id)]
            ids = record["absent_ids"]
            valide = (
                data.get("schema") == 1
                and interaction.guild_id == sv.SUIVI_GUILD_ID
                and str(interaction.guild_id) == record["guild_id"]
                and str(interaction.channel_id) == record["channel_id"]
                and str(message.author.id) == record["author_id"]
                and message.author.id == interaction.client.user.id
                and isinstance(ids, list) and len(ids) <= 100
                and all(isinstance(uid, str) and uid.isdigit() and 16 <= len(uid) <= 20 for uid in ids)
                and len(ids) == len(set(ids))
            )
            if not valide:
                raise ValueError("Contexte du bilan invalide")
            titre = str(record["session"])[:100]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            await interaction.followup.send(
                "La liste de ce bilan est indisponible pour le moment.",
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            return
        embed = discord.Embed(title="Absents · %s" % titre, color=0x9AA0A6)
        SessionsVoc._ajouter_lignes(embed, "%d absent(s)" % len(ids),
                                   ["<@%s>" % uid for uid in ids] or ["Aucun"])
        embed.set_footer(text="Jessye US · Youl4b")
        await interaction.followup.send(embed=embed, ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())
        print("[sessions] détail des absents affiché : message %s, %d personnes"
              % (message.id, len(ids)), flush=True)


class SessionBilanView(discord.ui.View):
    """Quatre boutons persistants, avec les détails figés du bilan affiché."""

    def __init__(self):
        super().__init__(timeout=None)

    @staticmethod
    def detail_embed(record, sid):
        if record.get("kind") != "bilan" or sid not in {"s1", "s2", "s3", "s4"}:
            raise ValueError("Type de bilan invalide")
        jour = _dt.date.fromisoformat(record["jour"])
        session = record["sessions"][sid]
        heure = _dt.time.fromisoformat(session["heure"]).strftime("%H:%M")
        presents, partiels, absents = (session[k] for k in ("presents", "partiels", "absent_ids"))
        if not all(isinstance(rows, list) for rows in (presents, partiels, absents)):
            raise ValueError("Listes invalides")
        ids = [row["id"] for row in presents + partiels] + absents
        if (len(ids) > 100 or len(ids) != len(set(ids)) or
                not all(isinstance(uid, str) and uid.isdigit() and 16 <= len(uid) <= 20 for uid in ids)):
            raise ValueError("Identifiants invalides")
        for row in presents + partiels:
            if type(row["minutes"]) is not int or not 0 <= row["minutes"] <= 1440:
                raise ValueError("Durée invalide")

        def ligne(row):
            minutes = row["minutes"]
            duree = "%d min" % minutes if minutes < 60 else "%d h %02d" % divmod(minutes, 60)
            return "<@%s> — **%s**" % (row["id"], duree)

        embed = discord.Embed(title="Session %s · %s" % (sid[1:], heure),
            description="%s · heure du Bénin" % jour.strftime("%d/%m/%Y"), color=0x9AA0A6)
        SessionsVoc._ajouter_lignes(embed, "Présents (%d)" % len(presents),
                                   [ligne(row) for row in presents] or ["Aucun"])
        if partiels:
            SessionsVoc._ajouter_lignes(embed, "Passages courts (%d)" % len(partiels),
                                       [ligne(row) for row in partiels])
        SessionsVoc._ajouter_lignes(embed, "Absents (%d)" % len(absents),
                                   ["<@%s>" % uid for uid in absents] or ["Aucun"])
        embed.set_footer(text="Jessye US · Youl4b · bilan définitif")
        if len(embed) > 6000 or len(embed.fields) > 25:
            raise ValueError("Bilan trop long")
        return embed

    async def _afficher(self, interaction, sid):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            data = json.loads(FICHIER_APERCUS.read_text(encoding="utf-8"))
            message = interaction.message
            record = data["messages"][str(message.id)]
            if not (data.get("schema") == 1
                    and interaction.guild_id == sv.SUIVI_GUILD_ID
                    and str(interaction.guild_id) == record["guild_id"]
                    and str(interaction.channel_id) == record["channel_id"]
                    and str(message.author.id) == record["author_id"]
                    and message.author.id == interaction.client.user.id):
                raise ValueError("Contexte du bilan invalide")
            embed = self.detail_embed(record, sid)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            await interaction.followup.send("Les détails de cette session sont indisponibles pour le moment.",
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            return
        await interaction.followup.send(embed=embed, ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())
        print("[sessions] détail du bilan affiché : message %s, %s" % (message.id, sid), flush=True)

    @discord.ui.button(label="Session 1", style=discord.ButtonStyle.secondary, custom_id="sessions:bilan:v1:s1")
    async def session1(self, interaction, button):
        await self._afficher(interaction, "s1")

    @discord.ui.button(label="Session 2", style=discord.ButtonStyle.secondary, custom_id="sessions:bilan:v1:s2")
    async def session2(self, interaction, button):
        await self._afficher(interaction, "s2")

    @discord.ui.button(label="Session 3", style=discord.ButtonStyle.secondary, custom_id="sessions:bilan:v1:s3")
    async def session3(self, interaction, button):
        await self._afficher(interaction, "s3")

    @discord.ui.button(label="Session 4", style=discord.ButtonStyle.secondary, custom_id="sessions:bilan:v1:s4")
    async def session4(self, interaction, button):
        await self._afficher(interaction, "s4")


class SessionsVoc(commands.Cog):
    """Pointage des sessions vocales. Zero commande slash."""

    def __init__(self, bot):
        self.bot = bot
        # Ce qu'on a deja poste, pour ne pas resservir le meme resume a chaque
        # tour de boucle : { "<guild>:<jour>" : True }
        self._resumes_faits = {}
        self.boucle.start()

    async def cog_load(self):
        self._absents_view = SessionAbsentsView()
        self.bot.add_view(self._absents_view)
        self._bilan_view = SessionBilanView()
        self.bot.add_view(self._bilan_view)
        print("[sessions] bouton des absents enregistré", flush=True)
        print("[sessions] boutons du bilan enregistrés", flush=True)

    def cog_unload(self):
        self.boucle.cancel()
        if getattr(self, "_absents_view", None) is not None:
            self._absents_view.stop()
        if getattr(self, "_bilan_view", None) is not None:
            self._bilan_view.stop()

    # ------------------------------------------------------------------ #
    # Les salons suivis
    # ------------------------------------------------------------------ #
    def _vocaux(self) -> list:
        """Les salons vocaux a surveiller.

        Trois facons de les designer, de la plus precise a la plus souple :
        une liste d'identifiants, une categorie, un motif de nom. Le
        proprietaire hesitait entre « un salon par session » et « un seul
        salon pour toutes » : les deux marchent sans rien changer ici, parce
        que c'est l'HORLOGE qui decide de la session, jamais le salon.

        `hasattr(c, "send")` ne sert a rien pour filtrer : en discord.py 2.x
        un salon vocal a aussi un `send`. Seul `isinstance` tranche.
        """
        cfg = sv.config()
        out = []
        for c in self.bot.get_all_channels():
            if not isinstance(c, (discord.VoiceChannel, discord.StageChannel)):
                continue
            if getattr(getattr(c, "guild", None), "id", None) != sv.SUIVI_GUILD_ID:
                continue
            if sv.salon_suivi(c.id, getattr(c, "name", ""),
                              getattr(getattr(c, "category", None), "name", ""), cfg):
                out.append(c)
        return out

    # ------------------------------------------------------------------ #
    # La boucle
    # ------------------------------------------------------------------ #
    @tasks.loop(minutes=1)
    async def boucle(self):
        if not self.bot.is_ready():
            return  # Le cache vocal déconnecté ne constitue pas une présence.
        try:
            self._pointer()
        except Exception as e:                       # noqa: BLE001
            print(f"[sessions] pointage : {e}", flush=True)
        try:
            await self._direct()
        except Exception as e:                       # noqa: BLE001
            print(f"[sessions] direct : {e}", flush=True)
        # Le bilan d'HIER avant le message du jour : bot eteint toute une
        # journee et redemarre a 8 h 30, l'ordre inverse posait le message du
        # jour puis, en dessous, le bilan de la veille -- « le dernier message
        # est encore l'ancien bilan », la plainte du 28/09.
        try:
            await self._resume_si_lheure()
        except Exception as e:                       # noqa: BLE001
            print(f"[sessions] resume : {e}", flush=True)
        try:
            await self._bilan_vivant()
        except Exception as e:                       # noqa: BLE001
            print(f"[sessions] bilan du jour : {e}", flush=True)

    @boucle.before_loop
    async def _avant(self):
        await self.bot.wait_until_ready()
        self._attendus_enrichis()

    def _pointer(self):
        """Une minute de presence pour chacun de ceux qui sont la.

        On ne compte NI les bots NI les gens sourds cote serveur : un compte
        laisse connecte toute la nuit dans un salon n'a assiste a rien, et le
        faire figurer parmi les presents fausserait le seul chiffre que le
        proprietaire va regarder.
        """
        if sv.session_a(_t.time()) is None:
            return                                    # hors creneau : rien a noter
        attendus = {a["id"]: a for a in self._attendus_enrichis()}
        vus, deja = [], set()
        for ch in self._vocaux():
            for m in getattr(ch, "members", []) or []:
                if getattr(m, "bot", False) or m.id in deja or str(m.id) not in attendus:
                    continue
                etat = getattr(m, "voice", None)
                if etat is not None and getattr(etat, "deaf", False):
                    continue
                deja.add(m.id)
                vus.append({"id": str(m.id),
                            "nom": attendus[str(m.id)]["nom"]})
        if vus:
            sv.pointer(vus, 60)

    # ------------------------------------------------------------------ #
    # Le resume du jour
    # ------------------------------------------------------------------ #
    def _verrou(self) -> asyncio.Lock:
        """Un seul passage a la fois sur les messages du bilan.

        Le bouton du site (poster_resume) tourne dans la boucle du bot EN MEME
        TEMPS que la boucle d'une minute : sans verrou, un clic pendant la
        pose du message du jour en posait un second.
        """
        v = getattr(self, "_verrou_bilan", None)
        if v is None:
            v = self._verrou_bilan = asyncio.Lock()
        return v

    async def _resume_si_lheure(self):
        """A `resume_heure` (8 h au Benin), le bilan d'HIER : fige, et jamais en double.

        Depuis le 28/09 le bilan d'une journee est pose des sa premiere session
        et reecrit au fil des sessions (_bilan_vivant). A l'heure du bilan :
        - le message du jour existe dans le salon -> on s'assure qu'il est
          fige a jour (derniere reecriture si besoin) et on NE poste RIEN ;
        - il n'existe pas (bot eteint toute la journee, salon cree apres,
          message supprime a la main) -> le bilan part comme avant (image,
          puis repli texte) : un bilan ne se perd jamais.
        """
        cfg = sv.config()
        if not cfg.get("resume_actif"):
            return
        # L'horloge par time.time() (et non datetime.now) : la meme que le
        # reste du cog, que les simulations remplacent.
        maintenant_ts = _t.time()
        maintenant = _dt.datetime.fromtimestamp(maintenant_ts, sv._tz())
        if maintenant.hour != int(cfg.get("resume_heure", 8)):
            return
        # Le resume porte sur la journee ECOULEE : a huit heures du matin, ce
        # qui interesse le proprietaire est la nuit qui vient de passer, pas
        # la journee qui commence et dont aucune session n'a encore eu lieu.
        hier = (maintenant.date() - _dt.timedelta(days=1)).isoformat()
        contenu = None
        for salon in self._salons_resume():
            # Par SALON, pas par serveur : avec deux salons « bilan » sur
            # Youl4b, la cle « serveur:jour » marquait le second comme servi
            # des que le premier l'etait.
            cle = "%s:%s" % (getattr(salon, "id", 0), hier)
            if self._resumes_faits.get(cle):
                continue
            try:
                async with self._verrou():
                    fait, contenu = await self._bilan_de_9h(salon, hier, maintenant_ts, contenu)
                if fait:
                    self._resumes_faits[cle] = True
            except Exception as e:                   # noqa: BLE001
                print(f"[sessions] envoi resume : {e}", flush=True)

    async def _bilan_de_9h(self, salon, hier: str, maintenant: float, contenu) -> tuple:
        """(fait, contenu) pour UN salon. `fait` faux = a retenter a la minute suivante."""
        nom = getattr(salon, "name", "?")
        fiche = sv.bilan_fiche(hier, salon.id)
        if fiche and fiche.get("message") and not fiche.get("supprime"):
            msg, introuvable = await self._chercher(fiche)
            if msg is not None:
                if not fiche.get("fige"):
                    if contenu is None:
                        contenu = await contenu_bilan(self.bot, hier, maintenant)
                    mode = await self._reecrire_bilan(msg, hier, contenu)
                    if not mode:
                        print("[sessions] bilan %s : dernière réécriture refusée dans #%s — "
                              "retentée à la minute suivante, rien de posté" % (hier, nom), flush=True)
                        return False, contenu
                    sv.bilan_poser(hier, salon.id, dict(fiche, maj=maintenant, format=mode, fige=True,
                                                        essais=0, prochain=0))
                    print("[sessions] bilan %s figé à l'heure du bilan dans #%s (%s)"
                          % (hier, nom, mode), flush=True)
                print("[sessions] bilan %s : le message du jour est déjà dans #%s — pas de second"
                      % (hier, nom), flush=True)
                return True, contenu
            if not introuvable:
                # Illisible pour l'instant (reseau, 5xx) : il existe peut-etre
                # encore. Poster maintenant ferait deux bilans du meme jour.
                print("[sessions] bilan %s : message du jour illisible dans #%s — "
                      "retenté à la minute suivante" % (hier, nom), flush=True)
                return False, contenu
            print("[sessions] bilan %s : le message du jour a disparu de #%s — "
                  "le bilan final est reposté" % (hier, nom), flush=True)
        elif fiche and fiche.get("supprime"):
            print("[sessions] bilan %s : le message du jour avait été supprimé à la main dans #%s — "
                  "le bilan final est reposté" % (hier, nom), flush=True)
        # Comportement d'avant le 28/09 : retrouver un bilan deja publie (un
        # redemarrage pendant l'heure du bilan vide la memoire ; ancien embed,
        # image de 46e6240 ou message du jour), sinon le poster.
        deja = await self._bilans_publies(salon, hier)
        if deja:
            sv.bilan_poser(hier, salon.id, {"salon": salon.id, "message": deja[0].id, "maj": maintenant,
                                            "fige": True, "format": "repris"})
            return True, contenu
        mode, msg = await self._envoyer_bilan(salon, hier)
        sv.bilan_poser(hier, salon.id, {"salon": salon.id, "message": getattr(msg, "id", None),
                                        "maj": maintenant, "fige": True, "format": mode,
                                        "poste_a_l_heure_du_bilan": True})
        return True, contenu

    # ------------------------------------------------------------------ #
    # Le bilan du JOUR, tenu a jour au fil des sessions
    # ------------------------------------------------------------------ #
    async def _bilan_vivant(self):
        """Le bilan de la journee, pose des sa premiere session et reecrit ensuite.

        Demande du proprietaire du 28/09 : « un session-bilan toujours a jour,
        genre toutes les sessions ». Dans chaque salon « bilan », UN message
        par jour : pose des qu'une session du jour commence, reecrit toutes
        les `maj_minutes` (4) pendant une session et une fois apres la fin de
        chacune, puis FIGE quand la derniere est terminee. Plus besoin
        d'attendre le lendemain matin pour voir la journee.

        Deux jours a regarder : aujourd'hui, et hier -- la session de 23 h
        finit a 2 h, le lendemain.
        """
        cfg = sv.config()
        if not cfg.get("resume_actif"):
            return
        maintenant = _t.time()
        aujourd = sv.jour_de(maintenant)
        veille = (_dt.date.fromisoformat(aujourd) - _dt.timedelta(days=1)).isoformat()
        salons = self._salons_resume()
        if not salons:
            return
        for jour in (veille, aujourd):
            try:
                async with self._verrou():
                    await self._bilan_vivant_jour(jour, salons, maintenant, cfg)
            except Exception as e:                   # noqa: BLE001
                print(f"[sessions] bilan du jour {jour} : {type(e).__name__}: {e}", flush=True)

    @staticmethod
    def _bilan_a_reecrire(fiche: dict, sessions: list, maintenant: float, cfg: dict) -> bool:
        """Faut-il reecrire ce message maintenant ?

        Jamais plus d'une fois par tranche de `maj_minutes` et par salon. Et
        seulement s'il y a du neuf : une session en cours, ou une session
        terminee depuis la derniere reecriture (son compte definitif). Entre
        deux sessions, rien ne bouge : l'image garde son « relevé à ».
        """
        try:
            maj = float(fiche.get("maj") or 0)
        except (TypeError, ValueError):
            maj = 0.0
        if maintenant - maj < cfg["maj_minutes"] * 60:
            return False
        try:
            if float(fiche.get("prochain") or 0) > maintenant:
                return False                    # essais espaces apres une panne
        except (TypeError, ValueError):
            pass
        en_cours = any(float(s["debut"]) <= maintenant < float(s["fin"]) for s in sessions)
        fin_non_vue = any(maj < float(s["fin"]) <= maintenant for s in sessions)
        return en_cours or fin_non_vue

    async def _bilan_vivant_jour(self, jour: str, salons: list, maintenant: float, cfg: dict):
        sessions = sv.sessions_du_jour(jour)
        debut, fin = sv.journee_bornes(jour)
        if debut is None or maintenant < debut:
            return                                    # la journee n'a pas commence
        a_faire = []
        for salon in salons:
            fiche = sv.bilan_fiche(jour, salon.id)
            if fiche is None:
                # Pas de message : on le pose tant que la journee n'est pas
                # finie (bot redemarre, salon cree en cours de journee). Apres,
                # c'est l'heure du bilan qui s'en charge.
                if maintenant < fin:
                    a_faire.append((salon, None))
                continue
            if fiche.get("fige") or fiche.get("supprime"):
                continue
            if self._bilan_a_reecrire(fiche, sessions, maintenant, cfg):
                a_faire.append((salon, fiche))
        if not a_faire:
            return
        # UN dessin pour tous les salons de ce passage : les photos passent
        # par le cache partage avec le direct, l'image est refaite par salon
        # a partir des memes octets.
        contenu = await contenu_bilan(self.bot, jour, maintenant)
        for salon, fiche in a_faire:
            try:
                if fiche is None:
                    await self._poser_bilan_vivant(salon, jour, contenu, maintenant, fin)
                else:
                    await self._maj_bilan_vivant(salon, jour, fiche, contenu, maintenant, fin)
            except Exception as e:                   # noqa: BLE001
                print("[sessions] bilan du jour %s dans #%s : %s: %s"
                      % (jour, getattr(salon, "name", "?"), type(e).__name__, e), flush=True)

    async def _poser_bilan_vivant(self, salon, jour: str, contenu, maintenant: float, fin: float):
        """Le premier message du jour dans ce salon -- ou celui qui y est deja.

        Un bilan de ce jour deja dans le salon (bouton du site avant le
        deploiement, fiche perdue) est REPRIS et reecrit : jamais deux bilans
        d'un meme jour dans un salon.
        """
        nom = getattr(salon, "name", "?")
        deja = await self._bilans_publies(salon, jour)
        if deja:
            fiche = {"salon": salon.id, "message": deja[0].id, "maj": 0, "fige": False,
                     "format": "repris", "pose": maintenant}
            sv.bilan_poser(jour, salon.id, fiche)
            print("[sessions] bilan du jour %s : un bilan de ce jour est déjà dans #%s — repris, "
                  "pas de second" % (jour, nom), flush=True)
            await self._maj_bilan_vivant(salon, jour, fiche, contenu, maintenant, fin)
            return
        mode, msg = await self._envoyer_bilan(salon, jour, contenu, repli_v2=True)
        if msg is None:
            # Parti mais introuvable a la relecture : on ne sait pas lequel
            # reecrire. Le passage suivant le reprendra (_bilans_publies).
            print("[sessions] bilan du jour %s : posé dans #%s mais pas retrouvé — "
                  "repris au passage suivant" % (jour, nom), flush=True)
            return
        sv.bilan_purger()
        sv.bilan_poser(jour, salon.id, {"salon": salon.id, "message": msg.id, "maj": maintenant,
                                        "fige": maintenant >= fin, "format": mode, "pose": maintenant})
        print("[sessions] bilan du jour %s posé en %s dans #%s — réécrit au fil des sessions"
              % (jour, mode, nom), flush=True)

    async def _maj_bilan_vivant(self, salon, jour: str, fiche: dict, contenu, maintenant: float,
                                fin: float) -> str:
        """Reecrit le message du jour ; le fige si la journee est finie. Rend le mode, ou « »."""
        nom = getattr(salon, "name", "?")
        msg, introuvable = await self._chercher(fiche)
        if introuvable:
            # SUPPRIME A LA MAIN : c'est un droit, comme pour le direct. Pas
            # de repost aujourd'hui ; l'heure du bilan, demain, reposte le
            # bilan final -- un bilan ne se perd jamais.
            sv.bilan_poser(jour, salon.id, dict(fiche, supprime=True, maj=maintenant))
            print("[sessions] bilan du jour %s : message supprimé à la main dans #%s — pas reposté "
                  "aujourd'hui ; le bilan final partira à l'heure du bilan, demain" % (jour, nom),
                  flush=True)
            return ""
        mode = await self._reecrire_bilan(msg, jour, contenu) if msg is not None else ""
        if mode:
            # Journee finie mais dessin rate (repli texte) : PAS fige. L'heure
            # du bilan, demain, le reecrit une derniere fois (en image si le
            # dessin remarche) puis le fige -- sinon le bilan final de la
            # journee restait du texte pour toujours, alors qu'avant le 28/09
            # le 9 h aurait poste l'image.
            fige = maintenant >= fin and mode == "image"
            suite = ""
            if fige:
                suite = " — journée finie, message figé"
            elif maintenant >= fin:
                suite = " — journée finie mais en texte : dernier essai en image à l'heure du bilan"
            sv.bilan_poser(jour, salon.id, dict(fiche, maj=maintenant, format=mode, fige=fige,
                                                essais=0, prochain=0))
            print("[sessions] bilan du jour %s réécrit (%s) dans #%s%s"
                  % (jour, mode, nom, suite), flush=True)
            return mode
        # Refuse (image ET texte) ou illisible : pas marque fait, retente. Dix
        # essais a la minute, puis toutes les 15 min ; abandon DIT sept jours
        # apres la fin de la journee (la regle du gel du direct).
        essais = int(fiche.get("essais") or 0) + 1
        if maintenant - fin >= GEL_ABANDON:
            sv.bilan_poser(jour, salon.id, dict(fiche, fige=True, gel_rate=True, essais=essais))
            print("[sessions] bilan du jour %s : %d essais ratés dans #%s, abandon (le message "
                  "reste tel quel)" % (jour, essais, nom), flush=True)
        elif essais >= GEL_ESSAIS_MAX:
            sv.bilan_poser(jour, salon.id, dict(fiche, essais=essais,
                                                prochain=maintenant + GEL_ESPACEMENT))
            print("[sessions] bilan du jour %s : essai %d raté dans #%s, nouvel essai dans %d min"
                  % (jour, essais, nom, GEL_ESPACEMENT // 60), flush=True)
        else:
            sv.bilan_poser(jour, salon.id, dict(fiche, essais=essais))
            print("[sessions] bilan du jour %s : essai %d raté dans #%s, nouvel essai à la minute "
                  "suivante" % (jour, essais, nom), flush=True)
        return ""

    async def _reecrire_bilan(self, msg, jour: str, contenu) -> str:
        """Reecrit un bilan : « image », « texte » (repli), ou « » si rien n'a pu partir.

        La piece jointe est REMPLACEE (attachments=[fichier]) : une seule.
        Un message V2 ne redevient jamais un embed : son repli est du texte
        DANS un bloc V2. Un bilan a l'ancien format (embed) est converti a la
        premiere reecriture, contenu et embed vides dans la meme requete.
        """
        kwargs, infos = contenu
        v2 = est_v2(msg)
        if infos.get("png"):
            try:
                vue, fichier = message_bilan_image(jour, infos["png"], infos.get("ligne") or "",
                                                   infos.get("alt") or "")
                if v2:
                    await msg.edit(view=vue, attachments=[fichier])
                else:
                    await msg.edit(content=None, embed=None, view=vue, attachments=[fichier])
                    print("[sessions] bilan %s converti en image (ancien format embed)" % jour,
                          flush=True)
                return "image"
            except Exception as e:                   # noqa: BLE001
                print("[sessions] réécriture du bilan %s en image refusée (%s: %s) — repli sur le texte"
                      % (jour, type(e).__name__, str(e)[:200]), flush=True)
        embed = kwargs.get("embed") or embed_resume_texte(jour, infos.get("attendus") or [],
                                                          infos.get("maintenant"))
        try:
            if v2:
                await msg.edit(view=vue_texte_v2(texte_embed(embed)), attachments=[])
            else:
                await msg.edit(embed=embed)
            print("[sessions] bilan %s réécrit en TEXTE (repli%s)"
                  % (jour, ", bloc V2" if v2 else ", embed"), flush=True)
            return "texte"
        except Exception as e:                       # noqa: BLE001
            print("[sessions] réécriture du bilan %s : texte refusé aussi (%s: %s)"
                  % (jour, type(e).__name__, str(e)[:200]), flush=True)
            return ""

    def _salons_texte(self, motif: str, exclure: str = "") -> list:
        """Les salons TEXTE dont le nom porte `motif` (et pas `exclure`).

        L'exclusion n'est pas une precaution theorique : des que le
        proprietaire cree « session-bilan », ce salon porte AUSSI « session ».
        Sans l'exclure, le message en direct de chaque session irait
        s'empiler dans le salon du bilan.
        """
        out = []
        for c in self.bot.get_all_channels():
            if not isinstance(c, discord.TextChannel):
                continue
            if getattr(getattr(c, "guild", None), "id", None) != sv.SUIVI_GUILD_ID:
                continue
            if sv.salon_texte_ok(getattr(c, "name", ""), motif, exclure):
                out.append(c)
        return out

    def _salons_resume(self) -> list:
        """Ou va le BILAN de la journee."""
        return self._salons_texte(sv.config().get("salon_bilan") or "bilan")

    def _salons_direct(self) -> list:
        """Ou va le message EN DIRECT — jamais dans le salon du bilan."""
        cfg = sv.config()
        return self._salons_texte(cfg.get("salon_direct") or "session",
                                  exclure=cfg.get("salon_bilan") or "bilan")

    def embed_direct(self, session: dict, fige: bool = False) -> discord.Embed:
        """Le direct TEXTE (repli de l'image) : embed_direct_texte, avec les attendus du cog."""
        return embed_direct_texte(session, self._attendus_enrichis(), fige)

    @staticmethod
    def _ligne_presence(g, maintenant: float, fige: bool = False) -> str:
        """« Ana · arrivé 23:12 · 47 min » — et « parti 00:05 » s'il est sorti.

        TROIS FAITS, PAS UN. Le pseudo seul ne dit pas si quelqu'un a fait
        acte de presence ou s'il a tenu la session ; la duree seule ne dit pas
        s'il etait la au debut ou s'il est arrive a la fin. Et sans l'heure de
        SORTIE, un message fige laisserait croire que tout le monde etait
        encore la quand il s'est arrete.

        « Encore la » se lit sur le dernier relevé : le pointage passe chaque
        minute, donc au-dela de deux minutes sans etre vu, la personne est
        partie. On ne se fie pas a un evenement de deconnexion, qui se perd.
        """
        import datetime as _dL
        tz = sv._tz()

        def _h(ts):
            try:
                return _dL.datetime.fromtimestamp(float(ts), tz).strftime("%H:%M")
            except (TypeError, ValueError):
                return "?"

        bouts = [SessionsVoc._personne(g)]
        if g.get("hors_liste"):
            bouts.append("hors liste")
        if g.get("premiere"):
            bouts.append("arrivé %s" % _h(g["premiere"]))
        minutes = int(g.get("secondes") or 0) // 60
        bouts.append("%d min" % minutes if minutes < 60
                     else "%d h %02d" % (minutes // 60, minutes % 60))
        derniere = g.get("derniere")
        try:
            parti = derniere is not None and (maintenant - float(derniere)) > 120
        except (TypeError, ValueError):
            parti = False
        if parti or fige:
            bouts.append("parti %s" % _h(derniere))
        else:
            bouts.append("**encore là**")
        return "• " + " · ".join(bouts)

    async def _direct(self):
        """Poser le message, le reecrire, puis le figer. Dans cet ordre.

        Le gel passe AVANT la mise a jour : une session qui vient de se
        terminer doit recevoir son dernier compte, meme si une autre commence
        dans la foulee.

        EN IMAGE depuis le 28/09 (comme le bilan) : un message Components V2
        -- un titre court et une galerie d'une image --, dont la piece jointe
        est REMPLACEE a chaque reecriture.
        """
        import time as _tD
        cfg = sv.config()
        if not cfg.get("direct_actif"):
            return
        maintenant = _tD.time()

        # --- ce qui est termine : un dernier passage, puis plus jamais -----
        for cle, fiche in sv.direct_a_figer(maintenant):
            salon = self.bot.get_channel(int(fiche.get("salon") or 0))
            if getattr(getattr(salon, "guild", None), "id", None) != sv.SUIVI_GUILD_ID:
                continue
            try:
                if float(fiche.get("prochain_gel") or 0) > maintenant:
                    continue            # essais espaces apres les dix premiers
            except (TypeError, ValueError):
                pass
            jour, sid = str(cle).split(":", 1)
            sess = next((x for x in sv.sessions_du_jour(jour) if x["id"] == sid), None)
            msg, introuvable = await self._chercher(fiche)
            if sess is None or introuvable:
                # Message supprime a la main (c'est un droit : on ne le
                # reposte pas), ou session retiree de la configuration :
                # rien a figer, on n'y revient plus.
                print("[sessions] gel %s : %s — rien à figer"
                      % (cle, "session retirée de la configuration" if sess is None
                         else "message supprimé"), flush=True)
                sv.direct_poser(cle, dict(fiche, fige=True, maj=maintenant))
                continue
            mode = await self._reecrire(msg, sess, True, maintenant) if msg is not None else ""
            if mode:
                sv.direct_poser(cle, dict(fiche, fige=True, maj=maintenant, format=mode))
                continue
            # LE GEL N'EST PAS MARQUE FAIT S'IL A ECHOUE : le message
            # resterait sur « En cours », faux pour toujours. Retente a la
            # minute suivante GEL_ESSAIS_MAX fois, puis toutes les 15 min.
            essais = int(fiche.get("essais_gel") or 0) + 1
            try:
                depuis_fin = maintenant - float(fiche.get("fin") or 0)
            except (TypeError, ValueError):
                depuis_fin = 0.0
            if depuis_fin >= GEL_ABANDON:
                print("[sessions] gel %s : %d essais ratés en %d jours, abandon "
                      "(le message reste tel quel)" % (cle, essais, GEL_ABANDON // 86400),
                      flush=True)
                sv.direct_poser(cle, dict(fiche, fige=True, maj=maintenant, gel_rate=True,
                                          essais_gel=essais))
            elif essais >= GEL_ESSAIS_MAX:
                print("[sessions] gel %s : essai %d raté, nouvel essai dans %d min"
                      % (cle, essais, GEL_ESPACEMENT // 60), flush=True)
                sv.direct_poser(cle, dict(fiche, essais_gel=essais,
                                          prochain_gel=maintenant + GEL_ESPACEMENT))
            else:
                print("[sessions] gel %s : essai %d raté, nouvel essai à la minute suivante"
                      % (cle, essais), flush=True)
                sv.direct_poser(cle, dict(fiche, essais_gel=essais))

        # --- ce qui tourne : poser, ou reecrire si l'heure est venue ------
        sess = sv.session_a(maintenant)
        if sess is None:
            return
        cle = sv.direct_cle(sess)
        fiche = sv.direct_charger().get(cle)
        if fiche is None:
            await self._poser_direct(sess, cle, maintenant)
            return
        if fiche.get("fige"):
            return
        if (maintenant - float(fiche.get("maj") or 0)) < cfg["maj_minutes"] * 60:
            return
        msg = await self._retrouver(fiche)
        if msg is None:
            return
        mode = await self._reecrire(msg, sess, False, maintenant)
        if mode:
            sv.direct_poser(cle, dict(fiche, maj=maintenant, format=mode))

    async def _poser_direct(self, sess: dict, cle: str, maintenant: float):
        """Le premier message de la session : en image, sinon en embed texte.

        Un seul message, pas un par salon : le premier salon qui l'accepte
        le garde. Un envoi qui leve a pu arriver quand meme (delai depasse
        cote client) : on relit le salon avant de retenter en texte, sinon
        deux directs de la meme session se suivraient.
        """
        kwargs, infos = await contenu_direct(self.bot, sess, False, maintenant)
        png = infos.get("png")
        nom = NOM_DIRECT % (sess["jour"], sess["id"])
        for salon in self._salons_direct():
            msg, mode = None, ""
            if png is not None:
                debut = discord.utils.utcnow()
                try:
                    vue, fichier = message_direct_image(sess, png, infos.get("alt", ""))
                    msg = await salon.send(view=vue, file=fichier,
                                           allowed_mentions=discord.AllowedMentions.none())
                    mode = "image"
                except Exception as e:               # noqa: BLE001
                    print("[sessions] pose direct %s en image refusée dans #%s (%s: %s)"
                          % (cle, getattr(salon, "name", "?"), type(e).__name__, str(e)[:200]),
                          flush=True)
                    msg = await self._direct_arrive(salon, nom, debut)
                    if msg is not None:
                        mode = "image"
                        print("[sessions] direct %s : l'image était bien arrivée" % cle, flush=True)
            if msg is None:
                try:
                    msg = await salon.send(embed=embed_direct_texte(sess, infos["attendus"], False,
                                                                    maintenant),
                                           allowed_mentions=discord.AllowedMentions.none())
                    mode = "texte"
                except Exception as e:               # noqa: BLE001
                    print(f"[sessions] pose direct : {e}", flush=True)
                    continue
            sv.direct_poser(cle, {"salon": salon.id, "message": msg.id,
                                  "fin": sess["fin"], "maj": maintenant,
                                  "fige": False, "format": mode})
            print("[sessions] direct %s posé en %s dans #%s"
                  % (cle, mode.upper() if mode == "texte" else mode, getattr(salon, "name", "?")),
                  flush=True)
            break                                     # un seul message, pas un par salon

    async def _direct_arrive(self, salon, nom: str, debut):
        """Le direct que ce bot vient de poser dans `salon` (piece jointe `nom`), ou None."""
        try:
            async for m in salon.history(limit=10):
                if getattr(getattr(m, "author", None), "id", None) != getattr(self.bot.user, "id", None):
                    continue
                if not any(getattr(a, "filename", None) == nom for a in (getattr(m, "attachments", None) or [])):
                    continue
                cree = getattr(m, "created_at", None)
                if cree is None or cree >= debut - _dt.timedelta(minutes=2):
                    return m
        except Exception as e:                       # noqa: BLE001
            print(f"[sessions] relecture du salon du direct : {e}", flush=True)
        return None

    async def _reecrire(self, msg, sess: dict, fige: bool, maintenant: float) -> str:
        """Reecrit le direct : « image », « texte » (repli), ou « » si rien n'a pu partir.

        UN MESSAGE V2 NE REDEVIENT JAMAIS UN EMBED : Discord n'enleve pas le
        drapeau « composants ». Son repli est donc du texte DANS un bloc V2.
        Un message encore a l'ancien format (un direct pose avant le passage
        a l'image) est converti a la premiere reecriture -- contenu et embed
        vides dans la meme requete, que Discord exige pour poser le drapeau --
        et garde, lui, le repli embed tant qu'il n'est pas converti.
        """
        kwargs, infos = await contenu_direct(self.bot, sess, fige, maintenant)
        cle = sv.direct_cle(sess)
        v2 = est_v2(msg)
        if "view" in kwargs:
            try:
                if v2:
                    await msg.edit(view=kwargs["view"], attachments=[kwargs["file"]])
                else:
                    await msg.edit(content=None, embed=None, view=kwargs["view"],
                                   attachments=[kwargs["file"]])
                    print("[sessions] direct %s converti en image (ancien format embed)" % cle,
                          flush=True)
                return "image"
            except Exception as e:                   # noqa: BLE001
                print("[sessions] %s %s en image refusé (%s: %s) — repli sur le texte"
                      % ("gel" if fige else "maj direct", cle, type(e).__name__, str(e)[:200]),
                      flush=True)
        embed = kwargs.get("embed") or embed_direct_texte(sess, infos["attendus"], fige, maintenant)
        try:
            if v2:
                await msg.edit(view=vue_texte_v2(texte_embed(embed)), attachments=[])
            else:
                await msg.edit(embed=embed)
            print("[sessions] %s %s posé en TEXTE (repli%s)"
                  % ("gel" if fige else "maj direct", cle, ", bloc V2" if v2 else ", embed"), flush=True)
            return "texte"
        except Exception as e:                       # noqa: BLE001
            print("[sessions] %s %s : texte refusé aussi (%s: %s)"
                  % ("gel" if fige else "maj direct", cle, type(e).__name__, str(e)[:200]), flush=True)
            return ""

    async def _chercher(self, fiche: dict) -> tuple:
        """(message, introuvable) : introuvable = supprime ou salon disparu, pour de bon.

        Une erreur passagere (reseau, 5xx, acces retire le temps d'un
        reglage) rend (None, False) : le gel se retente (espace, jusqu'a GEL_ABANDON),
        au lieu de marquer fige une session jamais figee.
        """
        try:
            salon = self.bot.get_channel(int(fiche.get("salon") or 0))
        except (TypeError, ValueError):
            return None, True
        if salon is None or getattr(getattr(salon, "guild", None), "id", None) != sv.SUIVI_GUILD_ID:
            return None, True
        try:
            return await salon.fetch_message(int(fiche.get("message") or 0)), False
        except (discord.NotFound, TypeError, ValueError):
            return None, True
        except Exception as e:                       # noqa: BLE001
            print(f"[sessions] relecture du direct : {type(e).__name__}: {e}", flush=True)
            return None, False

    async def _retrouver(self, fiche: dict):
        """Le message deja poste, ou None s'il a ete supprime.

        Supprimer le message a la main est un droit : on ne le reposte pas,
        on laisse la session sans direct. Le registre des presences, lui,
        continue de compter -- l'affichage n'est pas la mesure.
        """
        msg, _introuvable = await self._chercher(fiche)
        return msg

    def embed_resume(self, jour: str) -> discord.Embed:
        """Le bilan TEXTE d'une journee (repli de l'image) : embed_resume_texte."""
        return embed_resume_texte(jour, self._attendus_enrichis())

    async def _bilans_publies(self, salon, jour: str) -> list:
        """Les bilans de ce jour deja dans le salon (ancien ou nouveau format)."""
        return [msg async for msg in salon.history(limit=20)
                if est_bilan_du(msg, jour, self.bot.user.id)]

    async def _deja_publie(self, salon, jour: str) -> bool:
        """Le bilan de ce jour est-il deja dans le salon (ancien ou nouveau format) ?"""
        return bool(await self._bilans_publies(salon, jour))

    @staticmethod
    def _poste_pendant(msg, avant, debut) -> bool:
        """Ce bilan est-il celui de la tentative qui vient d'echouer ?

        Absent du releve fait juste avant l'envoi, ET pas anterieur a son
        debut (deux minutes de marge pour l'horloge) : un bilan plus ancien
        du meme jour n'est jamais pris pour lui.
        """
        if avant is not None and getattr(msg, "id", None) in avant:
            return False
        cree = getattr(msg, "created_at", None)
        if cree is None:
            return avant is not None
        return cree >= debut - _dt.timedelta(minutes=2)

    async def envoyer_bilan(self, salon, jour: str) -> str:
        """Poste le bilan dans `salon` : « image », ou « texte » en repli."""
        mode, _msg = await self._envoyer_bilan(salon, jour)
        return mode

    async def _envoyer_bilan(self, salon, jour: str, contenu=None, repli_v2: bool = False) -> tuple:
        """Poste le bilan dans `salon` : (« image » ou « texte », message ou None).

        L'image d'abord ; si le dessin OU l'envoi echoue, le texte -- un bilan
        n'est jamais perdu. Avant ce repli on relit le salon : un envoi qui a
        expire cote client a pu arriver quand meme, et deux bilans le meme
        jour se liraient comme deux journees.
        `repli_v2` (le message du jour, reecrit ensuite) : le texte part DANS
        un bloc V2, pour que les reecritures suivantes restent des messages
        V2 ; sinon l'ancien embed. Leve seulement si le texte aussi est
        refuse (la boucle reessaie).
        """
        if contenu is None:
            contenu = await contenu_bilan(self.bot, jour)
        kwargs, infos = contenu
        avant, debut = None, discord.utils.utcnow()
        if infos.get("png") or "view" in kwargs:
            # Les bilans de ce jour DEJA la avant l'envoi. Sans ce releve, la
            # relecture du repli prenait un bilan plus ancien (bouton du site
            # a 12 h) pour l'image qui venait d'echouer (nouveau clic a 20 h,
            # 413) : aucun texte ne partait et le site affichait « poste ».
            try:
                avant = {getattr(m, "id", None) for m in await self._bilans_publies(salon, jour)}
            except Exception as e0:                  # noqa: BLE001
                print(f"[sessions] releve avant envoi : {e0}", flush=True)
                avant = None
            debut = discord.utils.utcnow()
            try:
                if infos.get("png"):
                    vue, fichier = message_bilan_image(jour, infos["png"], infos.get("ligne") or "",
                                                       infos.get("alt") or "")
                    envoi = {"view": vue, "file": fichier}
                else:
                    envoi = kwargs
                msg = await salon.send(allowed_mentions=discord.AllowedMentions.none(), **envoi)
                print("[sessions] bilan %s posté en image dans #%s"
                      % (jour, getattr(salon, "name", "?")), flush=True)
                return "image", msg
            except Exception as e:                   # noqa: BLE001
                print("[sessions] bilan %s : envoi de l'image refusé (%s: %s) — repli sur le texte"
                      % (jour, type(e).__name__, str(e)[:200]), flush=True)
                arrive = await self._arrive_pendant(salon, jour, avant, debut)
                if arrive is not None:
                    print("[sessions] bilan %s : l'image était bien arrivée, pas de repli"
                          % jour, flush=True)
                    return "image", arrive
        embed = kwargs.get("embed") or embed_resume_texte(jour, infos.get("attendus") or [],
                                                          infos.get("maintenant"))
        if repli_v2:
            try:
                msg = await salon.send(view=vue_texte_v2(texte_embed(embed)),
                                       allowed_mentions=discord.AllowedMentions.none())
            except Exception:
                # Arrive quand meme ? (meme relecture que pour l'image)
                arrive = await self._arrive_pendant(salon, jour, avant, debut)
                if arrive is not None:
                    return "texte", arrive
                raise
        else:
            msg = await salon.send(embed=embed)
        print("[sessions] bilan %s posté en TEXTE%s dans #%s"
              % (jour, " (bloc V2)" if repli_v2 else "", getattr(salon, "name", "?")), flush=True)
        return "texte", msg

    async def _arrive_pendant(self, salon, jour: str, avant, debut):
        """Le bilan de ce jour poste par la tentative qui vient d'echouer, ou None."""
        try:
            for m in await self._bilans_publies(salon, jour):
                if self._poste_pendant(m, avant, debut):
                    return m
        except Exception as e2:                      # noqa: BLE001
            print(f"[sessions] relecture avant repli : {e2}", flush=True)
        return None

    @staticmethod
    def _corps_session(s2: dict, complet=False) -> str:
        """Le contenu d'une session : une personne par ligne, ou un mot.

        Discord plafonne un champ a 1024 caracteres. On coupe donc, mais on
        DIT combien de lignes manquent : une liste tronquee en silence se lit
        comme une liste complete, et c'est elle qu'on croira.

        Statique : le bilan texte de repli se construit aussi sans le cog
        (embed_resume_texte, pour /demosessions sur le bot admin).
        """
        self = SessionsVoc   # ses aides (_ligne_pastille...) sont statiques
        if not s2.get("surveillee", True):
            return ("*Session non surveillée — le suivi ne tournait pas encore. "
                    "Aucun absent ne peut en être déduit.*")
        if not s2.get("terminee", True):
            # ELLE N'A PAS ENCORE EU LIEU, ou elle est en cours. Le premier
            # bilan accusait 179 personnes d'avoir manque une session qui
            # commencait huit heures plus tard.
            if s2["presents"] or s2["partiels"]:
                lignes = [self._ligne_pastille(g, "🟢") for g in s2["presents"]]
                lignes += [self._ligne_pastille(g, "🟠") for g in s2["partiels"]]
                return "\n".join(["*En cours…*"] + lignes) if complet else self._plafonner(["*En cours…*"] + lignes)
            return "*Pas encore commencée.*"
        lignes = [self._ligne_pastille(g, "🟢") for g in s2["presents"]]
        lignes += [self._ligne_pastille(g, "🟠") for g in s2["partiels"]]
        if s2.get("attendus_connus"):
            lignes += ["🔴 %s" % self._personne(a) for a in s2["absents"]]
        if not lignes:
            return "*Personne.*"
        if not s2.get("attendus_connus"):
            lignes.append("*Liste des VA attendus inconnue : les absents ne "
                          "peuvent pas être établis.*")
        return "\n".join(lignes) if complet else self._plafonner(lignes)

    @staticmethod
    def _personne(g: dict) -> str:
        nom = discord.utils.escape_mentions(discord.utils.escape_markdown(str(g.get("nom") or "")))
        uid = str(g.get("id") or "")
        return "%s · <@%s>" % (nom, uid) if uid.isdigit() else nom

    @staticmethod
    def _ajouter_lignes(embed, titre, lignes):
        """Découpe entre les personnes : une mention n'est jamais tronquée."""
        morceaux, courant = [], []
        for ligne in lignes:
            if len(ligne) > 1024:
                raise ValueError("Une ligne du bilan dépasse la limite Discord")
            if courant and len("\n".join(courant + [ligne])) > 1024:
                morceaux.append("\n".join(courant))
                courant = []
            courant.append(ligne)
        if courant:
            morceaux.append("\n".join(courant))
        for i, texte in enumerate(morceaux):
            embed.add_field(name=titre if i == 0 else titre + " (suite)", value=texte, inline=False)

    @staticmethod
    def _ligne_pastille(g: dict, pastille: str) -> str:
        m = int(g.get("secondes") or 0) // 60
        duree = "%d min" % m if m < 60 else "%d h %02d" % (m // 60, m % 60)
        return "%s %s — %s" % (pastille, SessionsVoc._personne(g), duree)

    @staticmethod
    def _plafonner(lignes, limite: int = 1010) -> str:
        """Colle les lignes sans depasser le champ, et dit ce qui manque."""
        out, total = [], 0
        for i, l in enumerate(lignes):
            if total + len(l) + 1 > limite - 40:
                reste = len(lignes) - i
                out.append("*… et %d de plus (voir la page Sessions)*" % reste)
                break
            out.append(l)
            total += len(l) + 1
        return "\n".join(out)

    def _attendus_enrichis(self) -> list:
        """Les personnes de Jessye, nommées comme sur le site, sur Youl4b."""
        # Une seule regle, partagee avec le bilan en image et /demosessions.
        attendus, raison = attendus_et_etat(self.bot)
        if raison:
            return []
        signature = tuple((a["id"], a["nom"]) for a in attendus)
        if signature != getattr(self, "_roster_signature", None):
            self._roster_signature = signature
            print("[sessions] Jessye US / Youl4b : %d personnes attendues" % len(attendus), flush=True)
        return attendus

    async def poster_resume(self, jour: str = "") -> dict:
        """Le bouton du site : poste le bilan du jour affiche -- ou le MET A JOUR.

        Si ce jour a deja son message dans un salon « bilan » (le message du
        jour tenu a jour, ou un bilan deja poste), il est REECRIT : un second
        bilan du meme jour se lirait comme une autre journee. Sinon il est
        poste comme avant. Rend {postes, mis_a_jour, echecs} : le site dit
        lequel des deux a eu lieu, et « 0 salon » n'est pas un succes.
        """
        if not jour:
            jour = sv.jour_de(_t.time())
        out = {"postes": 0, "mis_a_jour": 0, "echecs": 0}
        contenu = None
        async with self._verrou():
            for salon in self._salons_resume():
                try:
                    maintenant = _t.time()
                    _debut, fin = sv.journee_bornes(jour)
                    fin = maintenant if fin is None else fin
                    fiche = sv.bilan_fiche(jour, salon.id)
                    msg = None
                    if fiche and fiche.get("message") and not fiche.get("supprime"):
                        msg, introuvable = await self._chercher(fiche)
                        if msg is None and not introuvable:
                            raise RuntimeError("message du jour illisible pour l'instant : "
                                               "rien de posté (il existe peut-être encore)")
                    if msg is None:
                        deja = await self._bilans_publies(salon, jour)
                        msg = deja[0] if deja else None
                    if contenu is None:
                        contenu = await contenu_bilan(self.bot, jour, maintenant)
                    if msg is not None:
                        base = fiche if fiche and not fiche.get("supprime") else {}
                        if not contenu[1].get("png") and (base.get("fige") or maintenant >= fin):
                            # Dessin impossible au moment du clic : reecrire
                            # un bilan FINI remplacerait son image par du
                            # texte, pour toujours. On le laisse tel quel.
                            raise RuntimeError("dessin impossible (%s) : le bilan déjà posté est "
                                               "laissé tel quel" % (contenu[1].get("erreur") or "?"))
                        mode = await self._reecrire_bilan(msg, jour, contenu)
                        if not mode:
                            raise RuntimeError("mise à jour refusée par Discord")
                        # Fige seulement en image (meme regle que _maj_bilan_vivant) :
                        # un repli texte d'une journee finie est repris en image a
                        # l'heure du bilan.
                        sv.bilan_poser(jour, salon.id, dict(
                            base, salon=salon.id, message=msg.id, maj=maintenant, format=mode,
                            fige=bool(base.get("fige")) or (maintenant >= fin and mode == "image"),
                            supprime=False, essais=0, prochain=0))
                        out["mis_a_jour"] += 1
                        print("[sessions] bouton du site : bilan %s mis à jour dans #%s"
                              % (jour, getattr(salon, "name", "?")), flush=True)
                    else:
                        mode, msg = await self._envoyer_bilan(salon, jour, contenu,
                                                              repli_v2=maintenant < fin)
                        if msg is not None:
                            sv.bilan_poser(jour, salon.id, {
                                "salon": salon.id, "message": msg.id, "maj": maintenant,
                                "fige": maintenant >= fin and mode == "image", "format": mode,
                                "pose": maintenant})
                        out["postes"] += 1
                except Exception as e:               # noqa: BLE001
                    out["echecs"] += 1
                    print(f"[sessions] envoi manuel : {e}", flush=True)
        return out

    def etat_direct(self) -> dict:
        """Qui est dans les salons MAINTENANT, pour le bandeau du site.

        Lu a la demande : le registre ne sait que ce qui est deja compte, il
        ne peut pas dire « en ce moment ».
        """
        salons = []
        noms = {a["id"]: a["nom"] for a in self._attendus_enrichis()}
        for ch in self._vocaux():
            gens = [{"id": str(m.id), "nom": noms[str(m.id)]}
                    for m in (getattr(ch, "members", []) or [])
                    if str(m.id) in noms and not getattr(m, "bot", False)
                    and not getattr(getattr(m, "voice", None), "deaf", False)]
            salons.append({"salon": getattr(ch, "name", "?"),
                           "id": ch.id, "gens": gens})
        s = sv.en_cours()
        return {"session": s, "salons": salons,
                "total": sum(len(x["gens"]) for x in salons)}


async def setup(bot):
    await bot.add_cog(SessionsVoc(bot))
