# -*- coding: utf-8 -*-
"""tests_bangers_miroir.py — les bangers recopiés sur You US et You FR.

Propriétaire, 10/11/2026 : « Sur FR … il va falloir quand même retrouver
banger Emma, banger Amelia … et sur l'autre, comme d'hab, banger et
all-banger », puis « oui, les bangers ».

Ce que ce fichier prouve, dans un dossier temporaire, avec de faux serveurs
Discord et les VRAIS composants de discord.py (aucun réseau, rien d'écrit
dans data/) :
  1. Les destinations : 💥・banger et 💣・all-banger sur You US, un
     🔥・banger-<model> par model sur You FR ; lues dans guild_features.
  2. Ce qui est candidat : seulement ce qui est PARU à la source, dans la
     fenêtre ; un journal illisible est nommé, pas sauté en silence.
  3. Un passage poste chaque carte une fois, dans le bon salon, sans « Géré
     par », sans mention, sans récapitulatif ; le suivant ne poste rien ; la
     parution du lendemain suit.
  4. Sans double envoi : intention laissée par une coupure (message présent
     ou absent), journal perdu (amorce).
  5. Les pannes : salon absent, vidéo trop lourde, refus de Discord, issue
     incertaine, journal impossible à écrire — une destination arrêtée ne
     retient pas les autres.
  6. Les sources ne sont JAMAIS écrites (journaux du matin, registre
     all-banger, détails des fiches).
  7. La carte du matin par défaut ne change pas ; le cog : production
     seulement, bot principal, zéro commande.

Lancement : python tests_bangers_miroir.py
"""
from __future__ import annotations

import ast
import asyncio
import datetime
import hashlib
import io
import json
import logging
import os
import pathlib
import sys
import tempfile
import types

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import discord                          # noqa: E402

import safe_json                        # noqa: E402
import bangers as bg                    # noqa: E402
import all_banger as ab                 # noqa: E402
import bangers_miroir as bm             # noqa: E402
import guild_features as gf             # noqa: E402

OKS, FAILS = [], []


def check(label, cond, detail=""):
    (OKS if cond else FAILS).append(label)
    print(("OK   " if cond else "FAIL ") + label
          + (f"  [{str(detail)[:400]}]" if detail and not cond else ""))


ns = types.SimpleNamespace
DATA = BOT / "data"


def _instantane():
    if not DATA.exists():
        return {}
    return {str(p.relative_to(DATA)): p.stat().st_mtime_ns for p in DATA.rglob("*") if p.is_file()}


AVANT = _instantane()

# ---------------------------------------------------------------- bac à sable --
TMP = pathlib.Path(tempfile.mkdtemp(prefix="bangers_miroir_test_"))
bg.FICHIER = TMP / "bangers.json"
bg.DOSSIER = TMP / "bangers"
bg.DETAILS_DIR = TMP / "bangers_details"
bg.DOSSIER_JOURNEES = TMP / "bangers_journees"
ab.FICHIER = TMP / "bangers_all.json"
bm.JOURNAL = TMP / "miroir" / "bangers_miroir.json"
for _d in (bg.DOSSIER, bg.DETAILS_DIR, bg.DOSSIER_JOURNEES):
    _d.mkdir(parents=True, exist_ok=True)

YOU_US, YOU_FR = int(gf.YOU_US_GUILD_ID), int(gf.YOU_FR_GUILD_ID)
RYUK = 1505416430840189041
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4000

#: Le 10/11/2026 à 09:30, heure de Paris : la publication du matin (journée
#: du 09/11) vient de partir.
NOW = datetime.datetime(2026, 11, 10, 9, 30, tzinfo=bg.TZ).timestamp()


def jour(n):
    """Le jour d'il y a n jours (ISO), vu de NOW."""
    return (datetime.datetime.fromtimestamp(NOW, bg.TZ).date() - datetime.timedelta(days=n)).isoformat()


def video(sc, taille=None):
    (bg.DOSSIER / f"{sc}.mp4").write_bytes(MP4 if taille is None else b"\x00\x00\x00\x18ftyp" + b"\x00" * taille)


def fiche(sc, compte, j, **kw):
    f = {"shortcode": sc, "compte": compte, "url": f"https://www.instagram.com/reel/{sc}/",
         "vues": 12400, "vues_actuelles": 15000, "likes": 210, "commentaires": 3,
         "description": f"Légende de {sc} #viral_one", "jour_bilan": j, "video_disponible": True,
         "statistiques_le": int(NOW) - 3600, "va": "Safidy", "discord_id": "424242",
         "annonce": {"message_id": 999, "channel_id": 1548115360702664804}}
    f.update(kw)
    return f


def journal(dossier, j, reels, **kw):
    dossier = pathlib.Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    record = {"schema": 1, "jour": j, "seuil": 10000, "reels": reels, "format": bg.FORMAT_DISCORD,
              "termine": True, "recaps": [{"texte": "## Bangers", "etat": "envoye", "message_id": 5}]}
    record.update(kw)
    safe_json.write(dossier / f"{j}.json", record)


def item(f, etat="envoye", mid=7000):
    return {"etat": etat, "message_id": mid if etat == "envoye" else None, "prepare": True, "fiche": f}


# ── la source : Youl4b (Jessye), deux journées dans la fenêtre, une trop vieille
journal(bg.DOSSIER_JOURNEES, jour(2), {
    "USaaa1": item(fiche("USaaa1", "jessy.one", jour(2))),
    "USaaa2": item(fiche("USaaa2", "jessy.two", jour(2), video_disponible=False)),
})
journal(bg.DOSSIER_JOURNEES, jour(1), {
    "USbbb1": item(fiche("USbbb1", "jessy.one", jour(1))),
    "USattente": item(fiche("USattente", "jessy.x", jour(1)), etat="attente"),
    "USdoublon": dict(item(fiche("USdoublon", "jessy.y", jour(1)), etat="doublon"), doublon_de="USbbb1"),
})
journal(bg.DOSSIER_JOURNEES, jour(30), {"USvieux": item(fiche("USvieux", "jessy.old", jour(30)))})
(bg.DOSSIER_JOURNEES / "notes.json").write_text("{}", encoding="utf-8")       # pas une journée
# ── Va IG : Emma (2 jours) et Amelia (1) ; les autres models n'ont rien
journal(bg.DOSSIER_JOURNEES / "fr" / "emma", jour(1), {
    "FRemma1": item(fiche("FRemma1", "emma.va2", jour(1), va_libelle="Emma VA 2", va_numero=2,
                          discord_id=None, statistiques_source="scrape")),
}, salon="fr:emma")
journal(bg.DOSSIER_JOURNEES / "fr" / "amelia", jour(1), {
    "FRamelia1": item(fiche("FRamelia1", "amelia.va1", jour(1), va_libelle="Amelia VA 3", va_numero=3)),
}, salon="fr:amelia")
for sc in ("USaaa1", "USbbb1", "FRemma1", "FRamelia1", "ALLus1", "ALLus2", "ALLlourd", "ALLvieux"):
    video(sc)
video("ALLlourd", taille=11 * 1024 * 1024)

# ── le registre all-banger : deux bangers de Youl4b, une jumelle FR, un marché FR,
# un prêt (pas encore posté), un trop vieux, un d'avant le champ « marche »
H = 3600
safe_json.write(ab.FICHIER, {"schema": 1, "reels": {
    "ALLus2": {"etat": "envoye", "message_id": 82, "channel_id": 1553240454961569832,
               "envoye_le": int(NOW) - 2 * H, "marche": "us"},
    "ALLus1": {"etat": "envoye", "message_id": 81, "channel_id": 1553240454961569832,
               "envoye_le": int(NOW) - 30 * H},                       # sans « marche » : Youl4b
    "ALLus1@fr:lola": {"etat": "envoye", "message_id": 83, "envoye_le": int(NOW) - H,
                       "marche": "fr:lola", "reel": "ALLus1"},
    "ALLfr1": {"etat": "envoye", "message_id": 84, "envoye_le": int(NOW) - H, "marche": "fr:emma"},
    "ALLpret": {"etat": "pret", "detecte_le": int(NOW) - H},
    "ALLvieux": {"etat": "envoye", "message_id": 85, "envoye_le": int(NOW) - 40 * 24 * H, "marche": "us"},
    "ALLlourd": {"etat": "envoye", "message_id": 86, "envoye_le": int(NOW) - H // 2, "marche": "us"},
    "ALLsansvideo": {"etat": "envoye", "message_id": 87, "envoye_le": int(NOW) - H // 4, "marche": "us"},
}})
safe_json.write(bg.FICHIER, {"seuil": 10000, "reels": {
    "ALLus1": {"shortcode": "ALLus1", "compte": "jessy.one", "vues": 20000, "description": "Desc ALLus1",
               "url": "https://www.instagram.com/reel/ALLus1/"},
    "ALLus2": {"shortcode": "ALLus2", "compte": "jessy.two", "vues": 31000, "description": "Desc ALLus2",
               "url": "https://www.instagram.com/reel/ALLus2/"},
}})


def _empreinte_sources():
    h = hashlib.sha256()
    for racine in (bg.DOSSIER_JOURNEES, bg.DETAILS_DIR):
        for p in sorted(racine.rglob("*")):
            if p.is_file():
                h.update(str(p.relative_to(TMP)).encode() + p.read_bytes())
    for p in (ab.FICHIER, bg.FICHIER):
        h.update(p.read_bytes())
    return h.hexdigest()


SOURCES_AVANT = _empreinte_sources()


# ─────────────────────────────────────────────────────── faux Discord ──

class Rep:
    def __init__(self, status):
        self.status, self.reason = status, "x"


class Message:
    _n = 500000

    def __init__(self, salon, auteur, view, files, nonce):
        Message._n += 1
        self.id, self.channel, self.nonce = Message._n, salon, nonce
        self.author = ns(id=auteur)
        self.attachments = [ns(filename=getattr(f, "filename", None)) for f in files or []]
        self.payload = view.to_components() if view is not None else []
        self.components = [ns(to_dict=lambda d=d: d) for d in self.payload]
        self.created_at = datetime.datetime.fromtimestamp(Salon.horloge, datetime.timezone.utc)

    def textes(self):
        out, pile = [], list(self.payload)
        while pile:
            c = pile.pop()
            if isinstance(c, dict):
                if c.get("type") == 10:
                    out.append(c.get("content") or "")
                pile += [v for v in c.values() if isinstance(v, (dict, list))]
            elif isinstance(c, list):
                pile += c
        return "\n".join(out)


class Salon:
    _n = 9000
    horloge = NOW

    def __init__(self, guild, nom, cat=None):
        Salon._n += 1
        self.id, self.name, self.guild, self.category = Salon._n, nom, guild, cat
        self.position = Salon._n
        self.messages = []
        self.envois = 0
        #: une exception à lever au prochain envoi (puis effacée), ou à tous
        self.casse, self.casse_toujours = None, None
        #: l'envoi PART mais la réponse se perd (issue incertaine)
        self.perd_reponse = False
        self.historique_casse = False
        self.droits = dict(view_channel=True, send_messages=True, attach_files=True,
                           read_message_history=True)

    def permissions_for(self, m):
        return ns(**self.droits)

    async def send(self, view=None, files=None, nonce=None, allowed_mentions=None, **kw):
        self.envois += 1
        ex = self.casse_toujours or self.casse
        self.casse = None
        if ex is not None:
            raise ex
        self.dernieres_mentions = allowed_mentions
        m = Message(self, RYUK, view, files, nonce)
        self.messages.append(m)
        if self.perd_reponse:
            self.perd_reponse = False
            raise discord.HTTPException(Rep(502), "Bad Gateway")
        return m

    def history(self, limit=100, after=None, **kw):
        if self.historique_casse:
            raise discord.HTTPException(Rep(403), "Missing Access")
        msgs = [m for m in reversed(self.messages) if after is None or m.created_at > after][:limit]

        async def gen():
            for m in msgs:
                yield m
        return gen()


class Guilde:
    def __init__(self, gid, nom, salons):
        self.id, self.name, self.unavailable = gid, nom, False
        self.me = ns(id=RYUK)
        self.filesize_limit = 10 * 1024 * 1024
        self.text_channels = [Salon(self, n) for n in salons]

    def salon(self, fin):
        return next(c for c in self.text_channels if c.name.endswith(fin))


class Client:
    def __init__(self, guildes):
        self.user = ns(id=RYUK)
        self._g = {g.id: g for g in guildes}

    def get_guild(self, gid):
        return self._g.get(int(gid))


def serveurs():
    us = Guilde(YOU_US, "You US", ["💬・général", "💥・banger", "💣・all-banger"])
    fr = Guilde(YOU_FR, "You FR", ["💬・général"] + ["🔥・banger-" + m for m in bg.MODELS_FR])
    return us, fr, Client([us, fr])


SOMMEILS = []


async def _dormir(s):
    SOMMEILS.append(s)


def passer(client, **kw):
    kw.setdefault("maintenant", NOW)
    return asyncio.run(bm.tour(client, dormir=_dormir, **kw))


class Ecoute(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lignes = []

    def emit(self, rec):
        self.lignes.append(rec.getMessage())


ECOUTE = Ecoute()
bm.log.addHandler(ECOUTE)
bm.log.setLevel(logging.INFO)


# ══════════════════════════════════════════════ 1. les destinations ══
print("1. Destinations")
dests = bm.destinations()
par_cle = {d["cle"]: d for d in dests}
check("You US : 💥・banger (matin de Jessye) et 💣・all-banger",
      {(d["nom"], d["genre"]) for d in dests if d["guild_id"] == YOU_US}
      == {("banger", "matin"), ("all-banger", "all")}
      and par_cle[f"{YOU_US}:banger"]["source"]["cle"] == "us")
check("You FR : un 🔥・banger-<model> par model de Va IG, rien d'autre",
      [(d["nom"], d["genre"], d["source"]["cle"]) for d in dests if d["guild_id"] == YOU_FR]
      == [("banger-" + m, "matin", "fr:" + m) for m in bg.MODELS_FR])
check("aucune destination sur Youl4b, YouCham ni Va IG",
      {d["guild_id"] for d in dests} == {YOU_US, YOU_FR})
check("la table vit dans guild_features (BANGERS_MIROIR), à part du marché",
      gf.BANGERS_MIROIR == {gf.YOU_US_GUILD_ID: "us", gf.YOU_FR_GUILD_ID: "fr"}
      and gf.BANGERS_MIROIR is not gf.MARCHE_SERVEUR)
_src = (BOT / "bangers_miroir.py").read_text(encoding="utf-8")
check("bangers_miroir ne recopie aucun id de serveur",
      not any(str(g) in _src for g in (YOU_US, YOU_FR, bg.GUILD_ID, bg.GUILD_FR)))
_sauve_bm = dict(gf.BANGERS_MIROIR)
gf.BANGERS_MIROIR.clear()
check("table vide : aucune destination (la copie se coupe sans toucher au menu)",
      bm.destinations() == [] and gf.marche_serveur(YOU_FR) == "fr")
gf.BANGERS_MIROIR.update(_sauve_bm)
us, fr, client = serveurs()
check("les salons sont retrouvés par leur nom sans décor",
      bm.salon_de(us, par_cle[f"{YOU_US}:banger"]) is us.salon("・banger")
      and bm.salon_de(us, par_cle[f"{YOU_US}:all-banger"]) is us.salon("all-banger")
      and bm.salon_de(fr, par_cle[f"{YOU_FR}:banger-emma"]) is fr.salon("banger-emma"))
check("💥・banger n'est jamais confondu avec 💣・all-banger ni un banger-<model>",
      bm.salon_de(fr, par_cle[f"{YOU_US}:banger"]) is None
      and bm.salon_de(us, par_cle[f"{YOU_FR}:banger-emma"]) is None)
check("un nonce par salon pour le même reel",
      bm.nonce(par_cle[f"{YOU_US}:banger"], "X") != bm.nonce(par_cle[f"{YOU_US}:all-banger"], "X")
      and len(bm.nonce(par_cle[f"{YOU_US}:banger"], "X")) <= 25)


# ══════════════════════════════════════════════ 2. les candidats ══
print("2. Ce qui est candidat")
DEPUIS = NOW - bm.RATTRAPAGE_JOURS * 86400
c, ill = bm.candidats_matin(par_cle[f"{YOU_US}:banger"], DEPUIS, NOW)
check("matin US : seulement les fiches PARUES, du jour le plus ancien au plus récent",
      [x["sc"] for x in c] == ["USaaa1", "USaaa2", "USbbb1"] and not ill, ([x["sc"] for x in c], ill))
check("… ni en attente, ni doublon, ni la journée hors fenêtre, ni un fichier qui n'est pas un jour",
      not {"USattente", "USdoublon", "USvieux"} & {x["sc"] for x in c})
c, ill = bm.candidats_matin(par_cle[f"{YOU_FR}:banger-emma"], DEPUIS, NOW)
check("matin FR : le journal de la model (fr/emma), pas celui de Jessye ni d'Amelia",
      [x["sc"] for x in c] == ["FRemma1"])
check("une model sans journal : aucun candidat, aucune erreur",
      bm.candidats_matin(par_cle[f"{YOU_FR}:banger-sarah"], DEPUIS, NOW) == ([], []))
(bg.DOSSIER_JOURNEES / "fr" / "lola").mkdir(parents=True)
(bg.DOSSIER_JOURNEES / "fr" / "lola" / f"{jour(1)}.json").write_text("{pas du json", encoding="utf-8")
journal(bg.DOSSIER_JOURNEES / "fr" / "lola", jour(2), {
    "FRlola1": item(fiche("FRlola1", "lola.va4", jour(2))),
    "FRlolaKO": item({"shortcode": "FRlolaKO"})})
c, ill = bm.candidats_matin(par_cle[f"{YOU_FR}:banger-lola"], DEPUIS, NOW)
check("journal illisible et fiche incomplète : NOMMÉS, les autres parutions partent",
      [x["sc"] for x in c] == ["FRlola1"] and len(ill) == 2
      and any(jour(1) in x for x in ill) and any("FRlolaKO" in x for x in ill), ill)
c, _ = bm.candidats_all(par_cle[f"{YOU_US}:all-banger"], DEPUIS, NOW)
check("all-banger : les bangers POSTÉS de Youl4b, dans l'ordre d'arrivée",
      [x["sc"] for x in c] == ["ALLus1", "ALLus2", "ALLlourd", "ALLsansvideo"], [x["sc"] for x in c])
check("… ni jumelle FR, ni marché FR, ni prêt, ni hors fenêtre",
      not {"ALLus1@fr:lola", "ALLfr1", "ALLpret", "ALLvieux"} & {x["sc"] for x in c})
c2, _ = bm.candidats_all(par_cle[f"{YOU_US}:all-banger"], NOW - H, NOW)
check("la mise en service borne le passé (rien d'avant « depuis »)",
      [x["sc"] for x in c2] == ["ALLlourd", "ALLsansvideo"])
SOURCES_AVANT = _empreinte_sources()          # le journal de Lola vient d'être ajouté


# ══════════════════════════════════════════════ 3. un passage ══
print("3. Un passage")
b1 = passer(client)
sb, sa = us.salon("・banger"), us.salon("all-banger")
check("You US 💥・banger : les trois cartes du matin, dans l'ordre de la source",
      [m.attachments[0].filename if m.attachments else "" for m in sb.messages]
      == ["USaaa1.mp4", "USaaa2_description.txt", "USbbb1.mp4"], [[a.filename for a in m.attachments] for m in sb.messages])
t0 = sb.messages[0].textes()
check("la carte : compte, model, date, statistiques, description à copier",
      "### @jessy.one" in t0 and f"Jessye · Bangers du {datetime.date.fromisoformat(jour(2)).strftime('%d/%m/%Y')}" in t0
      and "**15 000** vues" in t0 and "Description à copier" in t0 and "Légende de USaaa1" in t0, t0)
check("… SANS « Géré par », sans nom ni mention du VA de Youl4b",
      "Géré par" not in t0 and "Safidy" not in t0 and "<@" not in t0 and "424242" not in t0, t0)
check("… avec la vidéo de l'archive et le bouton vers le reel",
      [a.filename for a in sb.messages[0].attachments] == ["USaaa1.mp4", "USaaa1_description.txt"]
      and "instagram.com/reel/USaaa1/" in json.dumps(sb.messages[0].payload))
check("une fiche sans vidéo est recopiée quand même, et le dit",
      "Vidéo indisponible dans Discord" in sb.messages[1].textes())
check("aucun récapitulatif (le classement des VA de Youl4b)",
      not any("## Bangers" in m.textes() for m in sb.messages) and len(sb.messages) == 3)
check("aucune mention ne notifie", all(
    getattr(c_, "dernieres_mentions", None) is not None
    and not c_.dernieres_mentions.everyone and not c_.dernieres_mentions.users
    for c_ in (sb, sa)))
check("un nonce par carte, celui de la destination",
      [m.nonce for m in sb.messages] == [bm.nonce(par_cle[f"{YOU_US}:banger"], s)
                                         for s in ("USaaa1", "USaaa2", "USbbb1")])
check("You US 💣・all-banger : la carte all-banger (vidéo, vues, description, lien), dans l'ordre",
      [m.attachments[0].filename for m in sa.messages] == ["ALLus1.mp4", "ALLus2.mp4"]
      and "**20 000** vues" in sa.messages[0].textes() and "Desc ALLus1" in sa.messages[0].textes()
      and "@" not in sa.messages[0].textes().replace("Description à copier", ""),
      [m.textes() for m in sa.messages])
check("… la vidéo trop lourde et la vidéo disparue sont COMPTÉES, pas postées",
      b1["trop_lourds"] == 1 and b1["echecs"] == 1 and len(sa.messages) == 2, b1)
se, sam = fr.salon("banger-emma"), fr.salon("banger-amelia")
te = se.messages[0].textes() if se.messages else ""
check("You FR 🔥・banger-emma : la carte d'Emma, sans « Géré par » ni numéro de VA de Va IG",
      len(se.messages) == 1 and "### @emma.va2" in te and "Emma · Bangers du" in te
      and "Géré par" not in te and "Emma VA 2" not in te and "Relevé du scrape" in te, te)
check("You FR : Amelia dans le sien, Lola dans le sien, rien chez les models sans banger",
      [len(fr.salon("banger-" + m).messages) for m in bg.MODELS_FR]
      == [1 if m in ("amelia", "emma", "lola") else 0 for m in bg.MODELS_FR],
      {m: len(fr.salon("banger-" + m).messages) for m in bg.MODELS_FR})
check("rien dans les salons généraux", not us.salon("général").messages and not fr.salon("général").messages)
check("bilan du passage", b1["envoyes"] == 8 and not b1["attentes"] and b1["restants"] == 0, b1)
check("un répit entre deux cartes, pas avant la première", SOMMEILS == [bm.DELAI_ENTRE_MESSAGES] * 7, SOMMEILS)
j = bm.charger()
check("le journal : une entrée par carte et par salon, la mise en service datée",
      j["envois"][f"{YOU_US}:banger|USaaa1"]["etat"] == "envoye"
      and j["envois"][f"{YOU_US}:banger|USaaa1"]["message_id"] == sb.messages[0].id
      and j["envois"][f"{YOU_US}:all-banger|ALLlourd"]["etat"] == "trop_lourd"
      and j["envois"][f"{YOU_US}:all-banger|ALLsansvideo"]["etat"] == "echec"
      and j["destinations"][f"{YOU_US}:banger"]["depuis"] == int(NOW - bm.RATTRAPAGE_JOURS * 86400), j)
n_avant = {c_.id: c_.envois for g in (us, fr) for c_ in g.text_channels}
b2 = passer(client)
check("second passage : RIEN n'est renvoyé",
      b2["envoyes"] == 0 and {c_.id: c_.envois for g in (us, fr) for c_ in g.text_channels} == n_avant, b2)
# la parution du lendemain
journal(bg.DOSSIER_JOURNEES, jour(0), {"USccc1": item(fiche("USccc1", "jessy.three", jour(0)))})
video("USccc1")
b3 = passer(client)
check("la parution suivante part seule, une fois",
      b3["envoyes"] == 1 and [a.filename for a in sb.messages[-1].attachments][0] == "USccc1.mp4"
      and len(sb.messages) == 4, b3)
(bg.DOSSIER_JOURNEES / f"{jour(0)}.json").unlink()
SOURCES_APRES_3 = _empreinte_sources()
check("les sources n'ont pas été écrites (journaux, registre all-banger, détails)",
      SOURCES_APRES_3 == SOURCES_AVANT)
check("… et aucune annonce n'est posée dans les détails d'une fiche", not list(bg.DETAILS_DIR.glob("*")))


# ══════════════════════════════════════════════ 4. sans double envoi ══
print("4. Sans double envoi")


def repartir(garder_journal=False):
    if not garder_journal and bm.JOURNAL.exists():
        bm.JOURNAL.unlink()
    for p in bm.JOURNAL.parent.glob("*.prev"):
        if not garder_journal:
            p.unlink()
    bm._DITS.clear()
    SOMMEILS.clear()
    ECOUTE.lignes.clear()
    return serveurs()


# 4a. coupure pendant l'envoi : le message EST parti
us, fr, client = repartir()
sb = us.salon("・banger")
sb.perd_reponse = True                       # la 1re carte part, la réponse se perd
b = passer(client)
check("issue incertaine : la destination s'arrête là, les autres continuent",
      b["incertains"] == 1 and len(sb.messages) == 1 and len(us.salon("all-banger").messages) == 2
      and len(fr.salon("banger-emma").messages) == 1, b)
check("… l'intention reste écrite (état « envoi »)",
      bm.charger()["envois"][f"{YOU_US}:banger|USaaa1"]["etat"] == "envoi")
b = passer(client, maintenant=NOW + 60)
check("une minute après : trop tôt pour vérifier, rien n'est renvoyé", sb.envois == 1 and b["incertains"] == 1, b)
Salon.horloge = NOW
b = passer(client, maintenant=NOW + 600)
check("dix minutes après : retrouvée dans le salon, PAS renvoyée ; les suivantes partent",
      b["retrouves"] == 1 and b["envoyes"] == 2
      and [m.attachments[0].filename for m in sb.messages] == ["USaaa1.mp4", "USaaa2_description.txt", "USbbb1.mp4"], b)
# 4b. coupure AVANT que le message parte : l'intention est seule
us, fr, client = repartir()
sb = us.salon("・banger")
jx = bm._vide()
jx["destinations"][f"{YOU_US}:banger"] = {"depuis": int(DEPUIS), "amorce": True}
jx["envois"][f"{YOU_US}:banger|USaaa1"] = {"etat": "envoi", "intention_le": NOW - 900, "essais": 0}
bm._ecrire(jx)
b = passer(client)
check("intention sans message : vérifiée absente, la carte repart À SA PLACE (la première)",
      [m.attachments[0].filename for m in sb.messages][0] == "USaaa1.mp4" and len(sb.messages) == 3
      and b["envoyes"] >= 3 and b["retrouves"] == 0, b)
# 4c. historique illisible : ni renvoi ni abandon
us, fr, client = repartir()
sb = us.salon("・banger")
bm._ecrire(jx)
sb.historique_casse = True
b = passer(client)
check("vérification impossible (historique illisible) : rien n'est renvoyé à l'aveugle",
      sb.envois == 0 and f"{YOU_US}:banger" in b["attentes"]
      and bm.charger()["envois"][f"{YOU_US}:banger|USaaa1"]["etat"] == "envoi", b)
# 4d. journal perdu : l'amorce
us, fr, client = repartir()
passer(client)
total = sum(c_.envois for g in (us, fr) for c_ in g.text_channels)
bm.JOURNAL.unlink()
for p in bm.JOURNAL.parent.glob("*"):
    p.unlink()
for g in (us, fr):
    for c_ in g.text_channels:
        for m in c_.messages:
            m.nonce = None                    # Discord ne rend pas le nonce à la relecture
bm._DITS.clear()
b = passer(client)
check("journal perdu : l'historique des salons est relu, RIEN n'est reposté",
      sum(c_.envois for g in (us, fr) for c_ in g.text_channels) == total and b["envoyes"] == 0
      and b["retrouves"] == 8, (b, total))
check("… et le journal est reconstruit",
      bm.charger()["envois"][f"{YOU_US}:banger|USbbb1"]["etat"] == "envoye"
      and bm.charger()["destinations"][f"{YOU_FR}:banger-emma"]["amorce"] is True)
# 4e. amorce impossible
us, fr, client = repartir()
us.salon("・banger").historique_casse = True
b = passer(client)
check("amorce impossible (historique illisible) : ce salon n'envoie rien, les autres si",
      us.salon("・banger").envois == 0 and len(us.salon("all-banger").messages) == 2
      and "rien n'est envoyé à l'aveugle" in b["attentes"][f"{YOU_US}:banger"], b)


# ══════════════════════════════════════════════ 5. les pannes ══
print("5. Pannes")
us, fr, client = repartir()
us.text_channels = [c_ for c_ in us.text_channels if not c_.name.endswith("・banger")]
fr.salon("banger-emma").droits["attach_files"] = False
b = passer(client)
check("salon supprimé / droit manquant : dit, compté, les autres salons reçoivent",
      "aucun salon « banger »" in b["attentes"][f"{YOU_US}:banger"]
      and "joindre un fichier" in b["attentes"][f"{YOU_FR}:banger-emma"]
      and len(us.salon("all-banger").messages) == 2 and len(fr.salon("banger-amelia").messages) == 1
      and not fr.salon("banger-emma").messages, b)
n_dits = len([l for l in ECOUTE.lignes if "aucun salon « banger »" in l])
passer(client)
check("la même cause n'est dite qu'UNE fois au journal du bot",
      len([l for l in ECOUTE.lignes if "aucun salon « banger »" in l]) == n_dits == 1, n_dits)

us, fr, client = repartir()
client._g.pop(YOU_FR)
b = passer(client)
check("un serveur hors de portée : ses salons attendent, l'autre serveur est servi",
      all("hors de portée" in b["attentes"][f"{YOU_FR}:banger-{m}"] for m in bg.MODELS_FR)
      and len(us.salon("・banger").messages) == 3, b)

us, fr, client = repartir()
sb = us.salon("・banger")
sb.casse_toujours = discord.HTTPException(Rep(400), "Invalid Form Body")
b = passer(client)
check("refus de Discord (400) : compté, la carte réessayée plus tard, les autres salons servis",
      b["refus"] == 3 and not sb.messages and len(us.salon("all-banger").messages) == 2
      and bm.charger()["envois"][f"{YOU_US}:banger|USaaa1"] == {"etat": "attente", "essais": 1, "cause": "http_400"}, b)
passer(client)
b = passer(client)
check(f"… abandonnée après {bm.ESSAIS_MAX} refus, et c'est écrit",
      bm.charger()["envois"][f"{YOU_US}:banger|USaaa1"]["etat"] == "echec"
      and bm.charger()["envois"][f"{YOU_US}:banger|USaaa1"]["essais"] == bm.ESSAIS_MAX
      and any("abandonné" in l for l in ECOUTE.lignes), bm.charger()["envois"])
n = sb.envois
passer(client)
check("… puis plus jamais retentée", sb.envois == n)

us, fr, client = repartir()
sb = us.salon("・banger")
sb.casse = discord.HTTPException(Rep(403), "Missing Permissions")
b = passer(client)
check("403 à l'envoi : la destination s'arrête, l'intention est retirée (rien n'est parti)",
      sb.envois == 1 and not sb.messages and "http_403" in b["attentes"][f"{YOU_US}:banger"]
      and bm.charger()["envois"][f"{YOU_US}:banger|USaaa1"]["etat"] == "attente", b)
b = passer(client)
check("… et tout part au passage suivant", len(sb.messages) == 3 and b["envoyes"] == 3, b)

us, fr, client = repartir()
us.salon("all-banger").casse = discord.HTTPException(Rep(413), "Payload Too Large")
b = passer(client)
check("413 : classée trop lourde, la suivante part",
      bm.charger()["envois"][f"{YOU_US}:all-banger|ALLus1"]["etat"] == "trop_lourd"
      and [m.attachments[0].filename for m in us.salon("all-banger").messages] == ["ALLus2.mp4"], b)

us, fr, client = repartir()
_vrai_ecrire = bm._ecrire
bm._ecrire = lambda d: False
try:
    b = passer(client)
finally:
    bm._ecrire = _vrai_ecrire
check("journal impossible à écrire : AUCUN envoi (rien ne dirait ce qui est parti)",
      sum(c_.envois for g in (us, fr) for c_ in g.text_channels) == 0
      and b["attentes"].get("journal") == "journal non enregistré", b)

us, fr, client = repartir()
b = passer(client, par_tour=2)
check("plafond par salon : 2 cartes par salon, le reste compté pour le passage suivant",
      len(us.salon("・banger").messages) == 2 and b["restants"] == 3
      and len(us.salon("all-banger").messages) == 2, b)
b = passer(client, par_tour=2)
check("… et le reste part ensuite, dans l'ordre",
      [m.attachments[0].filename for m in us.salon("・banger").messages]
      == ["USaaa1.mp4", "USaaa2_description.txt", "USbbb1.mp4"] and b["restants"] == 0, b)


async def _deux():
    return await asyncio.gather(bm.tour(client, dormir=_dormir, maintenant=NOW),
                                bm.tour(client, dormir=_dormir, maintenant=NOW))


us, fr, client = repartir()
r = asyncio.run(_deux())
check("deux passages lancés ensemble : un seul tourne, aucun doublon",
      sorted(bool(x.get("en_cours")) for x in r) == [False, True]
      and len(us.salon("・banger").messages) == 3, r)

# la purge du journal
jp = bm._vide()
jp["envois"] = {"a|vieux": {"etat": "envoye", "le": int(NOW - 60 * 86400)},
                "a|recent": {"etat": "envoye", "le": int(NOW - 5 * 86400)},
                "a|encours": {"etat": "envoi", "intention_le": NOW - 60 * 86400}}
check("purge : seules les entrées tranchées depuis longtemps partent, jamais une intention",
      bm._purger(jp, NOW) == 1 and set(jp["envois"]) == {"a|recent", "a|encours"})
check("les sources toujours intactes après toutes les pannes", _empreinte_sources() == SOURCES_AVANT)


# ══════════════════════════════ 7. la carte du matin et le cog ══
print("7. Carte par défaut et cog")
f = fiche("USaaa1", "jessy.one", jour(2))


def entete(**kw):
    vue, fichiers = bg.fiche_discord(f, bg.chemin_video("USaaa1"), **kw)
    for x in fichiers:
        x.close()
    return vue.to_components()[0]["components"][0]["content"]


check("carte du matin par défaut : inchangée (« Géré par » et la mention du VA)",
      entete().startswith("### @jessy.one\n**Géré par :** <@424242> · Safidy\nJessye · Bangers du "))
check("anonyme (Va IG) : inchangée", "**Géré par :** VA\n" in entete(anonyme=True))
check("sans_gerant : la ligne disparaît, le reste est identique",
      entete(anonyme=True, sans_gerant=True) == entete(anonyme=True).replace("**Géré par :** VA\n", ""))

import cogs.bangersmiroir as cbm  # noqa: E402

check("zéro commande slash", not cbm.BangersMiroir.__cog_app_commands__)
faux = types.ModuleType("web_upload")
faux._machine_proprietaire = lambda quoi: os.environ.get("VA_MACHINE_PROD") == "1"
_sauve_wu = sys.modules.get("web_upload")
sys.modules["web_upload"] = faux
_sauve_env = os.environ.pop("VA_MACHINE_PROD", None)


async def _armes():
    a = cbm.BangersMiroir(ns())
    mac = a.boucle.is_running()
    a.cog_unload()
    os.environ["VA_MACHINE_PROD"] = "1"
    b_ = cbm.BangersMiroir(ns())
    prod = b_.boucle.is_running()
    b_.cog_unload()
    return mac, prod


try:
    mac, prod = asyncio.run(_armes())
finally:
    os.environ.pop("VA_MACHINE_PROD", None)
    if _sauve_env is not None:
        os.environ["VA_MACHINE_PROD"] = _sauve_env
    if _sauve_wu is None:
        sys.modules.pop("web_upload", None)
    else:
        sys.modules["web_upload"] = _sauve_wu
check("sans VA_MACHINE_PROD : boucle non armée ; avec : armée", not mac and prod, (mac, prod))
arbre = ast.parse((BOT / "main.py").read_text(encoding="utf-8"))
listes = {n.targets[0].id: [e.value for e in n.value.elts] for n in arbre.body
          if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
          and n.targets[0].id in ("MAIN_COGS", "ADMIN_COGS")}
check("main.py : sur le bot principal, une seule fois, pas sur le bot admin",
      listes["MAIN_COGS"].count("bangersmiroir") == 1 and "bangersmiroir" not in listes["ADMIN_COGS"])
check("main.py : la fin de MAIN_COGS reste celle sur laquelle s'appuie le patch du VPS",
      listes["MAIN_COGS"][-1] == "bases_identite" and (BOT / "cogs" / "bangersmiroir.py").exists())
# D'autres suites découpent main.py sur le NOM des deux listes
# (tests_generateur_lien, tests_jailbreak) : le nommer dans le commentaire du
# cog les faisait échouer.
_main = (BOT / "main.py").read_text(encoding="utf-8")
_bloc = _main.split('"compteurjailbreak",')[1].split('"bangersmiroir",')[0]
check("main.py : le commentaire du cog ne nomme aucune des deux listes",
      "MAIN_COGS" not in _bloc and "ADMIN_COGS" not in _bloc and "]" not in _bloc, _bloc)

check("isolation : rien écrit ni modifié dans data/", _instantane() == AVANT)

print("=" * 70)
print(f"RESULTAT : {len(OKS)} OK / {len(FAILS)} ECHEC(S)")
print("=" * 70)
for x in FAILS:
    print("  - " + x)
sys.exit(1 if FAILS else 0)
