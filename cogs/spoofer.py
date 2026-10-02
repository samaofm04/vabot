# -*- coding: utf-8 -*-
"""Le salon <pseudo>-spoofer d'un VA : un fichier, N versions uniques.

POURQUOI (demande du proprietaire, 27/09/2026)
    « Le spoofing avec les videos metadonnees tourne vachement bien, j'aimerais
    le mettre a disposition de mes VA. [...] Il arrive, il selectionne le
    nombre, de base 5, il clique et il drop son media. C'est tout. Pour les
    photos et pour les videos. »

OU CA VIT
    Un salon par VA, « <pseudo>-spoofer », juste apres -menu (cree par
    cogs/welcome.create_us_tickets ; les VA deja la le recoivent de
    l'entretien ci-dessous). Il porte UN panneau, sans texte :

        [🔢 5]  [📤 Spoofer]

    🔢 ouvre une saisie du nombre (1 a 5) et redessine le panneau ; 📤 ouvre
    une fenetre ou l'on choisit sa photo ou sa video. Le nombre vit dans le
    custom_id des deux boutons : un salon n'a qu'un VA, c'est donc SON
    reglage, et il survit aux redemarrages sans rien ecrire.

LA TECHNOLOGIE
    Celle des brutes, reglee par la page du site « Metadonnees video
    (uniquification) » : cogs.user.brute_a_envoyer pour les videos (mode
    « metadonnees » ou « complet » selon le menu Mode de la page), et
    image_transform.transform_image pour les photos. Le spoofer marche meme
    interrupteur coupe : le VA le demande expressement, et sans ca il
    recevrait N copies de son propre fichier.

    Chaque version est VERIFIEE : elle existe, et son contenu differe de la
    source et des autres. Une version ratee est comptee et dite, jamais
    livree en silence.

OU PARTENT LES FICHIERS
    Dans <pseudo>-content, comme le telechargement et le contenu du menu :
    le salon -spoofer ne porte que le panneau. Sans texte quand tout est
    parti ; une ligne sinon (ratees, trop lourdes, format).

CE QUI N'EST PAS ICI
    Aucune commande slash : le bot principal en a 100 sur 100, une de plus
    faisait echouer toute la synchronisation.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import random
import tempfile
import time
from pathlib import Path

import discord
from discord.ext import commands, tasks

import safe_json

_RACINE = Path(__file__).resolve().parents[1]

#: Travail en cours par VA : un redemarrage (chaque deploiement) le coupe ;
#: au rechargement, le VA est prevenu au lieu d'attendre des fichiers qui ne
#: viendront pas.
MARQUEUR = _RACINE / "data" / "spoofer_en_cours.json"

QTE_DEFAUT = 5
QTE_MAX = 5

VIDEOS = frozenset({".mp4", ".mov", ".m4v", ".webm", ".mkv"})
#: Conteneurs qu'une version « metadonnees seules » (remux -c copy) ne sait
#: pas refaire en .mp4 fiable : re-encodes (mode complet).
_A_REENCODER = frozenset({".webm", ".mkv"})
#: Au-dela, le fichier n'est pas telecharge : il occupait la memoire et le
#: verrou unique pendant des minutes pour, au bout, ne pas tenir sur Discord.
TAILLE_MAX = 200 * 1024 * 1024
PHOTOS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"})

#: Un traitement a la fois : le VPS a deux coeurs, partages avec le site et
#: le reste du bot. En mode complet, cinq re-encodages de trois VA en meme
#: temps faisaient rater leurs trois secondes aux autres panneaux.
_FILE = asyncio.Semaphore(1)

#: Pause entre deux messages de livraison (limite de debit de Discord).
PAUSE_ENVOI = 1.0


def _borne(q) -> int:
    try:
        q = int(q)
    except (TypeError, ValueError):
        return QTE_DEFAUT
    return q if 1 <= q <= QTE_MAX else QTE_DEFAUT


def _norm(nom) -> str:
    try:
        from cogs.welcome import nom_sans_decor
        return nom_sans_decor(nom)
    except Exception:
        return str(nom or "").strip().lower()


def _est_salon_spoofer(canal) -> bool:
    nom = getattr(canal, "name", "") or ""
    try:
        from cogs.welcome import salon_de_service
        if salon_de_service(nom):
            return False
    except Exception:
        pass
    return _norm(nom).endswith("-spoofer") or _commun(canal)


def _commun(canal) -> bool:
    """Le salon spoofer COMMUN de la categorie Outils (serveur FR, cogs/outils.py) :
    un panneau pour tous, le nombre retenu par personne, les fichiers dans le
    salon va- de chacun."""
    try:
        from cogs.outils import est_salon_outils
        return est_salon_outils(canal, "spoofer")
    except Exception:
        return False


#: Le nombre choisi par personne dans le salon commun : le nombre du panneau
#: (custom_id) y serait celui du dernier VA qui l'a change, pour tous.
QTE_PERSO = _RACINE / "data" / "spoofer_qte.json"


def qte_perso(uid) -> int:
    d = safe_json.load(QTE_PERSO, default={}) or {}
    return _borne((d if isinstance(d, dict) else {}).get(str(uid), QTE_DEFAUT))


def retenir_qte(uid, q: int) -> None:
    d = safe_json.load(QTE_PERSO, default={}) or {}
    d = d if isinstance(d, dict) else {}
    d[str(uid)] = _borne(q)
    QTE_PERSO.parent.mkdir(parents=True, exist_ok=True)
    if not safe_json.write(QTE_PERSO, d, indent=1):
        print(f"[spoofer] nombre de {uid} non ecrit : perdu au prochain redemarrage")


# ───────────────────────────────────────────────────────────── panneau ──

def _bouton_quantite(q: int) -> discord.ui.Button:
    """Le MEME dessin que la quantite du menu VA (« 🔢 5 ») : une seule
    fonction, sinon les deux divergent au premier changement."""
    try:
        from cogs.user import _jb_bouton_quantite
        b = _jb_bouton_quantite(q, f"spf:qb:{q}")
        b.row = None
        return b
    except Exception:
        return discord.ui.Button(label=str(q), emoji="🔢",
                                 style=discord.ButtonStyle.secondary,
                                 custom_id=f"spf:qb:{q}")


class SpfQte(discord.ui.DynamicItem[discord.ui.Button], template=r"spf:qb:(?P<q>[1-5])"):
    """🔢 : combien de versions. Ouvre la saisie, puis redessine le panneau."""

    def __init__(self, q: int = QTE_DEFAUT):
        self.q = _borne(q)
        super().__init__(_bouton_quantite(self.q))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["q"])

    async def callback(self, interaction: discord.Interaction):
        # La fenetre doit etre la TOUTE PREMIERE reponse (trois secondes).
        q = qte_perso(interaction.user.id) if _commun(interaction.channel) else self.q
        await interaction.response.send_modal(FenetreQuantite(q))


class SpfGo(discord.ui.DynamicItem[discord.ui.Button], template=r"spf:go:(?P<q>[1-5])"):
    """📤 : choisir le fichier. Le nombre est porte ici aussi : un clic apres
    un redemarrage utilise la valeur AFFICHEE, pas une valeur oubliee."""

    def __init__(self, q: int = QTE_DEFAUT):
        self.q = _borne(q)
        super().__init__(discord.ui.Button(label="Spoofer", emoji="📤",
                                           style=discord.ButtonStyle.primary,
                                           custom_id=f"spf:go:{self.q}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["q"])

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Spoofer") if interaction.client else None
        # Teste SANS attendre : rien d'asynchrone avant la fenetre.
        if cog is not None and interaction.user.id in cog.en_cours:
            await _dire(interaction, "⏳ Ton spoof précédent n'est pas fini.")
            return
        q = self.q
        if _commun(interaction.channel):
            from cogs.outils import SANS_SALON, salon_perso
            if salon_perso(interaction.guild, interaction.user) is None:
                await interaction.response.send_message(SANS_SALON, ephemeral=True)
                return
            q = qte_perso(interaction.user.id)
        await interaction.response.send_modal(FenetreFichier(q))


#: L'icone du panneau (27/09 : « mets cette icone pour le spoofer », comme
#: la vignette du panneau Numero). Jointe au message, affichee en vignette.
_ICONE = Path(__file__).resolve().parent.parent / "emojis" / "spoofer.png"
_ICONE_NOM = "spoofer.png"
#: Le bleu de l'icone.
_BLEU = 0x1E84EA


def fichier_icone():
    """L'icone a joindre, neuve a chaque envoi (un discord.File ne se lit
    qu'une fois), ou None si le fichier manque : le panneau part alors sans
    vignette plutot que pas du tout, et le journal le dit."""
    if not _ICONE.exists():
        print(f"[spoofer] icone absente ({_ICONE}) : panneau sans vignette")
        return None
    return discord.File(str(_ICONE), filename=_ICONE_NOM)


def panneau(q: int = QTE_DEFAUT, icone=None) -> discord.ui.LayoutView:
    """Le panneau, comme celui du Numero : un bloc bleu, « Spoofer » et
    l'icone en vignette, puis les deux boutons. `icone=False` (fichier
    absent, ou message d'avant sans l'icone jointe) : les boutons seuls --
    une vignette sans piece jointe ferait refuser le message."""
    q = _borne(q)
    ui = discord.ui
    vue = ui.LayoutView(timeout=None)
    rangee = ui.ActionRow()
    rangee.add_item(SpfQte(q))
    rangee.add_item(SpfGo(q))
    if _ICONE.exists() if icone is None else bool(icone):
        tete = ui.Section(ui.TextDisplay("## Spoofer"),
                          accessory=ui.Thumbnail("attachment://" + _ICONE_NOM))
        vue.add_item(ui.Container(tete, rangee, accent_colour=_BLEU))
    else:
        vue.add_item(rangee)
    return vue


def _porte_icone(message) -> bool:
    """Le panneau montre-t-il l'icone ? On la cherche DANS la vignette : un
    message Components V2 ne liste pas la piece jointe qu'il affiche
    (« attachments »: [] constate le 27/09), et la chercher la faisait
    reposer les 34 panneaux a chaque demarrage -- et redessiner sans
    l'icone le panneau d'un VA qui change le nombre."""
    if any(getattr(a, "filename", "") == _ICONE_NOM
           for a in (getattr(message, "attachments", None) or [])):
        return True
    pile = list(getattr(message, "components", None) or [])
    while pile:
        c = pile.pop()
        url = str(getattr(getattr(c, "media", None), "url", "") or "")
        if ("/" + _ICONE_NOM) in url or url.endswith(":" + "//" + _ICONE_NOM) \
                or url.split("?")[0].endswith(_ICONE_NOM):
            return True
        pile += list(getattr(c, "children", None) or [])
        pile += list(getattr(c, "components", None) or [])
        acc = getattr(c, "accessory", None)
        if acc is not None:
            pile.append(acc)
    return False


def _custom_ids(message) -> set:
    out, pile = set(), list(getattr(message, "components", None) or [])
    while pile:
        c = pile.pop()
        cid = getattr(c, "custom_id", None)
        if cid:
            out.add(cid)
        pile += list(getattr(c, "children", None) or [])
    return out


def est_panneau(message, moi: int) -> bool:
    """Un panneau du spoofer (actuel ou ancien) poste par le bot."""
    return (getattr(getattr(message, "author", None), "id", None) == moi
            and any(c.startswith("spf:") for c in _custom_ids(message)))


def panneau_a_jour(message, moi: int) -> bool:
    ids = _custom_ids(message)
    return (est_panneau(message, moi) and not getattr(message, "embeds", None)
            and any(c.startswith("spf:qb:") for c in ids)
            and any(c.startswith("spf:go:") for c in ids)
            # sans l'icone (panneau d'avant le 27/09) : il est repose
            and (_porte_icone(message) or not _ICONE.exists()))


# ───────────────────────────────────────────────────────────── fenetres ──

#: custom_id des fenetres ouvertes PAR CE PROCESSUS. Une soumission absente
#: d'ici vient d'une fenetre ouverte AVANT un redemarrage (un par
#: deploiement) : discord.py la jetait sans repondre et le VA perdait son
#: televersement. Le test « absente de _view_store._modals » ne suffit pas :
#: une fenetre finie sans rendre la main en est deja retiree, et le fichier
#: etait alors traite deux fois (constate en simulation).
_OUVERTES: set = set()


class FenetreQuantite(discord.ui.Modal, title="🔢"):
    nombre = discord.ui.TextInput(label="Combien de versions (1 à 5)", placeholder="5",
                                  required=True, min_length=1, max_length=1,
                                  custom_id="spf:nombre")

    def __init__(self, q: int = QTE_DEFAUT, custom_id: str = None):
        super().__init__(custom_id=custom_id or f"spf:qte:{os.urandom(6).hex()}")
        if custom_id is None:
            _OUVERTES.add(self.custom_id)
        self.nombre.default = str(_borne(q))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            q = int(str(self.nombre.value or "").strip())
        except ValueError:
            q = 0
        if not 1 <= q <= QTE_MAX:
            await _dire(interaction, f"🔢 Choisis un nombre entre 1 et {QTE_MAX}.")
            return
        if _commun(getattr(interaction, "channel", None)):
            retenir_qte(interaction.user.id, q)
            await interaction.response.send_message(f"🔢 {q}", ephemeral=True)
            return
        try:
            # la vignette pointe sur la piece jointe DU message : un
            # panneau qui ne l'a pas est redessine sans elle
            icone = _porte_icone(getattr(interaction, "message", None))
            try:
                await interaction.response.edit_message(view=panneau(q, icone=icone))
            except discord.HTTPException:
                if not icone:
                    raise
                # piece jointe perdue : on la renvoie, une fois (comme le
                # panneau Numero)
                f = fichier_icone()
                await interaction.response.edit_message(
                    view=panneau(q, icone=f is not None),
                    attachments=[f] if f is not None else [])
        except Exception as e:                               # noqa: BLE001
            print(f"[spoofer] panneau non redessine : {type(e).__name__}: {e}")
            if not interaction.response.is_done():
                await interaction.response.defer()


class FenetreFichier(discord.ui.Modal, title="Spoofer"):
    fichier = discord.ui.Label(
        text="Photo ou vidéo",
        component=discord.ui.FileUpload(custom_id="spf:fichier",
                                        min_values=1, max_values=1, required=True))

    def __init__(self, q: int = QTE_DEFAUT, custom_id: str = None):
        self.q = _borne(q)
        super().__init__(custom_id=custom_id or f"spf:fen:{self.q}:{os.urandom(6).hex()}")
        if custom_id is None:
            _OUVERTES.add(self.custom_id)

    async def on_submit(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Spoofer") if interaction.client else None
        if cog is None:
            await _dire(interaction, "🎭 Spoofer indisponible pour le moment.")
            return
        uid = interaction.user.id
        # Deux fenetres ouvertes par deux clics peuvent etre soumises toutes
        # les deux : le verrou se reprend ICI, sans rien attendre avant.
        if uid in cog.en_cours:
            await _dire(interaction, "⏳ Ton spoof précédent n'est pas fini.")
            return
        cog.en_cours.add(uid)
        try:
            # accuse de reception silencieux, dans les trois secondes
            try:
                await interaction.response.defer()
            except Exception:
                pass
            pieces = list(getattr(self.fichier.component, "values", None) or [])
            if not pieces:
                await _dire(interaction, "📎 Aucun fichier reçu.")
                return
            await cog.traiter(interaction, pieces[0], self.q)
        finally:
            cog.en_cours.discard(uid)


# ────────────────────────────────────────────────────────────── moteur ──

def _md5(p: Path) -> str:
    h = hashlib.md5()
    with Path(p).open("rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def _nom_iphone(ext: str, pris: set) -> str:
    """Un nom comme en sort un iPhone (« IMG_4821.MOV ») : le nom d'origine
    (« download (3)_2_2.mp4 ») ne suit pas la version spoofee."""
    for _ in range(50):
        n = f"IMG_{random.randint(1000, 9999)}{ext.upper()}"
        if n not in pris:
            pris.add(n)
            return n
    n = f"IMG_{len(pris) + 1000}{ext.upper()}"
    pris.add(n)
    return n


async def versions_video(src: Path, dossier: Path, q: int, identite: str,
                         complet=None, force_ext=None) -> tuple:
    """(sorties, ratees) : q versions de la video, par le moteur des brutes."""
    from cogs.user import brute_a_envoyer
    sorties, ratees, vus, pris = [], 0, {_md5(src)}, set()
    for _ in range(q):
        ext = force_ext or (".mp4" if complet else src.suffix.lower())
        sortie = Path(dossier) / _nom_iphone(ext, pris)
        f, ok, _raison = await brute_a_envoyer(src, dossier, identity=identite,
                                               sortie=sortie, forcer=True, complet=complet,
                                               noter=False)
        if not ok or Path(f) == src or not sortie.exists() or sortie.stat().st_size == 0:
            ratees += 1
            continue
        h = _md5(sortie)
        if h in vus:                  # identique a la source ou a une autre
            ratees += 1
            continue
        vus.add(h)
        sorties.append(sortie)
    return sorties, ratees


async def versions_photo(src: Path, dossier: Path, q: int) -> tuple:
    """(sorties, ratees) : q versions de la photo, TOUJOURS en .jpg -- un PNG
    ressortait sans EXIF et identique d'une version a l'autre, un HEIC recopie
    tel quel. transform_image rend True meme quand il n'a fait que recopier :
    chaque sortie est comparee a la source et aux autres."""
    import image_transform as it
    cfg = dict(it.load_config())
    cfg["enabled"] = True
    cfg["random_us_metadata"] = {"enabled": True}
    sorties, ratees, vus, pris = [], 0, {_md5(src)}, set()
    for _ in range(q):
        sortie = Path(dossier) / _nom_iphone(".jpg", pris)
        try:
            ok = await asyncio.to_thread(it.transform_image, src, sortie, cfg, "post")
        except Exception:
            ok = False
        if not ok or not sortie.exists() or sortie.stat().st_size == 0:
            ratees += 1
            continue
        h = _md5(sortie)
        if h in vus:
            ratees += 1
            continue
        vus.add(h)
        sorties.append(sortie)
    return sorties, ratees


# ─────────────────────────────────────────────────────────── utilitaires ──

def _cible_content(interaction):
    """Le salon -content du VA (meme recherche que le contenu du menu :
    categorie d'abord). A defaut, le salon ou l'on a clique.

    Dans le salon commun des Outils : le salon va- du VA, ou None -- jamais
    le salon commun, ou tout le monde verrait ses fichiers."""
    canal = getattr(interaction, "channel", None)
    if _commun(canal):
        from cogs.outils import salon_perso
        return salon_perso(getattr(interaction, "guild", None), interaction.user)
    try:
        from cogs.user import _us_content_target
        c = _us_content_target(interaction)
        if c is not None:
            return c
    except Exception as e:                                   # noqa: BLE001
        print(f"[spoofer] salon -content introuvable : {e}")
    return getattr(interaction, "channel", None)


async def _dire(interaction, texte: str) -> None:
    """Une ligne au VA, dans son -content (regle du proprietaire : jamais
    dans le salon du panneau). Ne leve jamais."""
    try:
        from cogs.user import _jb_dire
        await _jb_dire(interaction, texte, "spoofer")
        return
    except Exception as e:                                   # noqa: BLE001
        print(f"[spoofer] message non dit ({type(e).__name__}: {e}) : {texte[:120]}")
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(texte, ephemeral=True)
        else:
            await interaction.followup.send(texte, ephemeral=True)
    except Exception:
        pass


class _Refus(Exception):
    """Un spoof refuse avant tout traitement : le message est pour le VA."""


async def _trop_longue(src: Path, plafond: int) -> bool:
    """En mode complet, une version pese au moins (800 + 128) kbit/s x duree
    / 1,04 : au-dela du plafond, aucune ne tiendra."""
    try:
        import video_transform as vt
        duree = await asyncio.to_thread(vt.duree_secondes, src)
    except Exception:
        return False
    return bool(duree) and duree > 0 and (800 + 128) * 125 * duree / 1.04 > plafond


def _balayer_temporaires(age_min: int = 3600) -> int:
    """Les dossiers spoof_* laisses par un redemarrage pendant un spoof : le
    TemporaryDirectory ne les efface qu'a sa fin normale. Ce sont des copies
    de travail (source et versions), jamais du vault."""
    import shutil
    racine = Path(tempfile.gettempdir())
    n = 0
    try:
        for d in racine.glob("spoof_*"):
            try:
                if d.is_dir() and time.time() - d.stat().st_mtime > age_min \
                        and d.resolve().parent == racine.resolve():
                    shutil.rmtree(d, ignore_errors=True)
                    n += 1
            except OSError:
                pass
    except OSError:
        pass
    if n:
        print(f"[spoofer] {n} dossier(s) temporaire(s) d'un spoof interrompu retire(s)")
    return n


def _marquer(uid: int, info) -> None:
    d = safe_json.load(MARQUEUR, default={}) or {}
    d = d if isinstance(d, dict) else {}
    if info is None:
        d.pop(str(uid), None)
    else:
        d[str(uid)] = info
    MARQUEUR.parent.mkdir(parents=True, exist_ok=True)
    safe_json.write(MARQUEUR, d, indent=1)


def _bien_range(menu, spf) -> bool:
    """Le -spoofer est-il juste apres le -menu, dans le meme dossier ?"""
    cat = getattr(menu, "category", None)
    if cat is None or getattr(spf, "category", None) is not cat:
        return getattr(spf, "category", None) is cat
    ordre = sorted(getattr(cat, "text_channels", []) or [], key=lambda c: c.position)
    try:
        return ordre.index(spf) == ordre.index(menu) + 1
    except ValueError:
        return True           # introuvable dans le cache : on ne force rien


# ─────────────────────────────────────────────────────────────────── cog ──

class Spoofer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        #: un spoof a la fois par VA
        self.en_cours = set()
        #: fenetres d'avant redemarrage reprises (gardees jusqu'a leur fin)
        self._taches = set()
        #: le marqueur n'est lu qu'au premier tour (apres le redemarrage) : au
        #: tour de 24 h il annoncait « interrompu » a un spoof EN COURS
        self._marqueur_lu = False

    async def cog_load(self):
        try:
            self.bot.add_dynamic_items(SpfQte, SpfGo)
        except Exception as e:                               # noqa: BLE001
            print(f"[spoofer] boutons non rattaches : {e}")
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()               # photos HEIC d'iPhone
        except Exception as e:                               # noqa: BLE001
            print(f"[spoofer] HEIC non lisible : {e}")
        _balayer_temporaires()
        try:
            if not self._entretien.is_running():
                self._entretien.start()
        except Exception as e:                               # noqa: BLE001
            print(f"[spoofer] entretien non lance : {e}")

    async def cog_unload(self):
        try:
            self._entretien.cancel()
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_interaction(self, interaction):
        """Une fenetre ouverte AVANT un redemarrage et validee apres : elle est
        reconstruite a partir de son custom_id et traitee comme les autres."""
        if interaction.type is not discord.InteractionType.modal_submit:
            return
        data = interaction.data or {}
        cid = str(data.get("custom_id") or "")
        if not cid.startswith(("spf:fen:", "spf:qte:")) or cid in _OUVERTES:
            return                        # fenetre de ce processus : discord.py s'en charge
        print(f"[spoofer] fenetre d'avant redemarrage reprise : {cid}")
        try:
            if cid.startswith("spf:fen:"):
                m = FenetreFichier(cid.split(":")[2], custom_id=cid)
            else:
                m = FenetreQuantite(custom_id=cid)
            t = m._dispatch_submit(interaction, data.get("components") or [],
                                   data.get("resolved") or {})
            self._taches.add(t)
            t.add_done_callback(self._taches.discard)
        except Exception as e:                               # noqa: BLE001
            print(f"[spoofer] fenetre {cid} non reprise : {type(e).__name__}: {e}")

    # ------------------------------------------------------------ travail --

    async def traiter(self, interaction, piece, q: int) -> dict:
        """Telecharge la piece, fabrique q versions, les livre dans -content.
        Rend un bilan (utile aux tests et au journal)."""
        q = _borne(q)
        cible = _cible_content(interaction)
        nom = str(getattr(piece, "filename", "") or "fichier")
        ext = Path(nom).suffix.lower()
        bilan = {"q": q, "livrees": 0, "ratees": 0, "lourdes": 0, "refus": ""}
        if cible is None:
            # salon commun sans salon va- (le bouton l'a deja refuse ; une
            # fenetre ouverte avant que le salon disparaisse arrive ici)
            from cogs.outils import SANS_SALON
            bilan["refus"] = "salon"
            await _dire(interaction, SANS_SALON)
            return bilan
        if ext not in VIDEOS and ext not in PHOTOS:
            bilan["refus"] = "format"
            await _dire(interaction, f"📎 {nom} : format non pris (photo ou vidéo).")
            return bilan
        # La vraie limite est celle que Discord annonce pour cette interaction
        # (10 Mio codes en dur dans discord.py, 20 depuis septembre) ; on prend
        # la plus grande des deux, et un 413 reste compte.
        taille = int(getattr(piece, "size", 0) or 0)
        if taille > TAILLE_MAX:
            bilan["refus"] = "taille"
            await _dire(interaction, f"📎 {nom} : {taille // 1048576} Mo, trop lourd "
                                     f"(au plus {TAILLE_MAX // 1048576} Mo).")
            return bilan
        from cogs import telechargement as tl
        limite = max(tl._limite(cible), int(getattr(interaction, "filesize_limit", 0) or 0))
        video = ext in VIDEOS
        # En « metadonnees seules », une version pese autant que la source :
        # une video trop lourde pour repartir passe en mode complet (debit
        # borne). Un .webm / .mkv aussi : le remux en .mp4 n'est pas fiable.
        complet = True if (video and (taille > limite - tl._MARGE_ENVOI
                                      or ext in _A_REENCODER)) else None
        uid = int(getattr(interaction.user, "id", 0) or 0)
        _marquer(uid, {"salon": getattr(cible, "id", None), "fichier": nom[:120],
                       "q": q, "t": int(time.time())})
        try:
            with tempfile.TemporaryDirectory(prefix="spoof_") as d:
                d = Path(d)
                src = d / ("source" + ext)
                # tout de suite : l'adresse du fichier chez Discord expire
                await piece.save(src)
                if complet and await _trop_longue(src, limite - tl._MARGE_ENVOI):
                    # _brider_debit ne descend pas sous 800 kbps (audio 128 au
                    # moins) : au-dela, AUCUNE version ne tient -- q re-encodages
                    # sous le verrou unique pour « 0/q trop lourdes » (mesure :
                    # 100 s -> 12,2 Mo pour 9,75 permis). On le dit sans encoder.
                    bilan["refus"] = "duree"
                    bilan["lourdes"] = q
                    raise _Refus(f"📎 {nom} : trop longue pour tenir sur Discord "
                                 "une fois re-encodée — envoie-la plus courte.")
                async with _FILE:
                    if video:
                        sorties, ratees = await versions_video(
                            src, d, q, f"spoofer {getattr(interaction.user, 'name', uid)}",
                            complet=complet, force_ext=".mp4" if ext in _A_REENCODER else None)
                    else:
                        sorties, ratees = await versions_photo(src, d, q)
                bilan["ratees"] = ratees
                lots, lourds = tl.repartir(sorties, limite)
                bilan["lourdes"] = len(lourds)
                for i, lot in enumerate(lots):
                    ok, trop, _err = await tl._poster(cible, "", lot)
                    if ok:
                        bilan["livrees"] += len(lot)
                    elif trop:
                        bilan["lourdes"] += len(lot)
                    else:
                        bilan["ratees"] += len(lot)
                    if i < len(lots) - 1:
                        await asyncio.sleep(PAUSE_ENVOI)
        except _Refus as e:
            await tl._poster(cible, str(e))
            _marquer(uid, None)
            return bilan
        except Exception as e:                               # noqa: BLE001
            print(f"[spoofer] {nom} : {type(e).__name__}: {e}")
            bilan["ratees"] = q - bilan["livrees"]
        finally:
            _marquer(uid, None)
        if bilan["livrees"] < q:
            morceaux = []
            if bilan["ratees"]:
                morceaux.append(f"{bilan['ratees']} ratée(s)")
            if bilan["lourdes"]:
                morceaux.append(f"{bilan['lourdes']} trop lourde(s) pour Discord")
            await tl._poster(cible, f"🎭 {nom} : {bilan['livrees']}/{q}"
                             + (" — " + ", ".join(morceaux) if morceaux else ""))
        print(f"[spoofer] {nom} ({'video' if video else 'photo'}, "
              f"{int(getattr(piece, 'size', 0) or 0) // 1024} Ko, limite {limite // 1048576} Mo"
              f"{', complet' if complet else ''}) : {bilan}")
        return bilan

    # -------------------------------------------------------- les salons --

    async def assurer_panneau(self, canal) -> int:
        """Le panneau du salon, a jour et seul. Un salon deja bon n'est pas
        touche. Seuls les PANNEAUX du bot partent : une livraison de repli
        (sans salon -content) peut vivre ici. Rend 1 si un panneau est pose."""
        if not _est_salon_spoofer(canal):
            return 0
        moi = getattr(getattr(self.bot, "user", None), "id", 0)
        try:
            # 200 : sans -content, les livraisons de repli vivent ici, et au-dela
            # de 50 le panneau n'etait plus vu -- un second etait pose
            panneaux = [m async for m in canal.history(limit=200) if est_panneau(m, moi)]
        except Exception as e:                               # noqa: BLE001
            print(f"[spoofer] #{getattr(canal, 'name', '?')} illisible : {e}")
            return 0
        if len(panneaux) == 1 and panneau_a_jour(panneaux[0], moi):
            return 0
        # le nombre que le VA avait choisi suit le panneau repose
        q = QTE_DEFAUT
        for m in panneaux:
            for cid in _custom_ids(m):
                if cid.startswith("spf:qb:"):
                    q = _borne(cid.rsplit(":", 1)[-1])
        for m in panneaux:
            try:
                await m.delete()
            except Exception as e:                           # noqa: BLE001
                print(f"[spoofer] ancien panneau non retire de #{getattr(canal, 'name', '?')} : {e}")
        try:
            f = fichier_icone()
            if f is not None:
                await canal.send(view=panneau(q, icone=True), file=f)
            else:
                await canal.send(view=panneau(q, icone=False))
            return 1
        except Exception as e:                               # noqa: BLE001
            print(f"[spoofer] panneau non pose dans #{getattr(canal, 'name', '?')} : {e}")
            return 0

    async def _provisionner(self, guilde) -> int:
        """Les VA deja la recoivent leur -spoofer par le chemin normal de
        creation (create_us_tickets : droits, ordre, panneau). JAMAIS par
        /ticketsall, qui supprimerait les dossiers des VA renommes."""
        from cogs.welcome import _us_ticket_name, create_us_tickets
        # LA cle de welcome (nom_sans_decor) ; le PREMIER du nom, comme
        # discord.utils.find dans create_us_tickets
        par_nom = {}
        for c in guilde.text_channels:
            par_nom.setdefault(_norm(c.name), c)
        faits = 0
        for m in list(getattr(guilde, "members", []) or []):
            if getattr(m, "bot", False):
                continue
            menu = par_nom.get(_us_ticket_name(m, "menu"))
            spf = par_nom.get(_us_ticket_name(m, "spoofer"))
            if menu is None or (spf is not None and _bien_range(menu, spf)):
                continue
            try:
                if spf is None or getattr(menu, "category", None) is None \
                        or getattr(spf, "category", None) is not menu.category:
                    _cr, err = await create_us_tickets(guilde, m, self.bot)
                    if err:
                        print(f"[spoofer] dossier de {m.name} : {err}")
                else:
                    # seulement mal range : UN deplacement. Relancer tout
                    # create_us_tickets ne deplacait rien quand un salon etranger
                    # separait -menu et -spoofer, mais reposait le panneau -download
                    # a chaque demarrage.
                    await spf.move(after=menu, category=menu.category,
                                   reason="-spoofer juste apres -menu")
                faits += 1
            except Exception as e:                           # noqa: BLE001
                print(f"[spoofer] dossier de {getattr(m, 'name', '?')} : {type(e).__name__}: {e}")
            await asyncio.sleep(1.0)
        return faits

    async def _prevenir_interrompus(self) -> None:
        """Un spoof coupe par un redemarrage : le VA l'apprend. Une fois, au
        premier tour ; seuls les spoofs qui NE tournent PAS sont annonces et
        retires du marqueur (un spoof lance entre-temps y reste)."""
        if self._marqueur_lu:
            return
        self._marqueur_lu = True
        d = safe_json.load(MARQUEUR, default={}) or {}
        if not isinstance(d, dict) or not d:
            return
        dits = []
        for uid, info in list(d.items()):
            if str(uid).isdigit() and int(uid) in self.en_cours:
                continue
            try:
                salon = self.bot.get_channel(int((info or {}).get("salon") or 0))
                if salon is not None:
                    await salon.send(f"🎭 {info.get('fichier', 'fichier')} : interrompu par un "
                                     "redémarrage, renvoie-le.")
                else:
                    print(f"[spoofer] spoof interrompu de {uid} : salon introuvable")
            except Exception as e:                           # noqa: BLE001
                print(f"[spoofer] interruption non signalee a {uid} : {e}")
            dits.append(uid)
        for uid in dits:
            _marquer(uid, None)

    @tasks.loop(hours=24)
    async def _entretien(self):
        try:
            await self._prevenir_interrompus()
        except Exception as e:                               # noqa: BLE001
            print(f"[spoofer] marqueur : {e}")
        try:
            import guild_features as gf
        except Exception:
            gf = None
        for guilde in list(getattr(self.bot, "guilds", []) or []):
            if gf is not None and not gf.is_us_guild(guilde):
                continue
            try:
                n = await self._provisionner(guilde)
                if n:
                    print(f"[spoofer] {n} dossier(s) de VA completes d'un -spoofer")
                # les dossiers dont le VA a change de pseudo : par leurs droits
                try:
                    from cogs.welcome import completer_dossiers_us
                    b = await completer_dossiers_us(guilde, ("spoofer",))
                    if b.get("crees"):
                        await asyncio.sleep(2.0)   # le cache recoit les salons neufs
                except Exception as e:                       # noqa: BLE001
                    print(f"[spoofer] dossiers renommes : {type(e).__name__}: {e}")
                poses = 0
                for canal in list(guilde.text_channels):
                    if _est_salon_spoofer(canal):
                        poses += await self.assurer_panneau(canal)
                if poses:
                    print(f"[spoofer] {poses} panneau(x) pose(s)")
            except Exception as e:                           # noqa: BLE001
                print(f"[spoofer] entretien de {getattr(guilde, 'name', '?')} : "
                      f"{type(e).__name__}: {e}")

    @_entretien.before_loop
    async def _avant_entretien(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Spoofer(bot))
