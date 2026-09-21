"""reels_source.py — D'ou viennent les URL video des reels.

UN SEUL endroit decide quelle source interroger, au lieu de huit appels
disperses qui nommaient Apify en dur. C'est la regle du projet : quand
plusieurs endroits decident la meme chose, les fusionner — sinon un
changement de fournisseur oblige a les retrouver tous, et celui qu'on
oublie continue silencieusement sur l'ancien.

L'ORDRE, et pourquoi :

  1. HikerAPI — 0,001 $ la requete, solde PREPAYE qui n'expire jamais.
     Rend l'URL video, la legende, les vues et le proprietaire en un
     seul appel.
  2. Apify — garde en secours. Il reste utile le jour ou HikerAPI tombe
     ou que son solde s'epuise, mais il coute ~2,30 $ / 1 000 resultats,
     soit plus de deux mille fois le prix, et son quota mensuel laissait
     le parc aveugle des qu'il etait consomme.

Le repli est PAR REEL, pas par lot : si HikerAPI en resout neuf sur dix,
Apify n'est interroge que pour le dixieme. On ne repaie jamais ce qui est
deja resolu.

L'interface est exactement celle d'apify_reels : les appelants ne savent
pas quelle source a repondu, et n'ont pas a le savoir.
"""
from __future__ import annotations

from typing import Any, Dict, List


def _sources():
    """Les sources dans l'ordre de preference, celles qui sont configurees."""
    dispo = []
    try:
        import hiker_reels as _hk
        if _hk.configured():
            dispo.append(("hiker", _hk))
    except Exception:
        pass
    try:
        import apify_reels as _ap
        if _ap.configured():
            dispo.append(("apify", _ap))
    except Exception:
        pass
    return dispo


def configured() -> bool:
    """Vrai des qu'AU MOINS une source est utilisable."""
    return bool(_sources())


def fetch_video_urls(reel_urls: List[str], timeout: int = 240,
                     diag: Dict[str, Any] = None) -> Dict[str, Dict[str, Any]]:
    """Resout des liens reels en passant d'une source a l'autre.

    Rend {shortcode: {video_url, caption, likes, comments, owner, ...}},
    le meme contrat qu'apify_reels.fetch_video_urls.

    `diag` recoit en plus `source`, qui nomme la ou les sources ayant
    reellement repondu — sans lui, un diagnostic ne peut pas distinguer
    « HikerAPI a tout resolu » de « HikerAPI etait muet et Apify a
    rattrape », alors que la facture, elle, fait la difference.
    """
    liens = [u for u in (reel_urls or []) if u]
    if diag is not None:
        diag.update({"sent": len(liens), "status": None, "resolved": 0,
                     "error": "", "source": ""})
    if not liens:
        if diag is not None:
            diag["error"] = "aucun lien"
        return {}

    sources = _sources()
    if not sources:
        if diag is not None:
            diag["error"] = "aucune source configuree"
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    restants = list(liens)
    servies: List[str] = []
    erreurs: List[str] = []

    for nom, module in sources:
        if not restants:
            break
        sous_diag: Dict[str, Any] = {}
        try:
            trouve = module.fetch_video_urls(restants, timeout=timeout,
                                             diag=sous_diag) or {}
        except Exception as e:
            erreurs.append(f"{nom}: {str(e)[:70]}")
            continue
        if trouve:
            out.update(trouve)
            servies.append(f"{nom}({len(trouve)})")
        if sous_diag.get("error"):
            erreurs.append(f"{nom}: {str(sous_diag['error'])[:70]}")
        # Ne redemander que ce qui manque encore : chaque source suivante
        # est plus chere, on ne lui repasse pas ce qui est deja resolu.
        try:
            import hiker_reels as _hk
            restants = [u for u in restants if _hk.shortcode(u) not in out]
        except Exception:
            restants = [] if out else restants

    if diag is not None:
        diag["resolved"] = len(out)
        diag["source"] = " + ".join(servies)
        diag["status"] = 200 if out else 404
        # On ne masque pas les erreurs quand ca a fini par marcher : savoir
        # que la premiere source a echoue est ce qui permet de voir venir
        # une panne avant qu'elle ne soit totale.
        if erreurs:
            diag["error"] = " | ".join(erreurs)

    return out
