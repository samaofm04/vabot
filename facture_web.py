"""facture_web.py — Module Facture : compta mensuelle OFM (revenus / dépenses).

Façon expert-comptable adapté agence OFM :
- mois par mois (data/facture.json), bouton "Démarrer mois suivant" qui reporte
  les lignes récurrentes (freq != once) avec paiements remis à zéro
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
    try:
        d = json.loads(FACTURE_FILE.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            d.setdefault("settings", {})
            d.setdefault("months", {})
            return d
    except Exception:
        pass
    return {"settings": {}, "months": {}}


def _save(d: dict):
    with _LOCK:
        FACTURE_FILE.parent.mkdir(parents=True, exist_ok=True)
        FACTURE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _cur_month() -> str:
    return datetime.date.today().strftime("%Y-%m")


def _month_shift(month: str, delta: int) -> str:
    idx = int(month[:4]) * 12 + int(month[5:7]) - 1 + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def _month_bounds(month: str):
    y, m = int(month[:4]), int(month[5:7])
    last = calendar.monthrange(y, m)[1]
    return datetime.date(y, m, 1), datetime.date(y, m, last)


def _to_usd(amount: float, currency: str, settings: dict) -> float:
    rate = float(settings.get("eur_usd") or 1.08)
    if (currency or "USD").upper() == "EUR":
        return amount * rate
    return amount


_MYPULS_CACHE_FILE = DATA_DIR / "facture_mypuls_cache.json"
_MYPULS_MONTH_CACHE: dict = {}


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
                _MYPULS_CACHE_FILE.write_text(json.dumps(_MYPULS_MONTH_CACHE), encoding="utf-8")
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
        _MYPULS_CACHE_FILE.write_text(json.dumps(_MYPULS_MONTH_CACHE), encoding="utf-8")
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
    """Clics éligibles cumulés des VAs Discord (non-jailbreak) sur le mois.
    Mois clos figé en cache disque ; mois courant re-calculé toutes les 10 min
    (les jours passés sortent du day-cache paie -> rapide)."""
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
        import web_upload
        first, last = _month_bounds(month)
        if first > datetime.date.today():
            return 0
        clicks = int(web_upload.compute_va_eligible_clicks(first.isoformat(), last.isoformat()))
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


def compute_state(month: str) -> dict:
    """État complet du mois : settings + lignes (montants USD résolus) + totaux."""
    d = _load()
    settings = {
        "eur_usd": float(d["settings"].get("eur_usd") or 1.08),
        "cutoff": int(d["settings"].get("cutoff") or 15),
        "associates": d["settings"].get("associates") or [],
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
    for l in lines:
        if l.get("type") != "rev":
            continue
        form = l.get("form") or "fixed"
        if form == "fixed":
            usd = _to_usd(float(l.get("amount") or 0), l.get("currency") or "USD", settings)
        elif form == "mypuls":
            usd = round(_to_usd(_mypuls_ca(l.get("mypuls_model") or "", month), "EUR", settings), 2)
        else:
            continue  # % d'un autre revenu -> résolu ensuite via rev_bases
        if l.get("id"):
            resolved_rev[l["id"]] = usd
            rev_bases[f"line:{l['id']}"] = usd
        rev_bases["rev_total"] += usd
        if l.get("cat") in ("rev_of", "rev_mym"):
            rev_bases[l["cat"]] += usd

    out_lines = []
    tot_rev = tot_exp = 0.0
    by_market = {mk: {"rev": 0.0, "exp": 0.0, "rev_count": 0, "exp_count": 0} for mk in MARKETS}
    for l in lines:
        extra = {}
        if l.get("id") in resolved_rev:
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

    assoc_pct = sum(float(a.get("pct") or 0) for a in settings["associates"])
    net = round(tot_rev - tot_exp, 2)
    lead = round(net * max(0.0, (100.0 - assoc_pct)) / 100.0, 2) if net > 0 else net
    for bm in by_market.values():
        bm["rev"] = round(bm["rev"], 2)
        bm["exp"] = round(bm["exp"], 2)
        n = round(bm["rev"] - bm["exp"], 2)
        bm["net"] = n
        bm["lead"] = round(n * max(0.0, (100.0 - assoc_pct)) / 100.0, 2) if n > 0 else n

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
            "assoc_pct": round(assoc_pct, 2),
            "rev_count": sum(1 for l in lines if l.get("type") == "rev"),
            "exp_count": sum(1 for l in lines if l.get("type") != "rev"),
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
    }
    try:
        line["amount"] = round(float(raw.get("amount") or 0), 2)
    except Exception:
        line["amount"] = 0.0
    try:
        line["pct"] = round(float(raw.get("pct") or 0), 2)
    except Exception:
        line["pct"] = 0.0
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
        rows.append({"month": m, "rev": t["rev"], "exp": t["exp"], "net": t["net"],
                     "lead": t["lead"], "fr": bm["fr"], "us": bm["us"]})
        tot["rev"] += t["rev"]; tot["exp"] += t["exp"]
        tot["net"] += t["net"]; tot["lead"] += t["lead"]
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


# ---------- routes ----------
def register(app, is_auth):
    from flask import request, jsonify, send_file

    _seed_pay35_20260709()  # one-shot : payes 35% Lola/Emma/Alicia (voir docstring)
    _seed_rev_compte2_20260709()  # one-shot : revenus compte séparé Amelia/Julia/Lola + payes %
    _seed_of_chatters_20260709()  # one-shot : compte 2 -> Revenue OF + chatteurs % liés aux 3
    _seed_chatters_mym_20260709()  # CORRECTIF : chatteurs % -> CA MyPuls (toutes sauf Amelia)
    _seed_va_classique_20260709()  # one-shot : ligne auto VA classique (clics x 0.07$)

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
            return jsonify(compute_state(month))
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    @app.route("/facture/mypuls_models")
    def facture_mypuls_models():
        """Liste des créatrices MyPuls (pour le select 'CA MyPuls auto')."""
        if not is_auth():
            return jsonify({"ok": False, "error": "unauth"}), 401
        try:
            import mypuls
            res = mypuls.list_creators()
            if not res.get("ok"):
                return jsonify({"ok": False, "error": res.get("error") or "MyPuls indisponible"})
            return jsonify({"ok": True, "models": sorted(res.get("creators") or {}, key=str.lower)})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

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
        before = len(m.get("lines") or [])
        m["lines"] = [l for l in (m.get("lines") or []) if l.get("id") != lid]
        _save(d)
        return jsonify({"ok": True, "deleted": before - len(m["lines"])})

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
            st["eur_usd"] = max(0.5, min(2.0, float(request.form.get("eur_usd") or 1.08)))
        except Exception:
            pass
        try:
            st["cutoff"] = max(1, min(28, int(request.form.get("cutoff") or 15)))
        except Exception:
            pass
        try:
            assoc = json.loads(request.form.get("associates") or "[]")
            clean = []
            for a in assoc[:10]:
                if isinstance(a, dict) and (a.get("name") or "").strip():
                    clean.append({"name": str(a["name"]).strip()[:40],
                                  "pct": max(0.0, min(100.0, float(a.get("pct") or 0)))})
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
        src = (d["months"].get(month) or {}).get("lines") or []
        new_lines = []
        id_map = {}  # ancien id -> nouvel id (pour réécrire les % liés)
        for l in src:
            if l.get("freq") == "once":
                continue
            nl = dict(l)
            nl["id"] = uuid.uuid4().hex[:12]
            if l.get("id"):
                id_map[l["id"]] = nl["id"]
            nl["paid"] = False
            nl["paid_at"] = ""
            # décale les phases d'un mois
            phs = []
            for p in (l.get("phases") or []):
                try:
                    pd = datetime.date.fromisoformat(p["date"])
                    ny = pd.year + (1 if pd.month == 12 else 0)
                    nmn = 1 if pd.month == 12 else pd.month + 1
                    lastd = calendar.monthrange(ny, nmn)[1]
                    phs.append({"date": datetime.date(ny, nmn, min(pd.day, lastd)).isoformat(),
                                "paid": False, "paid_at": ""})
                except Exception:
                    pass
            nl["phases"] = phs
            new_lines.append(nl)
        # Réécrit les liens % (line:/lines:) vers les NOUVELLES ids du mois copié
        # (sinon le % pointerait sur les lignes de l'ancien mois -> base 0)
        for nl in new_lines:
            po = nl.get("pct_of") or ""
            if po.startswith("line:"):
                nl["pct_of"] = "line:" + id_map.get(po[5:], po[5:])
            elif po.startswith("lines:"):
                nl["pct_of"] = "lines:" + ",".join(id_map.get(i, i) for i in po[6:].split(",") if i)
        d["months"][nm] = {"lines": new_lines}
        _save(d)
        return jsonify({"ok": True, "month": nm, "count": len(new_lines)})
