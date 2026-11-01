# -*- coding: utf-8 -*-
"""La version SANS TEXTE d'un montage, et ses textes à part.

POURQUOI (propriétaire, 01/11/2026)
    Pour Caption, Template, Trash et Flash : « à chaque fois qu'il envoie, tu
    envoies toujours ça à côté, et remets l'écrit séparément … comme ça le
    copier-coller est facile ». Des VA préfèrent écrire eux-mêmes leurs
    textes sur Instagram (« ça prend mieux »). Le bot livre donc UNE carte,
    la vidéo SANS le texte à gauche (« la fraîche »), la même déjà prête à
    droite, puis chaque texte seul dans son message
    (cogs/user._livrer_avec_sans_texte).

D'OÙ VIENT LA VIDÉO SANS TEXTE
    Noctus monte d'abord la vidéo dans models/<id>/input (template + brute,
    ou la brute seule pour une caption), PUIS y incruste les textes vers
    models/<id>/output. Le fichier d'entrée est le même montage, sans texte :
    aucun rendu de plus sur un serveur à deux processeurs. Vu le 01/11 sur
    le Flash de brune (brute d'ema_bb0) : même image au même instant, le
    texte du bot en moins.

CE QUI NE PART PAS
    Les textes DÉJÀ dans la vidéo d'origine (une trend, une brute TikTok)
    restent : seuls ceux du bot disparaissent.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional

#: Le moteur n'en incruste pas plus (noctus_web.build_montage_caps).
TEXTES_MAX = 40


def video_du_rendu(model_id: str) -> Optional[Path]:
    """La vidéo d'entrée du rendu `model_id` — le montage avant ses textes —,
    ou None : rendu inconnu, dossier déjà purgé (on garde les 12 derniers),
    ou plus d'une vidéo (on ne devine pas laquelle)."""
    if not model_id:
        return None
    try:
        import noctus_web
        entree = noctus_web._models_dir() / noctus_web._safe(str(model_id)) / "input"
        videos = sorted(p for p in entree.glob("*.mp4") if p.is_file() and p.stat().st_size > 0)
    except Exception:                                        # noqa: BLE001
        return None
    return videos[0] if len(videos) == 1 else None


def textes(draft: Any) -> List[str]:
    """Les textes que le bot incruste, dans l'ordre du montage, chacun une
    fois — lus comme le moteur les lit (segments, éventuellement en JSON)."""
    segments = draft.get("segments") if isinstance(draft, dict) else None
    if isinstance(segments, str):
        try:
            segments = json.loads(segments or "[]")
        except ValueError:
            segments = []
    out: List[str] = []
    for s in (segments if isinstance(segments, list) else [])[:TEXTES_MAX]:
        t = str((s or {}).get("text") or "").strip() if isinstance(s, dict) else ""
        if t and t not in out:
            out.append(t)
    return out
