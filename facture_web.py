"""facture_web.py — Module Facture : compta mensuelle OFM (revenus / dépenses).

Façon expert-comptable adapté agence OFM :
- mois par mois (data/facture.json) : les lignes récurrentes (freq != once)
  sont reportées AUTOMATIQUEMENT sur le mois en cours à l'ouverture de la page
  (_autofill_months), paiements remis à zéro ; le bouton "Démarrer mois
  suivant" fait la même chose à la demande, pour prendre de l'avance
- lignes revenus/dépenses par catégorie (Revenue OF/MYM, modèles, chatters,
  VAs, managers, apps, autres), montant fixe (USD/EUR) ou % d'un revenu
- phases de paiement optionnelles (quinzaine/hebdo), "Marquer payé" par
  ligne ou par phase
- KPI : revenus, dépenses, bénéfice net, part lead (100% - associés)

UI 100% client-side : /facture/app.js (fichier séparé bot/facture_app.js)
qui consomme /facture/state. Enregistré dans web_upload.create_app() via
facture_web.register(app, is_auth).
"""
from __future__ import annotations

import json
import re
import time
import uuid
import calendar
import datetime
import threading
from pathlib import Path
import safe_json

DATA_DIR = Path("data")
FACTURE_FILE = DATA_DIR / "facture.json"
BOT_DIR = Path(__file__).parent.resolve()
_LOCK = threading.Lock()

CATS = {
    "rev_of":    {"label": "Revenue OF",   "icon": "💎", "type": "rev"},
    "rev_mym":   {"label": "Revenue MYM",  "icon": "💛", "type": "rev"},
    "rev_other": {"label": "Autre revenu", "icon": "💵", "type": "rev"},
    "model":     {"label": "Paye modèle",  "icon": "🧜‍♀️", "type": "exp"},
    "chatter":   {"label": "Chatter",      "icon": "💬", "type": "exp"},
    "va":        {"label": "VA",           "icon": "👤", "type": "exp"},
    "manager":   {"label": "Manager",      "icon": "👔", "type": "exp"},
    "app":       {"label": "App / Outil",  "icon": "📱", "type": "exp"},
    "other":     {"label": "Autres",       "icon": "📁", "type": "exp"},
}
CAT_ORDER = ["rev_of", "rev_mym", "rev_other", "model", "chatter", "va", "manager", "app", "other"]
# Bases % « catégorie » (héritées) + on ajoute dynamiquement chaque LIGNE de revenu
# (clé "line:<id>") pour lier un % à un revenu précis.
PCT_BASES = {"rev_total": "de TOUS les revenus", "rev_of": "de Revenue OF", "rev_mym": "de Revenue MYM"}
# Marchés : chaque ligne appartient à un marché. Les anciennes lignes sans le
# champ sont considérées US (l'activité historique de l'user est 100% US).
# Filtre + KPI séparés côté client, split au Bilan.
MARKETS = {"fr": {"label": "Marché FR", "icon": "🇫🇷"}, "us": {"label": "Marché US", "icon": "🇺🇸"}}
MARKET_ORDER = ["fr", "us"]
MARKET_DEFAULT = "us"


def _load() -> dict:
    """Lit data/facture.json — avec le filet `.prev`.

    Avant : lecture directe + `except: pass`. Un fichier tronqué (coupure
    pendant une écriture) rendait donc {} en silence ; les graines se
    rejouaient sur cette « base vierge » et la première sauvegarde recopiait
    d'abord le fichier corrompu sur .prev — la compta ET son filet étaient
    perdus d'un coup. `load_or_prev` restaure la dernière copie saine (et la
    réécrit sans écraser .prev) au lieu de faire croire à un fichier vide.
    """
    try:
        d = safe_json.load_or_prev(FACTURE_FILE)
        if isinstance(d, dict):
            d.setdefault("settings", {})
            d.setdefault("months", {})
            return d
        print(f"[facture] {FACTURE_FILE.name} n'est pas un objet JSON "
              f"({type(d).__name__}) — base vide servie", flush=True)
    except FileNotFoundError:
        # « Fichier absent » et « fichier présent mais illisible » arrivaient
        # ICI tous les deux : load_or_prev lève FileNotFoundError en cherchant
        # un .prev qui n'existe pas, et le cas le plus DANGEREUX — compta
        # tronquée, aucun filet — repartait donc à vide en silence, sous une
        # branche écrite pour la première ouverture. On les sépare.
        if FACTURE_FILE.exists():
            print(f"[facture] ALERTE : {FACTURE_FILE.name} est illisible et il "
                  f"n'existe aucun .prev — base vide servie. NE RIEN "
                  f"ENREGISTRER avant d'avoir restauré une sauvegarde : la "
                  f"prochaine écriture graverait ce vide.", flush=True)
    except Exception as e:
        # ni le fichier ni .prev ne sont lisibles : on le DIT (sinon la
        # sauvegarde suivante gravait ce vide sans laisser de trace).
        # Message sans emoji : la console Windows (cp1252) refuse de les
        # encoder, et une exception ICI ferait tomber tout le module.
        print(f"[facture] ALERTE : {FACTURE_FILE.name} illisible et .prev "
              f"inutilisable ({e}) — base vide servie", flush=True)
    return {"settings": {}, "months": {}}


def _save(d: dict):
    with _LOCK:
        FACTURE_FILE.parent.mkdir(parents=True, exist_ok=True)
        safe_json.write_text(FACTURE_FILE, json.dumps(d, ensure_ascii=False, indent=1))


def _cur_month() -> str:
    return datetime.date.today().strftime("%Y-%m")


_AUTOFILL_LOCK = threading.Lock()
_AUTOFILL_MAX = 12          # garde-fou : jamais plus d'un an de rattrapage


def _as_date(txt):
    """'YYYY-MM-DD' -> date, ou None si vide/illisible (champ saisi à la main)."""
    try:
        return datetime.date.fromisoformat(str(txt or "").strip()[:10])
    except Exception:
        return None


def _line_active_in(line: dict, month: str) -> bool:
    """La ligne est-elle en vigueur pendant `month` ('YYYY-MM') ?

    « Date de début » et « Date de fin » étaient saisies, stockées… et lues par
    personne : un abonnement 50 $/mois terminé le 30/06 était reporté en
    juillet, août, septembre, cumul du Bilan compris. Une ligne compte pour le
    mois entier dès qu'elle chevauche le mois (pas de prorata : la compta se
    fait au mois, comme le reste du module).
    """
    first, last = _month_bounds(month)
    fin = _as_date(line.get("end"))
    if fin and fin < first:
        return False
    debut = _as_date(line.get("start"))
    if debut and debut > last:
        return False
    return True


def _carry_lines(src: list, dest_month: str = "") -> tuple:
    """Lignes d'un mois -> lignes du mois `dest_month`. Rend (lignes, terminées).

    On garde les récurrentes (freq != once), on leur donne une identité neuve,
    on remet les paiements à zéro et on décale les phases d'un mois. Les liens
    « % d'une autre ligne » sont réécrits vers les NOUVELLES ids : sinon le
    pourcentage pointerait sur les lignes du mois précédent et calculerait sur
    une base à zéro.

    Une ligne dont la « Date de fin » est passée n'est PAS reportée : c'est
    définitif, elle ne peut plus redevenir active, donc rien n'est perdu. Les
    labels des lignes écartées sont rendus à l'appelant (jamais d'abandon
    silencieux : le mois créé doit pouvoir dire ce qu'il a laissé derrière).

    À l'inverse une ligne PAS ENCORE commencée est reportée quand même : la
    supprimer ici la ferait disparaître avant même sa date de début (le report
    est en chaîne, un mois ne voit que le précédent). Son montant est mis à
    zéro à l'affichage par _line_active_in, pas ici.
    """
    new_lines, id_map, finies = [], {}, []
    for l in src or []:
        if l.get("freq") == "once":
            continue
        _fin = _as_date(l.get("end"))
        if dest_month and _fin and _fin < _month_bounds(dest_month)[0]:
            finies.append({"label": l.get("label") or l.get("id") or "?",
                           "end": str(l.get("end") or "")})
            continue
        nl = dict(l)
        nl["id"] = uuid.uuid4().hex[:12]
        if l.get("id"):
            id_map[l["id"]] = nl["id"]
        nl["paid"] = False
        nl["paid_at"] = ""
        phs = []
        for ph in (l.get("phases") or []):
            try:
                pd = datetime.date.fromisoformat(ph["date"])
                ny = pd.year + (1 if pd.month == 12 else 0)
                nmn = 1 if pd.month == 12 else pd.month + 1
                lastd = calendar.monthrange(ny, nmn)[1]
                phs.append({"date": datetime.date(ny, nmn, min(pd.day, lastd)).isoformat(),
                            "paid": False, "paid_at": ""})
            except Exception:
                pass
        nl["phases"] = phs
        new_lines.append(nl)
    for nl in new_lines:
        po = nl.get("pct_of") or ""
        if po.startswith("line:"):
            nl["pct_of"] = "line:" + id_map.get(po[5:], po[5:])
        elif po.startswith("lines:"):
            nl["pct_of"] = "lines:" + ",".join(id_map.get(i, i) for i in po[6:].split(",") if i)
    return new_lines, finies


def _autofill_months(upto: str = "") -> int:
    """Crée les mois MANQUANTS jusqu'au mois en cours, avec les lignes
    récurrentes reportées — une charge mensuelle saisie une fois revient
    ensuite toute seule, sans avoir à cliquer « Démarrer mois suivant ».

    Deux garde-fous :
    - un mois DÉJÀ présent n'est jamais retouché, même vide : le vider est un
      choix, on ne le re-remplit pas dans son dos ;
    - au plus 12 mois de rattrapage, pour qu'un fichier ancien ne fabrique pas
      des années de comptabilité d'un coup.
    """
    cible = (upto or _cur_month())[:7]
    faits = 0
    with _AUTOFILL_LOCK:
        d = _load()
        mois = d.get("months") or {}
        avec_lignes = sorted(k for k in mois if (mois[k].get("lines") or []))
        if not avec_lignes:
            return 0
        cur = avec_lignes[-1]
        if cur >= cible:
            return 0
        while cur < cible and faits < _AUTOFILL_MAX:
            nxt = _month_shift(cur, 1)
            if nxt in mois:                       # mois existant : on n'y touche pas
                cur = nxt
                continue
            lignes, finies = _carry_lines((mois.get(cur) or {}).get("lines") or [], nxt)
            if finies:
                # Rien ne doit disparaître sans trace : on nomme les lignes que
                # leur date de fin sort du report.
                print(f"[facture] {nxt} : {len(finies)} ligne(s) NON reportée(s) "
                      "(date de fin passée) : "
                      + ", ".join(f"{f['label']} (fin {f['end']})" for f in finies[:8]),
                      flush=True)
            if not lignes:                        # rien de récurrent à propager
                break
            mois[nxt] = {"lines": lignes, "auto": True}
            cur = nxt
            faits += 1
        if faits:
            d["months"] = mois
            _save(d)
    return faits


def _month_shift(month: str, delta: int) -> str:
    idx = int(month[:4]) * 12 + int(month[5:7]) - 1 + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def _month_bounds(month: str):
    y, m = int(month[:4]), int(month[5:7])
    last = calendar.monthrange(y, m)[1]
    return datetime.date(y, m, 1), datetime.date(y, m, last)


def _month_last_day(month: str) -> str:
    """'YYYY-MM' -> 'YYYY-MM-DD' du dernier jour du mois (pour le taux historique)."""
    return _month_bounds(month)[1].isoformat()


_EUR_USD_SRC_CACHE = {"ts": 0.0, "val": None}   # mémo process (taux, source)
_EUR_USD_SRC_TTL = 60


def _live_eur_usd_src() -> tuple:
    """(taux, source) — source in {api, cache, stale_cache, fallback, error}.
    Sert à ne JAMAIS figer un mois clos sur le repli 1.10 (source 'fallback').

    MÉMOÏSÉ 60 s en process : compute_bilan appelle _month_rate pour CHAQUE mois
    clos ; sans ce cache, un cache BCE froid + API injoignable relançait un
    requests.get(timeout=10) par mois (~120 s de hang par rendu, rejoué à chaque
    ouverture). Ici : au plus un appel réseau court par salve de rendu."""
    import time as _t
    now = _t.time()
    c = _EUR_USD_SRC_CACHE
    if c["val"] is not None and (now - c["ts"]) < _EUR_USD_SRC_TTL:
        return c["val"]
    try:
        import mypuls
        r = mypuls.get_eur_usd_rate()
        val = (float(r["rate"]), str(r.get("source") or "?"))
    except Exception:
        val = (1.10, "error")
    c["val"] = val
    c["ts"] = now
    return val


def _live_eur_usd() -> float:
    """Taux EUR->USD UNIQUE pour tout le site : le taux BCE live (cache 24 h),
    repli 1.10. Avant : la Facture convertissait à 1.08, la home à 1.14 et la
    paie chatteurs au taux BCE -> trois valeurs différentes pour le même revenu
    (jusqu'à ~8 % d'écart sur la part lead). settings.eur_usd reste prioritaire
    si l'utilisateur l'a fixé explicitement."""
    return _live_eur_usd_src()[0]


def _to_usd(amount: float, currency: str, settings: dict) -> float:
    rate = float(settings.get("eur_usd") or 0) or _live_eur_usd()
    if (currency or "USD").upper() == "EUR":
        return amount * rate
    return amount


_MYPULS_CACHE_FILE = DATA_DIR / "facture_mypuls_cache.json"
_MYPULS_MONTH_CACHE: dict = {}

def _norm_model(s: str) -> str:
    """Clé de comparaison d'un pseudo : sans emoji, sans accent, sans ponctuation.
    « Khloe 💕 » et « khloe » donnent la même clé."""
    import unicodedata
    txt = unicodedata.normalize("NFKD", str(s or ""))
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    keep = [c for c in txt.lower() if c.isalnum() or c.isspace()]
    return " ".join("".join(keep).split())


def _squash(s: str) -> str:
    """Clé ultra-tolérante : lettres/chiffres seulement.
    « Amelia_xoxo », « amelia.xoxo », « Amelia XOXO » -> « ameliaxoxo »."""
    return re.sub(r"[^a-z0-9]", "", _norm_model(s))


def _resolve_api_creator(model: str, creators: list):
    """Retrouve la créatrice de l'API correspondant au libellé stocké sur la ligne.

    Le libellé vient du SCRAPING (le select est rempli par list_creators(), qui
    lit le HTML), alors qu'on le compare au champ `pseudo` de l'API REST : deux
    référentiels de noms distincts, donc l'égalité stricte casse facilement.
    4 passes du plus strict au plus large, une passe n'étant retenue que si elle
    donne UN SEUL candidat (jamais d'appariement ambigu), puis repli par ID.
    Retourne (creator|None, explication).
    """
    want_n, want_s = _norm_model(model), _squash(model)
    if not want_s:
        return None, "libellé de créatrice vide sur la ligne"

    def _uniq(cands):
        return cands[0] if len(cands) == 1 else None

    # 1) égalité normalisée sur le pseudo (comportement historique)
    for c in creators:
        if want_n and _norm_model(c.get("pseudo")) == want_n:
            return c, "pseudo exact"
    # 2) égalité « squash » : underscore / point / espace ignorés
    m = _uniq([c for c in creators if _squash(c.get("pseudo")) == want_s])
    if m:
        return m, "pseudo squash"
    # Les passes floues ne s'appliquent qu'à un libellé assez long pour être
    # discriminant : sur 3-4 lettres, un préfixe attrape n'importe qui.
    if len(want_s) >= 5:
        # 3) préfixe dans un sens ou dans l'autre (handle vs prénom)
        m = _uniq([c for c in creators
                   if _squash(c.get("pseudo"))
                   and (_squash(c.get("pseudo")).startswith(want_s)
                        or want_s.startswith(_squash(c.get("pseudo"))))])
        if m:
            return m, "pseudo préfixe"
        # 4) sous-chaîne
        m = _uniq([c for c in creators
                   if _squash(c.get("pseudo"))
                   and (want_s in _squash(c.get("pseudo"))
                        or _squash(c.get("pseudo")) in want_s)])
        if m:
            return m, "pseudo sous-chaîne"
    # 5) REPLI PAR ID : marche même si `pseudo` est null (autorisé par la spec)
    # ou si la créatrice n'est pas listée. list_creators() renvoie {nom: id}
    # dans le MÊME espace d'ID que l'API.
    try:
        import mypuls
        scraped = (mypuls.list_creators().get("creators") or {})
        cid = next((i for n, i in scraped.items() if _squash(n) == want_s), None)
        if cid is None and len(want_s) >= 5:
            cid = next((i for n, i in scraped.items()
                        if _squash(n) and (_squash(n).startswith(want_s)
                                           or want_s.startswith(_squash(n)))), None)
        if cid is not None:
            byid = next((c for c in creators if c.get("id") == cid), None)
            return (byid or {"id": cid, "pseudo": model, "currency": "", "platform": ""}), \
                   f"repli par ID scraping (#{cid})"
    except Exception as e:
        return None, f"repli par ID impossible : {type(e).__name__}: {e}"
    dispo = ", ".join((c.get("pseudo") or f"#{c.get('id')}") for c in creators[:10])
    return None, f"aucune correspondance (API : {dispo})"


def _mypuls_month_amount(model: str, month: str, creator_id=None):
    """CA du mois d'une créatrice -> (montant, devise, deja_net, info).

    info = {"api", "why", "creator_id", "resolution", "api_configured"}
    PRIORITÉ ABSOLUE à l'API : montant EXACT, posts inclus, DÉJÀ NET, bonne
    devise (le scraping était toujours supposé en EUR, ce qui gonflait de 8 %
    les créatrices OnlyFans facturées en USD).
    Tout repli sur le scraping est LOGGÉ et REMONTÉ à l'interface : si le token
    API est là, un montant scrapé n'est JAMAIS présenté comme net.
    """
    import calendar
    import traceback
    info = {"api": False, "why": "", "creator_id": None, "resolution": "",
            "api_configured": False}
    try:
        import mypuls
        info["api_configured"] = mypuls.api_configured()
    except Exception as e:
        info["why"] = f"module mypuls indisponible : {type(e).__name__}: {e}"
        print("[facture] " + traceback.format_exc(), flush=True)

    if info["api_configured"]:
        try:
            y, m = int(month[:4]), int(month[5:7])
            last = calendar.monthrange(y, m)[1]
            d_from = f"{month}-01"
            # Borne de fin JAMAIS dans le futur : même convention que le scraping
            # (min(last, today)) et que le dashboard (end=today).
            d_to = min(datetime.date(y, m, last), datetime.date.today()).isoformat()
            if d_to < d_from:
                return 0.0, "USD", True, dict(info, api=True, resolution="mois futur")

            creators = mypuls.api_creators_cached()
            match, why_res = None, ""
            if creator_id:                       # ID épinglé sur la ligne : chemin roi
                try:
                    _cid = int(creator_id)
                    match = next((c for c in creators if c.get("id") == _cid),
                                 {"id": _cid, "pseudo": model, "currency": "", "platform": ""})
                    why_res = f"ID épinglé (#{_cid})"
                except Exception:
                    match = None
            if match is None:
                match, why_res = _resolve_api_creator(model, creators)
            info["resolution"] = why_res

            if match is None:
                info["why"] = f"« {model} » : {why_res}"
            else:
                info["creator_id"] = match.get("id")
                r = mypuls.api_creator_stats_cached(match["id"], d_from, d_to)
                if not r.get("ok") and d_to != f"{month}-{last:02d}":
                    # 2e chance avec la borne pleine du mois
                    r = mypuls.api_creator_stats_cached(match["id"], d_from, f"{month}-{last:02d}")
                if r.get("ok"):
                    rev = ((r.get("data") or {}).get("revenue") or {})
                    cur = (rev.get("currency") or match.get("currency") or "USD").upper()
                    # STALE : api_creator_stats_cached sert le dernier bon relevé
                    # quand l'API échoue. On garde ce montant (mieux que le repli
                    # scraping EUR/brut) mais on le SIGNALE — sinon une valeur
                    # périmée passait pour un chiffre API exact (revenus, net et
                    # part lead faussés sans aucun indice).
                    _st = bool(r.get("stale"))
                    _inf = dict(info, api=True)
                    if _st:
                        _inf["stale"] = True
                        _inf["stale_ts"] = r.get("stale_ts")
                        _inf["why"] = "dernier relevé MyPuls (API momentanément indisponible)"
                    return float(rev.get("total") or 0), cur, True, _inf
                info["why"] = (f"stats API KO (créatrice #{match.get('id')}) : "
                               f"{str(r.get('error'))[:120]}")
        except Exception as e:
            info["why"] = f"exception : {type(e).__name__}: {e}"
            print("[facture] " + traceback.format_exc(), flush=True)   # PLUS JAMAIS avalée
    elif not info["why"]:
        info["why"] = "token API absent (Settings → MyPuls)"

    # ---- REPLI SCRAPING : brut, supposé EUR, jamais silencieux ----
    print(f"[facture] repli scraping « {model} » ({month}) : {info['why']}", flush=True)
    return float(_mypuls_ca(model, month) or 0), "EUR", False, info


def _mypuls_ca(model: str, month: str) -> float:
    """CA MyPuls (EUR) d'une créatrice sur un mois entier.
    Mois PASSÉS : cache disque permanent (le CA ne bouge plus une fois le mois
    fini) ; mois COURANT : cache 5 min interne de mypuls.fetch_team_stats."""
    want = (model or "").strip().lower()
    if not want:
        return 0.0
    cur = _cur_month()
    key = f"{month}|{want}"
    global _MYPULS_MONTH_CACHE
    if month < cur:
        if not _MYPULS_MONTH_CACHE and _MYPULS_CACHE_FILE.exists():
            try:
                _MYPULS_MONTH_CACHE = json.loads(_MYPULS_CACHE_FILE.read_text(encoding="utf-8"))
            except Exception:
                _MYPULS_MONTH_CACHE = {}
        if key in _MYPULS_MONTH_CACHE:
            return float(_MYPULS_MONTH_CACHE[key])
    try:
        import mypuls
        first, last = _month_bounds(month)
        today = datetime.date.today()
        if first > today:
            return 0.0
        st = mypuls.fetch_team_stats(first.isoformat(), min(last, today).isoformat())
        if not st.get("ok"):
            return 0.0
        tot = round(sum(float(tx.get("amount") or 0) for tx in (st.get("transactions") or [])
                        if (tx.get("creator") or "").strip().lower() == want), 2)
        if month < cur:  # mois clos + fetch OK -> on fige
            _MYPULS_MONTH_CACHE[key] = tot
            try:
                _MYPULS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                safe_json.write_text(_MYPULS_CACHE_FILE, json.dumps(_MYPULS_MONTH_CACHE))
            except Exception:
                pass
        return tot
    except Exception:
        return 0.0


def _pcache_get(key: str):
    """Cache disque permanent (mois clos) partagé CA/frais MyPuls."""
    global _MYPULS_MONTH_CACHE
    if not _MYPULS_MONTH_CACHE and _MYPULS_CACHE_FILE.exists():
        try:
            _MYPULS_MONTH_CACHE = json.loads(_MYPULS_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            _MYPULS_MONTH_CACHE = {}
    return _MYPULS_MONTH_CACHE.get(key)


def _pcache_set(key: str, val: float):
    _MYPULS_MONTH_CACHE[key] = val
    try:
        _MYPULS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        safe_json.write_text(_MYPULS_CACHE_FILE, json.dumps(_MYPULS_MONTH_CACHE))
    except Exception:
        pass


def _mypuls_crm_fees(month: str) -> float:
    """Total (EUR) des factures CRM MyPuls du mois (onglet Factures & Paiements).
    Mois clos = figé en cache disque (clé '<mois>|__crm__')."""
    cur = _cur_month()
    key = f"{month}|__crm__"
    if month < cur:
        v = _pcache_get(key)
        if v is not None:
            return float(v)
    try:
        import mypuls
        res = mypuls.fetch_invoices()
        if not res.get("ok"):
            return 0.0
        tot = round(sum(float(i.get("amount") or 0) for i in (res.get("invoices") or [])
                        if (i.get("date_iso") or "")[:7] == month), 2)
        if month < cur:
            _pcache_set(key, tot)
        return tot
    except Exception:
        return 0.0


VA_CLICK_RATE = 0.07  # $/clic éligible — taux « expert » appliqué à plat (pour être large)
_VA_CLICKS_CACHE: dict = {}  # month -> (ts, clicks)


def _va_clicks_month(month: str) -> int:
    """Clics éligibles (FR/BE/CH/LU/MC) des GROUPES marché FR (Lola/Amelia/Alicia/
    Julia/Emma/Sarah, JAMAIS les groupes jailbreak) sur le mois entier.
    Mois clos figé en cache disque ; mois courant re-calculé toutes les 10 min.
    Si GMS indispo (cookie board expiré, etc.) on GARDE la dernière valeur connue
    au lieu d'afficher un faux 0."""
    cur = _cur_month()
    key = f"{month}|__vaclicks__"
    if month < cur:
        v = _pcache_get(key)
        if v is not None:
            return int(v)
    c = _VA_CLICKS_CACHE.get(month)
    if c and (time.time() - c[0]) < 600:
        return int(c[1])
    try:
        import gms
        first, last = _month_bounds(month)
        if first > datetime.date.today():
            return 0
        res = gms.fr_market_eligible_clicks(first.isoformat(), last.isoformat())
        if not res.get("ok"):
            return int(c[1]) if c else 0  # indispo -> garde l'ancien, pas de faux 0
        clicks = int(res.get("eligible") or 0)
    except Exception:
        return int(c[1]) if c else 0
    _VA_CLICKS_CACHE[month] = (time.time(), clicks)
    if month < cur and clicks > 0:
        _pcache_set(key, clicks)
    return clicks


def _line_usd(line: dict, rev_bases: dict, settings: dict) -> float:
    """Montant mensuel en USD d'une ligne : fixe converti, ou % d'une base revenus
    (globale 'rev_total'/'rev_of'/'rev_mym', UNE ligne 'line:<id>' ou PLUSIEURS
    lignes 'lines:<id1>,<id2>,...' -> somme des revenus sélectionnés)."""
    if (line.get("form") or "fixed") == "pct":
        pct = float(line.get("pct") or 0)
        po = line.get("pct_of") or "rev_total"
        if po.startswith("lines:"):
            base = sum(float(rev_bases.get(f"line:{i}", 0)) for i in po[6:].split(",") if i)
        else:
            base = float(rev_bases.get(po, 0))
        return round(pct / 100.0 * base, 2)
    return round(_to_usd(float(line.get("amount") or 0), line.get("currency") or "USD", settings), 2)


def _pct_base_ids(line: dict) -> list:
    """Ids des revenus servant de base à une ligne en % (vide si base globale).

    Une seule lecture de `pct_of` pour tout le module : 'line:<id>' (une base)
    et 'lines:<id>,<id>' (plusieurs) se comportaient différemment à trois
    endroits, et c'est exactement là que les messages se sont mis à mentir.
    """
    if (line.get("form") or "fixed") != "pct":
        return []
    po = str(line.get("pct_of") or "")
    if po.startswith("lines:"):
        return [i for i in po[6:].split(",") if i]
    if po.startswith("line:") and po[5:]:
        return [po[5:]]
    return []               # rev_total / rev_of / rev_mym : jamais orphelines


def _lines_index(d: dict) -> dict:
    """id de ligne -> ligne, TOUS mois confondus (première occurrence gardée).

    Le report mensuel réattribue des ids neufs : une base qui n'est plus
    reportée parce que sa DATE DE FIN est passée n'existe plus que dans les
    mois précédents. Sans cet index, impossible de distinguer une base
    SUPPRIMÉE d'une base TERMINÉE — et l'écran conseillait « redonne-leur une
    base » à propos d'une ligne qui s'était simplement arrêtée à sa date de fin.
    """
    idx = {}
    for m in (d.get("months") or {}).values():
        for l in (m.get("lines") or []):
            i = l.get("id")
            if i and i not in idx:
                idx[i] = l
    return idx


def _pct_base_state(line: dict, rev_bases: dict, idx: dict, month: str):
    """État des bases « % d'une ligne », ou None si elles répondent toutes.

    QUATRE situations que l'écran confondait sous « base supprimée — 0 $ » :
      - TOUTES les bases ont disparu -> la ligne vaut bien 0 $ ;
      - une base sur plusieurs a disparu et ce qui RESTE vaut encore quelque
        chose -> la ligne calcule dessus : annoncer 0 $ était faux ;
      - une base sur plusieurs a disparu et ce qui RESTE vaut 0 $ ce mois-ci
        (revenu pas encore commencé, ou à zéro) -> la ligne est rendue à 0 $ :
        lui promettre « elle compte encore, seulement plus petit » était faux,
        d'où `reste_usd` / `reste_nul`, calculés en DOLLARS et pas en nombre
        d'ids ;
      - la base n'a PAS été supprimée : on la RETROUVE dans le fichier (`idx`),
        elle n'est simplement pas dans CE mois — date de fin passée, ligne
        ponctuelle (freq « once »), fin repoussée après coup, type basculé en
        dépense... Le badge la NOMME : écrire « supprimée » juste avant son nom
        se contredisait à l'œil nu.

    C'est donc l'INDEX qui tranche « supprimée » (un id retrouvé n'a pas été
    supprimé), jamais la date de fin : celle-ci ne fait que préciser POURQUOI
    la base n'est plus reportée.
    Rendu : {"total", "manquantes", "vide", "expirees", "supprimees",
             "absentes", "reste_usd", "reste_nul", "details"[{etat,label,end}]}.
    """
    if (line.get("form") or "fixed") != "pct":
        return None
    po = str(line.get("pct_of") or "")
    ids = _pct_base_ids(line)
    if not ids:
        if po.startswith("lines:"):
            # base VIDÉE (la dernière ligne de base a été supprimée) : plus rien
            # à calculer, et plus aucun id pour dire de quoi il s'agissait.
            return {"total": 0, "manquantes": 0, "vide": True,
                    "expirees": 0, "supprimees": 0, "absentes": 0,
                    "reste_usd": 0.0, "reste_nul": True, "details": []}
        return None
    manquants = [i for i in ids if f"line:{i}" not in rev_bases]
    if not manquants:
        return None
    # Ce qui RESTE, en dollars : une base qui répond encore peut très bien
    # valoir 0 ce mois-ci (revenu pas encore commencé, ou nul). Compter les ids
    # ne dit donc rien du montant obtenu.
    reste_usd = round(sum(float(rev_bases.get(f"line:{i}") or 0.0)
                          for i in ids if f"line:{i}" in rev_bases), 2)
    first = _month_bounds(month)[0]
    details, expirees, supprimees, absentes = [], 0, 0, 0
    for i in manquants:
        src = idx.get(i)
        if src is None:
            # Introuvable dans TOUT le fichier : celle-là a bien été supprimée.
            # (Le report donne des ids neufs : un id survivant se retrouve
            # toujours dans le mois où il vit.) Ni libellé ni date à montrer.
            supprimees += 1
            details.append({"etat": "supprimee", "label": "", "end": ""})
            continue
        fin = _as_date(src.get("end"))
        if fin and fin < first:
            expirees += 1
            details.append({"etat": "terminee",
                            "label": str(src.get("label") or "")[:60],
                            "end": str(src.get("end") or "")})
        else:
            # Retrouvée, pas terminée : elle EXISTE, elle n'est simplement pas
            # dans ce mois. La faire retomber sur « supprimée » était le
            # mensonge — le badge donne son nom dans la phrase suivante.
            absentes += 1
            details.append({"etat": "absente",
                            "label": str(src.get("label") or "")[:60], "end": ""})
    return {"total": len(ids), "manquantes": len(manquants), "vide": False,
            "expirees": expirees, "supprimees": supprimees, "absentes": absentes,
            "reste_usd": reste_usd, "reste_nul": abs(reste_usd) < 0.005,
            "details": details[:6]}


def _pin_creator_id(month: str, line_id, cid: int) -> None:
    """Écrit l'ID MyPuls résolu sur une ligne (backfill).
    Idempotent : n'écrase jamais un ID déjà posé. NB : pas de `with _LOCK` ici,
    _save() le prend déjà (verrou non réentrant -> deadlock sinon), même idiome
    que les routes du module."""
    if not line_id or not cid:
        return
    d = _load()
    for l in ((d["months"].get(month) or {}).get("lines") or []):
        if l.get("id") == line_id and not l.get("mypuls_creator_id"):
            l["mypuls_creator_id"] = int(cid)
            _save(d)
            print(f"[facture] ID MyPuls #{cid} épinglé sur la ligne "
                  f"« {l.get('label')} » ({month})", flush=True)
            break


def _month_rate(d: dict, month: str) -> float:
    """Taux EUR->USD à utiliser pour CE mois.

    Un mois CLOS garde le taux figé au moment de sa clôture : sans ça, ses
    totaux (et le Bilan cumulé) changeaient tout seuls chaque jour au gré du
    marché des changes. Le mois EN COURS suit le taux courant.
    """
    fixed = (d.get("settings") or {}).get("month_rates") or {}
    if month in fixed:
        try:
            v = float(fixed[month] or 0)
            if v > 0:
                return v
        except Exception:
            pass
    override = float((d.get("settings") or {}).get("eur_usd") or 0)
    if override > 0:
        cur_rate, src = override, "override"
    else:
        cur_rate, src = _live_eur_usd_src()
    if month < _cur_month():
        # Mois terminé : on fige le taux pour toujours — MAIS :
        #  - un mois SAISI TARDIVEMENT (ex. juin saisi en octobre) doit être figé
        #    sur SON taux d'époque, pas sur le 'latest' du jour (qui sur/sous-
        #    évaluait ses lignes EUR de quelques %). On récupère donc le taux BCE
        #    HISTORIQUE du dernier jour du mois ;
        #  - jamais le repli 1.10 (source 'fallback'/'error') ;
        #  - via un upsert ATOMIQUE (jamais _save du snapshot d'un GET).
        freeze = None
        if override > 0:
            freeze = override                       # taux manuel = autorité
        else:
            try:
                import mypuls
                h = mypuls.get_eur_usd_rate_for_date(_month_last_day(month))
                if h.get("source") in ("api", "cache") and float(h.get("rate") or 0) > 0:
                    freeze = float(h["rate"])
            except Exception:
                freeze = None
            # Repli : historique indisponible -> taux live SEULEMENT s'il est fiable.
            if freeze is None and src in ("api", "cache", "stale_cache") and cur_rate > 0:
                freeze = cur_rate
        if freeze and freeze > 0:
            _freeze_month_rate(month, freeze)
            # reflète dans le snapshot courant (mémoire seule, pas de persistance)
            d.setdefault("settings", {}).setdefault("month_rates", {}).setdefault(month, freeze)
            return freeze
    return cur_rate


def _freeze_month_rate(month: str, rate: float) -> None:
    """Fige le taux d'un mois clos de façon ATOMIQUE : re-lit le document sous
    verrou et n'ajoute QUE settings.month_rates[month] s'il est absent. Ne
    réécrit jamais un snapshot venu d'un chemin GET -> pas de lost-update d'une
    ligne/toggle enregistré par une requête POST concurrente."""
    try:
        with _LOCK:
            cur = _load()
            mr = cur.setdefault("settings", {}).setdefault("month_rates", {})
            if month in mr:
                return
            mr[month] = rate
            FACTURE_FILE.parent.mkdir(parents=True, exist_ok=True)
            safe_json.write_text(FACTURE_FILE, json.dumps(cur, ensure_ascii=False, indent=1))
    except Exception:
        pass


def compute_state(month: str) -> dict:
    """État complet du mois : settings + lignes (montants USD résolus) + totaux."""
    d = _load()
    settings = {
        "eur_usd": _month_rate(d, month),
        # BRUT : 0 = mode auto (taux BCE live). Le champ du modal doit afficher
        # CE zéro (vide), pas le taux résolu — sinon enregistrer les réglages
        # figeait le taux auto sur la valeur du jour pour tout le site.
        "eur_usd_raw": float(d["settings"].get("eur_usd") or 0),
        "cutoff": int(d["settings"].get("cutoff") or 15),
        "associates": d["settings"].get("associates") or [],
        # nom affiché pour « payée par moi » (menu Payée par + badge des lignes)
        "lead_name": str(d["settings"].get("lead_name") or "Sama").strip()[:40] or "Sama",
    }
    months = sorted(d["months"].keys())
    cur = _cur_month()
    if cur not in months:
        months.append(cur)
    # 6 mois précédents toujours proposés (navigation arrière même sans données,
    # pour saisir/consulter un mois passé)
    for i in range(1, 7):
        pm = _month_shift(cur, -i)
        if pm not in months:
            months.append(pm)
    # + le mois demandé lui-même (au cas où il est plus vieux que la fenêtre)
    if month not in months:
        months.append(month)
    months.sort()
    lines = list((d["months"].get(month) or {}).get("lines") or [])

    # Bases revenus (pour les lignes en %) : globales + PAR LIGNE ('line:<id>').
    # Une ligne 'mypuls' = revenu AUTO : CA du mois tiré de MyPuls (EUR->USD).
    rev_bases = {"rev_total": 0.0, "rev_of": 0.0, "rev_mym": 0.0}
    resolved_rev = {}
    resolved_src = {}   # id -> {"api": bool, "why": str} : provenance du montant MyPuls
    for l in lines:
        if l.get("type") != "rev":
            continue
        form = l.get("form") or "fixed"
        _already_net = False
        if not _line_active_in(l, month):
            # Hors [Date de début, Date de fin] : la ligne reste visible (elle
            # sera reportée tant que sa fin n'est pas passée) mais ne rapporte
            # rien ce mois-ci — et on n'interroge pas MyPuls pour rien.
            if form == "pct":
                continue          # mise à 0 par la 2e passe, plus bas
            usd = 0.0
        elif form == "fixed":
            usd = _to_usd(float(l.get("amount") or 0), l.get("currency") or "USD", settings)
        elif form == "mypuls":
            _amt, _cur, _already_net, _info = _mypuls_month_amount(
                l.get("mypuls_model") or "", month, l.get("mypuls_creator_id"))
            usd = round(_to_usd(_amt, _cur, settings), 2)
            # BACKFILL : la résolution par nom a trouvé la créatrice -> on épingle
            # son ID sur la ligne, définitivement. Les prochains rendus prennent
            # le chemin direct par ID et le résolveur flou meurt de lui-même.
            if (_already_net and _info.get("creator_id")
                    and not l.get("mypuls_creator_id")):
                try:
                    _pin_creator_id(month, l.get("id"), int(_info["creator_id"]))
                    l["mypuls_creator_id"] = int(_info["creator_id"])
                except Exception:
                    pass
            if l.get("id"):
                resolved_src[l["id"]] = {
                    "api": _already_net,
                    "why": _info.get("why") or "",
                    "creator_id": _info.get("creator_id"),
                    "resolution": _info.get("resolution") or "",
                    # token présent MAIS repli scraping -> ERREUR visible (rouge).
                    # Interdit de servir un montant scrapé qui a l'air net.
                    "error": bool(_info.get("api_configured")) and not _already_net,
                }
        else:
            continue  # % d'un autre revenu -> résolu ensuite via rev_bases
        # Frais plateforme (ex OnlyFans 20 %) : le montant est BRUT -> on garde le NET.
        # Si la source est l'API MyPuls, elle est DÉJÀ nette -> aucune déduction
        # (sinon on retirerait les 20 % deux fois).
        _fee = float(l.get("fee_pct") or 0)
        if _fee > 0 and not _already_net:
            usd = round(usd * (1 - _fee / 100.0), 2)
        if l.get("id"):
            resolved_rev[l["id"]] = usd
            rev_bases[f"line:{l['id']}"] = usd
        rev_bases["rev_total"] += usd
        if l.get("cat") in ("rev_of", "rev_mym"):
            rev_bases[l["cat"]] += usd

    # 2e passe : les REVENUS en « % d'un autre revenu ». Ils étaient comptés
    # dans le total affiché mais jamais versés dans rev_bases : toute dépense
    # en % (paye chatteur « 7 % de TOUS les revenus ») était donc calculée sur
    # une assiette amputée de ces revenus-là, et sous-payée d'autant.
    # Les montants sont calculés sur un INSTANTANÉ des bases de la 1re passe
    # puis ajoutés d'un bloc : sinon un revenu « % du total » se gonflerait
    # lui-même, et le résultat des autres dépendrait de l'ordre de saisie.
    _bases_1 = dict(rev_bases)
    _pct_rev = []
    for l in lines:
        if l.get("type") != "rev" or (l.get("form") or "fixed") != "pct":
            continue
        if not _line_active_in(l, month):
            usd = 0.0
        else:
            usd = _line_usd(l, _bases_1, settings)
            _fee = float(l.get("fee_pct") or 0)
            if _fee > 0:      # même règle que les autres revenus : brut -> net
                usd = round(usd * (1 - _fee / 100.0), 2)
        _pct_rev.append((l, usd))
    for l, usd in _pct_rev:
        if l.get("id"):
            resolved_rev[l["id"]] = usd
            rev_bases[f"line:{l['id']}"] = usd
        rev_bases["rev_total"] += usd
        if l.get("cat") in ("rev_of", "rev_mym"):
            rev_bases[l["cat"]] += usd

    out_lines = []
    tot_rev = tot_exp = 0.0
    by_market = {mk: {"rev": 0.0, "exp": 0.0, "rev_count": 0, "exp_count": 0,
                      "reimb": 0.0, "reimb_assoc": {}} for mk in MARKETS}
    # Lignes en % dont la base ne répond plus. Compteurs SÉPARÉS parce que ce
    # sont des phrases différentes à l'écran : rendue à 0 $ (plus aucune base,
    # ou bases restantes à 0 $), et parmi celles-là la part dont la base est
    # seulement ARRIVÉE À SA FIN ou VRAIMENT supprimée ; à part, les lignes
    # dont il reste une base QUI VAUT ENCORE quelque chose (montant réduit,
    # surtout pas 0 $).
    pct_orphelines = 0
    pct_orph_expirees = 0
    pct_orph_supprimees = 0
    pct_partielles = 0
    _lidx = _lines_index(d)     # pour retrouver une base des mois précédents
    for l in lines:
        extra = {}
        if l.get("id") in resolved_src:
            extra["mp_src"] = resolved_src[l["id"]]
        # Hors de sa période : plus rien à payer / à encaisser ce mois-ci. Le
        # test est refait ici (et pas hérité de la 1re passe) pour couvrir AUSSI
        # les lignes sans id, qui ne peuvent pas être retrouvées par leur clé.
        _actif = _line_active_in(l, month)
        if not _actif:
            usd = 0.0
        elif l.get("id") in resolved_rev:
            usd = resolved_rev[l["id"]]
        elif (l.get("form") or "") == "mypuls_crm":
            # dépense AUTO : total des factures CRM MyPuls du mois (EUR->USD)
            usd = round(_to_usd(_mypuls_crm_fees(month), "EUR", settings), 2)
        elif (l.get("form") or "") == "va_clicks":
            # dépense AUTO : clics éligibles des VAs Discord x 0.07$ (déjà en USD)
            clicks = _va_clicks_month(month)
            usd = round(clicks * VA_CLICK_RATE, 2)
            extra["va_clicks"] = clicks
        else:
            usd = _line_usd(l, rev_bases, settings)
        if (l.get("form") or "") == "pct" and _actif:
            # Base « % d'une ligne » qui ne répond plus : _line_usd rend 0 (ou
            # moins que prévu) sans le dire, et la paye s'évaporait en silence
            # — 800 $ de paye modèle en moins, part lead gonflée d'autant,
            # recopié chaque mois. On REMONTE l'état exact au client, qui écrit
            # la phrase correspondante. Inutile sur une ligne hors de sa
            # période : son 0 $ vient de ses dates, pas de sa base, et lui
            # donner une base n'y changerait rien.
            _pb = _pct_base_state(l, rev_bases, _lidx, month)
            if _pb:
                extra["pct_base"] = _pb
                _aucune = _pb["vide"] or _pb["manquantes"] >= _pb["total"]
                # 0 $ pour DEUX raisons : plus aucune base, ou des bases
                # restantes qui ne valent rien ce mois-ci. Ranger la seconde
                # dans « partielles » peignait en orange « la ligne compte
                # encore, seulement plus petit » une ligne rendue à 0 $.
                if _aucune or _pb["reste_nul"]:
                    pct_orphelines += 1
                    _mq = _pb["manquantes"]
                    if _aucune and _mq and _pb["expirees"] >= _mq:
                        pct_orph_expirees += 1   # ... par date de fin, pas par suppression
                    if _aucune and _mq and _pb["supprimees"] >= _mq:
                        pct_orph_supprimees += 1  # ... vraiment supprimées (introuvables)
                else:
                    pct_partielles += 1          # reste des bases QUI VALENT ENCORE
        if not _actif:
            extra["hors_periode"] = True
        ll = dict(l)
        ll.update(extra)
        ll["usd"] = usd
        mk = l.get("market") if l.get("market") in MARKETS else MARKET_DEFAULT
        ll["market"] = mk
        # payé = flag direct, ou toutes les phases payées
        phases = l.get("phases") or []
        if phases:
            ll["paid"] = all(p.get("paid") for p in phases)
        out_lines.append(ll)
        if l.get("type") == "rev":
            tot_rev += usd
            by_market[mk]["rev"] += usd
            by_market[mk]["rev_count"] += 1
        else:
            tot_exp += usd
            by_market[mk]["exp"] += usd
            by_market[mk]["exp_count"] += 1
            if ll.get("paid_by") == "lead":
                by_market[mk]["reimb"] += usd
            elif str(ll.get("paid_by") or "").startswith("assoc:"):
                # avancée par un associé : l'agence lui doit ce montant
                _an = str(ll["paid_by"])[6:]
                _ra = by_market[mk]["reimb_assoc"]
                _ra[_an] = _ra.get(_an, 0.0) + usd

    # Associés en 2 étages : d'abord les % PAR MARCHÉ (un associé « US » ne
    # touche que le net positif du marché US), puis les % GLOBAUX sur ce qui
    # reste. Sans associé de marché, le calcul est identique à l'ancien.
    assoc_global = sum(float(a.get("pct") or 0) for a in settings["associates"]
                       if a.get("market") not in MARKETS)
    assoc_by_mk = {mk: sum(float(a.get("pct") or 0) for a in settings["associates"]
                           if a.get("market") == mk) for mk in MARKETS}
    assoc_pct = round(assoc_global + sum(assoc_by_mk.values()), 2)
    net = round(tot_rev - tot_exp, 2)
    stage = {}
    for mk, bm in by_market.items():
        bm["rev"] = round(bm["rev"], 2)
        bm["exp"] = round(bm["exp"], 2)
        bm["net"] = round(bm["rev"] - bm["exp"], 2)
        bm["assoc_pct"] = round(assoc_global + assoc_by_mk[mk], 2)
        # marché en perte : la perte reste entière au lead (comme avant)
        stage[mk] = (bm["net"] * max(0.0, 100.0 - assoc_by_mk[mk]) / 100.0
                     if bm["net"] > 0 else bm["net"])
    base = sum(stage.values())
    kg = max(0.0, 100.0 - assoc_global) / 100.0
    lead = round(base * kg, 2) if base > 0 else round(base, 2)
    # Répartition par marché au PRORATA de la base (linéaire -> la somme des
    # parts par marché redonne toujours la part globale, même en perte).
    reimb_total = 0.0
    reimb_assoc_total = {}
    for mk, bm in by_market.items():
        if base:
            bm["lead"] = round(lead * stage[mk] / base, 2)
        else:
            bm["lead"] = 0.0
        bm["reimb"] = round(bm["reimb"], 2)
        bm["reimb_assoc"] = {k: round(v, 2) for k, v in bm["reimb_assoc"].items()}
        for _k, _v in bm["reimb_assoc"].items():
            reimb_assoc_total[_k] = round(reimb_assoc_total.get(_k, 0.0) + _v, 2)
        # ce que le lead ENCAISSE sur ce marché : sa part + ses avances remboursées
        bm["lead_pay"] = round(bm["lead"] + bm["reimb"], 2)
        reimb_total += bm["reimb"]

    # Cartes « Part <associé> » : part du split + ses avances à lui rembourser.
    # Garde-fous (revue adversariale) :
    # - cumul de % > 100 (config legacy, la route le refuse désormais) : parts
    #   ramenées au prorata -> lead + associés ne dépassent JAMAIS le net ;
    # - homonymes (même nom sur 2 marchés) : l'avance n'est comptée qu'UNE fois ;
    # - ventilation par marché d'un « tous » compensée au centime (le dernier
    #   marché absorbe l'arrondi : la somme des marchés = la carte globale).
    _sc_g = 100.0 / assoc_global if assoc_global > 100 else 1.0
    _sc_mk = {mk: (100.0 / v if v > 100 else 1.0) for mk, v in assoc_by_mk.items()}
    _mks = [mk for mk in MARKET_ORDER if mk in by_market] or list(by_market)

    def _parts_for(a):
        """({marché: part}, part_globale) — arrondis cohérents entre eux."""
        pct = float(a.get("pct") or 0)
        amk = a.get("market") if a.get("market") in MARKETS else "tous"
        if amk != "tous":
            p = round(max(0.0, by_market[amk]["net"]) * pct * _sc_mk[amk] / 100.0, 2)
            return {mk: (p if mk == amk else 0.0) for mk in _mks}, p
        raw = max(0.0, base) * pct * _sc_g / 100.0
        total = round(raw, 2)
        if base <= 0:
            return {mk: 0.0 for mk in _mks}, total
        parts = {mk: round(raw * stage[mk] / base, 2) for mk in _mks[:-1]}
        parts[_mks[-1]] = round(total - sum(parts.values()), 2)
        return parts, total

    _acards = []
    _seen_nm = set()
    for a in settings["associates"]:
        nm = (a.get("name") or "").strip()
        if not nm:
            continue
        parts, total = _parts_for(a)
        _acards.append((nm, a, parts, total, nm not in _seen_nm))
        _seen_nm.add(nm)

    def _assoc_cards(scope_mk=None):
        cards = []
        for nm, a, parts, total, first in _acards:
            part = parts.get(scope_mk, 0.0) if scope_mk else total
            _ra = by_market[scope_mk]["reimb_assoc"] if scope_mk else reimb_assoc_total
            reimb = round(float(_ra.get(nm) or 0.0), 2) if first else 0.0
            cards.append({"name": nm, "pct": float(a.get("pct") or 0),
                          "market": a.get("market") if a.get("market") in MARKETS else "tous",
                          "part": part, "reimb": reimb,
                          "pay": round(part + reimb, 2)})
        return cards

    for mk, bm in by_market.items():
        bm["assoc_parts"] = _assoc_cards(mk)

    return {
        "ok": True,
        "month": month,
        "months": months,
        "cur_month": cur,
        "settings": settings,
        "lines": out_lines,
        "totals": {
            "rev": round(tot_rev, 2),
            "exp": round(tot_exp, 2),
            "net": net,
            "lead": lead,
            "reimb": round(reimb_total, 2),
            "reimb_assoc": reimb_assoc_total,
            "assoc_parts": _assoc_cards(),
            "lead_pay": round(lead + reimb_total, 2),
            "assoc_pct": round(assoc_pct, 2),
            "assoc_global": round(assoc_global, 2),
            "assoc_by_mk": {mk: round(v, 2) for mk, v in assoc_by_mk.items()},
            "rev_count": sum(1 for l in lines if l.get("type") == "rev"),
            "exp_count": sum(1 for l in lines if l.get("type") != "rev"),
            # Comptés et remontés (bandeau en haut de page) : lignes en %
            # rendues à 0 $ par leur base, la part d'entre elles dont la base
            # est seulement arrivée à sa date de fin, celle dont la base a
            # vraiment été supprimée (le reste = une base absente de ce mois,
            # ni supprimée ni terminée -> le bandeau ne doit affirmer ni l'un
            # ni l'autre), et celles dont il ne manque qu'une base sur
            # plusieurs AVEC un reste qui vaut encore quelque chose.
            "pct_orphans": pct_orphelines,
            "pct_orphans_expirees": pct_orph_expirees,
            "pct_orphans_supprimees": pct_orph_supprimees,
            "pct_partielles": pct_partielles,
        },
        "cats": CATS,
        "cat_order": CAT_ORDER,
        "pct_bases": PCT_BASES,
        "markets": MARKETS,
        "market_order": MARKET_ORDER,
        "by_market": by_market,
        # Lignes de revenus (fixe OU CA MyPuls auto) -> pour lier un % à un revenu précis
        "rev_lines": [
            {"id": l["id"], "label": l.get("label") or "revenu",
             "cat": l.get("cat"), "usd": rev_bases.get(f"line:{l['id']}", 0.0)}
            for l in lines
            if l.get("type") == "rev" and (l.get("form") or "fixed") in ("fixed", "mypuls") and l.get("id")
        ],
    }


def _clean_paid_by(raw: dict) -> str:
    """'agence' (défaut), 'lead', ou 'assoc:Nom' — jamais autre chose."""
    pb = str(raw.get("paid_by") or "agence").strip()[:60]
    if raw.get("type") == "rev":
        return "agence"
    if pb == "lead":
        return "lead"
    if pb.startswith("assoc:") and pb[6:].strip():
        return "assoc:" + pb[6:].strip()[:40]
    return "agence"


def _sanitize_line(raw: dict) -> dict:
    """Nettoie/valide une ligne reçue du client."""
    def s(k, mx=200):
        return str(raw.get(k) or "").strip()[:mx]
    line = {
        "id": s("id", 24) or uuid.uuid4().hex[:12],
        "label": s("label", 120) or "Sans nom",
        "type": "rev" if raw.get("type") == "rev" else "exp",
        "cat": raw.get("cat") if raw.get("cat") in CATS else "other",
        "form": raw.get("form") if raw.get("form") in ("fixed", "pct", "mypuls", "mypuls_crm", "va_clicks") else "fixed",
        "mypuls_model": s("mypuls_model", 80),
        # ID API épinglé : une fois renseigné, plus aucun appariement par nom
        "mypuls_creator_id": (int(raw["mypuls_creator_id"])
                              if str(raw.get("mypuls_creator_id") or "").isdigit() else 0),
        "market": raw.get("market") if raw.get("market") in MARKETS else MARKET_DEFAULT,
        "currency": "EUR" if (raw.get("currency") or "").upper() == "EUR" else "USD",
        "freq": raw.get("freq") if raw.get("freq") in ("monthly", "biweekly", "weekly", "once") else "monthly",
        "start": s("start", 10),
        "end": s("end", 10),
        "link": s("link", 300),
        "notes": s("notes", 500),
        "next_pay": s("next_pay", 10),
        "paid": bool(raw.get("paid")),
        "paid_at": s("paid_at", 10),
        # dépense AVANCÉE en perso : 'lead' (ajoutée à sa part dans les KPI) ou
        # 'assoc:Nom' (l'agence doit rembourser cet associé). Revenu -> 'agence'.
        "paid_by": _clean_paid_by(raw),
    }
    try:
        line["amount"] = round(float(raw.get("amount") or 0), 2)
    except Exception:
        line["amount"] = 0.0
    try:
        line["pct"] = round(float(raw.get("pct") or 0), 2)
    except Exception:
        line["pct"] = 0.0
    # Frais de plateforme (%) retenus SUR un revenu : le montant saisi/récupéré est
    # BRUT, on affiche et on compte le NET. Ex : OnlyFans prend 20 %.
    try:
        line["fee_pct"] = min(100.0, max(0.0, round(float(raw.get("fee_pct") or 0), 2)))
    except Exception:
        line["fee_pct"] = 0.0
    pct_of = str(raw.get("pct_of") or "")[:1500]
    # base valide : catégorie connue, UNE ligne "line:<id>" ou PLUSIEURS "lines:<id>,<id>,..."
    line["pct_of"] = pct_of if (
        pct_of in PCT_BASES
        or re.match(r"^line:[a-zA-Z0-9]{4,32}$", pct_of)
        or re.match(r"^lines:[a-zA-Z0-9]{4,32}(,[a-zA-Z0-9]{4,32}){0,39}$", pct_of)
    ) else "rev_total"
    if line["form"] == "mypuls":
        line["type"] = "rev"  # un CA MyPuls est forcément un revenu
    elif line["form"] in ("mypuls_crm", "va_clicks"):
        line["type"] = "exp"  # factures CRM et paie VA = forcément des dépenses
    phases = []
    for p in (raw.get("phases") or [])[:8]:
        if isinstance(p, dict) and p.get("date"):
            phases.append({"date": str(p["date"])[:10],
                           "paid": bool(p.get("paid")),
                           "paid_at": str(p.get("paid_at") or "")[:10]})
    line["phases"] = phases
    return line


def compute_bilan() -> dict:
    """Bilan multi-mois : totaux de chaque mois AYANT des lignes (revenus,
    dépenses, net, part lead + split marché FR/US) + cumul global.
    Alimente la page Finances > Bilan (rendu serveur dans web_upload)."""
    d = _load()
    months = sorted(m for m, v in d["months"].items() if (v or {}).get("lines"))
    rows = []
    tot = {"rev": 0.0, "exp": 0.0, "net": 0.0, "lead": 0.0,
           "fr_rev": 0.0, "us_rev": 0.0, "fr_net": 0.0, "us_net": 0.0}
    for m in months:
        st = compute_state(m)
        t, bm = st["totals"], st["by_market"]
        _lp = t.get("lead_pay", t["lead"])   # part lead + avances a rembourser
        rows.append({"month": m, "rev": t["rev"], "exp": t["exp"], "net": t["net"],
                     "lead": _lp, "fr": bm["fr"], "us": bm["us"]})
        tot["rev"] += t["rev"]; tot["exp"] += t["exp"]
        tot["net"] += t["net"]; tot["lead"] += _lp
        tot["fr_rev"] += bm["fr"]["rev"]; tot["us_rev"] += bm["us"]["rev"]
        tot["fr_net"] += bm["fr"]["net"]; tot["us_net"] += bm["us"]["net"]
    for k in tot:
        tot[k] = round(tot[k], 2)
    return {"rows": rows, "totals": tot, "cur_month": _cur_month()}


def _seed_pay35_20260709():
    """One-shot (demande user du 09/07/2026) : créer à sa place les payes 35%
    liées au CA MyPuls de Lola, Emma et Alicia. Idempotent : saute si une paye %
    liée à la ligne existe déjà ; flag posé quand les 3 modèles sont traités."""
    try:
        d = _load()
        if d["settings"].get("seed_pay35_20260709"):
            return
        month = _cur_month()
        m = d["months"].setdefault(month, {"lines": []})
        lines = m.setdefault("lines", [])
        processed = 0
        changed = False
        for want in ("lola", "emma", "alicia"):
            rev = next((l for l in lines
                        if l.get("type") == "rev" and (l.get("form") or "") == "mypuls"
                        and (want in (l.get("mypuls_model") or "").lower()
                             or want in (l.get("label") or "").lower())), None)
            if not rev or not rev.get("id"):
                continue  # ligne CA pas (encore) là -> on retentera au prochain démarrage
            processed += 1
            ref = f"line:{rev['id']}"
            if any(l.get("form") == "pct" and l.get("pct_of") == ref for l in lines):
                continue  # une paye liée à ce CA existe déjà
            lines.append({
                "id": uuid.uuid4().hex[:12],
                "label": f"Paye {(rev.get('label') or want).strip()} (35%)",
                "type": "exp", "cat": "model", "form": "pct",
                "market": rev.get("market") if rev.get("market") in MARKETS else MARKET_DEFAULT,
                "currency": "USD", "freq": "monthly",
                "start": "", "end": "", "link": "",
                "notes": "créée automatiquement : 35% du CA MyPuls",
                "next_pay": "", "paid": False, "paid_at": "",
                "amount": 0.0, "pct": 35.0, "pct_of": ref,
                "mypuls_model": "", "phases": [],
            })
            changed = True
        if processed == 3:
            d["settings"]["seed_pay35_20260709"] = True
            changed = True
        if changed:
            _save(d)
    except Exception:
        pass


def _seed_rev_compte2_20260709():
    """One-shot (demande user du 09/07/2026) : revenus d'un COMPTE SÉPARÉ
    (différent de MyM/MyPuls) pour Amelia/Julia/Lola + paye % liée à chacun.
    Amelia 1629.82$ (paye 30%), Julia 164.48$ (paye 40%), Lola 2286.12$ (paye 35%)."""
    try:
        d = _load()
        if d["settings"].get("seed_revcpt2_20260709"):
            return
        month = _cur_month()
        m = d["months"].setdefault(month, {"lines": []})
        lines = m.setdefault("lines", [])
        base = {"currency": "USD", "freq": "monthly", "start": "", "end": "", "link": "",
                "next_pay": "", "paid": False, "paid_at": "", "mypuls_model": "", "phases": [],
                "market": "fr"}
        for name, amount, pct in (("Amelia", 1629.82, 30.0), ("Julia", 164.48, 40.0), ("Lola", 2286.12, 35.0)):
            rid = uuid.uuid4().hex[:12]
            lines.append(dict(base, id=rid, label=f"{name} (compte 2)", type="rev",
                              cat="rev_other", form="fixed", amount=amount, pct=0.0,
                              pct_of="rev_total", notes="compte séparé (pas MyM)"))
            lines.append(dict(base, id=uuid.uuid4().hex[:12], label=f"Paye {name} compte 2 ({pct:.0f}%)",
                              type="exp", cat="model", form="pct", amount=0.0, pct=pct,
                              pct_of=f"line:{rid}", notes=f"créée automatiquement : {pct:.0f}% du compte 2"))
        d["settings"]["seed_revcpt2_20260709"] = True
        _save(d)
    except Exception:
        pass


def _seed_of_chatters_20260709():
    """One-shot (demande user du 09/07/2026) : les 3 lignes 'compte 2'
    (Amelia/Julia/Lola) SONT le Revenue OF -> cat rev_of + label 'OF …'.
    Et toutes les payes CHATTEUR en % deviennent liées à la SOMME des 3."""
    try:
        d = _load()
        if d["settings"].get("seed_ofchat_20260709"):
            return
        month = _cur_month()
        lines = (d["months"].get(month) or {}).get("lines") or []
        c2 = [l for l in lines if l.get("type") == "rev" and "(compte 2)" in (l.get("label") or "")]
        if len(c2) < 3:
            return  # les lignes compte 2 pas encore là -> retente au prochain démarrage
        for l in c2:
            l["cat"] = "rev_of"
            base = (l.get("label") or "").replace(" (compte 2)", "").strip()
            if not base.upper().startswith("OF"):
                l["label"] = f"OF {base} (compte 2)"
        ids = ",".join(l["id"] for l in c2 if l.get("id"))
        for l in lines:
            if l.get("type") != "rev" and l.get("cat") == "chatter" and (l.get("form") or "") == "pct":
                l["pct_of"] = f"lines:{ids}"
        d["settings"]["seed_ofchat_20260709"] = True
        _save(d)
    except Exception:
        pass


def _seed_chatters_mym_20260709():
    """One-shot CORRECTIF (09/07/2026) : les chatteurs bossent sur MyM, pas OF.
    Leurs payes % doivent être liées à la SOMME des lignes CA MyPuls (toutes
    les modèles SAUF Amelia, gérée par une agence de chatting externe).
    Remplace le lien posé par _seed_of_chatters (qui pointait sur les OF)."""
    try:
        d = _load()
        if d["settings"].get("seed_chatmym_20260709"):
            return
        month = _cur_month()
        lines = (d["months"].get(month) or {}).get("lines") or []
        mym = [l for l in lines
               if l.get("type") == "rev" and (l.get("form") or "") == "mypuls"
               and "amelia" not in (l.get("label") or "").lower()
               and "amelia" not in (l.get("mypuls_model") or "").lower()
               and l.get("id")]
        if not mym:
            return  # lignes CA MyPuls pas encore là -> retente au prochain démarrage
        ids = ",".join(l["id"] for l in mym)
        for l in lines:
            if l.get("type") != "rev" and l.get("cat") == "chatter" and (l.get("form") or "") == "pct":
                l["pct_of"] = f"lines:{ids}"
        d["settings"]["seed_chatmym_20260709"] = True
        _save(d)
    except Exception:
        pass


def _seed_frais_crm_20260709():
    """One-shot (demande user du 09/07/2026) : ligne dépense auto « Frais CRM
    MyPuls » = total des factures du CRM MyPuls du mois (onglet Factures &
    Paiements), EUR->USD. Catégorie Autres."""
    try:
        d = _load()
        if d["settings"].get("seed_fraiscrm_20260709"):
            return
        month = _cur_month()
        m = d["months"].setdefault(month, {"lines": []})
        lines = m.setdefault("lines", [])
        if not any((l.get("form") or "") == "mypuls_crm" for l in lines):
            lines.append({
                "id": uuid.uuid4().hex[:12],
                "label": "Frais CRM MyPuls", "type": "exp", "cat": "other",
                "form": "mypuls_crm", "market": "fr",
                "currency": "USD", "freq": "monthly",
                "start": "", "end": "", "link": "",
                "notes": "auto : total des factures CRM MyPuls du mois (EUR→USD)",
                "next_pay": "", "paid": False, "paid_at": "",
                "amount": 0.0, "pct": 0.0, "pct_of": "rev_total",
                "mypuls_model": "", "phases": [],
            })
        d["settings"]["seed_fraiscrm_20260709"] = True
        _save(d)
    except Exception:
        pass


def _seed_va_classique_20260709():
    """One-shot (demande user du 09/07/2026) : ligne dépense auto « VA classique »
    = clics éligibles du mois de tous les VAs Discord x 0.07$ (taux expert plat)."""
    try:
        d = _load()
        if d["settings"].get("seed_vaclassique_20260709"):
            return
        month = _cur_month()
        m = d["months"].setdefault(month, {"lines": []})
        lines = m.setdefault("lines", [])
        if not any((l.get("form") or "") == "va_clicks" for l in lines):
            lines.append({
                "id": uuid.uuid4().hex[:12],
                "label": "VA classique", "type": "exp", "cat": "va",
                "form": "va_clicks", "market": "fr",
                "currency": "USD", "freq": "monthly",
                "start": "", "end": "", "link": "",
                "notes": "auto : clics éligibles du mois × 0.07$ (taux expert, large)",
                "next_pay": "", "paid": False, "paid_at": "",
                "amount": 0.0, "pct": 0.0, "pct_of": "rev_total",
                "mypuls_model": "", "phases": [],
            })
        d["settings"]["seed_vaclassique_20260709"] = True
        _save(d)
    except Exception:
        pass


# ---------- page (shell : tout le rendu est fait par facture_app.js) ----------
def render_page() -> str:
    return (
        "<div id='facture-root' style='max-width:1500px;margin:0 auto;width:100%'>"
        "<div style='display:flex;align-items:center;gap:10px;color:#888;font-size:13px;padding:30px 0'>"
        "<div style='width:20px;height:20px;border:3px solid rgba(59,130,246,.15);border-top-color:#3b82f6;"
        "border-radius:50%;animation:plSpin .8s linear infinite'></div> Chargement de la facture…</div>"
        "</div>"
        "<script src='/facture/app.js' defer></script>"
    )


def _seed_of_amelia_mrn():
    """One-shot (demande user du 19/07/2026) : nouvelle modèle OF « amelia.mrn »
    ajoutée dans MyPuls -> ligne de revenu AUTO (CA MyPuls du mois) + sa paye 30 %
    liée à cette ligne. Idempotent : ne crée rien si les lignes existent déjà."""
    try:
        d = _load()
        if d["settings"].get("seed_amelia_mrn_20260719"):
            return
        month = _cur_month()
        m = d["months"].setdefault(month, {"lines": []})
        lines = m.setdefault("lines", [])
        model = "amelia.mrn"
        # déjà présente ? (par mypuls_model ou par label)
        rev = next((l for l in lines
                    if l.get("type") == "rev"
                    and (model in (l.get("mypuls_model") or "").lower()
                         or model in (l.get("label") or "").lower())), None)
        base = {"currency": "USD", "freq": "monthly", "start": "", "end": "", "link": "",
                "next_pay": "", "paid": False, "paid_at": "", "mypuls_model": "",
                "phases": [], "market": MARKET_DEFAULT}
        if rev is None:
            rid = uuid.uuid4().hex[:12]
            rev = dict(base, id=rid, label=f"OF {model} (auto)", type="rev",
                       cat="rev_of", form="mypuls", amount=0.0, pct=0.0,
                       pct_of="rev_total", mypuls_model=model,
                       notes="CA MyPuls du mois, tiré automatiquement")
            lines.append(rev)
        ref = f"line:{rev['id']}"
        # paye 30 % liée à CETTE ligne (si pas déjà là)
        if not any(l.get("form") == "pct" and l.get("pct_of") == ref for l in lines):
            lines.append(dict(base, id=uuid.uuid4().hex[:12],
                              label=f"Paye {model} (30%)", type="exp", cat="model",
                              form="pct", amount=0.0, pct=30.0, pct_of=ref,
                              notes="créée automatiquement : 30% du CA OF"))
        d["settings"]["seed_amelia_mrn_20260719"] = True
        _save(d)
    except Exception:
        pass


def _seed_of_fee_amelia_mypuls():
    """One-shot (19/07/2026) : la ligne OF d'Amelia tirée de MyPuls est du BRUT.
    OnlyFans retient 20 % -> on pose fee_pct=20 pour que la facture compte le NET."""
    try:
        d = _load()
        if d["settings"].get("seed_of_fee_amelia_20260719"):
            return
        changed = False
        for m in d.get("months", {}).values():
            for l in m.get("lines", []):
                if (l.get("type") == "rev" and l.get("form") == "mypuls"
                        and "amelia" in (l.get("mypuls_model") or "").lower()
                        and not float(l.get("fee_pct") or 0)):
                    l["fee_pct"] = 20.0
                    if "frais OnlyFans" not in (l.get("notes") or ""):
                        l["notes"] = ((l.get("notes") or "") + " · net (frais OnlyFans 20% déduits)").strip(" ·")
                    changed = True
        d["settings"]["seed_of_fee_amelia_20260719"] = True
        if changed or True:
            _save(d)
    except Exception:
        pass


# ---------- routes ----------
def register(app, is_auth):
    from flask import request, jsonify, send_file

    # ---- Graines « one-shot » du 09/07/2026 ----------------------------------
    # Elles se ré-exécutaient à CHAQUE démarrage tant que leur drapeau n'était
    # pas posé : une ligne supprimée volontairement (paye 35 %, ligne de CA…)
    # revenait d'entre les morts au redémarrage suivant, et les liens % des
    # chatteurs pouvaient être réécrits par-dessus un choix manuel.
    # Elles ne servent plus qu'à une base VIERGE : on ne les lance donc que si
    # le mois courant n'a aucune ligne, et on les retire définitivement ensuite.
    try:
        _d_seed = _load()
        if not _d_seed["settings"].get("seeds_20260709_retired"):
            _m_seed = (_d_seed["months"].get(_cur_month()) or {}).get("lines") or []
            if not _m_seed:
                _seed_pay35_20260709()
                _seed_rev_compte2_20260709()
                _seed_of_chatters_20260709()
                _seed_chatters_mym_20260709()
                _seed_va_classique_20260709()
                _seed_frais_crm_20260709()
                _seed_of_amelia_mrn()
                _seed_of_fee_amelia_mypuls()
                print("[facture] graines initiales appliquées (facture vierge)", flush=True)
            else:
                print("[facture] graines one-shot retirées (facture déjà remplie)", flush=True)
            _d2_seed = _load()
            _d2_seed["settings"]["seeds_20260709_retired"] = True
            _save(_d2_seed)
    except Exception as _e_seed:
        print(f"[facture] graines : {_e_seed}", flush=True)

    @app.route("/facture/app.js")
    def facture_app_js():
        if not is_auth():
            return "", 401
        p = BOT_DIR / "facture_app.js"
        if not p.exists():
            return "// facture_app.js manquant", 404
        return send_file(str(p), mimetype="text/javascript", conditional=True)

    @app.route("/facture/state")
    def facture_state():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        month = (request.args.get("month") or _cur_month())[:7]
        if not re.match(r"^\d{4}-\d{2}$", month):
            month = _cur_month()
        try:
            # Le mois en cours se remplit tout seul des charges récurrentes du
            # mois précédent : sans ça, un 1er du mois affichait une page vide
            # alors que les lignes « tous les mois » étaient déjà saisies.
            _autofill_months()
        except Exception:
            pass          # la compta doit s'afficher même si le report échoue
        try:
            return jsonify(compute_state(month))
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    @app.route("/facture/mypuls_models")
    def facture_mypuls_models():
        """Liste des créatrices MyPuls (pour le select 'CA MyPuls auto').

        L'API est PRIORITAIRE : elle seule fournit l'ID, qu'on épingle ensuite sur
        la ligne pour ne plus jamais avoir à retrouver la créatrice par son nom
        (c'était la cause du montant faux de Jessye/Khloe). Le scraping complète
        la liste : les deux canaux n'ont pas forcément le même périmètre, et une
        créatrice visible uniquement au scraping ne doit pas disparaître.
        """
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        force = bool(request.args.get("refresh"))
        out, errs = [], []
        seen = set()
        try:
            import mypuls
            if mypuls.api_configured():
                for c in mypuls.api_creators_cached(force=force):
                    nm = (c.get("pseudo") or "").strip() or f"#{c.get('id')}"
                    out.append({"name": nm, "id": c.get("id"),
                                "platform": c.get("platform") or "",
                                "currency": c.get("currency") or "", "src": "api"})
                    seen.add(_squash(nm))
        except Exception as e:
            errs.append(f"API : {e}")
        try:
            import mypuls
            res = mypuls.list_creators(force_refresh=force)
            if res.get("ok") or res.get("creators"):
                for nm, cid in (res.get("creators") or {}).items():
                    if _squash(nm) in seen:
                        continue
                    out.append({"name": nm, "id": cid, "platform": "",
                                "currency": "", "src": "scraping"})
                    seen.add(_squash(nm))
            elif res.get("error"):
                errs.append(f"scraping : {res['error']}")
        except Exception as e:
            errs.append(f"scraping : {e}")
        if not out:
            return jsonify({"ok": False,
                            "error": " · ".join(errs) or "MyPuls indisponible"})
        out.sort(key=lambda c: (c["name"] or "").lower())
        return jsonify({"ok": True,
                        "models": [c["name"] for c in out],   # rétro-compat
                        "creators": out,
                        "warn": " · ".join(errs) or ""})

    @app.route("/facture/mypuls_debug")
    def facture_mypuls_debug():
        """Diagnostic : d'où vient réellement le montant d'une ligne « CA MyPuls »."""
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        model = request.args.get("model") or ""
        month = request.args.get("month") or _cur_month()
        out = {"ok": True, "model": model, "month": month, "cle_normalisee": _norm_model(model)}
        try:
            import mypuls
            out["token_api"] = mypuls.api_configured()
            out["createurs_api"] = [
                {"id": c.get("id"), "pseudo": c.get("pseudo"),
                 "cle": _norm_model(c.get("pseudo")), "devise": c.get("currency")}
                for c in (mypuls.api_creators_parsed() if mypuls.api_configured() else [])
            ]
        except Exception as e:
            out["erreur_api"] = f"{type(e).__name__}: {e}"
        amt, cur, net, info = _mypuls_month_amount(model, month,
                                                   request.args.get("creator_id"))
        out["resultat"] = {"montant": amt, "devise": cur, "deja_net": net,
                           "source": ("dernier relevé MyPuls (API indispo)" if info.get("stale")
                                      else ("API MyPuls" if net else "scraping (repli)")),
                           "stale": bool(info.get("stale")),
                           "creator_id": info.get("creator_id"),
                           "resolution": info.get("resolution")}
        out["repli_cause"] = info.get("why") or None
        return jsonify(out)

    @app.route("/facture/line/save", methods=["POST"])
    def facture_line_save():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        month = (request.form.get("month") or _cur_month())[:7]
        try:
            raw = json.loads(request.form.get("line") or "{}")
        except Exception as e:
            return jsonify({"ok": False, "error": f"JSON invalide: {e}"})
        line = _sanitize_line(raw)
        d = _load()
        m = d["months"].setdefault(month, {"lines": []})
        lines = m.setdefault("lines", [])
        for i, l in enumerate(lines):
            if l.get("id") == line["id"]:
                # préserve l'état de paiement si non fourni explicitement
                if "paid" not in raw:
                    line["paid"] = l.get("paid", False)
                    line["paid_at"] = l.get("paid_at", "")
                lines[i] = line
                break
        else:
            lines.append(line)
        _save(d)
        return jsonify({"ok": True, "id": line["id"]})

    @app.route("/facture/line/delete", methods=["POST"])
    def facture_line_delete():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        month = (request.form.get("month") or _cur_month())[:7]
        lid = (request.form.get("id") or "").strip()
        d = _load()
        m = d["months"].get(month) or {}
        lines = m.get("lines") or []
        # Une ligne de revenu peut servir de BASE à des payes en % (« 35 % de
        # OF Lola »). La supprimer sans rien dire mettait ces payes à $0 et
        # gonflait la part lead d'autant. On prévient, et on répare les liens.
        # DEUX conséquences distinctes, donc deux listes : une paye qui ne
        # garde AUCUNE base tombe à 0 $ ; une paye qui en garde une vaut encore
        # quelque chose — lui annoncer 0 $ était faux, l'écran et le message se
        # contredisaient.
        # Mais un id restant n'est pas une base restante : une paye reportée de mois
        # en mois garde son pct_of vers des bases qui, elles, n'ont pas été
        # reportées (date de fin passée, ligne ponctuelle...). Classer sur le
        # NOMBRE d'ids promettait « montant simplement recalculé » à une paye
        # qui, au rechargement, tombait à 0 $ avec un badge rouge — et sans la
        # note ⚠ que reçoivent les payes privées de base. On classe donc sur
        # les bases QUI RÉPONDENT ENCORE dans ce mois.
        _vivantes = {l.get("id") for l in lines
                     if l.get("type") == "rev" and l.get("id") and l.get("id") != lid}

        def _reste_vivant(ids):
            return [i for i in ids if i != lid and i in _vivantes]

        sans_base, reduites = [], []
        for l in lines:
            if l.get("form") != "pct" or not lid or l.get("id") == lid:
                continue
            ids = _pct_base_ids(l)
            if lid not in ids:
                continue
            nom = str(l.get("label") or l.get("id") or "?")
            if _reste_vivant(ids):
                reduites.append(nom)
            else:
                sans_base.append(nom)
        if (sans_base or reduites) and (request.form.get("confirm") or "") != "1":
            # Texte écrit ICI : c'est le serveur qui sait laquelle des deux
            # conséquences frappe quelle paye. Le client n'y ajoute que la
            # question finale.
            _nl = chr(10)
            _p = ["Des payes en % utilisent cette ligne comme base :"]
            if sans_base:
                _p.append(f"- {len(sans_base)} paye(s) n'auront plus AUCUNE base et "
                          "tomberont à 0 $ (elles ne sont PAS recalculées sur le total "
                          "des revenus) : " + ", ".join(sans_base[:6])
                          + (" ..." if len(sans_base) > 6 else ""))
            if reduites:
                _p.append(f"- {len(reduites)} paye(s) gardent au moins une AUTRE base "
                          "PRÉSENTE dans ce mois : leur montant sera simplement "
                          "recalculé sans celle-ci : "
                          + ", ".join(reduites[:6])
                          + (" ..." if len(reduites) > 6 else ""))
            return jsonify({"ok": False, "needs_confirm": True,
                            "sans_base": sans_base, "reduites": reduites,
                            "error": _nl.join(_p)})
        def _flag_base_gone(l):
            # NE PAS rebaser sur rev_total : ça paierait ce % sur le CA des AUTRES
            # modèles, en boucle chaque mois. Le base disparue -> _line_usd rend
            # déjà 0 (base introuvable). On flague pour révision manuelle.
            n = l.get("notes") or ""
            if "base supprimée" not in n:
                l["notes"] = (n + " ⚠ base supprimée — à revérifier").strip()
        for l in lines:
            if l.get("form") != "pct" or not lid:
                continue
            ids = _pct_base_ids(l)
            if lid not in ids:
                continue
            if str(l.get("pct_of") or "").startswith("lines:"):
                # on retire l'id supprimé, on GARDE les autres tels quels (même
                # morts : les purger effacerait la trace de ce qui manque).
                l["pct_of"] = "lines:" + ",".join(i for i in ids if i != lid)
            # base unique disparue : on LAISSE pct_of pendant (résout à 0), on
            # ne rebase PAS sur rev_total.
            # La note ⚠ suit la même règle que le message : elle est due dès
            # qu'il ne reste aucune base VIVANTE, pas seulement aucun id.
            if not _reste_vivant(ids):
                _flag_base_gone(l)
        before = len(lines)
        m["lines"] = [l for l in lines if l.get("id") != lid]
        _save(d)
        # `sans_base` : les payes qui n'ont plus aucune base VIVANTE et valent
        # donc 0 $ (rien n'est « rebasculé sur le total », ce serait payer ce %
        # sur le CA des autres modèles) ; elles portent la note ⚠. `reduites` :
        # celles dont il restait une base présente dans ce mois — elles
        # continuent de compter, avec un montant plus petit.
        return jsonify({"ok": True, "deleted": before - len(m["lines"]),
                        "sans_base": sans_base, "reduites": reduites})

    @app.route("/facture/line/pay", methods=["POST"])
    def facture_line_pay():
        """Toggle payé — ligne entière, ou une phase précise (phase_idx)."""
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        month = (request.form.get("month") or _cur_month())[:7]
        lid = (request.form.get("id") or "").strip()
        phase_idx = request.form.get("phase")
        today = datetime.date.today().isoformat()
        d = _load()
        for l in (d["months"].get(month) or {}).get("lines") or []:
            if l.get("id") != lid:
                continue
            if phase_idx is not None and phase_idx != "":
                try:
                    p = (l.get("phases") or [])[int(phase_idx)]
                    p["paid"] = not p.get("paid")
                    p["paid_at"] = today if p["paid"] else ""
                except Exception:
                    return jsonify({"ok": False, "error": "phase introuvable"})
            else:
                l["paid"] = not l.get("paid")
                l["paid_at"] = today if l["paid"] else ""
            _save(d)
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": "ligne introuvable"})

    @app.route("/facture/settings", methods=["POST"])
    def facture_settings():
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        d = _load()
        st = d["settings"]
        try:
            _r = float(request.form.get("eur_usd") or 0)
            # champ vide = auto (taux BCE live) ; une valeur = override explicite
            st["eur_usd"] = max(0.5, min(2.0, _r)) if _r else 0
        except Exception:
            pass
        try:
            st["cutoff"] = max(1, min(28, int(request.form.get("cutoff") or 15)))
        except Exception:
            pass
        # champ absent (vieux client) ou vidé -> on ne touche pas au nom stocké
        _ln = (request.form.get("lead_name") or "").strip()[:40]
        if _ln:
            st["lead_name"] = _ln
        try:
            assoc = json.loads(request.form.get("associates") or "[]")
            clean = []
            for a in assoc[:10]:
                if isinstance(a, dict) and (a.get("name") or "").strip():
                    clean.append({"name": str(a["name"]).strip()[:40],
                                  "pct": max(0.0, min(100.0, float(a.get("pct") or 0))),
                                  # 'tous' = % du net global ; 'fr'/'us' = % du
                                  # net de CE marché seulement
                                  "market": a.get("market") if a.get("market") in MARKETS else "tous"})
            # jamais plus de 100 % au même étage : les cartes distribueraient
            # plus d'argent que le net (le lead, lui, est clampé à 0)
            _gs = sum(a["pct"] for a in clean if a["market"] == "tous")
            _ms = {mk: sum(a["pct"] for a in clean if a["market"] == mk) for mk in MARKETS}
            if _gs > 100 or any(v > 100 for v in _ms.values()):
                return jsonify({"ok": False, "error": "Le total des % associés dépasse 100 (en global ou sur un même marché)"})
            st["associates"] = clean
        except Exception:
            pass
        _save(d)
        return jsonify({"ok": True})

    @app.route("/facture/next_month", methods=["POST"])
    def facture_next_month():
        """Démarre le mois suivant : reporte les lignes récurrentes, paiements à zéro."""
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        month = (request.form.get("month") or _cur_month())[:7]
        y, m = int(month[:4]), int(month[5:7])
        nm = f"{y + (1 if m == 12 else 0):04d}-{(1 if m == 12 else m + 1):02d}"
        d = _load()
        if nm in d["months"] and (d["months"][nm].get("lines") or []):
            return jsonify({"ok": False, "error": f"Le mois {nm} existe déjà"})
        # Même report que l'automatique (une seule implémentation)
        new_lines, finies = _carry_lines((d["months"].get(month) or {}).get("lines") or [], nm)
        d["months"][nm] = {"lines": new_lines}
        _save(d)
        # `expirees` remonte à l'écran : une charge terminée qui cesse d'être
        # reportée doit se voir, pas se deviner.
        return jsonify({"ok": True, "month": nm, "count": len(new_lines),
                        "expirees": [f"{f['label']} (fin {f['end']})" for f in finies]})
