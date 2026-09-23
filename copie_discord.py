"""Bouton « Copier » sous un message du bot.

Sur téléphone, sélectionner une caption à la main dans Discord est pénible :
on attrape la ligne d'à côté, l'horodatage, ou rien du tout. Le bouton renvoie
le texte du message — à lui seul, et visible du seul VA qui a cliqué — dans un
bloc de code. Discord pose son propre bouton de copie sur un bloc de code :
c'est lui qui fait le travail, on ne fait que lui présenter le texte.

Le texte n'est stocké nulle part : Discord renvoie le message d'origine dans
la charge de l'interaction, on le relit de là. Rien à tenir à jour, et le
bouton continue de marcher sur un message vieux de six mois.
"""

IDENTIFIANT = "copie"
MAX = 2000


def bouton():
    """La rangée de composants à coller sous un message."""
    return [{"type": 1, "components": [
        {"type": 2, "style": 2, "label": "Copier",
         "custom_id": IDENTIFIANT, "emoji": {"name": "📋"}}]}]


def _bloc(texte: str) -> str:
    # trois accents graves dans la caption fermeraient le bloc en plein milieu :
    # on glisse une espace invisible pour que Discord ne les voie plus comme une clôture
    texte = texte.replace("```", "`​``")
    marge = MAX - len("```\n\n```")
    if len(texte) > marge:
        texte = texte[:marge - 1] + "…"
    return "```\n" + texte + "\n```"


def traiter(p):
    """Rend la réponse Discord, ou None quand ce bouton n'est pas le nôtre."""
    p = p or {}
    if p.get("type") != 3:
        return None
    if ((p.get("data") or {}).get("custom_id") or "") != IDENTIFIANT:
        return None
    texte = ((p.get("message") or {}).get("content") or "").strip()
    if not texte:
        # un message sans texte (une image seule) : le dire plutôt que rendre du vide
        return {"type": 4, "data": {"flags": 64,
                                    "content": "Ce message n'a pas de texte à copier."}}
    return {"type": 4, "data": {"flags": 64, "content": _bloc(texte)}}
