# -*- coding: utf-8 -*-
"""Inscription publique avec validation admin, pour le dashboard Youlab.

Parcours en trois écrans, dans cet ordre et pour cette raison :

    1. mail          ->  2. code reçu par mail  ->  3. nom / pseudo / mot de passe
                                                        |
                                            compte créé en ATTENTE
                                                        |
                                        l'admin valide ou refuse
                                                        |
                                              le compte devient actif

Instagram met le code en dernier ; ici il vient en deuxième, et le décalage n'est
pas cosmétique. Chez eux le code ACTIVE le compte. Ici le compte n'est pas actif
après le code — c'est l'admin qui l'active — donc le code sert à autre chose : il
garantit que ce qui atterrit dans la file d'attente est joignable. Autant le
vérifier avant de faire remplir trois champs de plus, sinon on découvre à la fin
que l'adresse est bidon et on a fait remplir le formulaire pour rien.

Ce module ne s'installe pas tout seul : `register(app, deps)` reçoit du fichier
principal les fonctions dont il a besoin (hachage, chargement des comptes, garde
d'authentification). C'est ce qui évite l'import circulaire, et c'est aussi ce qui
rend ce fichier lisible seul — tout ce qu'il touche du reste du site est déclaré
en haut de `register`.

Le service signup-shield est OPTIONNEL. Sans lui le parcours fonctionne
exactement pareil, simplement personne ne calcule de score et l'admin voit tout
sans hiérarchie. Avec lui, chaque inscription arrive avec un score et la liste
des signaux qui l'ont produit, et la file d'attente se trie par ce qui mérite un
regard. Le brancher est le point 5 ; le parcours est le point 4, et un parcours
qui dépend d'un service tiers pour simplement s'afficher est un parcours qu'on ne
peut pas déboguer.
"""

import json
import logging
import os
import re
import secrets
import threading
import time
from html import escape as _esc
from pathlib import Path

log = logging.getLogger("vabot.signup")

DATA_DIR = Path("data")
PENDING_FILE = DATA_DIR / "pending_signups.json"
CODES_FILE = DATA_DIR / "signup_codes.json"

# --- Réglages -----------------------------------------------------------------
CODE_LENGTH = 6
CODE_TTL_S = 15 * 60
CODE_MAX_ATTEMPTS = 5
CODE_RESEND_INTERVAL_S = 60
CODE_MAX_SENDS = 3

# Plafond par IP sur le DÉMARRAGE d'une inscription. C'est la route qui écrit un
# enregistrement et envoie un mail : sans plafond, une boucle la transforme en
# générateur de messages sortants pointé sur l'adresse de son choix, et le coût
# est payé par quelqu'un qui n'a rien demandé.
START_MAX_PER_IP = 5
START_WINDOW_S = 3600

USERNAME_RE = re.compile(r"^[a-z0-9._]{3,30}$")
# Volontairement permissif. Une expression rationnelle stricte pour les adresses
# mail rejette des adresses valides (apostrophes, nouveaux TLD, unicode) et
# n'attrape rien qu'un envoi réel n'attrape mieux : la vraie validation, c'est
# que le code arrive.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")

MIN_PASSWORD_LENGTH = 8

_LOCK = threading.RLock()
_START_HITS = {}


# ==============================================================================
# Stockage
# ==============================================================================


def _read_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("lecture de %s impossible : %s", path, e)
    return default


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_pending() -> dict:
    return _read_json(PENDING_FILE, {})


def save_pending(rows: dict):
    _write_json(PENDING_FILE, rows)


def _load_codes() -> dict:
    return _read_json(CODES_FILE, {})


def _save_codes(rows: dict):
    _write_json(CODES_FILE, rows)


def _purge_codes(rows: dict, now: float) -> dict:
    """Retire les codes périmés depuis plus d'une heure.

    La fenêtre de renvoi survit à l'expiration du code : sans ça, attendre que le
    code meure remet le budget d'envois à zéro, et le budget est justement ce qui
    coûte des adresses à un attaquant.
    """
    return {
        k: v for k, v in rows.items()
        if now - float(v.get("first_send", 0)) < 3600
    }


# ==============================================================================
# Envoi du mail
# ==============================================================================


def _send_via_smtp(to_addr: str, code: str) -> None:
    import smtplib
    from email.message import EmailMessage

    host = os.environ.get("SIGNUP_SMTP_HOST", "")
    port = int(os.environ.get("SIGNUP_SMTP_PORT", "587"))
    user = os.environ.get("SIGNUP_SMTP_USER", "")
    pwd = os.environ.get("SIGNUP_SMTP_PASSWORD", "")
    sender = os.environ.get("SIGNUP_MAIL_FROM", user or "no-reply@youl4b.com")
    if not host:
        raise RuntimeError("SIGNUP_SMTP_HOST n'est pas défini")

    msg = EmailMessage()
    msg["Subject"] = f"{code} — ton code Youlab"
    msg["From"] = sender
    msg["To"] = to_addr
    msg.set_content(
        f"Ton code de vérification Youlab : {code}\n\n"
        f"Il expire dans {CODE_TTL_S // 60} minutes.\n"
        "Si tu n'as rien demandé, ignore ce message."
    )

    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.starttls()
        if user:
            smtp.login(user, pwd)
        smtp.send_message(msg)


def send_code_mail(to_addr: str, code: str) -> None:
    """Achemine le code, selon SIGNUP_MAIL_MODE.

    Deux modes seulement, et le défaut est le mode de développement qui ÉCRIT le
    code dans le journal. C'est délibérément bruyant : un mode par défaut qui ne
    fait rien silencieusement produit un formulaire où l'on saisit un code que
    rien n'a jamais envoyé, et ça se diagnostique très mal.
    """
    mode = os.environ.get("SIGNUP_MAIL_MODE", "log").strip().lower()
    if mode == "smtp":
        _send_via_smtp(to_addr, code)
        log.info("code d'inscription envoyé à %s", to_addr)
        return
    log.warning(
        "SIGNUP_MAIL_MODE=log : le code %s pour %s est écrit dans le journal et "
        "N'A PAS été envoyé. Passe à SIGNUP_MAIL_MODE=smtp avant d'ouvrir au public.",
        code, to_addr,
    )


# ==============================================================================
# Gabarits
# ==============================================================================


_PAGE = """<!doctype html><html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Youlab</title>
<style>
/* Valeurs relevees au pixel sur une capture de l'app Instagram (iPhone X,
   1125x2436 px = 375x812 points @3x), pas estimees a l'oeil :

     bouton         hauteur 44pt, largeur 344pt, marge laterale 16pt
     rayon          22pt, soit la moitie de la hauteur -> pilule
     ecart          13pt entre les deux boutons
     bas d'ecran    84pt sous le second bouton (marque + barre d'accueil)
     bleu plein     #0064df       gris clair  #f2f5f6
     texte fonce    #27292c       fond        #ffffff

   44pt n'est pas un choix esthetique : c'est la cible tactile minimale d'Apple.
   Un bouton plus court se rate au pouce, et c'est le genre de detail qu'on copie
   sans savoir qu'on copie une contrainte. */
:root{{
  --bleu:#0064df; --bleu-actif:#0055bd;
  --gris:#f2f5f6; --gris-actif:#e6eaec;
  --fond:#ffffff; --texte:#27292c; --texte-doux:#737b85; --bord:#dfe3e7;
  --marge:16px; --h-bouton:44px; --ecart:13px;
}}
*{{box-sizing:border-box}}
body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:var(--fond);color:var(--texte);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;padding:24px}}
.card{{width:100%;max-width:375px;padding:0 var(--marge)}}
.logo{{font-size:26px;font-weight:800;letter-spacing:-.5px;text-align:center;margin:0 0 6px;
color:var(--bleu)}}
.sub{{text-align:center;color:var(--texte-doux);font-size:14px;margin:0 0 22px}}
.step{{text-align:center;color:var(--texte-doux);font-size:11px;letter-spacing:1px;
text-transform:uppercase;margin:0 0 20px}}
label{{display:block;font-size:12px;color:var(--texte-doux);margin:0 0 6px}}
input{{width:100%;height:var(--h-bouton);padding:0 14px;margin:0 0 var(--ecart);
background:var(--gris);border:1px solid transparent;border-radius:12px;
color:var(--texte);font-size:15px;outline:none}}
input:focus{{border-color:var(--bord);background:#fff}}
button{{width:100%;height:var(--h-bouton);background:var(--bleu);border:0;
border-radius:calc(var(--h-bouton) / 2);color:#fff;font-size:15px;font-weight:600;
cursor:pointer;font-family:inherit}}
button:hover{{background:var(--bleu-actif)}}
button:disabled{{background:var(--gris);color:var(--texte-doux);cursor:not-allowed}}
button.secondary{{background:var(--gris);color:var(--texte)}}
button.secondary:hover{{background:var(--gris-actif)}}
button.discret{{background:transparent;color:var(--bleu);font-weight:500}}
button.discret:hover{{background:var(--gris)}}
.err{{background:#fdeced;color:#c02b34;padding:11px 14px;border-radius:12px;
font-size:13px;margin:0 0 16px}}
.ok{{background:#e9f7ee;color:#1a7f43;padding:11px 14px;border-radius:12px;
font-size:13px;margin:0 0 16px}}
.hint{{color:var(--texte-doux);font-size:12px;margin:-6px 0 16px}}
.foot{{text-align:center;font-size:13px;color:var(--texte-doux);margin:20px 0 0}}
.foot a{{color:var(--bleu);text-decoration:none}}
.code-input{{letter-spacing:10px;text-align:center;font-size:22px;font-weight:600}}
.hp{{position:absolute;left:-9999px;width:1px;height:1px;opacity:0}}
/* Accueil. Rythme vertical releve au pixel sur leur ecran :
     titre      hauteur de capitale 17,3pt  -> police 24px
     sous-titre 16px, interligne 24px
     titre -> sous-titre        13pt
     sous-titre -> 1er bouton   70pt
   Le sous-titre est en TEXTE PLEIN, pas en gris clair : il porte la phrase qui
   dit a quoi sert le site, et l'eclaircir pour faire joli la rend illisible en
   plein soleil -- c'est-a-dire exactement la ou un telephone est utilise. */
.title{{font-size:24px;line-height:1.2;font-weight:600;letter-spacing:-.2px;
text-align:center;margin:0 0 13px}}
.tagline{{text-align:center;color:var(--texte);font-size:16px;line-height:24px;
margin:0 0 70px}}
.btn-link{{display:block;text-decoration:none}}
.btn-link + .btn-link{{margin-top:var(--ecart)}}
.brand{{text-align:center;color:var(--texte-doux);font-size:13px;font-weight:600;
margin:24px 0 0}}
/* Sur un telephone : le titre se centre dans l'espace libre et les boutons
   descendent au ras du bas, a 84pt du bord comme sur leur ecran. C'est la zone
   que le pouce atteint sans changer de prise. Au-dessus de cette taille, carte
   centree -- ce qu'on attend d'un formulaire sur un ordinateur. */
@media (max-height:820px) and (max-width:560px){{
  body{{align-items:stretch;padding:0}}
  .card{{max-width:none;min-height:100vh;display:flex;flex-direction:column;
  padding:24px var(--marge) calc(50px + env(safe-area-inset-bottom))}}
  .welcome-top{{flex:1;display:flex;flex-direction:column;justify-content:center}}
  /* La marge de 70px vit deja sur .tagline ; en mode plein ecran c'est le
     centrage qui distribue le reste, exactement comme leur illustration mange
     le haut de l'ecran chez eux. */
  .welcome-top .tagline{{margin-bottom:0}}
}}
</style></head><body><div class="card">
{body}
</div></body></html>"""


def _page(title, body):
    return _PAGE.format(title=_esc(title), body=body)


def _alert(msg, kind="err"):
    return f'<div class="{kind}">{_esc(msg)}</div>' if msg else ""


# ==============================================================================
# Langues
# ==============================================================================

#: Deux langues, une seule table. Le reste du dashboard est en francais parce
#: qu'il est utilise par une equipe ; une page d'inscription publique, elle, est
#: lue par des gens dont on ne sait rien -- y compris la langue.
#:
#: Table plate plutot qu'un fichier de traduction : deux langues et une trentaine
#: de chaines ne justifient pas une dependance, et une chaine manquante doit etre
#: une erreur visible tout de suite, pas un fallback silencieux decouvert en
#: production sur la seule page que voient les inconnus.
TEXTES = {
    "fr": {
        "code": "fr",
        "autre_langue": "en",
        "autre_langue_nom": "English",
        "bienvenue_titre": "Bienvenue",
        "titre": "Rejoins Youlab",
        "tagline": "Tout ton travail au même endroit, avec les gens qui bossent dessus.",
        "commencer": "Commencer",
        "deja_compte": "J'ai déjà un compte",
        "inscription": "Inscription",
        "cree_ton_compte": "Crée ton compte",
        "etape": "Étape {n} sur 3",
        "email_label": "Adresse e-mail",
        "email_placeholder": "toi@exemple.com",
        "continuer": "Continuer",
        "verification": "Vérification",
        "code_envoye": "On a envoyé un code à",
        "code_label": "Code de vérification",
        "verifier": "Vérifier",
        "renvoyer": "Renvoyer le code",
        "changer_adresse": "Changer d'adresse",
        "ton_profil": "Ton profil",
        "adresse_confirmee": "Adresse confirmée. Plus que ton profil.",
        "nom_label": "Nom complet",
        "pseudo_label": "Nom d'utilisateur",
        "pseudo_aide": "3 à 30 caractères : lettres, chiffres, point, tiret bas.",
        "mdp_label": "Mot de passe",
        "mdp_aide": "{n} caractères minimum.",
        "creer_compte": "Créer mon compte",
        "en_attente_titre": "Compte en attente",
        "enregistre": "C'est enregistré.",
        "en_attente_corps": (
            "Ton compte est <b>en attente de validation</b>. Un administrateur le "
            "vérifie, et tu recevras un message à <b>{email}</b> dès qu'il est actif."
        ),
        "retour_connexion": "Retour à la connexion",
        "ton_adresse": "ton adresse",
        "err_email": "Cette adresse ne ressemble pas à une adresse e-mail.",
        "err_email_pris": "Une inscription existe déjà avec cette adresse.",
        "err_trop_ip": "Trop d'inscriptions depuis cette connexion. Réessaie plus tard.",
        "err_envoi": "L'envoi du mail a échoué. Réessaie dans un instant.",
        "err_attendre": "Patiente {n} seconde(s) avant de redemander un code.",
        "err_trop_codes": "Trop de codes demandés. Réessaie dans une heure.",
        "err_pas_de_code": "Aucun code en cours. Redemande-en un.",
        "err_code_expire": "Le code a expiré. Redemande-en un.",
        "err_trop_essais": "Trop d'essais. Redemande un code.",
        "err_code_faux": "Code incorrect. {n} essai(s) restant(s).",
        "note_renvoye": "Nouveau code envoyé.",
        "err_nom": "Indique ton nom complet.",
        "err_pseudo": (
            "Nom d'utilisateur invalide : 3 à 30 caractères, lettres, chiffres, "
            "point ou tiret bas."
        ),
        "err_mdp": "Mot de passe trop court ({n} caractères minimum).",
        "err_pseudo_pris": "Ce nom d'utilisateur est déjà pris.",
    },
    "en": {
        "code": "en",
        "autre_langue": "fr",
        "autre_langue_nom": "Français",
        "bienvenue_titre": "Welcome",
        "titre": "Join Youlab",
        "tagline": "All your work in one place, with the people who work on it.",
        "commencer": "Get started",
        "deja_compte": "I already have an account",
        "inscription": "Sign up",
        "cree_ton_compte": "Create your account",
        "etape": "Step {n} of 3",
        "email_label": "Email address",
        "email_placeholder": "you@example.com",
        "continuer": "Continue",
        "verification": "Verification",
        "code_envoye": "We sent a code to",
        "code_label": "Verification code",
        "verifier": "Verify",
        "renvoyer": "Resend code",
        "changer_adresse": "Use a different address",
        "ton_profil": "Your profile",
        "adresse_confirmee": "Address confirmed. Just your profile left.",
        "nom_label": "Full name",
        "pseudo_label": "Username",
        "pseudo_aide": "3 to 30 characters: letters, numbers, dot, underscore.",
        "mdp_label": "Password",
        "mdp_aide": "{n} characters minimum.",
        "creer_compte": "Create my account",
        "en_attente_titre": "Account pending",
        "enregistre": "You're all set.",
        "en_attente_corps": (
            "Your account is <b>waiting for approval</b>. An administrator is "
            "reviewing it, and you'll get a message at <b>{email}</b> as soon as "
            "it's active."
        ),
        "retour_connexion": "Back to sign in",
        "ton_adresse": "your address",
        "err_email": "That doesn't look like an email address.",
        "err_email_pris": "There's already a signup with this address.",
        "err_trop_ip": "Too many signups from this connection. Try again later.",
        "err_envoi": "We couldn't send the email. Try again in a moment.",
        "err_attendre": "Wait {n} second(s) before asking for another code.",
        "err_trop_codes": "Too many codes requested. Try again in an hour.",
        "err_pas_de_code": "No code is pending. Request a new one.",
        "err_code_expire": "The code has expired. Request a new one.",
        "err_trop_essais": "Too many attempts. Request a new code.",
        "err_code_faux": "Wrong code. {n} attempt(s) left.",
        "note_renvoye": "New code sent.",
        "err_nom": "Please enter your full name.",
        "err_pseudo": (
            "Invalid username: 3 to 30 characters, letters, numbers, dot or "
            "underscore."
        ),
        "err_mdp": "Password too short ({n} characters minimum).",
        "err_pseudo_pris": "That username is already taken.",
    },
}

#: L'inscription publique sert d'abord un public international ; le dashboard
#: derriere reste en francais pour l'equipe. Les deux tables existent, seul le
#: defaut change -- basculer se fait ici, ou par `?lang=` sur n'importe quel ecran.
LANGUE_DEFAUT = "en"


def textes(lang=None):
    """Table de chaines pour `lang`, francais par defaut."""
    return TEXTES.get((lang or "").lower(), TEXTES[LANGUE_DEFAUT])


def langue_depuis_entete(entete: str) -> str:
    """Devine la langue depuis un en-tete `Accept-Language`.

    Lecture volontairement grossiere : on cherche la premiere etiquette connue,
    sans traiter les facteurs de qualite. Un choix explicite via `?lang=` prime
    toujours, et c'est lui qui compte -- deviner ne sert qu'a offrir un premier
    affichage plausible a quelqu'un qui n'a encore rien demande.
    """
    for morceau in (entete or "").lower().replace(";", ",").split(","):
        etiquette = morceau.strip()[:2]
        if etiquette in TEXTES:
            return etiquette
    return LANGUE_DEFAUT


def _bascule_langue(t) -> str:
    """Le petit lien qui change de langue, en bas de chaque ecran."""
    return (
        f'<p class="foot"><a href="?lang={t["autre_langue"]}">'
        f'{_esc(t["autre_langue_nom"])}</a></p>'
    )


def _welcome(lang=None):
    """Écran d'accueil : les deux portes, avant tout formulaire.

    Relevé sur l'app Instagram (« Join Instagram » / `Get started` / `I already
    have a profile`). Ce qui vaut d'être copié n'est pas le style mais le fait que
    les deux chemins soient des BOUTONS de même largeur, l'un plein et l'autre
    clair — pas un bouton et un petit lien en bas de page.

    La différence n'est pas cosmétique. Un visiteur qui a déjà un compte et qui ne
    trouve pas « se connecter » ne repart pas : il crée un deuxième compte. Ça
    remplit la file d'attente admin de doublons qui ressemblent, signal pour
    signal, à ce qu'on cherche justement à filtrer — même appareil, adresses
    proches, à quelques minutes d'intervalle. Rendre la connexion évidente est
    autant une mesure anti-abus qu'un confort.
    """
    t = textes(lang)
    return _page(t["bienvenue_titre"], f"""
<div class="welcome-top">
  <h2 class="title">{_esc(t["titre"])}</h2>
  <p class="tagline">{_esc(t["tagline"])}</p>
</div>
<a href="/signup?lang={t["code"]}" class="btn-link">
  <button type="button">{_esc(t["commencer"])}</button>
</a>
<a href="/" class="btn-link">
  <button type="button" class="secondary">{_esc(t["deja_compte"])}</button>
</a>
<p class="brand">Youlab</p>
{_bascule_langue(t)}""")


def _step1(err="", email="", lang=None):
    t = textes(lang)
    return _page(t["inscription"], f"""
<h1 class="logo">Youlab</h1>
<p class="sub">{_esc(t["cree_ton_compte"])}</p>
<p class="step">{_esc(t["etape"].format(n=1))}</p>
{_alert(err)}
<form method="post" action="/signup/email" id="f">
  <input type="hidden" name="lang" value="{t["code"]}">
  <label for="email">{_esc(t["email_label"])}</label>
  <input type="email" id="email" name="email" value="{_esc(email)}" required autofocus
         autocomplete="email" placeholder="{_esc(t["email_placeholder"])}">
  <!-- Champ leurre : invisible pour une personne, rempli par ce qui ne lit pas le CSS. -->
  <input class="hp" type="text" name="company_website" tabindex="-1" autocomplete="off">
  <input type="hidden" name="fill_ms" id="fill_ms" value="">
  <button type="submit">{_esc(t["continuer"])}</button>
</form>
<a href="/" class="btn-link" style="margin-top:13px">
  <button type="button" class="secondary">{_esc(t["deja_compte"])}</button>
</a>
{_bascule_langue(t)}
<script>
  var t0 = Date.now();
  document.getElementById('f').addEventListener('submit', function () {{
    document.getElementById('fill_ms').value = String(Date.now() - t0);
  }});
</script>""")


def _step2(email, err="", note="", lang=None):
    t = textes(lang)
    return _page(t["verification"], f"""
<h1 class="logo">Youlab</h1>
<p class="sub">{_esc(t["code_envoye"])}<br><b>{_esc(email)}</b></p>
<p class="step">{_esc(t["etape"].format(n=2))}</p>
{_alert(err)}{_alert(note, "ok")}
<form method="post" action="/signup/code">
  <label for="code">{_esc(t["code_label"])}</label>
  <input class="code-input" type="text" id="code" name="code" required autofocus
         inputmode="numeric" pattern="[0-9]*" maxlength="{CODE_LENGTH}"
         autocomplete="one-time-code">
  <button type="submit">{_esc(t["verifier"])}</button>
</form>
<form method="post" action="/signup/resend" style="margin-top:13px">
  <button type="submit" class="discret">{_esc(t["renvoyer"])}</button>
</form>
<p class="foot"><a href="/signup">{_esc(t["changer_adresse"])}</a></p>""")


def _step3(err="", name="", username="", lang=None):
    t = textes(lang)
    return _page(t["ton_profil"], f"""
<h1 class="logo">Youlab</h1>
<p class="sub">{_esc(t["adresse_confirmee"])}</p>
<p class="step">{_esc(t["etape"].format(n=3))}</p>
{_alert(err)}
<form method="post" action="/signup/profile">
  <label for="name">{_esc(t["nom_label"])}</label>
  <input type="text" id="name" name="name" value="{_esc(name)}" required autofocus
         maxlength="60" autocomplete="name">
  <label for="username">{_esc(t["pseudo_label"])}</label>
  <input type="text" id="username" name="username" value="{_esc(username)}" required
         maxlength="30" autocomplete="username" pattern="[a-zA-Z0-9._]{{3,30}}">
  <p class="hint">{_esc(t["pseudo_aide"])}</p>
  <label for="password">{_esc(t["mdp_label"])}</label>
  <input type="password" id="password" name="password" required
         minlength="{MIN_PASSWORD_LENGTH}" autocomplete="new-password">
  <p class="hint">{_esc(t["mdp_aide"].format(n=MIN_PASSWORD_LENGTH))}</p>
  <button type="submit">{_esc(t["creer_compte"])}</button>
</form>""")


def _done(email, lang=None):
    t = textes(lang)
    return _page(t["en_attente_titre"], f"""
<h1 class="logo">Youlab</h1>
<p class="sub">{_esc(t["enregistre"])}</p>
<div class="ok" style="margin-top:18px">
  {t["en_attente_corps"].format(email=_esc(email))}
</div>
<p class="foot"><a href="/">{_esc(t["retour_connexion"])}</a></p>""")


# ==============================================================================
# Score (optionnel)
# ==============================================================================


def evaluate_risk(payload: dict) -> dict:
    """Interroge signup-shield si SIGNUPSHIELD_URL est défini.

    Échoue OUVERT et le dit. Ce service est un tri, pas une porte : s'il est
    injoignable, l'inscription doit continuer et arriver dans la file d'attente
    sans score. Un service de scoring en panne ne doit pas devenir une panne
    d'inscription — et de toute façon, ici, l'admin valide tout à la main.
    """
    base = os.environ.get("SIGNUPSHIELD_URL", "").strip().rstrip("/")
    if not base:
        return {}
    try:
        import requests
        headers = {"Content-Type": "application/json"}
        key = os.environ.get("SIGNUPSHIELD_API_KEY", "").strip()
        if key:
            headers["X-API-Key"] = key
        r = requests.post(
            f"{base}/v1/evaluate", json=payload, headers=headers, timeout=3
        )
        r.raise_for_status()
        body = r.json()
        return {
            "score": body.get("score"),
            "decision": body.get("decision"),
            "signals": body.get("signals") or [],
            "explain": body.get("explain") or "",
            "degraded": bool(body.get("degraded")),
        }
    except Exception as e:
        log.warning("signup-shield injoignable, inscription non scorée : %s", e)
        return {"error": str(e)[:200]}


# ==============================================================================
# Installation des routes
# ==============================================================================


def register(app, deps):
    """Branche le parcours public et l'écran d'administration sur `app`.

    `deps` doit fournir :
        hash_password(str) -> str        empreinte salée (scrypt côté web_upload)
        load_web_users() / save_web_users(dict)
        load_role_users() / save_role_users(list)
        is_auth() -> bool                session admin valide
        live_role() -> str               rôle de la session courante
    """
    from flask import request, session, redirect

    hash_password = deps["hash_password"]
    load_web_users = deps["load_web_users"]
    save_web_users = deps["save_web_users"]
    load_role_users = deps["load_role_users"]
    save_role_users = deps["save_role_users"]
    is_auth = deps["is_auth"]
    live_role = deps.get("live_role") or (lambda: "admin")

    def _ip() -> str:
        fwd = (request.headers.get("CF-Connecting-IP")
               or request.headers.get("X-Forwarded-For") or "")
        return (fwd.split(",")[0].strip() or request.remote_addr or "?")[:45]

    def _lang() -> str:
        """Langue de l'ecran courant, par ordre de priorite decroissante.

        Un choix explicite (`?lang=en`, ou le champ cache d'un formulaire) est
        memorise en session : sans ca, quelqu'un qui bascule en anglais a l'ecran 1
        se retrouve en francais a l'ecran 2, et recommence a chaque etape. Faute de
        choix, on devine depuis l'en-tete du navigateur -- ce qui n'est qu'une
        premiere proposition, jamais une decision.
        """
        demande = (request.values.get("lang") or "").strip().lower()
        if demande in TEXTES:
            session["signup_lang"] = demande
            return demande
        memorise = session.get("signup_lang")
        if memorise in TEXTES:
            return memorise
        return langue_depuis_entete(request.headers.get("Accept-Language", ""))

    def _start_allowed() -> bool:
        now = time.time()
        with _LOCK:
            hits = [t for t in _START_HITS.get(_ip(), []) if now - t < START_WINDOW_S]
            if len(hits) >= START_MAX_PER_IP:
                _START_HITS[_ip()] = hits
                return False
            hits.append(now)
            _START_HITS[_ip()] = hits
            return True

    def _username_taken(username: str) -> bool:
        """Vrai si le pseudo est pris — comptes actifs OU en attente.

        Les trois sources comptent. Ignorer la file d'attente laisserait deux
        personnes réserver le même pseudo, et la deuxième validation écraserait
        silencieusement le compte de la première.
        """
        u = username.lower()
        if u in {k.lower() for k in load_web_users()}:
            return True
        if any((r.get("username") or "").lower() == u for r in load_role_users()):
            return True
        return any(
            (row.get("username") or "").lower() == u and row.get("status") == "pending"
            for row in load_pending().values()
        )

    def _email_taken(email: str) -> bool:
        e = email.lower()
        return any(
            (row.get("email") or "").lower() == e and row.get("status") in ("pending", "approved")
            for row in load_pending().values()
        )

    def _issue_code(signup_id: str, email: str) -> tuple[bool, str]:
        """Génère, stocke et envoie un code. Renvoie (envoyé, message).

        Le code vit côté serveur, jamais dans la session. Les sessions Flask sont
        SIGNÉES mais pas CHIFFRÉES : leur contenu est lisible en base64 par qui
        détient le cookie. Un code de six chiffres posé là serait affiché au
        candidat, et son empreinte s'y casserait en une seconde par force brute
        sur un million de valeurs.
        """
        now = time.time()
        with _LOCK:
            rows = _purge_codes(_load_codes(), now)
            rec = rows.get(signup_id, {})
            sends = int(rec.get("sends", 0))
            last = float(rec.get("last_send", 0))

            if sends and now - last < CODE_RESEND_INTERVAL_S:
                left = int(CODE_RESEND_INTERVAL_S - (now - last))
                return False, "err_attendre", left
            if sends >= CODE_MAX_SENDS:
                return False, "err_trop_codes", 0

            code = "".join(secrets.choice("0123456789") for _ in range(CODE_LENGTH))
            rows[signup_id] = {
                "email": email,
                "code": code,
                "attempts": 0,
                "sends": sends + 1,
                "last_send": now,
                "first_send": rec.get("first_send", now),
                "expires_at": now + CODE_TTL_S,
            }
            _save_codes(rows)

        try:
            send_code_mail(email, code)
        except Exception as e:
            log.error("envoi du code à %s impossible : %s", email, e)
            return False, "err_envoi", 0
        return True, "", 0

    def _check_code(signup_id: str, supplied: str) -> tuple[bool, str, int]:
        import hmac as _hmac_cc
        now = time.time()
        with _LOCK:
            rows = _load_codes()
            rec = rows.get(signup_id)
            if not rec:
                return False, "err_pas_de_code", 0
            if now > float(rec.get("expires_at", 0)):
                rows.pop(signup_id, None)
                _save_codes(rows)
                return False, "err_code_expire", 0

            # On incrémente AVANT de comparer : le chemin qui réussit ne doit pas
            # être le seul à ne pas toucher au compteur, sinon c'est celui-là que
            # les tentatives automatiques emprunteront.
            attempts = int(rec.get("attempts", 0)) + 1
            rec["attempts"] = attempts
            if attempts > CODE_MAX_ATTEMPTS:
                rows.pop(signup_id, None)
                _save_codes(rows)
                return False, "err_trop_essais", 0
            rows[signup_id] = rec
            _save_codes(rows)

            ok = _hmac_cc.compare_digest(
                str(rec.get("code", "")), (supplied or "").strip()
            )
            if not ok:
                if attempts >= CODE_MAX_ATTEMPTS:
                    rows.pop(signup_id, None)
                    _save_codes(rows)
                left = max(0, CODE_MAX_ATTEMPTS - attempts)
                return False, "err_code_faux", left

            rows.pop(signup_id, None)   # à usage unique
            _save_codes(rows)
            return True, "", 0

    def _msg(t, cle: str, n: int = 0) -> str:
        """Rend une cle d'erreur dans la langue courante.

        Les fonctions internes renvoient une CLE, jamais une phrase : elles sont
        appelees depuis des routes qui ne connaissent la langue qu'au dernier
        moment, et une phrase francaise remontee jusqu'a un formulaire anglais est
        plus deroutante que pas de traduction du tout.
        """
        if not cle:
            return ""
        modele = t.get(cle, cle)
        return modele.format(n=n) if "{n}" in modele else modele

    # -- Étape 1 : adresse ------------------------------------------------------

    @app.route("/bienvenue", methods=["GET"])
    def signup_welcome():
        """Écran d'accueil à deux portes.

        Route séparée plutôt qu'un remplacement de `/` : `/` sert aujourd'hui le
        formulaire de connexion et tout le dashboard derrière, et le détourner
        depuis ce module changerait le comportement du site pour tous ceux qui y
        sont déjà connectés. Ce que ce module fait, il le fait sur ses propres
        routes ; brancher `/` dessus est une décision d'exploitation, pas un effet
        de bord d'un import.
        """
        return _welcome(lang=_lang())

    @app.route("/signup", methods=["GET"])
    def signup_start():
        return _step1(lang=_lang())

    @app.route("/signup/email", methods=["POST"])
    def signup_email():
        lang = _lang()
        t = textes(lang)
        email = (request.form.get("email") or "").strip().lower()
        honeypot = (request.form.get("company_website") or "").strip()
        fill_ms = (request.form.get("fill_ms") or "").strip()

        # Le leurre n'annonce jamais qu'il a servi : on rend l'écran suivant comme
        # si tout allait bien, sans rien envoyer ni rien enregistrer. Dire « champ
        # invalide » apprend au script exactement quoi corriger.
        if honeypot:
            log.info("inscription ignorée (leurre rempli) depuis %s", _ip())
            return _step2(email or t["ton_adresse"], lang=lang)

        if not EMAIL_RE.match(email) or len(email) > 254:
            return _step1(t["err_email"], email, lang=lang)
        if _email_taken(email):
            return _step1(t["err_email_pris"], email, lang=lang)
        if not _start_allowed():
            return _step1(t["err_trop_ip"], lang=lang)

        signup_id = secrets.token_urlsafe(16)
        session["signup"] = {
            "id": signup_id,
            "email": email,
            "verified": False,
            "started_at": time.time(),
            "fill_ms": fill_ms,
            "ip": _ip(),
            "user_agent": (request.headers.get("User-Agent") or "")[:1024],
        }
        sent, cle, n = _issue_code(signup_id, email)
        if not sent:
            return _step1(_msg(t, cle, n), email, lang=lang)
        return _step2(email, lang=lang)

    @app.route("/signup/resend", methods=["POST"])
    def signup_resend():
        lang = _lang()
        t = textes(lang)
        state = session.get("signup") or {}
        if not state.get("id"):
            return redirect("/signup")
        sent, cle, n = _issue_code(state["id"], state["email"])
        if not sent:
            return _step2(state["email"], err=_msg(t, cle, n), lang=lang)
        return _step2(state["email"], note=t["note_renvoye"], lang=lang)

    # -- Étape 2 : code ---------------------------------------------------------

    @app.route("/signup/code", methods=["POST"])
    def signup_code():
        lang = _lang()
        t = textes(lang)
        state = session.get("signup") or {}
        if not state.get("id"):
            return redirect("/signup")
        ok, cle, n = _check_code(state["id"], request.form.get("code") or "")
        if not ok:
            return _step2(state["email"], err=_msg(t, cle, n), lang=lang)
        state["verified"] = True
        session["signup"] = state
        return _step3(lang=lang)

    # -- Étape 3 : profil -------------------------------------------------------

    @app.route("/signup/profile", methods=["POST"])
    def signup_profile():
        state = session.get("signup") or {}
        if not state.get("id") or not state.get("verified"):
            # Non vérifié : on renvoie au début plutôt que d'afficher une erreur.
            # Ce chemin n'est atteignable qu'en sautant une étape volontairement.
            return redirect("/signup")

        lang = _lang()
        t = textes(lang)
        name = (request.form.get("name") or "").strip()
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""

        if len(name) < 2 or len(name) > 60:
            return _step3(t["err_nom"], name, username, lang=lang)
        if not USERNAME_RE.match(username):
            return _step3(t["err_pseudo"], name, username, lang=lang)
        if len(password) < MIN_PASSWORD_LENGTH:
            return _step3(
                t["err_mdp"].format(n=MIN_PASSWORD_LENGTH), name, username, lang=lang)
        if _username_taken(username):
            return _step3(t["err_pseudo_pris"], name, username, lang=lang)

        risk = evaluate_risk({
            "event_id": state["id"],
            "ip": state.get("ip"),
            "user_agent": state.get("user_agent"),
            "email": state["email"],
            "username": username,
            "metadata": {
                "form": "signup-v1",
                "fill_ms": str(state.get("fill_ms") or ""),
                "email_verified": "1",
            },
        })

        with _LOCK:
            rows = load_pending()
            rows[state["id"]] = {
                "email": state["email"],
                "name": name,
                "username": username,
                "password_hash": hash_password(password),
                "created_at": int(time.time()),
                "status": "pending",
                "ip": state.get("ip"),
                "user_agent": state.get("user_agent"),
                "fill_ms": state.get("fill_ms"),
                "risk": risk,
            }
            save_pending(rows)

        log.info(
            "inscription en attente : %s (%s) score=%s",
            username, state["email"], (risk or {}).get("score", "n/a"),
        )
        email = state["email"]
        session.pop("signup", None)
        return _done(email, lang=lang)

    # -- Administration ---------------------------------------------------------

    def _admin_ok() -> bool:
        return bool(is_auth()) and (live_role() or "").lower() == "admin"

    @app.route("/admin/pending", methods=["GET"])
    def admin_pending():
        if not _admin_ok():
            return redirect("/")
        rows = load_pending()
        waiting = sorted(
            ((k, v) for k, v in rows.items() if v.get("status") == "pending"),
            key=lambda kv: -(_score_of(kv[1])),
        )
        return _render_pending(waiting)

    def _score_of(row) -> float:
        try:
            return float((row.get("risk") or {}).get("score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _render_pending(waiting):
        if not waiting:
            body = ('<p class="sub">Aucune inscription en attente.</p>'
                    '<p class="foot"><a href="/">Retour au dashboard</a></p>')
            return _page("File d'attente", body)

        cards = []
        for key, row in waiting:
            risk = row.get("risk") or {}
            score = risk.get("score")
            signals = ", ".join(risk.get("signals") or []) or "aucun signal"
            if score is None:
                badge = '<span style="color:#5d6b8a">non scoré</span>'
            else:
                colour = "#86efac" if score < 40 else ("#fbbf24" if score < 75 else "#fca5a5")
                badge = f'<span style="color:{colour};font-weight:700">{score:.0f}/100</span>'
            when = time.strftime("%d/%m %H:%M", time.localtime(row.get("created_at", 0)))
            cards.append(f"""
<div style="background:#070c1a;border:1px solid #1c2743;border-radius:11px;padding:16px;margin:0 0 12px;text-align:left">
  <div style="display:flex;justify-content:space-between;align-items:baseline">
    <b style="font-size:16px">{_esc(row.get('username', ''))}</b>{badge}
  </div>
  <div style="color:#8494b4;font-size:13px;margin:4px 0 2px">{_esc(row.get('name', ''))}</div>
  <div style="color:#5d6b8a;font-size:12px">{_esc(row.get('email', ''))}</div>
  <div style="color:#5d6b8a;font-size:11px;margin:8px 0 0">{when} · {_esc(row.get('ip') or '?')}</div>
  <div style="color:#5d6b8a;font-size:11px;margin:2px 0 12px">{_esc(signals)}</div>
  <div style="display:flex;gap:8px">
    <form method="post" action="/admin/pending/approve" style="flex:1">
      <input type="hidden" name="id" value="{_esc(key)}">
      <button type="submit" style="padding:8px;font-size:13px">Valider</button>
    </form>
    <form method="post" action="/admin/pending/reject" style="flex:1">
      <input type="hidden" name="id" value="{_esc(key)}">
      <button type="submit" style="padding:8px;font-size:13px;background:#2a1116;color:#fca5a5">
        Refuser
      </button>
    </form>
  </div>
</div>""")

        body = (f'<p class="sub">{len(waiting)} inscription(s) en attente</p>'
                f'<p class="step">Les plus risquées en premier</p>'
                + "".join(cards)
                + '<p class="foot"><a href="/">Retour au dashboard</a></p>')
        return _PAGE.format(title="File d'attente", body=body).replace(
            "max-width:400px", "max-width:560px")

    @app.route("/admin/pending/approve", methods=["POST"])
    def admin_pending_approve():
        if not _admin_ok():
            return redirect("/")
        key = (request.form.get("id") or "").strip()
        with _LOCK:
            rows = load_pending()
            row = rows.get(key)
            if not row or row.get("status") != "pending":
                return redirect("/admin/pending")

            username = (row.get("username") or "").lower()
            # Re-vérifié au moment de valider, pas seulement à l'inscription :
            # entre les deux, quelqu'un a pu être validé avec le même pseudo, et
            # écraser un compte actif en cliquant « Valider » serait irréversible.
            if _username_taken(username):
                row["status"] = "rejected"
                row["reason"] = "nom d'utilisateur pris entre-temps"
                rows[key] = row
                save_pending(rows)
                return redirect("/admin/pending")

            web_users = load_web_users()
            web_users[username] = {
                "password_hash": row["password_hash"],
                "role": "va",
                "email": row.get("email", ""),
                "name": row.get("name", ""),
                "created_at": int(time.time()),
            }
            save_web_users(web_users)

            role_users = load_role_users()
            role_users.append({
                "username": username,
                "role": "va",
                "agency": "",
                "password_hash": row["password_hash"],
                "active": True,
                "created_at": int(time.time()),
            })
            save_role_users(role_users)

            row["status"] = "approved"
            row["approved_at"] = int(time.time())
            rows[key] = row
            save_pending(rows)

        log.info("inscription validée : %s", username)
        return redirect("/admin/pending")

    @app.route("/admin/pending/reject", methods=["POST"])
    def admin_pending_reject():
        if not _admin_ok():
            return redirect("/")
        key = (request.form.get("id") or "").strip()
        with _LOCK:
            rows = load_pending()
            row = rows.get(key)
            if row and row.get("status") == "pending":
                row["status"] = "rejected"
                row["rejected_at"] = int(time.time())
                rows[key] = row
                save_pending(rows)
        return redirect("/admin/pending")

    log.info("inscription publique branchée : /signup, file admin sur /admin/pending")
    return app
