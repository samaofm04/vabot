# -*- coding: utf-8 -*-
"""Pages « liens de suivi » des VA de You FR, une par model.

POURQUOI (propriétaire, 23/11/2026, devant la page JESSY LE RETOUR
/infloww/liens?c=emy) : « un lien exprès pour Alicia, … Emma, Lola, Julia,
un pour toutes les models du marché français, et un pour Lia, mais
uniquement pour les personnes qui sont dans le serveur You FR », puis
« uniquement pour eux stp vas-y », avec le logo MYM : les subs MYM comptent.

POURQUOI UN MODULE À PART, et pas une copie de infloww_liens (profil())
    infloww_liens ne sait compter que des liens OnlyFans « /c123 » d'UNE
    créatrice ; Alicia, Emma et Sarah ne sont que sur MYM, et chaque lien
    JB porte deux trackings (OF + MYM). Ici, un VA = ses liens GetMySocial
    de la model, et ses subs = ceux de SES trackings MyPuls, rattachés par
    l'adresse exacte (jamais par le nom : « Amelia_JB_1 » n'identifie rien).

QUI EST SUR LA PAGE
    Les VA de You FR = ceux du registre des liens JB (data/liens_jb_fr.json,
    liens_jb_fr : chaque membre de You FR avec un rôle de model reçoit les
    quatre). Pour Amelia, Emma, Lola, Alicia : leur lien JB. Julia et Sarah
    n'ont pas de lien JB : les liens Va IG (data/liens_va_fr.json) de ces
    mêmes VA, et eux seuls. Lia : les trackings MyPuls de Lia dont le nom
    porte le pseudo d'un VA de You FR (« Instagram FR @fahnih_37050 »).

AUCUN MONTANT : la page s'ouvre avec la clé des VA (pas de montants chez
les VA) ; ni revenu, ni gain, ni paie.

Ne lève jamais vers la route : une panne s'affiche SUR la page.
"""
from __future__ import annotations

import datetime as dt
import html
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import safe_json

DATA_DIR = Path(__file__).resolve().parent / "data"
JB_FICHIER = DATA_DIR / "liens_jb_fr.json"
FR_FICHIER = DATA_DIR / "liens_va_fr.json"
PARIS = ZoneInfo("Europe/Paris")

#: Les pages : clé de l'adresse (?c=) -> nom, créatrices MyPuls (OF, MYM),
#: d'où viennent ses VA. Ids MyPuls = liens_fr.MODELS (Lia : 3992).
PAGES: Dict[str, Dict[str, Any]] = {
    "amelia": {"nom": "Amelia", "source": "jb"},
    "emma": {"nom": "Emma", "source": "jb"},
    "lola": {"nom": "Lola", "source": "jb"},
    "alicia": {"nom": "Alicia", "source": "jb"},
    "julia": {"nom": "Julia", "source": "va_ig"},
    "sarah": {"nom": "Sarah", "source": "va_ig"},
    "lia": {"nom": "Lia", "source": "lia", "creator_ids": (3992,)},
}
#: Préfixe de l'adresse : « fr-amelia » évite toute collision avec les
#: profils de infloww_liens (?c=emy, ?c=lia : Lia y a déjà SA page YouCham).
PREFIXE = "fr-"

TTL_S = 900                      # un relevé (MyPuls ou GMS) resservi 15 min
ATTENTE_S = 8.0                  # la page n'attend pas plus : la suite au rechargement
_CACHE: Dict[Tuple, Dict[str, Any]] = {}
_FILS: Dict[Tuple, threading.Thread] = {}
_ECHECS: Dict[Tuple, Dict[str, Any]] = {}
_VERROU = threading.Lock()
ECHEC_S = 90                     # un échec n'est pas retenté avant


def page_de(c: Any) -> str:
    """« amelia » pour « fr-amelia » (casse ignorée), "" sinon."""
    c = str(c or "").strip().lower()
    if c.startswith(PREFIXE) and c[len(PREFIXE):] in PAGES:
        return c[len(PREFIXE):]
    return ""


# ─────────────────────────────────────────────────────────── qui est qui ──

def _norm_url(u: Any) -> str:
    """Adresse de tracking comparable : OnlyFans en minuscules (pseudo et
    « c123 » insensibles), MYM tel quel (son code distingue la casse)."""
    u = str(u or "").strip().rstrip("/")
    m = re.match(r"^https?://(?:www\.)?onlyfans\.com/([^/?#]+)/c0*(\d+)", u, re.I)
    if m:
        return f"of:{m.group(1).lower()}/c{int(m.group(2))}"
    m = re.match(r"^https?://(?:www\.)?mym\.fans/app/t/([A-Za-z0-9_-]+)", u)
    if m:
        return f"mym:{m.group(1)}"
    return u


def _registre(fichier: Path) -> Dict[str, Any]:
    d = safe_json.load(fichier, default={}) or {}
    liens = d.get("liens") if isinstance(d, dict) else None
    return liens if isinstance(liens, dict) else {}


def personnes(model: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """([{uid, pseudo, liens: [{link_id, url, trackings: {plate: url}}]}],
    avertissements). Jamais une entrée écartée sans le dire."""
    cfg = PAGES[model]
    avert: List[str] = []
    jb = _registre(JB_FICHIER)
    if not jb:
        avert.append("registre des liens JB (data/liens_jb_fr.json) vide ou illisible : "
                     "aucun VA de You FR connu")
    vas: Dict[str, str] = {}
    for k, e in jb.items():
        if isinstance(e, dict) and ":" in k:
            vas.setdefault(k.split(":", 1)[0], str(e.get("pseudo") or "").strip())
    out: Dict[str, Dict[str, Any]] = {}

    def _ajouter(uid: str, e: Mapping[str, Any]) -> None:
        tr = e.get("trackings") if isinstance(e.get("trackings"), dict) else {}
        p = out.setdefault(uid, {"uid": uid, "pseudo": vas.get(uid) or str(e.get("pseudo") or ""),
                                 "liens": []})
        p["liens"].append({"link_id": str(e.get("link_id") or ""),
                           "url": str(e.get("public_url") or ""),
                           "nom": str(e.get("display_name") or ""),
                           "trackings": {str(k): str(v) for k, v in tr.items() if v}})

    if cfg["source"] == "jb":
        for k, e in jb.items():
            if isinstance(e, dict) and k.endswith(f":{model}"):
                _ajouter(k.split(":", 1)[0], e)
    elif cfg["source"] == "va_ig":
        fr = _registre(FR_FICHIER)
        for k, e in fr.items():
            if isinstance(e, dict) and ":" in k and str(e.get("model") or "") == model:
                uid = k.split(":", 1)[0]
                if uid in vas:
                    _ajouter(uid, e)
        avert.append(f"Les VA de You FR n'ont pas de lien JB pour {cfg['nom']} : "
                     f"ce sont leurs liens Va IG qui sont comptés.")
    # lia : les lignes viennent des trackings MyPuls (voir tableau())
    for p in out.values():
        if not any(l["trackings"] for l in p["liens"]):
            avert.append(f"{p['pseudo']} : lien sans tracking MyPuls, aucun sub ne peut lui revenir")
    return sorted(out.values(), key=lambda p: p["pseudo"].casefold()), avert


# ─────────────────────────────────────────────────── relevés en arrière-plan ──

def _releve(cle: Tuple, fn) -> Dict[str, Any]:
    """Le résultat de fn() pour `cle`, gardé TTL_S. Un appel à la fois par
    clé, attendu au plus ATTENTE_S : au-delà {"en_cours": True} et la page
    le dit. Un échec n'est jamais gardé comme un résultat."""
    with _VERROU:
        hit = _CACHE.get(cle)
        if hit and time.time() - hit["t"] < TTL_S:
            return hit["v"]
        ech = _ECHECS.get(cle)
        if ech and time.time() - ech["t"] < ECHEC_S:
            return {"erreur": ech["raison"], **({"perime": hit["v"]} if hit else {})}
        f = _FILS.get(cle)
        if not f or not f.is_alive():
            def _run():
                try:
                    v = fn()
                    err = str(v.get("erreur") or "") if isinstance(v, dict) else "réponse vide"
                except Exception as e:                       # noqa: BLE001
                    v, err = None, f"{type(e).__name__} : {e}"[:300]
                with _VERROU:
                    if err:
                        _ECHECS[cle] = {"t": time.time(), "raison": err}
                    else:
                        _CACHE[cle] = {"t": time.time(), "v": v}
                        _ECHECS.pop(cle, None)
                    if len(_CACHE) > 60:
                        for k in sorted(_CACHE, key=lambda k: _CACHE[k]["t"])[:15]:
                            _CACHE.pop(k, None)
            f = threading.Thread(target=_run, daemon=True, name=f"liens-you-fr-{cle[0]}")
            _FILS[cle] = f
            f.start()
    f.join(ATTENTE_S)
    with _VERROU:
        neuf = _CACHE.get(cle)
        ech = _ECHECS.get(cle)
    if neuf and neuf is not hit:
        return neuf["v"]
    if f.is_alive():
        return {"en_cours": True, **({"perime": hit["v"]} if hit else {})}
    return {"erreur": (ech or {}).get("raison") or "relevé terminé sans résultat",
            **({"perime": hit["v"]} if hit else {})}


def _mypuls(du: str, au: str) -> Dict[str, Any]:
    """{par_url: {norm_url: item}, items: [...]} : UN appel tracking-links
    pour toute l'agence (bornes incluses, heure de Paris : relevé du 26/09
    dans infloww_liens)."""
    import mypuls
    r = mypuls.api_get("tracking-links", {"per_page": 500, "from": du, "to": au})
    if not isinstance(r, Mapping) or not r.get("ok"):
        return {"erreur": f"MyPuls : {(r or {}).get('error') if isinstance(r, Mapping) else r}"[:300]}
    d = r.get("data")
    items = d.get("data") if isinstance(d, Mapping) else d
    if not isinstance(items, list):
        return {"erreur": "MyPuls a rendu une réponse de forme imprévue"}
    par_url: Dict[str, Dict[str, Any]] = {}
    for it in items:
        if isinstance(it, Mapping) and it.get("url"):
            par_url[_norm_url(it["url"])] = dict(it)
    tronque = ""
    try:
        n = int((d or {}).get("count")) if isinstance(d, Mapping) and d.get("count") is not None else None
        if n is not None and n > len(items):
            tronque = f"MyPuls annonce {n} trackings, {len(items)} rendus : des subs peuvent manquer"
    except (TypeError, ValueError):
        pass
    return {"par_url": par_url, "items": [dict(i) for i in items if isinstance(i, Mapping)],
            "tronque": tronque}


def _gms(ids: Tuple[str, ...], du: str, au: str) -> Dict[str, Any]:
    """{link_id: (total, fr)} : un relevé GetMySocial par lien (cache d'une
    heure de gms). Un lien illisible est None : « — », jamais un faux 0."""
    import gms
    out: Dict[str, Any] = {}
    rates = 0
    for i in ids:
        try:
            tot, pays = gms.analytics_for_links([i], du, au)
        except Exception:                                    # noqa: BLE001
            tot, pays = None, None
        if tot is None:
            rates += 1
            out[i] = None
        else:
            out[i] = (int(tot or 0), int((pays or {}).get("FR") or 0))
    if ids and rates == len(ids):
        return {"erreur": "GetMySocial n'a rendu aucun relevé (quota ou panne)"}
    return {"clics": out, "rates": rates}


# ─────────────────────────────────────────────────────────────── tableau ──

def _aujourdhui() -> dt.date:
    return dt.datetime.now(PARIS).date()


def periode(args: Mapping[str, Any]) -> Tuple[str, str]:
    """(du, au) ISO. Par défaut la quinzaine en cours (1→15, 16→fin)."""
    auj = _aujourdhui()
    defaut_du = auj.replace(day=1 if auj.day <= 15 else 16)

    def _lire(v, d):
        try:
            return dt.date.fromisoformat(str(v or "").strip()[:10])
        except ValueError:
            return d
    du, au = _lire(args.get("du"), defaut_du), _lire(args.get("au"), auj)
    du, au = min(du, auj), min(au, auj)
    if du > au:
        du, au = au, du
    return du.isoformat(), au.isoformat()


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def tableau(model: str, du: str, au: str) -> Dict[str, Any]:
    cfg = PAGES[model]
    gens, avert = personnes(model)
    mp = _releve(("mypuls", du, au), lambda: _mypuls(du, au))
    mpv = mp if "par_url" in mp else (mp.get("perime") or {})
    if mp.get("en_cours"):
        avert.insert(0, "MyPuls répond lentement : subs en cours de lecture, recharge dans une minute.")
    elif mp.get("erreur"):
        avert.insert(0, f"Subs non lus : {mp['erreur']}" + (" — chiffres d'une lecture précédente"
                                                           if mp.get("perime") else ""))
    if mpv.get("tronque"):
        avert.append(mpv["tronque"])
    par_url = mpv.get("par_url") or {}

    if cfg["source"] == "lia":
        # les VA de You FR (pseudos du registre JB) dont le nom figure dans un
        # tracking de Lia : la seule trace qui relie un tracking Lia à un VA
        vas = {}
        for k, e in _registre(JB_FICHIER).items():
            if isinstance(e, dict) and e.get("pseudo"):
                vas.setdefault(k.split(":", 1)[0], str(e["pseudo"]))
        ids = set(cfg.get("creator_ids") or ())
        par_uid: Dict[str, Dict[str, Any]] = {}
        for it in mpv.get("items") or []:
            if _int(it.get("creator_id")) not in ids:
                continue
            nom = str(it.get("name") or "").lower()
            for uid, ps in vas.items():
                if ps.lower() in nom:
                    p = par_uid.setdefault(uid, {"uid": uid, "pseudo": ps, "liens": []})
                    p["liens"].append({"link_id": "", "url": "", "nom": str(it.get("name") or ""),
                                       "trackings": {str(it.get("platform") or "of"): str(it["url"])}})
        gens = sorted(par_uid.values(), key=lambda p: p["pseudo"].casefold())
        if mpv and not gens:
            avert.append("Aucun tracking de Lia ne porte le pseudo d'un VA de You FR.")

    ids = tuple(sorted({l["link_id"] for p in gens for l in p["liens"] if l["link_id"]}))
    gm: Dict[str, Any] = {}
    if ids:
        g = _releve(("gms", ids, du, au), lambda: _gms(ids, du, au))
        gv = g if "clics" in g else (g.get("perime") or {})
        gm = gv.get("clics") or {}
        if g.get("en_cours"):
            avert.append("Clics GetMySocial en cours de lecture : recharge dans une minute.")
        elif g.get("erreur"):
            avert.append(f"Clics GetMySocial non lus : {g['erreur']}")
        elif gv.get("rates"):
            avert.append(f"{gv['rates']} lien(s) GetMySocial non relu(s) : « — » à leur ligne.")

    lignes = []
    manquants = 0
    for p in gens:
        clics = fr = 0
        clics_ok = bool(ids) and any(l["link_id"] for l in p["liens"])
        visites = subs_of = subs_mym = 0
        for l in p["liens"]:
            if l["link_id"]:
                v = gm.get(l["link_id"])
                if v is None:
                    clics_ok = False
                else:
                    clics += v[0]
                    fr += v[1]
            for plate, u in l["trackings"].items():
                it = par_url.get(_norm_url(u))
                if it is None:
                    if par_url:
                        manquants += 1
                    continue
                visites += _int(it.get("visits_period"))
                s = _int(it.get("subscribers_period"))
                if str(it.get("platform") or plate) == "mym":
                    subs_mym += s
                else:
                    subs_of += s
        subs = subs_of + subs_mym
        lignes.append({"pseudo": p["pseudo"], "liens": p["liens"],
                       "clics": clics if clics_ok else None, "fr": fr if clics_ok else None,
                       "visites": visites if par_url else None,
                       "subs_of": subs_of, "subs_mym": subs_mym,
                       "subs": subs if par_url else None,
                       # sans page GetMySocial (Lia : un tracking seul), le
                       # CVR se prend sur les clics du bouton OF/MYM, et c'est dit
                       "cvr": ((subs / clics) if clics_ok and clics else
                               (subs / visites) if not ids and visites else None),
                       "cvr_bouton": not ids})
    if manquants:
        avert.append(f"{manquants} tracking(s) absent(s) de la réponse MyPuls : leurs subs ne sont pas comptés.")
    return {"model": model, "nom": cfg["nom"], "du": du, "au": au, "lignes": lignes,
            "avert": avert, "en_cours": bool(mp.get("en_cours"))}


# ───────────────────────────────────────────────────────────────── rendu ──

def _nb(v: Any) -> str:
    if v is None:
        return '<span class="faible">—</span>'
    return f"{int(v):,}".replace(",", " ")


def _pct(v: Optional[float]) -> str:
    if v is None:
        return '<span class="faible">—</span>'
    cl = "v1" if v >= 0.10 else "v2" if v >= 0.05 else "o1" if v >= 0.02 else "r"
    return f'<span class="nv {cl}">{v * 100:.2f} %</span>'.replace(".", ",")


def _jc(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}"


TRIS = {"nom": lambda x: x["pseudo"].casefold(), "clics": lambda x: x["clics"] or 0,
        "visites": lambda x: x["visites"] or 0, "subs": lambda x: x["subs"] or 0,
        "cvr": lambda x: x["cvr"] or 0}

CSS = """
:root{--fond:#0e0e10;--carte:#18181b;--bord:#2a2a2f;--texte:#f4f4f5;--faible:#a1a1aa;--acc:#f97341;--ambre:#f59e0b}
*{box-sizing:border-box}
html,body{margin:0;background:var(--fond);color:var(--texte)}
body{font:14px/1.45 -apple-system,system-ui,"Segoe UI",sans-serif;padding:20px 16px 32px;max-width:960px;margin:0 auto}
.marque{color:var(--acc);font-weight:700;font-size:12px;letter-spacing:.06em;text-transform:uppercase}
h1{font-size:20px;margin:4px 0 2px}
.sous{color:var(--faible);font-size:13px;margin:0 0 12px;overflow-wrap:anywhere}
.models{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 12px}
.models a,.raccourcis a{color:var(--faible);text-decoration:none;border:1px solid var(--bord);border-radius:999px;padding:3px 10px;font-size:12px}
.models a.on,.raccourcis a.on{color:var(--acc);border-color:var(--acc)}
.periode{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:0 0 8px}
.periode input{background:var(--carte);color:var(--texte);border:1px solid var(--bord);border-radius:6px;padding:5px 6px;font:inherit;color-scheme:dark}
.periode button{background:var(--acc);color:#1c0a02;border:0;border-radius:6px;padding:6px 12px;font:inherit;font-weight:700;cursor:pointer}
.raccourcis{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 12px}
.avert{background:#2a1d08;border:1px solid #4a3410;color:#fcd34d;border-radius:8px;padding:7px 10px;margin:0 0 8px;font-size:12.5px}
.boite{background:var(--carte);border:1px solid var(--bord);border-radius:12px;overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:9px 10px;border-bottom:1px solid var(--bord);text-align:left;vertical-align:top}
th{font-size:12px;font-weight:600;white-space:nowrap}
th a{color:var(--faible);text-decoration:none} th.on a{color:var(--acc)}
td.nom{overflow-wrap:anywhere;min-width:120px}
.det{color:var(--faible);font-size:11px;line-height:1.35;margin-top:3px}
.det a{color:var(--faible)}
.n{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.fort{font-weight:700} .faible{color:var(--faible)}
tfoot td{font-weight:700;border-bottom:0}
.nv{display:inline-block;border-radius:6px;padding:1px 7px;font-weight:700}
.nv.v1{background:#4ade80;color:#052e16} .nv.v2{background:#16a34a;color:#fff}
.nv.o1{background:#fbbf24;color:#1c1203} .nv.r{background:#dc2626;color:#fff}
.note{color:var(--faible);font-size:12px;margin-top:10px}
"""


def page_html(t: Mapping[str, Any], cle: str = "", tri: str = "subs", sens: str = "desc") -> str:
    e = html.escape
    model, du, au = t["model"], t["du"], t["au"]
    tri = tri if tri in TRIS else "subs"
    sens = sens if sens in ("asc", "desc") else "desc"

    def _url(**kw) -> str:
        base = {"c": PREFIXE + model, "du": du, "au": au, "tri": tri, "sens": sens}
        if cle:
            base["k"] = cle
        base.update(kw)
        return "?" + urlencode({k: v for k, v in base.items() if v})

    lignes = sorted(t["lignes"], key=TRIS[tri], reverse=(sens == "desc"))
    auj = _aujourdhui()
    q_du = auj.replace(day=1 if auj.day <= 15 else 16)
    prec_au = q_du - dt.timedelta(days=1)
    prec_du = prec_au.replace(day=1 if prec_au.day <= 15 else 16)
    raccourcis = [("Aujourd'hui", auj, auj), ("Cette quinzaine", q_du, auj),
                  ("Quinzaine précédente", prec_du, prec_au),
                  ("7 derniers jours", auj - dt.timedelta(days=6), auj),
                  ("30 derniers jours", auj - dt.timedelta(days=29), auj)]
    rac = "".join(
        f'<a href="{e(_url(du=a.isoformat(), au=b.isoformat()))}"'
        f'{" class=on" if (a.isoformat(), b.isoformat()) == (du, au) else ""}>{e(lib)}</a>'
        for lib, a, b in raccourcis)
    models = "".join(
        f'<a href="{e(_url(c=PREFIXE + m))}"{" class=on" if m == model else ""}>{e(c["nom"])}</a>'
        for m, c in PAGES.items())
    caches = "".join(f'<input type="hidden" name="{k}" value="{e(v)}">'
                     for k, v in (("k", cle), ("c", PREFIXE + model), ("tri", tri), ("sens", sens)) if v)

    def _th(cle_tri: str, lib: str, num: bool = True, titre: str = "") -> str:
        s = "asc" if cle_tri == "nom" else "desc"
        if cle_tri == tri:
            s = "asc" if sens == "desc" else "desc"
        cl = ("n " if num else "") + ("on" if cle_tri == tri else "")
        return (f'<th class="{cl.strip()}"{f" title={chr(34)}{e(titre)}{chr(34)}" if titre else ""}>'
                f'<a href="{e(_url(tri=cle_tri, sens=s))}">{e(lib)}</a></th>')

    corps = []
    T = {"clics": 0, "fr": 0, "visites": 0, "subs": 0, "of": 0, "mym": 0}
    clics_ok = visites_ok = True
    for x in lignes:
        det_liens = " · ".join(
            (f'<a href="{e(l["url"])}" rel="noopener noreferrer" target="_blank">'
             f'{e(l["url"].split("/")[-1])}</a>') if l["url"] else e(l["nom"])
            for l in x["liens"])
        det_subs = ""
        if x["subs"]:
            parts = []
            if x["subs_of"]:
                parts.append(f"{x['subs_of']} OF")
            if x["subs_mym"]:
                parts.append(f"{x['subs_mym']} MYM")
            det_subs = f'<div class="det">{" + ".join(parts)}</div>'
        det_fr = (f'<div class="det">dont {_nb(x["fr"])} FR</div>'
                  if x["fr"] is not None and x["clics"] else "")
        corps.append(
            f'<tr><td class="nom"><b>{e(x["pseudo"])}</b><div class="det">{det_liens}</div></td>'
            f'<td class="n">{_nb(x["clics"])}{det_fr}</td>'
            f'<td class="n">{_nb(x["visites"])}</td>'
            f'<td class="n fort">{_nb(x["subs"])}{det_subs}</td>'
            f'<td class="n">{_pct(x["cvr"])}'
            f'{"<div class=det>sur clics OF/MYM</div>" if x.get("cvr_bouton") and x["cvr"] is not None else ""}'
            '</td></tr>')
        if x["clics"] is None:
            clics_ok = False
        else:
            T["clics"] += x["clics"]
            T["fr"] += x["fr"] or 0
        if x["visites"] is None:
            visites_ok = False
        else:
            T["visites"] += x["visites"]
        T["subs"] += x["subs"] or 0
        T["of"] += x["subs_of"]
        T["mym"] += x["subs_mym"]
    pied = ""
    if lignes:
        sans_page = all(x.get("cvr_bouton") for x in lignes)
        cvr_t = ((T["subs"] / T["clics"]) if clics_ok and T["clics"] and not sans_page else
                 (T["subs"] / T["visites"]) if sans_page and T["visites"] else None)
        pied = (f'<tfoot><tr><td>Total · {len(lignes)} VA</td>'
                f'<td class="n">{_nb(T["clics"] if clics_ok else None)}</td>'
                f'<td class="n">{_nb(T["visites"] if visites_ok else None)}</td>'
                f'<td class="n">{_nb(T["subs"])}'
                f'<div class="det">{T["of"]} OF + {T["mym"]} MYM</div></td>'
                f'<td class="n">{_pct(cvr_t)}</td></tr></tfoot>')
    else:
        corps.append('<tr><td colspan="5" class="faible">Aucun VA de You FR sur cette model.</td></tr>')
    avert = "".join(f'<div class="avert">{e(a)}</div>' for a in t["avert"])
    rafraichir = '<meta http-equiv="refresh" content="45">' if t.get("en_cours") else ""
    titre = f"Liens de suivi · {t['nom']} · You FR"
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">'
        f'<meta name="color-scheme" content="dark">{rafraichir}<title>{e(titre)}</title>'
        f'<style>{CSS}</style></head><body>'
        '<div class="marque">MyPuls · You FR</div>'
        f'<h1>{e(titre)}</h1>'
        f'<p class="sous"><b>Du {_jc(du)} au {_jc(au)}</b> · VA du serveur You FR seulement · '
        f'{len(lignes)} VA</p>'
        f'<nav class="models" aria-label="Models">{models}</nav>'
        f'<form class="periode" method="get">{caches}'
        f'<input type="date" name="du" value="{du}" max="{auj.isoformat()}" aria-label="Date de début">'
        f'<span class="faible">→</span>'
        f'<input type="date" name="au" value="{au}" max="{auj.isoformat()}" aria-label="Date de fin">'
        f'<button type="submit">OK</button></form>'
        f'<nav class="raccourcis" aria-label="Périodes">{rac}</nav>'
        f'{avert}'
        '<div class="boite"><table><thead><tr>'
        + _th("nom", "VA", num=False)
        + _th("clics", "Clics", titre="Clics sur la page GetMySocial du VA, tous pays")
        + _th("visites", "Clics OF/MYM", titre="Clics sur les boutons OnlyFans / MYM (MyPuls)")
        + _th("subs", "Subs", titre="Nouveaux abonnés des trackings du VA (MyPuls), OF + MYM")
        + _th("cvr", "CVR", titre="Subs ÷ clics GetMySocial")
        + f'</tr></thead><tbody>{"".join(corps)}</tbody>{pied}</table></div>'
        '<p class="note">Subs : MyPuls, OnlyFans et MYM, bornes incluses (heure de Paris). '
        'CVR = subs ÷ clics GetMySocial. Chiffres relus toutes les 15 min.</p>'
        '</body></html>')


def page(args: Mapping[str, Any], cle: str = "") -> str:
    """La page de ?c=fr-<model>. Ne lève jamais."""
    model = page_de(args.get("c"))
    try:
        du, au = periode(args)
        t = tableau(model, du, au)
        return page_html(t, cle=cle, tri=str(args.get("tri") or "subs"),
                         sens=str(args.get("sens") or "desc"))
    except Exception as ex:                                  # noqa: BLE001
        auj = _aujourdhui().isoformat()
        return page_html({"model": model or "amelia", "nom": PAGES.get(model, {}).get("nom", "?"),
                          "du": auj, "au": auj, "lignes": [],
                          "avert": [f"La page n'a pas pu être construite : {type(ex).__name__} : {ex}"]},
                         cle=cle)
