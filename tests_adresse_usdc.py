"""L'adresse USDC d'un VA changée par la direction (adresse_usdc) : /trust/liens/adresse.

Propriétaire, 17/11/2026 : « son adresse modifiable que pour eux sur leur
Discord, ou par moi owner avec un mot de passe », puis « y a un accès où le
mec voit, mais moi j'ai un lien où je peux modifier, je mets mes logs ».

C'est l'adresse où part une paie : ce fichier prouve surtout QUI ne peut pas
la changer. Sans réseau et sans rien écrire dans le vrai data/ ; Discord est
simulé (les vraies carte et menu sont testés par tests_menu_v2_usdc.py).
  1. Qui : un compte du dashboard à accès complet. Sans compte, avec une clé
     de manager, avec le lien « Tes stats » d'un VA, avec un rôle restreint,
     depuis trust-ofm.com, depuis un autre site : refusé, rien n'est écrit.
  2. Quoi : les refus de la fenêtre 💳 (mauvais réseau, jeton USDC, Tron,
     .eth…), Ethereum refusé sur TRUST INSTAGRAM, un identifiant qui n'est pas
     un VA TRUST (ou un VA parti) refusé.
  3. La trace : l'adresse d'avant gardée avec qui l'avait posée, « par » le
     compte du site ; rien d'écrit ni d'annoncé si l'adresse ne change pas.
  4. Le ticket suit : carte 💳 (Twitter et Threads, pas Instagram), menu, le
     VA prévenu avec le bot de SON serveur ; ce qui rate est dit sur la page.
  5. « Modifier » ne paraît que sur la page de la direction ouverte avec un
     compte, jamais avec une clé ni sur la page d'un VA.

Lancer depuis la racine du dépôt : python tests_adresse_usdc.py
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import pathlib
import re
import sys
import tempfile

BOT = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(BOT))
os.chdir(BOT)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

OK, KO = [], []


def check(label, cond, detail=""):
    (OK if cond else KO).append(label)
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else f"  [{str(detail)[:300]}]"))


def adr_ok(page, court, reseau):
    """L'adresse courte, puis le logo USDC, le logo du BON réseau et son nom, dans cet ordre."""
    return re.search(rf'<b>{re.escape(court)}</b><span class="adrr"><span class="lgs">'
                     rf'<img src="/static/usdc/usdc\.png\?v=[0-9a-f]{{8}}" alt="USDC"[^>]*>'
                     rf'<img src="/static/usdc/{reseau.lower()}\.png\?v=[0-9a-f]{{8}}" alt=""[^>]*>'
                     rf'</span>{reseau}</span>', page) is not None


VRAIS = [BOT / "data" / n for n in ("suivi_va.json", "stats_trust_cle.json", "stats_va_cles.json", "tickets.json")]
AVANT = {str(p): (p.stat().st_mtime if p.exists() else None) for p in VRAIS}

import adresse_usdc as au       # noqa: E402
import liens_va                 # noqa: E402
import podium_discord as pod    # noqa: E402
import qr_code                  # noqa: E402
import stats_trust as st        # noqa: E402
import stats_va as sv           # noqa: E402
import suivi_va                 # noqa: E402
import tickets_discord as tk    # noqa: E402
import verif_discord as vd      # noqa: E402

TMP = pathlib.Path(tempfile.mkdtemp(prefix="adresse_usdc_"))
suivi_va.ETAT_FICHIER = TMP / "suivi_va.json"
st.CLE_FICHIER = TMP / "stats_trust_cle.json"
sv.CLES_FICHIER = TMP / "stats_va_cles.json"
JOUR = dt.date(2026, 11, 17)
pod._aujourdhui = lambda: JOUR
TW, IG, TH = sv.TWITTER_ID, sv.AGENCY_IG_ID, sv.THREADS_ID
AUTRE = "1535758943324999711"   # Youl4b (Spam) : pas un serveur TRUST
FICHES = {f"{TW}:96": {"numero": 96, "pseudo": "orphee"}, f"{TW}:3": {"numero": 14, "pseudo": "parti"},
          f"{IG}:108": {"numero": 108, "pseudo": "gamma"}, f"{TH}:163": {"numero": 163, "pseudo": "delta"},
          f"{AUTRE}:8": {"numero": 1, "pseudo": "spam_va"}}
liens_va._etat = lambda: {"liens": FICHES}
liens_va.lien_de = lambda g, u: dict(FICHES.get(f"{g}:{u}") or {})
tk.partis = lambda g: {"3": 1.0} if g == TW else {}
TICKETS = {f"{TW}:96": {"salon": "9001"}, f"{IG}:108": {"salon": "9002"}}     # le VA Threads n'a pas de ticket
tk._fiche = lambda g, u: dict(TICKETS.get(f"{g}:{u}") or {})
sv.chiffres = lambda g, u, du="", au="": {"numero": FICHES[f"{g}:{u}"]["numero"], "pseudo": FICHES[f"{g}:{u}"]["pseudo"],
                                          "gid": g, "du": du, "au": au, "subs": 1, "gagne": 1.0}

# Discord simulé : ce qui part, et avec le bot de quel serveur
DISCORD = []
REPONSES = {"carte": "", "menu": 200, "message": 200}


def _carte(g, u):
    DISCORD.append(("carte", g, u, vd.serveur_courant()))
    return REPONSES["carte"]


def _menu(g, u, *a, **k):
    DISCORD.append(("menu", g, u, vd.serveur_courant()))
    return REPONSES["menu"]


def _api(methode, chemin, **kw):
    DISCORD.append(("api", methode, chemin, vd.serveur_courant(), kw.get("json")))
    return REPONSES["message"], {"id": "777"}


tk.poser_carte_usdc, tk._maj_menu_v2, tk._api_reseau = _carte, _menu, _api

SOL = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
SOL2 = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
ETH = "0x52908400098527886E0F7030069857D2E4169EE7"
VA96, VA108, VA163 = f"{TW}:96", f"{IG}:108", f"{TH}:163"

import web_upload as wu         # noqa: E402
app = wu.create_app()
app.config["TESTING"] = True


def client(role=None, nom="admin"):
    c = app.test_client()
    if role:
        with c.session_transaction() as s:
            s["auth"], s["username"], s["role"] = True, nom, role
            if role == "owner":
                s["legacy_owner"] = True
    return c


def etat():
    return json.loads(suivi_va.ETAT_FICHIER.read_text(encoding="utf-8")) if suivi_va.ETAT_FICHIER.exists() else {}


print("1. Qui peut changer une adresse")
# le VA a donné son adresse par 💳, dans son ticket
check("le VA pose son adresse dans Discord", suivi_va.poser_adresse(TW, "96", SOL, "solana", par="96", strict=True)["ok"])
depart = etat()
anonyme = client()
r = anonyme.get(f"/trust/liens/adresse?va={VA96}")
check("sans compte : renvoi à l'accueil, rien de la page", r.status_code in (301, 302)
      and r.headers.get("Location", "").endswith("/") and SOL not in r.get_data(as_text=True), r.status_code)
r = anonyme.post("/trust/liens/adresse", data={"va": VA96, "reseau": "solana", "adresse": SOL2})
check("sans compte, POST : 403", r.status_code == 403, r.status_code)
k_mgr, k_tw = st.cle(), st.cle("tw")
for lib, k in (("clé des managers", k_mgr), ("clé Twitter", k_tw), ("lien « Tes stats » du VA", sv.jeton(TW, "96"))):
    rg = anonyme.get(f"/trust/liens/adresse?va={VA96}&k={k}&t={k}")
    rp = anonyme.post(f"/trust/liens/adresse?k={k}&t={k}",
                      data={"va": VA96, "reseau": "solana", "adresse": SOL2, "k": k, "t": k})
    check(f"{lib} : n'ouvre pas la page et ne change rien",
          rg.status_code in (301, 302) and rp.status_code == 403 and SOL not in rg.get_data(as_text=True),
          (rg.status_code, rp.status_code))
# un rôle restreint du dashboard (chatteur) : refusé, en lecture comme en écriture
import web_upload as _wu        # noqa: E402
_users = _wu._load_web_users
_wu._load_web_users = lambda: {"chat1": {"role": "chatter"}, "admin": {"role": "owner"}, "boss": {"role": "admin"}}
try:
    chatteur = client("chatter", "chat1")
    rg = chatteur.get(f"/trust/liens/adresse?va={VA96}")
    rp = chatteur.post("/trust/liens/adresse", data={"va": VA96, "reseau": "solana", "adresse": SOL2})
    check("rôle restreint du dashboard (chatteur) : 403 en lecture et en écriture",
          rg.status_code == 403 and rp.status_code == 403 and SOL not in rg.get_data(as_text=True),
          (rg.status_code, rp.status_code))
    owner = client("owner")
    r = owner.post("/trust/liens/adresse", data={"va": VA96, "reseau": "solana", "adresse": SOL2},
                   headers={"Sec-Fetch-Site": "cross-site"})
    check("formulaire envoyé depuis un autre site : 403", r.status_code == 403, r.status_code)
    rg = owner.get(f"/trust/liens/adresse?va={VA96}", headers={"Host": "trust-ofm.com"})
    rp = owner.post("/trust/liens/adresse", data={"va": VA96, "reseau": "solana", "adresse": SOL2},
                    headers={"Host": "trust-ofm.com"})
    check("trust-ofm.com ne sert pas cette page (ni en lecture ni en écriture)",
          rg.status_code == 404 and rp.status_code == 404 and SOL not in rg.get_data(as_text=True),
          (rg.status_code, rp.status_code))
    check("après tous ces refus : le fichier n'a pas bougé, Discord n'a rien reçu", etat() == depart and not DISCORD,
          DISCORD)

    r = owner.get(f"/trust/liens/adresse?va={VA96}")
    h = r.get_data(as_text=True)
    check("compte à accès complet : la page du VA, son QR, son adresse entière, posée par le VA",
          r.status_code == 200 and "Adresse USDC · Twitter VA 96" in h and "@orphee" in h and qr_code.svg(SOL) in h
          and f'<div class="a">{SOL}</div>' in h and "USDC · Solana" in h and "par le VA" in h, r.status_code)
    check("les logos : USDC et Solana devant « USDC · Solana », un logo par réseau dans le choix",
          re.search(r'<div class="r"><span class="lgs"><img src="/static/usdc/usdc\.png[^>]*><img src="/static/usdc/'
                    r'solana\.png[^>]*></span>USDC · Solana</div>', h)
          and re.findall(r'value="(\w+)"[^>]*> <span class="lgs"><img src="/static/usdc/(\w+)\.png', h)
          == [("solana", "solana"), ("ethereum", "ethereum")], h[h.find('class="fiche"'):][:300])
    check("en-têtes : no-store, noindex, no-referrer",
          "no-store" in r.headers.get("Cache-Control", "") and "noindex" in r.headers.get("X-Robots-Tag", "")
          and r.headers.get("Referrer-Policy") == "no-referrer")
    check("le formulaire : POST vers la page, les deux réseaux sur Twitter, le réseau en place coché",
          f'<form class="modif" method="post" action="/trust/liens/adresse"' in h
          and re.findall(r'name="reseau" value="(\w+)"( checked)?', h) == [("solana", " checked"), ("ethereum", "")]
          and f'name="va" value="{VA96}"' in h)
    check("aucun script, aucun mot de passe demandé ni écrit sur la page",
          "<script" not in h.lower() and 'type="password"' not in h.lower())

    print("2. Ce qui est refusé")
    for lib, donnees, mot in (
            ("adresse Ethereum donnée en Solana", {"reseau": "solana", "adresse": ETH}, "Ethereum"),
            ("adresse Solana donnée en Ethereum", {"reseau": "ethereum", "adresse": SOL2}, "Solana"),
            ("l'adresse du jeton USDC", {"reseau": "solana", "adresse": suivi_va.USDC_SOL}, "jeton USDC"),
            ("une adresse Tron", {"reseau": "solana", "adresse": "TJRabPrwbZy45sbavfcjinPJC18kjpRTv8"}, "Solana valide"),
            ("un nom .eth", {"reseau": "ethereum", "adresse": "vitalik.eth"}, ".eth"),
            ("rien", {"reseau": "solana", "adresse": ""}, "Solana valide"),
            ("un réseau inconnu", {"reseau": "tron", "adresse": SOL2}, "USDC Solana")):
        r = owner.post("/trust/liens/adresse", data=dict(donnees, va=VA96))
        b = r.get_data(as_text=True)
        check(f"{lib} : 400, dit pourquoi, la saisie gardée", r.status_code == 400 and "Pas enregistré" in b
              and mot in b and (not donnees["adresse"] or f'value="{donnees["adresse"]}"' in b), (r.status_code, mot))
    r = owner.post("/trust/liens/adresse", data={"va": VA108, "reseau": "ethereum", "adresse": ETH})
    check("TRUST INSTAGRAM : Ethereum refusé (Solana seul, comme sa fenêtre 💳)",
          r.status_code == 400 and "USDC Solana" in r.get_data(as_text=True)
          and 'value="ethereum"' not in owner.get(f"/trust/liens/adresse?va={VA108}").get_data(as_text=True))
    for lib, cle in (("un VA d'un autre serveur", f"{AUTRE}:8"), ("un VA parti", f"{TW}:3"),
                     ("un identifiant inconnu", f"{TW}:424242"), ("n'importe quoi", "../etc"), ("vide", "")):
        rg = owner.get(f"/trust/liens/adresse?va={cle}")
        rp = owner.post("/trust/liens/adresse", data={"va": cle, "reseau": "solana", "adresse": SOL2})
        check(f"{lib} : 404, rien n'est posé", rg.status_code == 404 and rp.status_code == 404,
              (rg.status_code, rp.status_code))
    hx = owner.post("/trust/liens/adresse", data={"va": VA96, "reseau": "solana",
                                                  "adresse": '"><img src=x onerror=alert(1)>'}).get_data(as_text=True)
    check("une saisie ne peut rien casser (échappée)", "<img src=x" not in hx)
    check("après tous ces refus : le fichier n'a pas bougé, Discord n'a rien reçu", etat() == depart and not DISCORD,
          DISCORD)

    print("3. Le changement, sa trace, le ticket")
    r = owner.post("/trust/liens/adresse", data={"va": VA96, "reseau": "ethereum", "adresse": ETH})
    check("adresse valide : enregistrée, retour 303 sur la page du VA",
          r.status_code == 303 and r.headers.get("Location", "").endswith(f"/trust/liens/adresse?va={TW}%3A96&ok=1"),
          (r.status_code, r.headers.get("Location")))
    e = suivi_va.paiement_de(TW, "96")
    check("l'adresse et le réseau sont ceux du formulaire, « par » le compte du site",
          e.get("adresse") == ETH and e.get("reseau") == "ethereum" and e.get("par") == "site:admin", e)
    check("l'adresse d'avant est gardée, avec qui l'avait posée (le VA)",
          [(x.get("adresse"), x.get("par")) for x in e.get("avant") or []] == [(SOL, "96")], e.get("avant"))
    check("le ticket suit, avec le bot de TRUST TWITTER : carte 💳, menu, puis le message",
          [(x[0], x[3]) for x in DISCORD] == [("carte", TW), ("menu", TW), ("api", TW)], DISCORD)
    msg = DISCORD[-1]
    check("le VA est prévenu dans SON ticket, lui seul mentionné, l'adresse courte et le réseau",
          msg[1:3] == ("POST", "/channels/9001/messages") and msg[4]["allowed_mentions"] == {"users": ["96"]}
          and msg[4]["content"] == "💳 <@96> ton adresse de paiement a été changée par la direction : "
                                   "USDC · Ethereum · `0x52…9EE7`", msg)
    h = owner.get(r.headers["Location"]).get_data(as_text=True)
    check("la page dit « Adresse enregistrée », montre la nouvelle, et l'ancienne dans « Adresses d'avant »",
          "✅ Adresse enregistrée" in h and qr_code.svg(ETH) in h and "par la direction (admin)" in h
          and "Adresses d'avant" in h
          and re.search(rf'<div class="h"><div class="a">{SOL}</div><div class="q">Solana · le [^<]* · par le VA</div>', h),
          h[-600:])
    check("la page « Tes stats » du VA montre la nouvelle adresse (lecture seule)",
          adr_ok(anonyme.get(f"/mes-stats?t={sv.jeton(TW, '96')}").get_data(as_text=True), "0x52…9EE7", "Ethereum"))
    DISCORD.clear()
    r = owner.post("/trust/liens/adresse", data={"va": VA96, "reseau": "ethereum", "adresse": ETH})
    check("la même adresse renvoyée : rien d'écrit, le VA n'est pas prévenu deux fois",
          r.status_code == 303 and r.headers["Location"].endswith("&ok=0") and not DISCORD
          and len(suivi_va.paiement_de(TW, "96").get("avant") or []) == 1
          and "déjà son adresse" in owner.get(r.headers["Location"]).get_data(as_text=True), DISCORD)
    r = owner.post("/trust/liens/adresse", data={"va": VA108, "reseau": "solana", "adresse": SOL2})
    e = suivi_va.paiement_de(IG, "108")
    check("TRUST INSTAGRAM, un VA sans adresse : posée, sans réseau noté (comme sa fenêtre), pas de carte",
          r.status_code == 303 and e.get("adresse") == SOL2 and "reseau" not in etat()["adresses"][VA108]
          and e.get("par") == "site:admin" and [(x[0], x[3]) for x in DISCORD] == [("menu", IG), ("api", IG)], DISCORD)
    DISCORD.clear()
    boss = client("admin", "boss")
    r = boss.post("/trust/liens/adresse", data={"va": VA163, "reseau": "solana", "adresse": SOL})
    hb = boss.get(r.headers["Location"]).get_data(as_text=True)
    check("un VA sans ticket : adresse posée quand même, et la page dit qu'il n'a pas été prévenu",
          r.status_code == 303 and r.headers["Location"].endswith("&ok=1&n=ticket")
          and suivi_va.paiement_de(TH, "163").get("par") == "site:boss" and not DISCORD
          and sv._e(au.NOTES["ticket"]) in hb, r.headers.get("Location"))
    REPONSES.update(carte="carte non modifiée (HTTP 500)", menu=500, message=403)
    r = owner.post("/trust/liens/adresse", data={"va": VA96, "reseau": "solana", "adresse": SOL2})
    hn = owner.get(r.headers["Location"]).get_data(as_text=True)
    check("Discord en panne : l'adresse est enregistrée, et chaque raté est dit sur la page",
          suivi_va.adresse_de(TW, "96") == SOL2 and r.headers["Location"].endswith("&ok=1&n=carte,menu,message")
          and all(sv._e(au.NOTES[n]) in hn for n in ("carte", "menu", "message")),
          r.headers.get("Location"))
    REPONSES.update(carte="", menu=200, message=200)
    hf = owner.get(f"/trust/liens/adresse?va={VA96}&ok=1&n=<b>x</b>,ticket,inconnu").get_data(as_text=True)
    check("les notes viennent d'une liste fermée : un lien forgé ne fait rien dire à la page",
          "<b>x</b>" not in hf and "inconnu" not in hf and sv._e(au.NOTES["ticket"]) in hf)
    if os.geteuid() != 0:
        avant_panne = suivi_va.adresse_de(TW, "96")
        suivi_va.ETAT_FICHIER.chmod(0)
        try:
            DISCORD.clear()
            r = owner.post("/trust/liens/adresse", data={"va": VA96, "reseau": "solana", "adresse": SOL})
            b = r.get_data(as_text=True)
            hg = owner.get(f"/trust/liens/adresse?va={VA96}").get_data(as_text=True)
        finally:
            suivi_va.ETAT_FICHIER.chmod(0o600)
        check("fichier des adresses illisible : 400, rien n'est écrit par-dessus, personne n'est prévenu",
              r.status_code == 400 and "rien n&#x27;a été changé" in b and not DISCORD
              and suivi_va.adresse_de(TW, "96") == avant_panne, r.status_code)
        check("... et la page le dit, sans formulaire ni « à renseigner »",
              "Adresses illisibles" in hg and "<form" not in hg and "à renseigner" not in hg)

    print("4. « Modifier » sur la page de la direction")
    lot = {"gens": [{"gid": g, "uid": u, "code": c, "plateforme": n, "numero": FICHES[f"{g}:{u}"]["numero"],
                     "pseudo": FICHES[f"{g}:{u}"]["pseudo"]}
                    for g, u, c, n in ((TW, "96", "tw", "Twitter"), (IG, "108", "ig", "Instagram"),
                                       (TH, "163", "th", "Threads"))],
           "lignes": {}, "pannes": {}, "remarques": [], "debut": 0, "fin": 1}
    kw = dict(cle_="", s="tous", du="2026-11-16", au="2026-11-17", tri="subs", sens="desc", jour=JOUR)
    hm = st.page_html(lot, None, modifier=True, **kw)
    check("compte connecté : chaque ligne porte « Modifier », vers la page de CE VA",
          re.findall(r'<a class="adrm" href="([^"]*)">Modifier</a>', hm)
          == [f"/trust/liens/adresse?va={g}%3A{u}" for g, u in ((TW, "96"), (IG, "108"), (TH, "163"))],
          re.findall(r'<a class="adrm" href="([^"]*)"', hm))
    check("... aussi pour un VA « à renseigner »",
          '<span class="manque">à renseigner</span><a class="adrm"' in st.page_html(
              lot, None, modifier=True, adresses={}, **kw))
    check("clé de manager : pas de « Modifier »", "adrm\"" not in st.page_html(lot, None, **dict(kw, cle_=k_mgr))
          and "/trust/liens/adresse" not in st.page_html(lot, None, **dict(kw, cle_=k_mgr)))
    check("adresses illisibles : pas de « Modifier » (on ne change pas ce qu'on ne lit pas)",
          "/trust/liens/adresse" not in st.page_html(lot, None, modifier=True, adresses=None, **kw))
    st._LOTS.clear()
    rm = owner.get("/trust/liens").get_data(as_text=True)
    rk = anonyme.get(f"/trust/liens?k={k_mgr}").get_data(as_text=True)
    if st._FIL:
        st._FIL.join(10)
    rm = owner.get("/trust/liens").get_data(as_text=True)
    rk = anonyme.get(f"/trust/liens?k={k_mgr}").get_data(as_text=True)
    check("la route : « Modifier » pour le compte connecté, pas avec la clé des managers",
          rm.count('class="adrm"') == 3 and "adrm\"" not in rk and "/trust/liens/adresse" not in rk,
          (rm.count('class="adrm"'), rk.count("adrm")))
    pva = anonyme.get(f"/mes-stats?t={sv.jeton(TW, '96')}").get_data(as_text=True)
    check("la page « Tes stats » d'un VA : jamais « Modifier », aucun lien vers la page de la direction",
          "Modifier" not in pva and "/trust/liens" not in pva and "<form" in pva and 'method="post"' not in pva.lower())
finally:
    _wu._load_web_users = _users

print("5. Isolation")
check("rien écrit dans le vrai data/", {str(p): (p.stat().st_mtime if p.exists() else None) for p in VRAIS} == AVANT)

print("=" * 70)
print(f"RESULTAT : {len(OK)} OK / {len(KO)} ECHEC(S)")
if KO:
    print("ECHECS :")
    for k in KO:
        print("  - " + k)
print("=" * 70)
sys.exit(1 if KO else 0)
