# -*- coding: utf-8 -*-
"""tests_sans_texte.py — la version SANS TEXTE des montages, et leurs textes.

Propriétaire, 01/11/2026 : pour Caption, Template, Trash et Flash, la vidéo
avec son texte, la même sans, puis chaque texte seul (copier-coller facile).

Ce qui est vérifié (sans_texte, cogs/user._livrer_avec_sans_texte et les
deux livraisons de montage) :
  - les textes du brouillon, dans l'ordre, une fois, liste ou JSON ;
  - la vidéo d'entrée du rendu : trouvée, absente, ambiguë ;
  - Template/Trash/Flash : UNE carte, à gauche la vidéo sans texte (l'ENTRÉE
    du rendu), à droite la même déjà prête (« à gauche la fraîche, à droite
    celle déjà good »), puis chaque texte du bot seul, puis la description ;
  - Caption : pareil, la brute sans la caption à gauche ;
  - la paire trop lourde ensemble : une carte chacune, la prête d'abord ;
  - le « ne poste pas » (repli) : rien de plus ; variante de la réserve ou
    rendu purgé : la carte de la vidéo prête, puis les textes ;
  - la vidéo sans texte passe par brute_a_envoyer (uniquification), et un
    échec de l'uniquification met le liseré rouge.

Faux moteur, fausse interaction, dossier temporaire : rien dans data/, aucun
appel réseau. Lancement : python tests_sans_texte.py
"""
from __future__ import annotations

import asyncio
import io
import os
import pathlib
import shutil
import sys
import tempfile
from types import SimpleNamespace

os.environ["VABOT_BANC_ESSAI"] = "1"
BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
try:                                   # console Windows en cp1252
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import discord                         # noqa: E402
import noctus_web                      # noqa: E402
import sans_texte                      # noqa: E402
from cogs import user as u             # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label + (f"  [{str(detail)[:600]}]" if detail and not cond else ""))


TMP = pathlib.Path(tempfile.mkdtemp(prefix="sans_texte_"))
MODELS = TMP / "models"


def rendu(model, entrees=("asm1_x.mp4",)):
    """Un rendu Noctus : ses vidéos d'entrée et sa sortie (avec texte)."""
    (MODELS / model / "input").mkdir(parents=True, exist_ok=True)
    for n in entrees:
        (MODELS / model / "input" / n).write_bytes(b"\x00" * 2048)
    sortie = MODELS / model / "output" / "V1" / "out.mp4"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_bytes(b"\x01" * 4096)
    return sortie


class Suivi:
    def __init__(self):
        self.envois = []

    async def send(self, content=None, **kw):
        textes, noms = [], []
        vue = kw.get("view")
        if vue is not None:
            textes = [c.content for c in vue.walk_children() if isinstance(c, discord.ui.TextDisplay)]
        for f in kw.get("files") or ([kw["file"]] if kw.get("file") else []):
            noms.append(f.filename)
        self.envois.append({"content": content, "textes": textes, "fichiers": noms})
        return SimpleNamespace(id=len(self.envois))


def itx():
    return SimpleNamespace(guild=None, user=SimpleNamespace(id=7, name="va", display_name="va"),
                           channel_id=9, channel=None, followup=Suivi(),
                           response=SimpleNamespace(is_done=lambda: True))


def courir(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def resume(envois):
    """Chaque envoi en une ligne : « carte[fichiers] » ou le texte seul."""
    out = []
    for e in envois:
        if e["fichiers"]:
            out.append(("carte", tuple(e["fichiers"]), tuple(e["textes"])))
        else:
            out.append(("texte", e["content"]))
    return out


_SAUVE = {
    "nw": {k: getattr(noctus_web, k) for k in ("_models_dir", "gen_from_draft", "status",
                                              "output_paths")},
    "u": {k: getattr(u, k) for k in ("load_transform_config", "_dossier_brutes",
                                     "transform_metadata_strict")},
}
try:
    noctus_web._models_dir = lambda: MODELS
    u.load_transform_config = lambda: {"enabled": False}
    u._dossier_brutes = lambda ident: TMP / "brutes"

    # ── 1. les textes du brouillon ───────────────────────────────────────
    check("textes : dans l'ordre, chacun une fois, vides sautés (segments en liste)",
          sans_texte.textes({"segments": [{"text": " A "}, {"text": ""}, {"text": "B"}, {"text": "A"}]})
          == ["A", "B"])
    check("textes : segments en JSON (comme l'éditeur les écrit)",
          sans_texte.textes({"segments": '[{"text": "x"}, {"text": "y"}]'}) == ["x", "y"])
    check("textes : brouillon absent ou illisible -> aucun",
          sans_texte.textes(None) == [] and sans_texte.textes({"segments": "{casse"}) == [])

    # ── 2. la vidéo d'entrée du rendu ────────────────────────────────────
    rendu("vam-un")
    rendu("vam-deux", entrees=("a.mp4", "b.mp4"))
    check("entrée : la vidéo avant ses textes",
          sans_texte.video_du_rendu("vam-un") == MODELS / "vam-un" / "input" / "asm1_x.mp4")
    check("entrée : rendu inconnu, ou deux vidéos (on ne devine pas) -> None",
          sans_texte.video_du_rendu("vam-rien") is None and sans_texte.video_du_rendu("vam-deux") is None
          and sans_texte.video_du_rendu("") is None)

    # ── 3. Template / Trash / Flash ──────────────────────────────────────
    DRAFT = {"segments": [{"text": "The view outside was amazing", "start": 0, "end": 2},
                          {"text": "POV: me", "start": 2, "end": 4}]}
    ETAT = {"n": 0}

    def faux_gen(src, draft, folders, model, brutes, report=None):
        ETAT["n"] += 1
        m = f"vam-flash{ETAT['n']}"
        rendu(m)
        return m

    noctus_web.gen_from_draft = faux_gen
    noctus_web.status = lambda m: {"state": "done"}
    noctus_web.output_paths = lambda m: [MODELS / m / "output" / "V1" / "out.mp4"]
    cog = u.UserCog(SimpleNamespace())
    src = TMP / "template.mp4"
    src.write_bytes(b"\x02" * 1024)
    i = itx()
    courir(cog._gen_and_send_montaged(i, src, DRAFT, "ma description", 1, 1, "brune",
                                      prefixe_fichier="flash"))
    r = resume(i.followup.envois)
    check("Flash : UNE carte, à gauche la vidéo sans texte, à droite la même déjà prête",
          r[0][0] == "carte" and r[0][1] == ("flash_1_sans_texte.mp4", "flash_1.mp4")
          and len([x for x in r if x[0] == "carte"]) == 1, r[:1])
    check("… puis chaque texte du bot SEUL, dans l'ordre, puis la description seule",
          [x[1] for x in r[1:]] == ["The view outside was amazing", "POV: me", "ma description"]
          and all(x[0] == "texte" for x in r[1:]), r[1:])

    # la paire refusée (trop lourde ENSEMBLE) : une carte chacune
    class SuiviLourd(Suivi):
        async def send(self, content=None, **kw):
            if len(kw.get("files") or []) > 1:
                raise discord.HTTPException(SimpleNamespace(status=413, reason="Payload Too Large"),
                                            {"code": 40005, "message": "Request entity too large"})
            return await super().send(content, **kw)

    i = itx()
    i.followup = SuiviLourd()
    courir(cog._gen_and_send_montaged(i, src, DRAFT, "ma description", 1, 1, "brune",
                                      prefixe_fichier="flash"))
    r = resume(i.followup.envois)
    check("paire trop lourde ensemble : la prête d'abord, puis la sans texte, puis les textes",
          [x[:2] for x in r[:2]] == [("carte", ("flash_1.mp4",)), ("carte", ("flash_1_sans_texte.mp4",))]
          and "sans texte" in r[1][2]
          and [x[1] for x in r[2:]] == ["The view outside was amazing", "POV: me", "ma description"], r)

    # le repli (template entier, « ne poste pas ») : rien de plus
    def faux_gen_repli(src, draft, folders, model, brutes, report=None):
        m = faux_gen(src, draft, folders, model, brutes, report)
        if report is not None:
            report.update({"repli": True, "message": "aucune brute"})
        return m

    noctus_web.gen_from_draft = faux_gen_repli
    i = itx()
    courir(cog._gen_and_send_montaged(i, src, DRAFT, "ma description", 1, 1, "brune"))
    r = resume(i.followup.envois)
    check("« ne poste pas » (repli) : la seule carte, rouge, ni version sans texte ni textes",
          len(r) == 1 and r[0][0] == "carte", r)
    noctus_web.gen_from_draft = faux_gen

    # rendu purgé avant l'envoi : les textes partent quand même
    noctus_web.output_paths = lambda m: (shutil.rmtree(MODELS / m / "input"),
                                         [MODELS / m / "output" / "V1" / "out.mp4"])[1]
    i = itx()
    courir(cog._gen_and_send_montaged(i, src, DRAFT, "ma description", 1, 1, "brune"))
    r = resume(i.followup.envois)
    check("entrée du rendu disparue : la carte de la vidéo prête, puis les textes seuls (rien de perdu)",
          [x[0] for x in r] == ["carte", "texte", "texte", "texte"]
          and r[1][1] == "The view outside was amazing", r)
    noctus_web.output_paths = lambda m: [MODELS / m / "output" / "V1" / "out.mp4"]

    # ── 4. Caption ───────────────────────────────────────────────────────
    cap = {"id": "c1", "text": "Men I'm not joking", "desc": "lien en bio"}
    block = {"font": "Strong", "items": [cap]}
    brute = TMP / "brute.mp4"
    brute.write_bytes(b"\x03" * 1024)
    i = itx()
    courir(cog._gen_and_send_caption(i, brute, cap, block, 1, 1, "brune"))
    r = resume(i.followup.envois)
    check("Caption : UNE carte (la brute sans la caption à gauche), la caption seule, la description seule",
          [x[0] for x in r] == ["carte", "texte", "texte"]
          and r[0][1] == ("reel_caption_1_sans_texte.mp4", "reel_caption_1.mp4")
          and [r[1][1], r[2][1]] == ["Men I'm not joking", "lien en bio"], r)

    # ── 5. l'uniquification ──────────────────────────────────────────────
    vus = []

    def faux_meta(video, sortie, **kw):
        vus.append(pathlib.Path(video).name)
        pathlib.Path(sortie).write_bytes(b"\x04" * 512)
        return True

    u.load_transform_config = lambda: {"enabled": True, "metadata_only": True}
    u.transform_metadata_strict = faux_meta
    PRETE = MODELS / "vam-un" / "output" / "V1" / "out.mp4"
    i = itx()
    courir(u._livrer_avec_sans_texte(i, 1, 1, "brune", PRETE, "x.mp4", "vam-un", DRAFT, "FLASH 1/1"))
    check("la version sans texte passe par brute_a_envoyer : métadonnées réécrites (uniquification)",
          vus == ["asm1_x.mp4"] and resume(i.followup.envois)[0][1] == ("x_sans_texte.mp4", "x.mp4"),
          (vus, resume(i.followup.envois)[:1]))
    NOTES = []

    async def faux_noter(interaction, identite, medias, recette, quoi):
        NOTES.append((list(medias), recette))
    _vrai_noter = u._noter_livraison
    u._noter_livraison = faux_noter
    try:
        courir(u._livrer_avec_sans_texte(itx(), 1, 1, "brune", PRETE, "x.mp4", "vam-un", DRAFT,
                                         "FLASH 1/1", recette={"action": "FLASH"}))
    finally:
        u._noter_livraison = _vrai_noter
    check("les favoris notent la vidéo DÉJÀ PRÊTE (à droite), jamais la sans texte",
          len(NOTES) == 1 and [n for _c, n in NOTES[0][0]] == ["x.mp4"]
          and NOTES[0][1] == {"action": "FLASH"}, NOTES)
    u.transform_metadata_strict = lambda video, sortie, **kw: False
    i = itx()
    courir(u._livrer_avec_sans_texte(i, 1, 1, "brune", PRETE, "x.mp4", "vam-un", DRAFT, "FLASH 1/1"))
    t0 = resume(i.followup.envois)[0][2]
    check("… uniquification ratée : la carte le dit (ne pas poster la version sans texte telle quelle)",
          any("sans texte n a **pas** pu etre rendue unique" in t for t in t0), t0)
    u.load_transform_config = lambda: {"enabled": False}

    # ── 6. variante de la réserve : textes seuls ─────────────────────────
    i = itx()
    courir(u._livrer_avec_sans_texte(i, 1, 1, "brune", PRETE, "x.mp4", None, DRAFT, "FLASH 1/1",
                                     textes=[(u._T_DESC, "desc")]))
    r = resume(i.followup.envois)
    check("variante de la réserve (aucun rendu) : la carte de la vidéo prête, les textes du bot "
          "puis la description, seuls",
          r[0][:2] == ("carte", ("x.mp4",)) and r[1:] == [("texte", "The view outside was amazing"),
                                                          ("texte", "POV: me"), ("texte", "desc")], r)
    check("le texte du bot porte son étiquette « ✍️ Texte »", u._ETIQUETTES.get(u._T_ECRIT) == "✍️ Texte")
except Exception as e:                                       # noqa: BLE001
    import traceback
    traceback.print_exc()
    check("sans texte : testable", False, repr(e))
finally:
    for k, v in _SAUVE["nw"].items():
        setattr(noctus_web, k, v)
    for k, v in _SAUVE["u"].items():
        setattr(u, k, v)
    shutil.rmtree(TMP, ignore_errors=True)

print()
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
if FAILS:
    print("ECHECS :")
    for f in FAILS:
        print("  -", f)
sys.exit(1 if FAILS else 0)
