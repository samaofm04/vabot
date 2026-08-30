# -*- coding: utf-8 -*-
"""va_portal.py — un lien par VA, une page pour lui seul.

Le referentiel des comptes Instagram (`jailbreak.json`) vit derriere le
dashboard, donc derriere un mot de passe que les VAs n'ont pas et n'auront
pas. Resultat : chaque ajout ou retrait de compte passait par un message
Discord et un aller-retour avec le proprietaire.

Ce module ouvre une porte etroite. Une fiche VA — un couple
(identite, nom du VA) — recoit un jeton, et le jeton donne UNE adresse :

    https://youl4b.com/mes-comptes/<jeton>

La page qui s'ouvre ne connait que cette fiche. Pas de liste d'identites,
pas de barre laterale, pas de navigation : il n'y a rien a atteindre depuis
la, parce qu'il n'y a rien d'autre de charge. Quelqu'un qui gere quatre
telephones a quatre fiches, donc quatre jetons, donc quatre pages, et
aucune des quatre ne mentionne les trois autres.

Ce qu'on peut y faire : **ajouter** des comptes et **en retirer**. Rien
d'autre. Pas de renommage de fiche, pas de deplacement vers une autre
identite, pas de suppression de fiche. C'est volontaire : tout ce qui
touche a la STRUCTURE reste au dashboard.

Trois choses meritent d'etre expliquees, parce qu'elles ne se devinent pas :

**Le jeton suit la fiche, pas son nom.** Renommer « VA NOUM 1X1 » en
« VA NOUM 1 » ne doit pas casser le lien deja envoye sur Discord — sinon
chaque renommage silencieux transforme une page vivante en 404 et personne
ne comprend pourquoi. `renommer_va` est appelee depuis la route de
renommage du dashboard, et deplace le jeton.

**Les mots de passe ne sortent pas.** La page montre le pseudo, les stats
et la date du dernier reel ; elle ne montre ni mot de passe, ni 2FA, ni
adresse mail. Un lien se recopie, se transfere, finit dans une conversation
de groupe : ce qui passe par la doit pouvoir etre lu par quelqu'un a qui il
n'etait pas destine sans que ce soit une fuite d'identifiants.

**Un jeton perdu ne peut pas tout casser.** Les actions sont plafonnees par
JOUR et par lien, et chacune est datee dans un journal que le proprietaire
peut lire. Un lien qui fuit permet d'ajouter du bruit, pas de vider une
fiche de cinquante comptes en une minute.

Le module ne s'installe pas seul : `register(app, deps)` recoit du fichier
principal les quelques fonctions dont il a besoin. C'est ce qui evite
l'import circulaire avec `web_upload`, et ce qui rend visible en une seule
liste tout ce qu'il peut toucher du reste du site.
"""
from __future__ import annotations

import datetime as _dt
import logging
import secrets
import threading
import time
from html import escape as _esc
from pathlib import Path
from typing import Any, Dict, List, Optional

import safe_json

log = logging.getLogger("vabot.va_portal")

DATA_DIR = Path("data")
LIENS_FILE = DATA_DIR / "jb_va_liens.json"

# Prefixe des adresses publiques. PAS « /va/ » : ce prefixe-la porte deja dix
# routes du dashboard (/va/reset, /va/get_insta_3...) et figure dans la liste
# des ecritures reservees aux acces complets — une page ouverte par jeton s'y
# serait fait refuser l'ajout des qu'un manager au role restreint l'ouvrait
# depuis le navigateur ou il est connecte.
RACINE = "/mes-comptes"

# Verrou reentrant : toute sequence lire-modifier-ecrire passe par la. Le
# journal est ecrit depuis les requetes publiques, qui peuvent arriver en
# parallele ; sans verrou, deux ajouts simultanes perdent une ligne.
_LOCK = threading.RLock()

# Plafonds par JOUR et par lien. Un lien qui fuit doit rester embetant, pas
# destructeur : on peut polluer une fiche, pas la vider.
MAX_AJOUTS_JOUR = 120
MAX_RETRAITS_JOUR = 30

# Nombre de lignes acceptees dans un seul collage. Au-dela on coupe et on le
# DIT — une ligne avalee en silence, c'est un compte qu'on croit ajoute.
MAX_LIGNES_COLLAGE = 100

# Longueur du journal conserve par lien. Assez pour repondre a « qui a retire
# ce compte hier », pas assez pour faire grossir le fichier indefiniment.
JOURNAL_MAX = 80


# ==============================================================================
# Stockage
# ==============================================================================

def _load() -> Dict[str, Any]:
    d = safe_json.load(LIENS_FILE, default={})
    return d if isinstance(d, dict) else {}


def _save(d: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    safe_json.write(LIENS_FILE, d)


def _norm(s: Any) -> str:
    return str(s or "").strip()


def _meme_fiche(rec: Dict[str, Any], identite: str, va: str) -> bool:
    return (_norm(rec.get("identite")).lower() == _norm(identite).lower()
            and _norm(rec.get("va")).lower() == _norm(va).lower())


def lien_pour(identite: str, va: str) -> str:
    """Le jeton ACTIF de cette fiche, ou '' si elle n'en a pas encore."""
    identite, va = _norm(identite), _norm(va)
    if not identite or not va:
        return ""
    with _LOCK:
        for jeton, rec in _load().items():
            if isinstance(rec, dict) and rec.get("actif", True) and _meme_fiche(rec, identite, va):
                return jeton
    return ""


def creer_lien(identite: str, va: str) -> str:
    """Rend le jeton de la fiche, en le creant au besoin.

    Idempotent a dessein : le bouton du dashboard sert aussi bien a creer le
    lien qu'a le relire, et un clic de plus ne doit pas invalider celui qui
    circule deja sur Discord.
    """
    identite, va = _norm(identite), _norm(va)
    if not identite or not va:
        return ""
    with _LOCK:
        d = _load()
        for jeton, rec in d.items():
            if isinstance(rec, dict) and rec.get("actif", True) and _meme_fiche(rec, identite, va):
                return jeton
        jeton = secrets.token_urlsafe(18)
        d[jeton] = {
            "identite": identite.lower(),
            "va": va,
            "cree": int(time.time()),
            "actif": True,
            "ouvertures": 0,
            "vu": 0,
            "journal": [],
        }
        _save(d)
        log.info("va_portal: lien cree pour %s / %s", identite, va)
        return jeton


def regenerer(identite: str, va: str) -> str:
    """Coupe l'ancien jeton et en rend un neuf.

    A utiliser quand un lien a fuite : l'ancien doit cesser de fonctionner
    tout de suite, pas cohabiter avec le nouveau.
    """
    identite, va = _norm(identite), _norm(va)
    if not identite or not va:
        return ""
    with _LOCK:
        d = _load()
        ancien_journal: List[Dict[str, Any]] = []
        for jeton, rec in list(d.items()):
            if isinstance(rec, dict) and _meme_fiche(rec, identite, va):
                # On garde l'historique : c'est lui qui repond a « qui a
                # retire ce compte », et regenerer un lien ne doit pas
                # effacer ce qui s'est passe avant.
                ancien_journal = list(rec.get("journal") or []) or ancien_journal
                d.pop(jeton, None)
        jeton = secrets.token_urlsafe(18)
        d[jeton] = {
            "identite": identite.lower(),
            "va": va,
            "cree": int(time.time()),
            "actif": True,
            "ouvertures": 0,
            "vu": 0,
            "journal": ancien_journal[-JOURNAL_MAX:],
        }
        _save(d)
        log.info("va_portal: lien REGENERE pour %s / %s", identite, va)
        return jeton


def revoquer(identite: str, va: str) -> bool:
    """Ferme le lien de cette fiche. Rend True si quelque chose a ete ferme."""
    identite, va = _norm(identite), _norm(va)
    if not identite or not va:
        return False
    with _LOCK:
        d = _load()
        touche = False
        for jeton, rec in list(d.items()):
            if isinstance(rec, dict) and _meme_fiche(rec, identite, va):
                d.pop(jeton, None)
                touche = True
        if touche:
            _save(d)
            log.info("va_portal: lien revoque pour %s / %s", identite, va)
        return touche


def renommer_va(identite: str, ancien: str, nouveau: str) -> bool:
    """Fait suivre le jeton quand la fiche change de nom.

    Sans ca, renommer une fiche depuis le dashboard transformait en 404 un
    lien deja envoye — sans un mot, et sans que le lien reapparaisse : la
    fiche renommee n'avait plus de jeton du tout.
    """
    identite, ancien, nouveau = _norm(identite), _norm(ancien), _norm(nouveau)
    if not identite or not ancien or not nouveau or ancien.lower() == nouveau.lower():
        return False
    with _LOCK:
        d = _load()
        touche = False
        for rec in d.values():
            if isinstance(rec, dict) and _meme_fiche(rec, identite, ancien):
                rec["va"] = nouveau
                touche = True
        if touche:
            _save(d)
        return touche


def oublier_identite(identite: str) -> int:
    """Ferme tous les liens d'une identite (identite supprimee ou renommee)."""
    identite = _norm(identite).lower()
    if not identite:
        return 0
    with _LOCK:
        d = _load()
        avant = len(d)
        d = {k: v for k, v in d.items()
             if not (isinstance(v, dict) and _norm(v.get("identite")).lower() == identite)}
        if len(d) != avant:
            _save(d)
        return avant - len(d)


def resoudre(jeton: str) -> Optional[Dict[str, Any]]:
    """La fiche derriere un jeton, ou None s'il est inconnu ou ferme."""
    jeton = _norm(jeton)
    if not jeton or len(jeton) > 120:
        return None
    rec = _load().get(jeton)
    if not isinstance(rec, dict) or not rec.get("actif", True):
        return None
    return rec


def liens_par_identite() -> Dict[str, List[Dict[str, Any]]]:
    """Vue admin : {identite: [{va, jeton, cree, ouvertures, vu}, ...]}."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for jeton, rec in _load().items():
        if not isinstance(rec, dict) or not rec.get("actif", True):
            continue
        ident = _norm(rec.get("identite")).lower()
        out.setdefault(ident, []).append({
            "va": _norm(rec.get("va")),
            "jeton": jeton,
            "cree": rec.get("cree") or 0,
            "ouvertures": rec.get("ouvertures") or 0,
            "vu": rec.get("vu") or 0,
        })
    for lignes in out.values():
        lignes.sort(key=lambda x: x["va"].lower())
    return out


def _aujourdhui() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d")


def compte_du_jour(rec: Dict[str, Any], action: str) -> int:
    jour = _aujourdhui()
    n = 0
    for ligne in (rec.get("journal") or []):
        if isinstance(ligne, dict) and ligne.get("a") == action and str(ligne.get("j")) == jour:
            n += int(ligne.get("n") or 1)
    return n


def journaliser(jeton: str, action: str, cibles: List[str], ip: str = "") -> None:
    """Ecrit une ligne d'historique sur le lien. Jamais bloquant pour l'appelant."""
    try:
        with _LOCK:
            d = _load()
            rec = d.get(jeton)
            if not isinstance(rec, dict):
                return
            j = list(rec.get("journal") or [])
            j.append({
                "t": int(time.time()),
                "j": _aujourdhui(),
                "a": action,
                "n": len(cibles) or 1,
                "c": [str(c)[:40] for c in cibles[:12]],
                "ip": str(ip or "")[:45],
            })
            rec["journal"] = j[-JOURNAL_MAX:]
            d[jeton] = rec
            _save(d)
    except Exception as e:                        # noqa: BLE001
        log.warning("va_portal: journal non ecrit (%s)", e)


def _marquer_ouverture(jeton: str) -> None:
    try:
        with _LOCK:
            d = _load()
            rec = d.get(jeton)
            if not isinstance(rec, dict):
                return
            rec["ouvertures"] = int(rec.get("ouvertures") or 0) + 1
            rec["vu"] = int(time.time())
            d[jeton] = rec
            _save(d)
    except Exception:
        pass                                       # un compteur perdu n'est rien


# ==============================================================================
# Rendu
# ==============================================================================

def _fmt_count(n) -> str:
    """1234 -> 1.2k, 1500000 -> 1.5M. Meme format que le dashboard."""
    try:
        n = int(n)
    except Exception:
        return "—"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def _age_reel(valeur) -> tuple:
    """(libelle, date courte) pour un horodatage de dernier reel."""
    if not valeur:
        return ("—", "")
    try:
        d_post = _dt.datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
        if d_post.tzinfo is None:
            d_post = d_post.replace(tzinfo=_dt.timezone.utc)
        h = int((_dt.datetime.now(_dt.timezone.utc) - d_post).total_seconds() / 3600)
        if h < 1:
            lbl = "à l'instant"
        elif h < 24:
            lbl = f"il y a {h}h"
        else:
            lbl = f"il y a {h // 24}j"
        return (lbl, d_post.strftime("%d/%m %Hh%M"))
    except Exception:
        return ("—", "")


# Feuille de style de la page. Elle est autonome : la page publique ne charge
# rien du dashboard, donc rien ne peut casser ici quand le dashboard change de
# theme — et inversement.
_CSS = """
:root{
  --fond:#f5f6f8; --carte:#ffffff; --bord:#e6e8ec; --texte:#14161a;
  --doux:#6b7280; --tres-doux:#9ca3af; --accent:#ec4899; --vert:#16a34a;
  --rouge:#dc2626; --orange:#ea580c; --ombre:0 1px 3px rgba(16,24,40,.06);
}
@media (prefers-color-scheme: dark){
  :root{
    --fond:#0b0d11; --carte:#14171d; --bord:#232833; --texte:#e8eaee;
    --doux:#8b93a1; --tres-doux:#6b7280; --ombre:0 1px 3px rgba(0,0,0,.4);
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--fond);color:var(--texte);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  font-size:14px;line-height:1.45;-webkit-text-size-adjust:100%}
.wrap{max-width:960px;margin:0 auto;padding:18px 14px 60px}
.carte{background:var(--carte);border:1px solid var(--bord);border-radius:14px;
  box-shadow:var(--ombre);margin-bottom:16px}
.tete{display:flex;align-items:center;gap:14px;padding:16px 18px;flex-wrap:wrap}
.pp{width:46px;height:46px;border-radius:50%;flex-shrink:0;display:flex;
  align-items:center;justify-content:center;color:#fff;font-weight:800;font-size:18px;
  position:relative;overflow:hidden}
/* L initiale coloree est TOUJOURS dessous, la photo par-dessus. Une photo qui
   ne charge pas laisse donc une pastille, pas un trou : avant, l image ratee
   se cachait et il ne restait rien du tout a la place. */
.pp img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;
  border-radius:inherit;background:inherit}
.tete h1{margin:0;font-size:19px;font-weight:800;letter-spacing:-.2px}
.tete .meta{display:flex;gap:6px;flex-wrap:wrap;margin-top:5px}
.pill{font-size:11px;font-weight:700;padding:2px 9px;border-radius:20px;
  background:rgba(120,130,150,.14);color:var(--doux);white-space:nowrap}
.pill.id{background:rgba(236,72,153,.14);color:var(--accent)}
.pill.ok{background:rgba(22,163,74,.14);color:var(--vert)}
.pill.ban{background:rgba(220,38,38,.14);color:var(--rouge)}
.pill.warn{background:rgba(234,88,12,.14);color:var(--orange)}
.compteur{margin-left:auto;text-align:right}
.compteur b{display:block;font-size:24px;font-weight:800;color:var(--accent);line-height:1}
.compteur span{font-size:10px;letter-spacing:1px;color:var(--tres-doux)}
.bloc{padding:14px 18px;border-top:1px solid var(--bord)}
.bloc h2{margin:0 0 8px;font-size:13px;font-weight:800;letter-spacing:.3px}
.aide{color:var(--doux);font-size:12px;margin:0 0 10px}
textarea{width:100%;min-height:88px;resize:vertical;padding:10px 12px;font:inherit;
  font-size:13px;border:1px solid var(--bord);border-radius:10px;background:var(--fond);
  color:var(--texte)}
textarea:focus{outline:2px solid rgba(236,72,153,.35);outline-offset:1px}
.btn{border:0;border-radius:10px;padding:10px 18px;font:inherit;font-weight:700;
  font-size:13px;cursor:pointer;background:var(--accent);color:#fff}
.btn:disabled{opacity:.55;cursor:default}
.btn.gris{background:rgba(120,130,150,.16);color:var(--texte)}
/* Deux grilles imbriquees, et c'est voulu : la ligne place pastille / nom /
   chiffres / croix, et le bloc « chiffres » aligne les colonnes entre elles.
   Une grille plate a huit colonnes s'ecroulait sur telephone — les cinq
   valeurs atterrissaient dans la meme case et se superposaient. */
.thead,.ligne{display:grid;grid-template-columns:38px minmax(0,1fr) auto 34px;
  gap:8px;align-items:center}
.chiffres{display:grid;grid-template-columns:66px 66px 66px 76px 94px;gap:8px;
  align-items:center}
.thead{padding:8px 18px;font-size:10px;letter-spacing:.6px;color:var(--tres-doux);
  font-weight:800;border-top:1px solid var(--bord)}
.thead .r{text-align:right}
.ligne{padding:9px 18px;border-top:1px solid var(--bord)}
.ligne:hover{background:rgba(120,130,150,.05)}
.ligne.bannie{opacity:.6}
.ligne img.pp,.ligne .pp{width:34px;height:34px;font-size:14px}
.nom{min-width:0}
.nom a{color:var(--texte);font-weight:700;text-decoration:none;font-size:13px}
.nom a:hover{color:var(--accent)}
.nom .sous{color:var(--tres-doux);font-size:11px;margin-top:1px}
.badge{font-size:9px;font-weight:800;padding:1px 6px;border-radius:5px;margin-left:6px;
  white-space:nowrap;vertical-align:1px}
.badge.actif{background:rgba(22,163,74,.14);color:var(--vert)}
.badge.banni{background:rgba(220,38,38,.14);color:var(--rouge)}
.badge.attente{background:rgba(120,130,150,.16);color:var(--doux)}
.badge.echec{background:rgba(234,88,12,.14);color:var(--orange)}
.num{text-align:right;font-weight:700;font-size:13px}
.num.v{color:var(--vert)}
.reel{font-size:11px}
.reel b{display:block;font-weight:700;font-size:12px}
.reel span{color:var(--tres-doux)}
.sup{background:transparent;border:1px solid var(--bord);color:var(--doux);
  width:26px;height:26px;border-radius:7px;cursor:pointer;font-size:14px;line-height:1}
.sup:hover{border-color:var(--rouge);color:var(--rouge)}
.vide{padding:26px 18px;text-align:center;color:var(--doux);font-size:13px}
.note{color:var(--tres-doux);font-size:11px;text-align:center;margin-top:18px}
#msg{position:fixed;left:50%;transform:translateX(-50%);bottom:20px;z-index:9;
  padding:11px 20px;border-radius:11px;font-size:13px;font-weight:700;color:#fff;
  background:#16a34a;box-shadow:0 8px 24px rgba(0,0,0,.2);display:none;max-width:92vw}
#msg.err{background:#dc2626}
@media (max-width:720px){
  .wrap{padding:10px 8px 50px}
  /* L'en-tete de colonnes disparait : chaque chiffre porte alors son propre
     libelle, sinon on lit « 672 / 0 / 85.3k » sans savoir ce que c'est. */
  .thead{display:none}
  .ligne{grid-template-columns:34px minmax(0,1fr) 30px;row-gap:8px;padding:11px 14px}
  .ligne>:first-child{grid-column:1;grid-row:1}
  .ligne>.nom{grid-column:2;grid-row:1}
  .ligne>.sup{grid-column:3;grid-row:1}
  .ligne>.chiffres{grid-column:1 / -1;grid-row:2;
    grid-template-columns:repeat(auto-fit,minmax(74px,1fr));gap:8px 10px}
  .chiffres .num{text-align:left}
  .chiffres .num::after{content:attr(data-lab);display:block;font-size:9px;
    color:var(--tres-doux);font-weight:600;letter-spacing:.3px}
  .compteur{margin-left:0}
}
"""

# Le script est court a dessein : il envoie un formulaire, il recoit du HTML,
# il le pose. Toute la mise en forme est faite par le serveur — c'est ce qui
# evite d'avoir deux rendus a maintenir, l'un serveur l'autre client, qui
# divergent au premier correctif applique d'un seul cote.
_JS = """
function vpMsg(txt, err){
  var m = document.getElementById('msg');
  if(!m) return;
  m.textContent = txt;
  m.className = err ? 'err' : '';
  m.style.display = 'block';
  clearTimeout(window.__vpT);
  window.__vpT = setTimeout(function(){ m.style.display = 'none'; }, 4200);
}
function vpPose(html, total){
  var z = document.getElementById('liste');
  if(z && typeof html === 'string') z.innerHTML = html;
  var c = document.getElementById('total');
  if(c && typeof total !== 'undefined') c.textContent = total;
}
function vpEnvoie(url, data, btn, libelle){
  var vieux = btn ? btn.textContent : '';
  if(btn){ btn.disabled = true; btn.textContent = '…'; }
  return fetch(url, {method:'POST', body:data, headers:{'Accept':'application/json'}})
    .then(function(r){ return r.json(); })
    .then(function(j){
      if(btn){ btn.disabled = false; btn.textContent = libelle || vieux; }
      if(j && j.liste !== undefined) vpPose(j.liste, j.total);
      vpMsg((j && (j.msg || j.error)) || 'Erreur', !(j && j.ok));
      return j;
    })
    .catch(function(e){
      if(btn){ btn.disabled = false; btn.textContent = libelle || vieux; }
      vpMsg('Connexion perdue — reessaie', true);
    });
}
function vpAjouter(btn){
  var ta = document.getElementById('ajout');
  var txt = (ta && ta.value || '').trim();
  if(!txt){ vpMsg('Colle au moins un pseudo ou un lien', true); return; }
  var fd = new FormData();
  fd.append('comptes', txt);
  vpEnvoie(window.__vpBase + '/ajouter', fd, btn, '+ Ajouter').then(function(j){
    if(j && j.ok && ta) ta.value = '';
  });
}
document.addEventListener('click', function(ev){
  var b = ev.target.closest ? ev.target.closest('button.sup') : null;
  if(!b) return;
  var u = b.getAttribute('data-compte') || '';
  var id = b.getAttribute('data-id') || '';
  if(!id) return;
  if(!confirm('Retirer @' + u + ' de ta liste ?')) return;
  var fd = new FormData();
  fd.append('compte_id', id);
  vpEnvoie(window.__vpBase + '/retirer', fd, null, '');
});
"""

_GABARIT = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<meta name="referrer" content="no-referrer">
<title>__TITRE__</title>
<style>__CSS__</style>
</head>
<body>
<div class="wrap">__CORPS__</div>
<div id="msg"></div>
<script>window.__vpBase = "__BASE__";</script>
<script>__JS__</script>
</body>
</html>"""


def _page(titre: str, corps: str, base: str) -> str:
    return (_GABARIT
            .replace("__CSS__", _CSS)
            .replace("__JS__", _JS)
            .replace("__TITRE__", _esc(titre))
            .replace("__BASE__", _esc(base))
            .replace("__CORPS__", corps))


def _avatar(nom: str, classe: str = "pp", photo: str = "") -> str:
    """Pastille d'un compte : l'initiale coloree, et la photo par-dessus si on
    en a une. L'initiale reste dessous — une photo qui ne charge pas laisse
    une pastille lisible au lieu d'un trou."""
    teinte = sum(ord(c) for c in (nom or "?")) % 360
    init = _esc((nom or "?")[:1].upper())
    img = ""
    if photo:
        img = (f"<img src='{_esc(photo)}' loading='lazy' decoding='async' "
               f"referrerpolicy='no-referrer' alt='' "
               f"onerror=\"this.remove()\">")
    return (f"<div class='{classe}' style='background:hsl({teinte},48%,45%)'>"
            f"{init}{img}</div>")


def _url_photo(s: dict, handle: str, base_pp: str) -> str:
    """L'adresse de la photo de profil, vue depuis la page publique.

    Le cache range la copie locale sous « /insta/pp/<handle> » — une route du
    dashboard, qui repond 401 a qui n'a pas de session. Telle quelle, elle ne
    donnait donc RIEN sur cette page : les comptes qui avaient une photo
    etaient justement ceux qui s'affichaient vides. On la reecrit vers la
    route servie par le jeton, qui ne sert que les comptes de SA fiche.

    Une URL Instagram directe (ancien cache) est laissee telle quelle : elle
    se charge sans session, et `referrerpolicy=no-referrer` empeche le jeton
    de fuir dans l'en-tete Referer.
    """
    url = str(s.get("profile_pic_url") or "").strip()
    if not url:
        return ""
    if url.startswith("/insta/pp/"):
        return (base_pp + "/" + handle) if base_pp else ""
    return url


def _ligne_compte(a: dict, stats: dict, normaliser, base_pp: str = "") -> str:
    """Une ligne du tableau. Volontairement sans mot de passe, sans 2FA et sans
    adresse mail : voir l'en-tete du module."""
    pseudo_brut = str(a.get("username") or "?")
    try:
        h = normaliser(pseudo_brut) if callable(normaliser) else pseudo_brut.lower().lstrip("@")
    except Exception:
        h = pseudo_brut.lower().lstrip("@")
    s = stats.get(h) or {}
    banni = bool(s.get("banned"))
    jamais = not s
    ok = bool(s) and not s.get("error")

    pp = _avatar(h, photo=_url_photo(s, h, base_pp))

    if banni:
        badge = "<span class='badge banni'>Banni</span>"
    elif jamais:
        badge = "<span class='badge attente'>Non scrapé</span>"
    elif s.get("error"):
        badge = "<span class='badge echec'>Échec</span>"
    else:
        badge = "<span class='badge actif'>Actif</span>"

    if ok:
        foll = _fmt_count(s.get("followers"))
        d24 = _fmt_count(s.get("daily"))
        sem = _fmt_count(s.get("weekly"))
        bi = _fmt_count(s.get("biweekly"))
    else:
        foll = d24 = sem = bi = "—"
    lbl, date_courte = _age_reel(s.get("last_reel_at") or s.get("last_post_at")) if ok else ("—", "")

    aid = int(a.get("id") or 0)
    ps = _esc(pseudo_brut)
    return (
        f"<div class='ligne{' bannie' if banni else ''}'>"
        f"{pp}"
        f"<div class='nom'>"
        f"<div><a href='https://instagram.com/{_esc(h)}/' target='_blank' "
        f"rel='noopener noreferrer'>@{ps}</a>{badge}</div>"
        f"<div class='sous'>Instagram</div>"
        f"</div>"
        f"<div class='chiffres'>"
        f"<div class='num' data-lab='abonnés'>{foll}</div>"
        f"<div class='num v' data-lab='vues 24h'>{d24}</div>"
        f"<div class='num v' data-lab='vues sem'>{sem}</div>"
        f"<div class='num v' data-lab='vues 2 sem'>{bi}</div>"
        f"<div class='reel'><b>{_esc(lbl)}</b>"
        f"<span>{_esc(date_courte)}</span></div>"
        f"</div>"
        f"<button type='button' class='sup' data-id='{aid}' data-compte='{ps}' "
        f"title='Retirer ce compte de ta liste'>×</button>"
        f"</div>"
    )


def _entete_tableau() -> str:
    # Meme structure que `.ligne` — quatre enfants dont un bloc `chiffres` —
    # sinon les colonnes de l'en-tete ne tombent pas sur celles des lignes.
    return ("<div class='thead'><span></span><span>Compte</span>"
            "<span class='chiffres'>"
            "<span class='r'>Abonnés</span><span class='r'>Vues 24h</span>"
            "<span class='r'>Vues sem</span><span class='r'>Vues 2 sem</span>"
            "<span>Dernier reel</span>"
            "</span><span></span></div>")


def _tri(comptes: List[dict], stats: dict, normaliser) -> List[dict]:
    """Actifs en tete (plus gros d'abord), puis en attente, echecs, bannis.

    Meme ordre que le dashboard : quelqu'un qui regarde les deux ecrans doit
    y voir la meme chose dans le meme ordre.
    """
    def rang(a):
        brut = str(a.get("username") or "")
        try:
            h = normaliser(brut) if callable(normaliser) else brut.lower().lstrip("@")
        except Exception:
            h = brut.lower().lstrip("@")
        s = stats.get(h) or {}
        if s.get("banned"):
            return (4, 0, 0)
        if not s:
            return (2, 0, 0)
        if s.get("error"):
            return (3, 0, 0)
        if s.get("stale"):
            return (1, 0, 0)
        return (0, -(s.get("followers") or 0), -(s.get("weekly") or 0))
    return sorted(comptes, key=rang)


def _resume(comptes: List[dict], stats: dict, normaliser) -> Dict[str, int]:
    """Actifs / bannis / non scrapes / silencieux depuis plus de 48 h."""
    n = {"actif": 0, "ban": 0, "attente": 0, "oubli": 0}
    maintenant = time.time()
    for a in comptes:
        brut = str(a.get("username") or "")
        try:
            h = normaliser(brut) if callable(normaliser) else brut.lower().lstrip("@")
        except Exception:
            h = brut.lower().lstrip("@")
        s = stats.get(h) or {}
        if s.get("banned"):
            n["ban"] += 1
            continue
        if not s or s.get("error"):
            n["attente"] += 1
            continue
        n["actif"] += 1
        lr = s.get("last_reel_at") or s.get("last_post_at")
        if lr:
            try:
                d = _dt.datetime.fromisoformat(str(lr).replace("Z", "+00:00"))
                if d.tzinfo is None:
                    d = d.replace(tzinfo=_dt.timezone.utc)
                if (maintenant - d.timestamp()) > 48 * 3600:
                    n["oubli"] += 1
            except Exception:
                pass
    return n


# ==============================================================================
# Installation des routes
# ==============================================================================

def register(app, deps):
    """Branche `/mes-comptes/<jeton>` sur `app`.

    `deps` doit fournir :
        pseudo_instagram(str) -> str     pseudo tire d'une ligne collee ('' si rien)
        normalize_handle(str) -> str     handle normalise, cle du cache de stats
        stats_cache() -> dict            cache des stats Instagram par handle
        pp_locale(handle) -> Path|None   copie locale de la photo de profil
        kick_scrape(list, label=) -> int scrape immediat en arriere-plan (optionnel)
        push_sheet(snapshot) -> None     pousse le classeur Google (optionnel)
    """
    from flask import request, jsonify, make_response

    pseudo_instagram = deps["pseudo_instagram"]
    normalize_handle = deps.get("normalize_handle") or (lambda s: str(s or "").strip().lower().lstrip("@"))
    stats_cache = deps.get("stats_cache") or (lambda: {})
    kick_scrape = deps.get("kick_scrape")
    push_sheet = deps.get("push_sheet")

    def _pp_locale_defaut(handle):
        """Repli : le module de scrape sait deja ou vit la copie locale. Le
        passer en dependance reste preferable — c'est ce qui garde la liste
        de ce que ce module touche lisible en un seul endroit."""
        try:
            import insta_scraper as _ig
            return _ig.local_pp_path(handle)
        except Exception:                           # noqa: BLE001
            return None

    pp_locale = deps.get("pp_locale") or _pp_locale_defaut

    def _ip() -> str:
        fwd = (request.headers.get("CF-Connecting-IP")
               or request.headers.get("X-Forwarded-For") or "")
        return (fwd.split(",")[0].strip() or request.remote_addr or "?")[:45]

    def _visiteur_en_clair() -> bool:
        """True SEULEMENT si on sait que le navigateur s'est connecte en http.

        Ici l'adresse EST le secret : le jeton voyage dans la ligne de requete.
        Sur ce site, `http://youl4b.com/...` repond 200 sans rediriger — le
        jeton passait donc en clair, lisible par n'importe quel relais entre le
        telephone du VA et Cloudflare. Aucune autre page du dashboard n'a ce
        probleme au meme degre : ailleurs le secret est dans un cookie ou un
        corps de requete, ici il est dans l'URL.

        Flask ne peut pas voir le schema tout seul : derriere Cloudflare, il
        recoit toujours du http. Seule l'en-tete posee par le proxy dit sur quoi
        le navigateur s'est reellement connecte.

        Dans le doute — en-tete absente, appel direct a l'origine, sonde de
        supervision — on rend False. Une redirection posee sur une supposition
        casse plus qu'elle ne protege.
        """
        xf = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
        if xf:
            return xf == "http"
        cfv = (request.headers.get("CF-Visitor") or "").replace(" ", "").lower()
        if '"scheme":"http"' in cfv:
            return True
        if '"scheme":"https"' in cfv:
            return False
        return False

    def _vers_https():
        """La meme adresse en https, ou None s'il n'y a rien a corriger."""
        if not _visiteur_en_clair():
            return None
        from flask import redirect
        return redirect("https://" + (request.host or "") + (request.path or "/"), code=301)

    def _comptes_de(identite: str, va: str) -> List[dict]:
        import jailbreak as jb
        entree = jb._load().get((identite or "").lower()) or {}
        vl = (va or "").strip().lower()
        return [a for a in (entree.get("accounts") or [])
                if isinstance(a, dict) and (a.get("va") or "").strip().lower() == vl]

    def _liste_html(comptes: List[dict], jeton: str = "") -> str:
        stats = stats_cache() or {}
        if not comptes:
            return ("<div class='vide'>Aucun compte pour l'instant — colle tes pseudos "
                    "ou tes liens Instagram ci-dessus.</div>")
        # Les photos passent par le jeton, jamais par la route du dashboard :
        # voir _url_photo. Sans jeton (appel interne), on retombe sur les
        # initiales — jamais sur une adresse qui repondrait 401.
        base_pp = (RACINE + "/" + jeton + "/pp") if jeton else ""
        return _entete_tableau() + "".join(
            _ligne_compte(a, stats, normalize_handle, base_pp)
            for a in _tri(comptes, stats, normalize_handle)
        )

    def _sans_index(reponse):
        """Un lien porteur ne doit ni etre indexe, ni mis en cache par un proxy,
        ni fuir dans le Referer quand le VA clique sur un profil Instagram."""
        reponse.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        reponse.headers["Referrer-Policy"] = "no-referrer"
        reponse.headers["Cache-Control"] = "no-store, private"
        return reponse

    def _refus(message: str, code: int = 404):
        corps = (f"<div class='carte'><div class='vide'>{_esc(message)}</div></div>"
                 "<p class='note'>Demande un nouveau lien a ton manager.</p>")
        rep = make_response(_page("Lien invalide", corps, ""), code)
        rep.headers["Content-Type"] = "text/html; charset=utf-8"
        return _sans_index(rep)

    @app.route(RACINE + "/<jeton>", methods=["GET"])
    def va_portail(jeton):
        # AVANT de resoudre quoi que ce soit : si le VA est arrive en clair, on
        # le renvoie en https. Le jeton du premier appel est deja passe en
        # clair — on ne peut plus rien pour celui-la — mais tout le reste de la
        # session, y compris les ajouts et les retraits, se fera chiffre.
        vers = _vers_https()
        if vers is not None:
            return vers
        rec = resoudre(jeton)
        if rec is None:
            return _refus("Ce lien n'est plus valable.")
        identite = _norm(rec.get("identite"))
        va = _norm(rec.get("va"))
        try:
            comptes = _comptes_de(identite, va)
        except Exception as e:                      # noqa: BLE001
            log.error("va_portal: lecture jailbreak impossible (%s)", e)
            return _refus("Référentiel momentanément indisponible — réessaie dans une minute.", 503)

        _marquer_ouverture(jeton)
        stats = stats_cache() or {}
        r = _resume(comptes, stats, normalize_handle)

        pastilles = [f"<span class='pill id'>@{_esc(identite)}</span>",
                     f"<span class='pill ok'>✓ {r['actif']} actifs</span>"]
        if r["ban"]:
            pastilles.append(f"<span class='pill ban'>⛔ {r['ban']} banni"
                             f"{'s' if r['ban'] > 1 else ''}</span>")
        if r["attente"]:
            pastilles.append(f"<span class='pill'>◌ {r['attente']} en attente</span>")
        if r["oubli"]:
            pastilles.append(f"<span class='pill warn'>🕒 {r['oubli']} oubli"
                             f"{'s' if r['oubli'] > 1 else ''} 48h</span>")

        corps = (
            "<div class='carte'>"
            "<div class='tete'>"
            + _avatar(va)
            + "<div><h1>" + _esc(va) + "</h1>"
              "<div class='meta'>" + "".join(pastilles) + "</div></div>"
              "<div class='compteur'><b id='total'>" + str(len(comptes)) + "</b>"
              "<span>COMPTES</span></div>"
            "</div>"
            "<div class='bloc'>"
            "<h2>+ Ajouter des comptes</h2>"
            "<p class='aide'>Un par ligne. Le pseudo, le @pseudo ou le lien Instagram "
            "collé depuis le partage — ce qui suit le « ? » est ignoré tout seul.</p>"
            "<textarea id='ajout' placeholder='monpseudo&#10;@autre.pseudo&#10;"
            "https://www.instagram.com/troisieme'></textarea>"
            "<div style='margin-top:9px'>"
            "<button type='button' class='btn' onclick='vpAjouter(this)'>+ Ajouter</button>"
            "</div>"
            "</div>"
            "<div id='liste'>" + _liste_html(comptes, jeton) + "</div>"
            "</div>"
            "<p class='note'>Cette page ne montre que tes comptes. "
            "Les stats se rafraîchissent deux fois par jour.<br>"
            "Ne partage pas ce lien : il ouvre ta liste sans mot de passe.</p>"
        )
        rep = make_response(_page(va + " — mes comptes", corps, RACINE + "/" + _esc(jeton)))
        rep.headers["Content-Type"] = "text/html; charset=utf-8"
        return _sans_index(rep)

    @app.route(RACINE + "/<jeton>/pp/<handle>")
    def va_portail_pp(jeton, handle):
        """La photo de profil d'un compte de CETTE fiche, et d'aucune autre.

        La route du dashboard (/insta/pp/<handle>) exige une session : sur
        cette page elle repondait 401, donc les comptes qui avaient une photo
        etaient precisement ceux qui s'affichaient vides. Celle-ci sert le
        meme fichier local, mais seulement pour les pseudos rattaches au
        jeton — un jeton ne devient pas un lecteur de photos de toute
        l'agence.
        """
        from flask import send_file
        rec = resoudre(jeton)
        if rec is None:
            return "", 404
        h = normalize_handle(handle or "")
        if not h:
            return "", 404
        comptes = _comptes_de(_norm(rec.get("identite")), _norm(rec.get("va")))
        connus = {normalize_handle(a.get("username") or "") for a in comptes}
        if h not in connus:
            return "", 404
        chemin = pp_locale(h) if callable(pp_locale) else None
        if not chemin:
            # 404 mis en cache : sans en-tete, un compte sans copie locale
            # coutait une requete a chaque affichage de la page, pour rien.
            rep = make_response("", 404)
            rep.mimetype = "text/plain"
            rep.headers["Cache-Control"] = "public, max-age=3600"
            return rep
        rep = send_file(str(chemin), mimetype="image/jpeg", conditional=True)
        # « private » : la photo passe par une adresse porteuse de jeton, elle
        # n'a rien a faire dans le cache partage d'un proxy.
        rep.headers["Cache-Control"] = "private, max-age=86400"
        rep.headers["Referrer-Policy"] = "no-referrer"
        return rep

    @app.route(RACINE + "/<jeton>/ajouter", methods=["POST"])
    def va_portail_ajouter(jeton):
        rec = resoudre(jeton)
        if rec is None:
            return jsonify({"ok": False, "error": "Lien expiré — demande-en un nouveau"}), 404
        identite, va = _norm(rec.get("identite")), _norm(rec.get("va"))

        deja = compte_du_jour(rec, "ajout")
        if deja >= MAX_AJOUTS_JOUR:
            return jsonify({"ok": False,
                            "error": f"Plafond du jour atteint ({MAX_AJOUTS_JOUR}). "
                                     "Reviens demain ou passe par ton manager."})

        brut = request.form.get("comptes") or ""
        pseudos, ecartes, tronque = [], [], 0
        lignes = brut.replace(",", "\n").replace(";", "\n").replace("\t", "\n").splitlines()
        if len(lignes) > MAX_LIGNES_COLLAGE:
            tronque = len(lignes) - MAX_LIGNES_COLLAGE
            lignes = lignes[:MAX_LIGNES_COLLAGE]
        for ligne in lignes:
            t = ligne.strip()
            if not t:
                continue
            p = pseudo_instagram(t)
            if p:
                if p not in pseudos:
                    pseudos.append(p)
            else:
                ecartes.append(t[:40])
        if not pseudos:
            detail = (" Non reconnu : " + ", ".join(ecartes[:4])) if ecartes else ""
            return jsonify({"ok": False, "error": ("Aucun compte reconnu." + detail)[:240]})
        if len(pseudos) > (MAX_AJOUTS_JOUR - deja):
            pseudos = pseudos[:MAX_AJOUTS_JOUR - deja]
            tronque += 1

        try:
            import jailbreak as jb
            res = jb.bulk_add_accounts(identite, pseudos, va=va)
        except Exception as e:                      # noqa: BLE001
            log.error("va_portal: ajout refuse (%s)", e)
            return jsonify({"ok": False, "error": f"Ajout impossible : {e}"[:200]})

        ajoutes = res.get("added_usernames") or []
        journaliser(jeton, "ajout", ajoutes or pseudos, _ip())
        if ajoutes and callable(kick_scrape):
            try:
                kick_scrape(ajoutes, label="va-portail")
            except Exception as e:                  # noqa: BLE001
                log.warning("va_portal: scrape non lance (%s)", e)
        if ajoutes and callable(push_sheet):
            try:
                push_sheet()
            except Exception as e:                  # noqa: BLE001
                log.warning("va_portal: push Sheet non lance (%s)", e)

        morceaux = [f"{res.get('added', 0)} compte(s) ajouté(s)"]
        if res.get("skipped_dup"):
            morceaux.append(f"{res['skipped_dup']} déjà présent(s)")
        if res.get("skipped_invalid"):
            morceaux.append(f"{res['skipped_invalid']} invalide(s)")
        if ecartes:
            morceaux.append(f"{len(ecartes)} ligne(s) non reconnue(s) : "
                            + ", ".join(ecartes[:3]))
        if tronque:
            morceaux.append(f"{tronque} ligne(s) laissée(s) de côté (plafond)")

        comptes = _comptes_de(identite, va)
        return jsonify({"ok": True, "msg": " · ".join(morceaux),
                        "liste": _liste_html(comptes, jeton), "total": len(comptes)})

    @app.route(RACINE + "/<jeton>/retirer", methods=["POST"])
    def va_portail_retirer(jeton):
        rec = resoudre(jeton)
        if rec is None:
            return jsonify({"ok": False, "error": "Lien expiré — demande-en un nouveau"}), 404
        identite, va = _norm(rec.get("identite")), _norm(rec.get("va"))

        if compte_du_jour(rec, "retrait") >= MAX_RETRAITS_JOUR:
            return jsonify({"ok": False,
                            "error": f"Plafond de retraits du jour atteint "
                                     f"({MAX_RETRAITS_JOUR}). Passe par ton manager."})
        try:
            compte_id = int(request.form.get("compte_id") or 0)
        except Exception:
            compte_id = 0
        if not compte_id:
            return jsonify({"ok": False, "error": "Compte introuvable"})

        # Le jeton ne donne acces qu'a SA fiche : on verifie que le compte vise
        # est bien dans cette liste AVANT de supprimer. Sans ce controle, un
        # identifiant devine dans une autre fiche serait supprimable depuis ici.
        comptes = _comptes_de(identite, va)
        vise = next((a for a in comptes if int(a.get("id") or 0) == compte_id), None)
        if vise is None:
            log.warning("va_portal: retrait hors perimetre refuse (%s / %s / %s)",
                        identite, va, compte_id)
            return jsonify({"ok": False, "error": "Ce compte n'est pas dans ta liste"})

        try:
            import jailbreak as jb
            enleve = jb.remove_account(identite, compte_id)
        except Exception as e:                      # noqa: BLE001
            log.error("va_portal: retrait impossible (%s)", e)
            return jsonify({"ok": False, "error": f"Retrait impossible : {e}"[:200]})
        if not enleve:
            return jsonify({"ok": False, "error": "Compte introuvable"})

        pseudo = _norm(vise.get("username"))
        journaliser(jeton, "retrait", [pseudo], _ip())
        if callable(push_sheet):
            try:
                push_sheet()
            except Exception as e:                  # noqa: BLE001
                log.warning("va_portal: push Sheet non lance (%s)", e)

        comptes = _comptes_de(identite, va)
        return jsonify({"ok": True, "msg": f"@{pseudo} retiré",
                        "liste": _liste_html(comptes, jeton), "total": len(comptes)})

    return app
