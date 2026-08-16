# -*- coding: utf-8 -*-
"""Fait tourner le parcours d'inscription seul, en local, sans lancer le bot.

Sert a regarder les ecrans dans un vrai navigateur -- avec les formulaires qui
soumettent, les erreurs qui s'affichent, le code qui arrive. `web_upload.py` fait
43 000 lignes et demarre le bot Discord avec ; on ne relance pas tout ca pour
verifier une marge.

    python apercu_signup.py            # http://127.0.0.1:8899/bienvenue

Le code de verification s'affiche dans cette console, puisque SIGNUP_MAIL_MODE
vaut "log" par defaut. C'est ce qui permet d'aller jusqu'au bout du parcours sans
serveur de mail.

IMPORTANT : les comptes crees ici atterrissent dans les MEMES fichiers que le vrai
site (`data/pending_signups.json`, `data/web_admin_users.json`). Lance-le depuis un
dossier de travail separe si tu ne veux pas melanger, ou supprime les lignes de
test ensuite depuis /admin/pending.
"""

import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, redirect  # noqa: E402

import signup_public  # noqa: E402

# Un magasin de comptes en memoire : l'apercu ne doit pas pouvoir ecrire dans
# web_admin_users.json, sinon un clic sur « Valider » cree un vrai compte sur le
# vrai site depuis un outil dont le nom commence par "apercu".
_FAUX_WEB, _FAUX_ROLES = {}, []


def _faux_hash(mot_de_passe):
    """Le vrai scrypt, importe depuis web_upload si possible.

    On essaie d'abord le vrai : c'est la seule facon de verifier que la fonction
    de hachage du site fonctionne bien dans ce parcours. S'il n'est pas importable
    (il tire des dependances du bot), on retombe sur un marqueur inoffensif.
    """
    try:
        from web_upload import _hash_password
        return _hash_password(mot_de_passe)
    except Exception:
        return "apercu$" + str(len(mot_de_passe or ""))


def main():
    app = Flask(__name__)
    app.secret_key = os.urandom(24)

    signup_public.register(app, {
        "hash_password": _faux_hash,
        "load_web_users": lambda: dict(_FAUX_WEB),
        "save_web_users": lambda d: (_FAUX_WEB.clear(), _FAUX_WEB.update(d)),
        "load_role_users": lambda: list(_FAUX_ROLES),
        "save_role_users": lambda l: (_FAUX_ROLES.clear(), _FAUX_ROLES.extend(l)),
        # L'apercu est admin en permanence, pour pouvoir regarder la file d'attente.
        "is_auth": lambda: True,
        "live_role": lambda: "admin",
    })

    @app.route("/")
    def _faux_login():
        return (
            '<body style="font:15px system-ui;padding:40px;max-width:520px;margin:auto">'
            "<h2>Page de connexion (factice)</h2>"
            "<p>Sur le vrai site, c'est ici que se trouve le formulaire de connexion. "
            "Cet apercu ne sert qu'a verifier que les boutons pointent au bon endroit.</p>"
            '<p><a href="/bienvenue">&larr; Retour a l\'accueil</a> &middot; '
            '<a href="/admin/pending">File d\'attente admin</a></p></body>'
        )

    port = int(os.environ.get("APERCU_PORT", "8899"))
    print()
    print(f"  Accueil        http://127.0.0.1:{port}/bienvenue")
    print(f"  Inscription    http://127.0.0.1:{port}/signup")
    print(f"  File admin     http://127.0.0.1:{port}/admin/pending")
    print()
    print("  Le code de verification s'affiche ci-dessous au lieu d'etre envoye.")
    print("  Ctrl+C pour arreter.")
    print()
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
