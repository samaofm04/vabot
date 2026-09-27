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

VIDEOS = frozenset({".mp4", ".mov", ".m4v"})
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
    return _norm(nom).endswith("-spoofer")


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
        await interaction.response.send_modal(FenetreQuantite(self.q))


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
        await interaction.response.send_modal(FenetreFichier(self.q))


def panneau(q: int = QTE_DEFAUT) -> discord.ui.LayoutView:
    """Le panneau : une rangee, deux boutons, aucun texte."""
    q = _borne(q)
    vue = discord.ui.LayoutView(timeout=None)
    rangee = discord.ui.ActionRow()
    rangee.add_item(SpfQte(q))
    rangee.add_item(SpfGo(q))
    vue.add_item(rangee)
    return vue


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
            and any(c.startswith("spf:go:") for c in ids))


# ───────────────────────────────────────────────────────────── fenetres ──

class FenetreQuantite(discord.ui.Modal, title="🔢"):
    nombre = discord.ui.TextInput(label="Combien de versions (1 à 5)", placeholder="5",
                                  required=True, min_length=1, max_length=1)

    def __init__(self, q: int = QTE_DEFAUT):
        super().__init__()
        self.nombre.default = str(_borne(q))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            q = int(str(self.nombre.value or "").strip())
        except ValueError:
            q = 0
        if not 1 <= q <= QTE_MAX:
            await _dire(interaction, f"🔢 Choisis un nombre entre 1 et {QTE_MAX}.")
            return
        try:
            await interaction.response.edit_message(view=panneau(q))
        except Exception as e:                               # noqa: BLE001
            print(f"[spoofer] panneau non redessine : {type(e).__name__}: {e}")
            if not interaction.response.is_done():
                await interaction.response.defer()


class FenetreFichier(discord.ui.Modal, title="Spoofer"):
    fichier = discord.ui.Label(
        text="Photo ou vidéo",
        component=discord.ui.FileUpload(min_values=1, max_values=1, required=True))

    def __init__(self, q: int = QTE_DEFAUT):
        super().__init__()
        self.q = _borne(q)

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
                         complet=None) -> tuple:
    """(sorties, ratees) : q versions de la video, par le moteur des brutes."""
    from cogs.user import brute_a_envoyer
    sorties, ratees, vus, pris = [], 0, {_md5(src)}, set()
    for _ in range(q):
        ext = ".mp4" if complet else src.suffix.lower()
        sortie = Path(dossier) / _nom_iphone(ext, pris)
        f, ok, _raison = await brute_a_envoyer(src, dossier, identity=identite,
                                               sortie=sortie, forcer=True, complet=complet)
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
    categorie d'abord). A defaut, le salon ou l'on a clique."""
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


def _marquer(uid: int, info) -> None:
    d = safe_json.load(MARQUEUR, default={}) or {}
    d = d if isinstance(d, dict) else {}
    if info is None:
        d.pop(str(uid), None)
    else:
        d[str(uid)] = info
    MARQUEUR.parent.mkdir(parents=True, exist_ok=True)
    safe_json.write(MARQUEUR, d, indent=1)


# ─────────────────────────────────────────────────────────────────── cog ──

class Spoofer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        #: un spoof a la fois par VA
        self.en_cours = set()

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

    # ------------------------------------------------------------ travail --

    async def traiter(self, interaction, piece, q: int) -> dict:
        """Telecharge la piece, fabrique q versions, les livre dans -content.
        Rend un bilan (utile aux tests et au journal)."""
        q = _borne(q)
        cible = _cible_content(interaction)
        nom = str(getattr(piece, "filename", "") or "fichier")
        ext = Path(nom).suffix.lower()
        bilan = {"q": q, "livrees": 0, "ratees": 0, "lourdes": 0, "refus": ""}
        if ext not in VIDEOS and ext not in PHOTOS:
            bilan["refus"] = "format"
            await _dire(interaction, f"📎 {nom} : format non pris (photo ou vidéo).")
            return bilan
        # La vraie limite est celle que Discord annonce pour cette interaction
        # (10 Mio codes en dur dans discord.py, 20 depuis septembre) ; on prend
        # la plus grande des deux, et un 413 reste compte.
        from cogs import telechargement as tl
        limite = max(tl._limite(cible), int(getattr(interaction, "filesize_limit", 0) or 0))
        video = ext in VIDEOS
        # En « metadonnees seules », une version pese autant que la source :
        # une video trop lourde pour repartir passe en mode complet (debit borne).
        complet = True if (video and int(getattr(piece, "size", 0) or 0)
                           > limite - tl._MARGE_ENVOI) else None
        uid = int(getattr(interaction.user, "id", 0) or 0)
        _marquer(uid, {"salon": getattr(cible, "id", None), "fichier": nom[:120],
                       "q": q, "t": int(time.time())})
        try:
            with tempfile.TemporaryDirectory(prefix="spoof_") as d:
                d = Path(d)
                src = d / ("source" + ext)
                # tout de suite : l'adresse du fichier chez Discord expire
                await piece.save(src)
                async with _FILE:
                    if video:
                        sorties, ratees = await versions_video(
                            src, d, q, f"spoofer {getattr(interaction.user, 'name', uid)}",
                            complet=complet)
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
            panneaux = [m async for m in canal.history(limit=50) if est_panneau(m, moi)]
        except Exception as e:                               # noqa: BLE001
            print(f"[spoofer] #{getattr(canal, 'name', '?')} illisible : {e}")
            return 0
        if len(panneaux) == 1 and panneau_a_jour(panneaux[0], moi):
            return 0
        for m in panneaux:
            try:
                await m.delete()
            except Exception:
                pass
        try:
            await canal.send(view=panneau(QTE_DEFAUT))
            return 1
        except Exception as e:                               # noqa: BLE001
            print(f"[spoofer] panneau non pose dans #{getattr(canal, 'name', '?')} : {e}")
            return 0

    async def _provisionner(self, guilde) -> int:
        """Les VA deja la recoivent leur -spoofer par le chemin normal de
        creation (create_us_tickets : droits, ordre, panneau). JAMAIS par
        /ticketsall, qui supprimerait les dossiers des VA renommes."""
        from cogs.welcome import _us_ticket_name, _us_norm, create_us_tickets
        noms = {_us_norm(c.name) for c in guilde.text_channels}
        faits = 0
        for m in list(getattr(guilde, "members", []) or []):
            if getattr(m, "bot", False):
                continue
            if (_us_ticket_name(m, "menu") in noms
                    and _us_ticket_name(m, "spoofer") not in noms):
                try:
                    _cr, err = await create_us_tickets(guilde, m, self.bot)
                    if err:
                        print(f"[spoofer] dossier de {m.name} : {err}")
                    faits += 1
                except Exception as e:                       # noqa: BLE001
                    print(f"[spoofer] dossier de {getattr(m, 'name', '?')} : {e}")
                await asyncio.sleep(1.0)
        return faits

    async def _prevenir_interrompus(self) -> None:
        """Un spoof coupe par un redemarrage : le VA l'apprend."""
        d = safe_json.load(MARQUEUR, default={}) or {}
        if not isinstance(d, dict) or not d:
            return
        for uid, info in list(d.items()):
            try:
                salon = self.bot.get_channel(int((info or {}).get("salon") or 0))
                if salon is not None:
                    await salon.send(f"🎭 {info.get('fichier', 'fichier')} : interrompu par un "
                                     "redémarrage, renvoie-le.")
            except Exception as e:                           # noqa: BLE001
                print(f"[spoofer] interruption non signalee a {uid} : {e}")
        safe_json.write(MARQUEUR, {}, indent=1)

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
