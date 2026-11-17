"""L'adresse USDC d'un VA TRUST, changée par la direction : /trust/liens/adresse.

Propriétaire, 17/11/2026 : « son adresse modifiable que pour eux sur leur
Discord, ou par moi owner avec un mot de passe », puis « y a un accès où le
mec voit, mais moi j'ai un lien où je peux modifier, je mets mes logs ».

Deux accès, donc, et ils ne se mélangent pas :
- le VA VOIT son adresse sur sa page « Tes stats » (lien à clé, lecture
  seule) et ne la change que par 💳 dans son ticket Discord ;
- la direction a SON lien : la page /trust/liens ouverte avec un compte du
  dashboard à accès complet (« je mets mes logs »), sur youl4b.com. Chaque
  ligne y porte « Modifier », qui mène ici. Pas de second mot de passe à
  retenir : celui du compte. Une clé de manager (?k=) ou le lien d'un VA
  n'ouvrent jamais cette page, et trust-ofm.com ne la sert pas (domaines.
  CHEMINS_TRUST ne la liste pas).

Une adresse de paie ne change jamais en silence :
- l'entrée d'avant reste dans « avant » (suivi_va.poser_adresse, dix au
  plus), avec qui l'a posée ; ici « par » vaut « site:<compte> » ;
- le VA est prévenu d'une ligne dans son ticket, sa carte 💳 et son menu
  sont refaits (le ticket montrait sinon l'ancienne adresse) ;
- ce qui n'a pas pu être fait côté Discord est dit sur la page (NOTES).
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote

import stats_trust as st
import stats_va as sv
import suivi_va

CHEMIN = st.CHEMIN + "/adresse"
#: Ce que le ticket Discord n'a pas pu suivre, dit sur la page après
#: l'enregistrement. Des codes dans l'adresse, jamais du texte libre : un
#: lien forgé ne peut rien faire dire à cette page.
NOTES = {
    "ticket": "Ce VA n'a pas de ticket : il n'a pas été prévenu.",
    "carte": "La carte 💳 de son ticket n'a pas pu être refaite.",
    "menu": "Le menu de son ticket n'a pas pu être remis à jour.",
    "message": "Le message qui le prévient n'est pas parti.",
}
#: Un changement à la fois : deux onglets ouverts ne se croisent pas.
_VERROU = threading.Lock()
_e = sv._e


def va(cle: Any) -> Optional[Dict[str, Any]]:
    """Le VA « gid:uid » s'il est sur la page de la direction (une fiche d'un
    des trois serveurs TRUST, pas parti) ; None sinon. On ne pose pas
    d'adresse à un identifiant qui n'est pas un VA."""
    g, _s, u = str(cle or "").partition(":")
    if not (g.isdigit() and u.isdigit()):
        return None
    gens, _remarques = st.personnes()
    return next((p for p in gens if p["gid"] == g and p["uid"] == u), None)


def reseaux(gid: Any) -> Tuple[str, ...]:
    """Les réseaux qu'un VA de ce serveur peut choisir par 💳 : la direction
    n'en pose pas d'autre (TRUST INSTAGRAM : Solana seul)."""
    import tickets_discord as tk
    return ("solana", "ethereum") if str(gid) in tk.USDC_RESEAUX_ICI else ("solana",)


def lien(gid: Any, uid: Any) -> str:
    return f"{CHEMIN}?va={quote(f'{gid}:{uid}', safe='')}"


def _court(a: str) -> str:
    return a if len(a) <= 11 else f"{a[:4]}…{a[-4:]}"


def message(uid: str, adresse: str, reseau: str) -> str:
    """Ce que le VA lit dans son ticket. L'adresse courte, comme dans son menu."""
    return (f"💳 <@{uid}> ton adresse de paiement a été changée par la direction : "
            f"USDC · {suivi_va.RESEAUX.get(reseau, 'Solana')} · `{_court(adresse)}`")


def suite_discord(p: Mapping[str, Any], adresse: str, reseau: str) -> List[str]:
    """Le ticket du VA suit le changement : carte 💳 (TRUST TWITTER et
    THREADS), menu, et le VA prévenu. Rend les codes (NOTES) de ce qui n'a
    pas pu être fait ; ne lève pas : l'adresse est déjà enregistrée."""
    gid, uid = str(p["gid"]), str(p["uid"])
    try:
        import tickets_discord as tk
        import verif_discord as vd
        salon = str(tk._fiche(gid, uid).get("salon") or "")
    except Exception as e:                                   # noqa: BLE001
        print(f"[usdc] ticket de {gid}:{uid} illisible : {type(e).__name__}: {e}", flush=True)
        return ["ticket"]
    if not salon:
        return ["ticket"]
    notes: List[str] = []
    with vd.sur_serveur(gid):
        if gid in tk.USDC_RESEAUX_ICI:
            try:
                souci = tk.poser_carte_usdc(gid, uid)
            except Exception as e:                           # noqa: BLE001
                souci = f"{type(e).__name__}: {e}"
            if souci:
                print(f"[usdc] carte de {gid}:{uid} après un changement du site : {souci}", flush=True)
                notes.append("carte")
        try:
            code = tk._maj_menu_v2(gid, uid)
        except Exception as e:                               # noqa: BLE001
            print(f"[usdc] menu de {gid}:{uid} : {type(e).__name__}: {e}", flush=True)
            code = -1
        if code not in (0, 200):
            notes.append("menu")
        try:
            code, _r = tk._api_reseau("POST", f"/channels/{salon}/messages",
                                      json={"content": message(uid, adresse, reseau),
                                            "allowed_mentions": {"users": [uid]}})
        except Exception as e:                               # noqa: BLE001
            print(f"[usdc] avis à {gid}:{uid} : {type(e).__name__}: {e}", flush=True)
            code = -1
        if code not in (200, 201):
            notes.append("message")
    return notes


def enregistrer(form: Mapping[str, Any], par: str) -> Dict[str, Any]:
    """Pose l'adresse du formulaire (va, reseau, adresse) au nom du compte
    `par`. Rend {ok, erreur, va, change, notes}. Mêmes refus que la fenêtre
    💳 du ticket (suivi_va.verifier_adresse) : mauvais réseau, adresse du
    jeton USDC, Tron, .eth… Une adresse déjà en place n'est ni réécrite ni
    annoncée au VA."""
    p = va(form.get("va"))
    if p is None:
        return {"ok": False, "erreur": "VA introuvable.", "va": None}
    gid, uid = p["gid"], p["uid"]
    permis = reseaux(gid)
    reseau = str(form.get("reseau") or permis[0]).strip().lower()
    if reseau not in permis:
        return {"ok": False, "va": p,
                "erreur": f"Sur TRUST {str(p['plateforme']).upper()}, les paiements partent en USDC Solana."}
    a, err = suivi_va.verifier_adresse(form.get("adresse"), reseau)
    if err:
        return {"ok": False, "erreur": err, "va": p}
    with _VERROU:
        if suivi_va.paiements() is None:
            # fichier illisible : poser_adresse repartirait d'un fichier vide
            return {"ok": False, "va": p,
                    "erreur": "Les adresses ne sont pas lisibles (data/suivi_va.json) : rien n'a été changé."}
        avant = suivi_va.paiement_de(gid, uid)
        if avant.get("adresse") == a and avant.get("reseau") == reseau:
            return {"ok": True, "erreur": "", "va": p, "change": False, "notes": []}
        # TRUST INSTAGRAM garde son entrée sans réseau noté (l'annonce des
        # primes y reste mot pour mot celle d'avant) : vérifiée en strict
        # ci-dessus, écrite comme le fait sa fenêtre
        r = suivi_va.poser_adresse(gid, uid, a, reseau, par=f"site:{par}", strict=len(permis) > 1)
        if not r.get("ok"):
            return {"ok": False, "erreur": str(r.get("erreur") or "Adresse refusée."), "va": p}
        if suivi_va.paiement_de(gid, uid).get("adresse") != a:
            # poser_adresse ne dit rien d'une écriture refusée : on relit
            return {"ok": False, "va": p,
                    "erreur": "L'adresse n'a pas pu être écrite (data/suivi_va.json) : rien n'a été changé."}
    print(f"[usdc] adresse de {gid}:{uid} changée sur le site par {par} : "
          f"{_court(str(avant.get('adresse') or '')) or 'aucune'} -> {_court(a)} ({reseau})", flush=True)
    return {"ok": True, "erreur": "", "va": p, "change": True, "notes": suite_discord(p, a, reseau)}


def retour(res: Mapping[str, Any]) -> str:
    """Où revenir après un enregistrement : la même page, qui dit ce qui a été fait."""
    p = res["va"]
    notes = ",".join(n for n in (res.get("notes") or []) if n in NOTES)
    return (lien(p["gid"], p["uid"]) + ("&ok=1" if res.get("change") else "&ok=0")
            + (f"&n={notes}" if notes else ""))


# ─── la page ─────────────────────────────────────────────────────────────
_STYLE = """
body{max-width:640px}
.retour{display:inline-block;color:var(--faible);text-decoration:none;font-size:13px;margin:0 0 14px}
.fiche{display:flex;gap:16px;align-items:center;background:var(--carte);border:1px solid var(--bord);border-radius:12px;padding:14px;margin:0 0 16px}
.fiche svg{display:block;width:132px;height:132px;border-radius:8px;flex:none}
.fiche .r{font-weight:700;font-size:15px;margin:0 0 4px}
.fiche .a{font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;overflow-wrap:anywhere;word-break:break-all;-webkit-user-select:all;user-select:all}
.fiche .q{color:var(--faible);font-size:12px;margin-top:6px}
.modif{background:var(--carte);border:1px solid var(--bord);border-radius:12px;padding:14px;margin:0 0 16px}
.modif .lib{display:block;color:var(--faible);font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin:0 0 6px}
.modif .choix{display:flex;gap:8px;margin:0 0 14px}
.modif .choix label .lgs{margin-right:0;vertical-align:0}
.modif .choix label{display:flex;align-items:center;gap:6px;border:1px solid var(--bord);border-radius:8px;padding:7px 12px;font-weight:600;cursor:pointer}
.modif input[type=text]{width:100%;background:var(--fond);color:var(--texte);border:1px solid var(--bord);border-radius:8px;padding:10px;font:13px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;margin:0 0 14px}
.modif button{background:var(--acc);color:#1c0a02;border:0;border-radius:8px;padding:10px 18px;font:inherit;font-weight:700;cursor:pointer}
.fait{border:1px solid #4ade80;color:#4ade80;border-radius:10px;padding:8px 12px;margin:0 0 12px;font-size:13px;font-weight:600}
.note{border:1px solid var(--ambre);color:var(--ambre);border-radius:10px;padding:8px 12px;margin:0 0 12px;font-size:13px}
.err{margin:0 0 12px;font-size:13px}
.hist .h{padding:8px 0;border-top:1px solid var(--bord)}
.hist .h:first-of-type{border-top:0;padding-top:0}
.hist .h:last-child{padding-bottom:0}
.hist .a{font:11px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;overflow-wrap:anywhere;word-break:break-all}
.hist .q{color:var(--faible);font-size:12px;margin-top:2px}
@media (max-width:480px){.fiche{flex-direction:column;align-items:flex-start}}
"""


def _quand(e: Mapping[str, Any]) -> str:
    t = sv._paris(e.get("quand"))
    return t.strftime("%d/%m/%Y à %H:%M") if t else "date inconnue"


def _par(e: Mapping[str, Any], uid: str) -> str:
    """Qui a posé cette adresse : le VA (par 💳), la direction (ici), ou un
    autre compte Discord (un manager n'a pas ce bouton : à regarder)."""
    par = str(e.get("par") or "")
    if par.startswith("site:"):
        return f"la direction ({par[5:]})"
    if not par or par == str(uid):
        return "le VA"
    return f"le compte Discord {par}"


def page_html(p: Mapping[str, Any], *, erreur: str = "", saisie: Optional[Mapping[str, Any]] = None,
              fait: Any = "", notes: Any = "") -> str:
    """La page d'un VA : son adresse en place (QR, réseau, adresse entière,
    depuis quand et par qui), le formulaire, les adresses d'avant. `fait` :
    « 1 » après un changement, « 0 » si l'adresse était déjà celle-là ;
    `notes` : codes de NOTES séparés par des virgules. Tout est échappé."""
    gid, uid = str(p["gid"]), str(p["uid"])
    num = str(p.get("numero") or "")
    nom = f"{p['plateforme']} VA {num}" if num.isdigit() else f"{p['plateforme']} (sans numéro)"
    tous = suivi_va.paiements()
    e = suivi_va.paiement_de(gid, uid) if tous is not None else {}
    permis = reseaux(gid)
    if tous is None:
        fiche = ('<div class="err"><b>Adresses illisibles</b> (data/suivi_va.json). '
                 'Rien ne peut être changé ici pour le moment.</div>')
    elif not e:
        fiche = '<div class="fiche"><span class="manque"><b>à renseigner</b></span></div>'
    else:
        a = str(e["adresse"])
        try:
            import qr_code
            dessin = qr_code.svg(a)
        except Exception as ex:                              # noqa: BLE001
            print(f"[usdc] QR non dessiné : {type(ex).__name__}: {ex}", flush=True)
            dessin = ""
        fiche = (f'<div class="fiche">{dessin}<div><div class="r">{sv.logos_usdc(e.get("reseau"))}USDC · '
                 f'{_e(suivi_va.RESEAUX.get(str(e.get("reseau")), "Solana"))}</div>'
                 f'<div class="a">{_e(a)}</div>'
                 f'<div class="q">depuis le {_e(_quand(e))} · par {_e(_par(e, uid))}</div></div></div>')
    etat = ""
    if str(fait) == "1":
        etat = '<div class="fait">✅ Adresse enregistrée</div>'
    elif str(fait) == "0":
        etat = '<div class="note">C\'était déjà son adresse : rien n\'a changé.</div>'
    etat += "".join(f'<div class="note">{_e(NOTES[n])}</div>'
                    for n in str(notes or "").split(",") if n in NOTES)
    if erreur:
        etat += f'<div class="err"><b>Pas enregistré.</b> {_e(erreur)}</div>'
    saisie = saisie or {}
    choisi = str(saisie.get("reseau") or e.get("reseau") or permis[0])
    choisi = choisi if choisi in permis else permis[0]
    choix = "".join(
        f'<label><input type="radio" name="reseau" value="{_e(r)}"{" checked" if r == choisi else ""}> '
        f'<span class="lgs">{sv.logo_reseau(r)}</span>{_e(suivi_va.RESEAUX[r])}</label>' for r in permis)
    formulaire = "" if tous is None else (
        f'<form class="modif" method="post" action="{_e(CHEMIN)}" autocomplete="off">'
        f'<input type="hidden" name="va" value="{_e(gid)}:{_e(uid)}">'
        f'<span class="lib">Réseau</span><div class="choix">{choix}</div>'
        '<span class="lib">Nouvelle adresse</span>'
        f'<input type="text" name="adresse" value="{_e(saisie.get("adresse") or "")}" required maxlength="120" '
        'spellcheck="false" autocapitalize="off" autocorrect="off" aria-label="Nouvelle adresse USDC">'
        '<button type="submit">Enregistrer</button></form>')
    avant = [x for x in (e.get("avant") or []) if isinstance(x, dict) and x.get("adresse")]
    historique = ""
    if avant:
        lignes = "".join(
            f'<div class="h"><div class="a">{_e(x["adresse"])}</div>'
            f'<div class="q">{_e(suivi_va.RESEAUX.get(str(x.get("reseau")), "Solana"))} · '
            f'le {_e(_quand(x))} · par {_e(_par(x, uid))}</div></div>' for x in avant)
        historique = f'<div class="modif hist"><span class="lib">Adresses d\'avant</span>{lignes}</div>'
    corps = (f'<a class="retour" href="{_e(st.CHEMIN)}">← Tous les VA</a>'
             f'<h1>💳 Adresse USDC · {_e(nom)}</h1>'
             + (f'<p class="sous">@{_e(p["pseudo"])}</p>' if p.get("pseudo") else '<p class="sous"></p>')
             + etat + fiche + formulaire + historique)
    return f'''<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">
<meta name="color-scheme" content="dark">
<title>{_e("Adresse USDC · " + nom)}</title><style>{sv._STYLE}{_STYLE}</style></head><body>
<div class="marque">TRUST · Direction</div>
{corps}
</body></html>'''
