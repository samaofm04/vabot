"""Lecture de l'API officielle d'Infloww — un module À PART.

Rien d'existant n'importe ce fichier : ni le podium, ni MyPuls, ni les bots.
Le propriétaire l'a voulu ainsi pour ne rien casser de ce qui tourne. Si
l'API tombe, seule la page /infloww le dit ; le reste continue comme avant.

L'API (doc : infloww-openapi.stoplight.io, spéc. OpenAPI 1.4) est en LECTURE
SEULE et répond sur https://openapi.infloww.com/v1/...

DEUX EN-TÊTES, SANS QUOI CLOUDFLARE BLOQUE TOUT. `Authorization` porte la clé
brute (sans « Bearer »), et `x-oid` l'identifiant d'agence. Sans `x-oid`, la
requête ne passe même pas le pare-feu : la page « you have been blocked » de
Cloudflare, et pas une erreur de l'API — 64 essais l'ont montré avant de lire
la doc. L'identifiant d'agence est le nombre inscrit dans la clé elle-même
(« st_ifw_<oid>… »), vérifié : la clé seule suffit à le retrouver.

Les pièges de l'API, tous rencontrés :
- les compteurs arrivent en TEXTE (« "210" ») : on les convertit, sans quoi
  une somme concatène au lieu d'additionner ;
- une requête couvre 31 jours au plus : au-delà, « Query time span exceeds
  the maximum allowed days ». On découpe ;
- `endTime` ne peut pas être dans le futur : « must be a past or present
  time » ;
- la liste des liens de suivi est filtrée par DATE DE CRÉATION du lien, pas
  par activité : pour les avoir tous, il faut remonter tranche par tranche ;
- les données d'OnlyFans arrivent avec 2 à 4 heures de retard.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
CLE_FICHIER = DATA_DIR / "infloww_api_key"
CONFIG_FICHIER = DATA_DIR / "infloww_config.json"
CACHE_FICHIER = DATA_DIR / "infloww_cache.json"

BASE = "https://openapi.infloww.com"
FENETRE_MAX_JOURS = 31
CACHE_S = 600            # dix minutes : l'API plafonne à 1 000 requêtes/minute par agence
PLATEFORME = "OnlyFans"

# Les créatrices suivies ici. Jessye seulement, pour commencer : c'est le
# marché US que le propriétaire veut regarder avec cette source.
SUIVIES = ["jessyewdiference"]


class ErreurInfloww(Exception):
    """Une erreur de l'API, avec l'identifiant que le support réclame."""

    def __init__(self, message: str, code: int = 0, request_id: str = ""):
        super().__init__(message)
        self.code = code
        self.request_id = request_id


# ─── accès ───────────────────────────────────────────────────────────────
def cle() -> str:
    v = (os.environ.get("INFLOWW_API_KEY") or "").strip()
    if v:
        return v
    for p in (CLE_FICHIER, Path.home() / ".config" / "infloww_api_key"):
        try:
            v = p.read_text(encoding="utf-8").strip()
            if v:
                return v
        except Exception:
            pass
    return ""


def _config() -> Dict[str, Any]:
    try:
        return safe_json.load(CONFIG_FICHIER, default={}) or {}
    except Exception:
        return {}


def oid(k: Optional[str] = None) -> str:
    """L'identifiant d'agence : réglé à la main, sinon lu dans la clé."""
    v = str(_config().get("oid") or "").strip()
    if v:
        return v
    m = re.match(r"^st_ifw_(\d{8,20})", k if k is not None else cle())
    return m.group(1) if m else ""


def configure() -> bool:
    return bool(cle() and oid())


def suivies() -> List[str]:
    return list(_config().get("suivies") or SUIVIES)


# ─── appels ──────────────────────────────────────────────────────────────
def _get(chemin: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """GET sur l'API. Lève ErreurInfloww avec ce qui permet de comprendre."""
    k = cle()
    if not k:
        raise ErreurInfloww("clé API Infloww absente (data/infloww_api_key)")
    o = oid(k)
    if not o:
        raise ErreurInfloww("identifiant d'agence (x-oid) introuvable")
    url = BASE + chemin + "?" + urllib.parse.urlencode(params, doseq=True)
    for essai in range(3):
        req = urllib.request.Request(url, headers={
            "Authorization": k, "x-oid": o, "Accept": "application/json",
            "User-Agent": "youl4b/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            brut = e.read(2000)
            rid = e.headers.get("x-request-id") or ""
            if e.code == 429 and essai < 2:
                time.sleep(2 + 3 * essai)
                continue
            if b"Cloudflare" in brut:
                raise ErreurInfloww("bloqué par Cloudflare (en-têtes d'accès refusés)",
                                    e.code, rid)
            try:
                msg = json.loads(brut).get("errorMessage") or brut.decode("utf-8", "replace")
            except Exception:
                msg = brut.decode("utf-8", "replace")
            raise ErreurInfloww(str(msg)[:200], e.code, rid)
        except urllib.error.URLError as e:
            if essai < 2:
                time.sleep(2)
                continue
            raise ErreurInfloww(f"réseau : {e.reason}")
    raise ErreurInfloww("trop de requêtes (429) malgré les reprises", 429)


def _avec_cache(cle_cache: str, fabrique, duree: int = CACHE_S):
    """Relit le cache s'il a moins de `duree` secondes, sinon rappelle l'API.

    Un échec n'est jamais mis en cache : la page suivante doit réessayer, pas
    servir une erreur pendant dix minutes.
    """
    try:
        cache = safe_json.load(CACHE_FICHIER, default={}) or {}
    except Exception:
        cache = {}
    ent = cache.get(cle_cache) or {}
    if ent and time.time() - float(ent.get("t") or 0) < duree:
        return ent.get("v"), float(ent["t"])
    v = fabrique()
    cache[cle_cache] = {"t": time.time(), "v": v}
    # le cache ne doit pas grossir sans fin : on garde les 200 entrées récentes
    if len(cache) > 200:
        for k in sorted(cache, key=lambda x: float(cache[x].get("t") or 0))[:len(cache) - 200]:
            cache.pop(k, None)
    safe_json.write_text(CACHE_FICHIER, json.dumps(cache, ensure_ascii=False))
    return v, time.time()


def _n(v: Any) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _tranches(debut: dt.date, fin: dt.date, jours: int = FENETRE_MAX_JOURS):
    """[debut, fin] découpé en morceaux de `jours` jours au plus."""
    d = debut
    while d <= fin:
        f = min(fin, d + dt.timedelta(days=jours - 1))
        yield d, f
        d = f + dt.timedelta(days=1)


# ─── lectures ────────────────────────────────────────────────────────────
def creatrices() -> List[Dict[str, Any]]:
    """Les créatrices connectées à Infloww que la clé a le droit de lire."""
    def f():
        return (_get("/v1/creators", {}).get("data") or {}).get("list") or []
    return _avec_cache("creators", f)[0]


def creatrice(pseudo: str) -> Optional[Dict[str, Any]]:
    p = str(pseudo or "").lower()
    for c in creatrices():
        if str(c.get("userName") or "").lower() == p:
            return c
    return None


def abonnes_par_jour(creator_id: str, debut: dt.date, fin: dt.date) -> List[Dict[str, Any]]:
    """[{date, nouveaux, renouvellements}] jour par jour, sur n'importe quelle durée."""
    fin = min(fin, dt.date.today())
    out: List[Dict[str, Any]] = []
    for a, b in _tranches(debut, fin):
        def f(a=a, b=b):
            d = _get("/v1/creator-report/fans/subscriber-count",
                     {"creatorIds": creator_id, "platformCode": PLATEFORME,
                      "startTime": a.isoformat(), "endTime": b.isoformat()})
            return (d.get("data") or {}).get("list") or []
        # un jour passé ne change plus : on le garde une heure, pas dix minutes
        duree = CACHE_S if b >= dt.date.today() - dt.timedelta(days=1) else 3600
        for x in _avec_cache(f"subs:{creator_id}:{a}:{b}", f, duree)[0]:
            out.append({"date": str(x.get("date")),
                        "nouveaux": _n(x.get("newSubscribers")),
                        "renouvellements": _n(x.get("subscriberRenewals"))})
    out.sort(key=lambda x: x["date"])
    return out


def liens_suivi(creator_id: str, depuis: dt.date) -> List[Dict[str, Any]]:
    """Tous les liens de suivi créés depuis `depuis`, avec leurs compteurs.

    Les compteurs (clics, abonnés) sont CUMULÉS depuis la création du lien,
    comme sur OnlyFans — ce n'est pas l'activité de la période.
    """
    maintenant = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
    tous: Dict[str, Dict[str, Any]] = {}
    for a, b in _tranches(depuis, maintenant.date()):
        fin = min(dt.datetime.combine(b, dt.time(23, 59, 59), dt.timezone.utc), maintenant)

        def f(a=a, fin=fin):
            lot, cur = [], None
            for _ in range(50):              # garde-fou : 5 000 liens par tranche
                p = {"creatorId": creator_id, "linkType": "TRACKING", "platformCode": PLATEFORME,
                     "startTime": f"{a.isoformat()}T00:00:00Z",
                     "endTime": fin.strftime("%Y-%m-%dT%H:%M:%SZ"), "limit": 100}
                if cur:
                    p["cursor"] = cur
                d = _get("/v1/links", p)
                lot += (d.get("data") or {}).get("list") or []
                cur = d.get("cursor")
                if not d.get("hasMore"):
                    break
            return lot
        for x in _avec_cache(f"liens:{creator_id}:{a}:{b}", f)[0]:
            tous[str(x.get("id"))] = x
    out = []
    for x in tous.values():
        out.append({"id": str(x.get("id")), "nom": str(x.get("name") or ""),
                    "code": str(x.get("code") or ""), "source": str(x.get("source") or ""),
                    "clics": _n(x.get("clickCount")), "abonnes": _n(x.get("subCount")),
                    "conversion": str(x.get("subscriptionCVR") or "0"),
                    "revenus": _n(x.get("earningsNet")) / 100.0,
                    "termine": bool(x.get("finishedFlag")),
                    "cree": dt.datetime.fromtimestamp(_n(x.get("createdTime")) / 1000).date().isoformat()
                    if _n(x.get("createdTime")) else ""})
    out.sort(key=lambda x: (-x["abonnes"], -x["clics"]))
    return out


def bilan(pseudo: str, jours: int = 30) -> Dict[str, Any]:
    """Tout ce que la page affiche, pour une créatrice, sur les `jours` derniers jours."""
    c = creatrice(pseudo)
    if not c:
        raise ErreurInfloww(f"« {pseudo} » n'est pas connectée à Infloww, ou la clé "
                            "n'a pas le droit de la lire")
    fin = dt.date.today()
    debut = fin - dt.timedelta(days=max(1, jours) - 1)
    parjour = abonnes_par_jour(str(c["id"]), debut, fin)
    cree = dt.datetime.fromtimestamp(_n(c.get("createdTime")) / 1000).date() \
        if _n(c.get("createdTime")) else debut
    liens = liens_suivi(str(c["id"]), cree)
    nouveaux = sum(x["nouveaux"] for x in parjour)
    return {"creatrice": c, "debut": debut.isoformat(), "fin": fin.isoformat(),
            "jours": parjour, "nouveaux": nouveaux,
            "renouvellements": sum(x["renouvellements"] for x in parjour),
            "moyenne": round(nouveaux / len(parjour), 1) if parjour else 0,
            "liens": liens, "lu_a": time.time()}


# ─── la page ─────────────────────────────────────────────────────────────
# Rendue ENTIÈREMENT côté serveur, sans JavaScript : le dashboard a déjà perdu
# des pages entières à cause d'une apostrophe dans du JS logé dans une chaîne
# Python. Ici il n'y en a pas, donc rien de ce genre ne peut casser.
def _e(s: Any) -> str:
    import html
    return html.escape(str(s if s is not None else ""), quote=True)


PERIODES = (7, 30, 90)


def _nb(n: Any) -> str:
    """12 345 : l'espace des milliers, posé sur le nombre seul — jamais par un
    remplacement global, qui effacerait aussi les virgules des noms de liens."""
    return f"{_n(n):,}".replace(",", "\u202f")


def page_html(pseudo: str, jours: int, bilan_: Optional[Dict[str, Any]] = None,
              erreur: Optional[ErreurInfloww] = None) -> str:
    onglets = "".join(
        f'<a class="ong{" on" if p == jours else ""}" href="?creatrice={_e(pseudo)}&jours={p}">{p} jours</a>'
        for p in PERIODES)
    autres = "".join(
        f'<a class="ong{" on" if s == pseudo else ""}" href="?creatrice={_e(s)}&jours={jours}">@{_e(s)}</a>'
        for s in suivies()) if len(suivies()) > 1 else ""
    if erreur is not None:
        rid = f"<br><small>x-request-id : <code>{_e(erreur.request_id)}</code> — à donner au support Infloww</small>" \
            if erreur.request_id else ""
        corps = (f'<div class="err"><b>Infloww n\'a pas répondu.</b><br>{_e(erreur)}'
                 f'{" (HTTP " + str(erreur.code) + ")" if erreur.code else ""}{rid}</div>')
    else:
        b = bilan_ or {}
        c = b.get("creatrice") or {}
        maxi = max([x["nouveaux"] for x in b.get("jours", [])] or [1]) or 1
        hier = b["jours"][-2]["nouveaux"] if len(b.get("jours", [])) >= 2 else 0
        lignes_j = "".join(
            f'<tr><td>{_e(x["date"])}</td><td class="n">{x["nouveaux"]}</td>'
            f'<td class="barre"><span style="width:{round(100 * x["nouveaux"] / maxi)}%"></span></td>'
            f'<td class="n faible">{x["renouvellements"]}</td></tr>'
            for x in reversed(b.get("jours", [])))
        lignes_l = "".join(
            f'<tr{" class=fini" if x["termine"] else ""}><td>{_e(x["nom"])}</td><td class="faible">c{_e(x["code"])}</td>'
            f'<td class="n">{_nb(x["clics"])}</td><td class="n fort">{_nb(x["abonnes"])}</td>'
            f'<td class="n">{_e(x["conversion"])} %</td><td class="faible">{_e(x["source"])}</td>'
            f'<td class="faible">{_e(x["cree"])}</td></tr>'
            for x in b.get("liens", []))
        lu = dt.datetime.fromtimestamp(b.get("lu_a") or time.time()).strftime("%d/%m à %Hh%M")
        corps = f'''
<div class="tuiles">
  <div class="tuile"><div class="v">{_nb(b.get("nouveaux", 0))}</div><div class="l">nouveaux abonnés · {jours} j</div></div>
  <div class="tuile"><div class="v">{b.get("moyenne", 0)}</div><div class="l">par jour en moyenne</div></div>
  <div class="tuile"><div class="v">{hier}</div><div class="l">hier</div></div>
  <div class="tuile"><div class="v">{b.get("renouvellements", 0)}</div><div class="l">renouvellements</div></div>
</div>
<p class="note">@{_e(c.get("userName"))} · du {_e(b.get("debut"))} au {_e(b.get("fin"))} · lu le {lu}
 · OnlyFans transmet ses chiffres avec 2 à 4 h de retard : aujourd'hui est encore incomplet.</p>
<h2>Jour par jour</h2>
<table><tr><th>Date</th><th class="n">Nouveaux</th><th></th><th class="n">Renouv.</th></tr>{lignes_j}</table>
<h2>Liens de suivi <span class="faible">— {len(b.get("liens", []))} liens, compteurs cumulés depuis leur création</span></h2>
<div class="table-scroll"><table><tr><th>Lien</th><th>Code</th><th class="n">Clics</th><th class="n">Abonnés</th><th class="n">Conversion</th><th>Source</th><th>Créé le</th></tr>{lignes_l}</table></div>'''
    return f'''<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Infloww · subs</title>
<style>
:root{{--fond:#151515;--carte:#242424;--bord:#3a3a3a;--texte:#f2f2f2;--faible:#9a9a9a;--bleu:#1677FF;--rouge:#ef4444}}
body{{margin:0;background:var(--fond);color:var(--texte);font:14px/1.5 -apple-system,system-ui,sans-serif;padding:24px 16px;max-width:1100px;margin:auto}}
h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:15px;margin:28px 0 10px}}
.sous{{color:var(--faible);margin:0 0 16px;font-size:13px}}
.ongs{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:18px}}
.ong{{padding:6px 12px;border:1px solid var(--bord);border-radius:8px;color:var(--faible);text-decoration:none;font-size:13px}}
.ong.on{{background:var(--bleu);border-color:var(--bleu);color:#fff}}
.tuiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}}
.tuile{{background:var(--carte);border:1px solid var(--bord);border-radius:12px;padding:14px 16px}}
.tuile .v{{font-size:26px;font-weight:700}} .tuile .l{{color:var(--faible);font-size:12px}}
.note{{color:var(--faible);font-size:12px;margin:10px 0 0}}
table{{width:100%;border-collapse:collapse;background:var(--carte);border:1px solid var(--bord);border-radius:12px;overflow:hidden}}
th,td{{padding:7px 10px;border-bottom:1px solid var(--bord);text-align:left;font-size:13px}}
th{{color:var(--faible);font-weight:600;font-size:12px}}
.n{{text-align:right;font-variant-numeric:tabular-nums}} .fort{{font-weight:700;color:#fff}} .faible{{color:var(--faible)}}
.barre{{width:38%}} .barre span{{display:block;height:8px;border-radius:4px;background:var(--bleu)}}
tr.fini td{{opacity:.5}}
.err{{background:rgba(239,68,68,.12);border:1px solid var(--rouge);border-radius:12px;padding:14px 16px}}
.table-scroll{{overflow-x:auto}}
</style></head><body>
<h1>Infloww · abonnés</h1>
<p class="sous">Source : API officielle d'Infloww, en lecture seule. Page à part : elle ne nourrit ni le podium ni la paie.</p>
<div class="ongs">{onglets}</div>{f'<div class="ongs">{autres}</div>' if autres else ""}
{corps}
</body></html>'''
