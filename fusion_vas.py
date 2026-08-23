# -*- coding: utf-8 -*-
"""Fusionne les fiches VA dupliquees d'une meme identite.

    python fusion_vas.py                      # apercu, n ecrit RIEN
    python fusion_vas.py --identite jessye    # apercu d une seule identite
    python fusion_vas.py --appliquer          # ecrit, apres sauvegarde

A lancer SUR LE VPS, ou vivent les donnees.

Pourquoi cet outil existe. Un VA n'a pas d'identifiant : le lien compte -> VA
est le NOM recopie en texte. Renommer une fiche pouvait donc la dedoubler —
l'une gardait les comptes, l'autre le nom voulu. Les causes sont corrigees
(pierres tombales au renommage, semeur qui reconnait un VA a son pseudo,
synchro qui respecte les tombes), mais les fiches deja dupliquees restent.

CE QUE FAIT LA FUSION, ET RIEN D AUTRE : re-etiqueter des comptes.
    account["va"] = <nom du survivant>
Aucun compte n'est cree, aucun n'est supprime, aucun username n'est touche.
L'outil REFUSE d'ecrire si le nombre total de comptes change, ne serait-ce que
d'une unite.

Ordre a respecter, sinon le poller defait le travail :
    1. /sheetsync pause
    2. python fusion_vas.py                (lire le rapport)
    3. python fusion_vas.py --appliquer
    4. /sheetsync push                     (push force : realigne les classeurs)
    5. /sheetsync resume
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import shutil
import sys
from pathlib import Path

import jailbreak as jb

#: Un jeton final « x1 », « X12 »… ajoute a la main pour distinguer les
#: telephones d un meme VA. On le retire pour rapprocher « Roucham » et
#: « Roucham X1 », mais JAMAIS pour decider seul : un rapprochement par le nom
#: ne fusionne que si les pseudos ne s y opposent pas.
_SUFFIXE_X = re.compile(r"\s*x\s*\d+$", re.IGNORECASE)


def _norm(nom: str) -> str:
    n = re.sub(r"\s+", " ", str(nom or "").strip().lower())
    return _SUFFIXE_X.sub("", n).strip()


def _pseudo(v) -> str:
    if isinstance(v, dict):
        return str(v.get("discord_username") or "").strip().lower()
    return ""


def _nom(v) -> str:
    if isinstance(v, dict):
        return str(v.get("name") or "").strip()
    return str(v or "").strip()


def groupes_d_identite(entry: dict) -> list:
    """Les groupes de fiches a fusionner pour UNE identite.

    Deux fiches se rejoignent si elles partagent un pseudo Discord non vide,
    ou si leurs noms se confondent une fois le suffixe « X<n> » retire. Le
    regroupement ne franchit JAMAIS la frontiere d'une identite : le meme nom
    sous deux identites designe deux personnes differentes.
    """
    vas = [v for v in (entry.get("vas") or []) if _nom(v)]
    # Les fiches implicites comptent : elles s'affichent et portent des comptes.
    connus = {_nom(v).lower() for v in vas}
    for a in (entry.get("accounts") or []):
        va = str(a.get("va") or "").strip()
        if va and va.lower() not in connus:
            vas.append({"name": va, "discord_username": ""})
            connus.add(va.lower())

    parent = {i: i for i in range(len(vas))}

    def trouve(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def unir(i, j):
        ri, rj = trouve(i), trouve(j)
        if ri != rj:
            parent[rj] = ri

    par_pseudo, par_nom = {}, {}
    for i, v in enumerate(vas):
        p = _pseudo(v)
        if p:
            if p in par_pseudo:
                unir(par_pseudo[p], i)
            else:
                par_pseudo[p] = i
        n = _norm(_nom(v))
        if n:
            if n in par_nom:
                unir(par_nom[n], i)
            else:
                par_nom[n] = i

    paquets = {}
    for i in range(len(vas)):
        paquets.setdefault(trouve(i), []).append(vas[i])
    return [g for g in paquets.values() if len(g) > 1]


def compte_par_va(entry: dict) -> dict:
    out = {}
    for a in (entry.get("accounts") or []):
        va = str(a.get("va") or "").strip().lower()
        if va:
            out[va] = out.get(va, 0) + 1
    return out


def choisir_survivant(groupe: list, compte: dict):
    """(survivant, absorbes, motif, conflit).

    En cas de doute on ne fusionne pas : une fiche en trop se re-fusionne
    demain, un compte mal recolle se paie en mot de passe perdu.
    """
    avec_pseudo = [v for v in groupe if _pseudo(v)]
    pseudos = {_pseudo(v) for v in avec_pseudo}

    if len(pseudos) > 1:
        return None, [], "pseudos Discord differents", True

    if len(avec_pseudo) == 1:
        gagnant = avec_pseudo[0]
        motif = "seule fiche portant un pseudo Discord"
    elif len(avec_pseudo) > 1:
        # Meme pseudo sur plusieurs fiches : ce n'est pas un conflit, c'est un
        # doublon franc. On garde celle qui porte le plus de comptes.
        gagnant = max(avec_pseudo,
                      key=lambda v: (compte.get(_nom(v).lower(), 0),
                                     -groupe.index(v)))
        motif = "meme pseudo — on garde la fiche la mieux fournie"
    else:
        gagnant = max(groupe,
                      key=lambda v: (compte.get(_nom(v).lower(), 0),
                                     -groupe.index(v)))
        motif = "aucun pseudo — on garde la fiche la mieux fournie"

    absorbes = [v for v in groupe if v is not gagnant]
    return gagnant, absorbes, motif, False


def analyser(data: dict, identite: str = "") -> list:
    """Ce qui serait fait, sans rien ecrire."""
    plan = []
    for ident, entry in sorted((data or {}).items()):
        if not isinstance(entry, dict):
            continue
        if identite and ident != identite:
            continue
        compte = compte_par_va(entry)
        for groupe in groupes_d_identite(entry):
            gagnant, absorbes, motif, conflit = choisir_survivant(groupe, compte)
            plan.append({
                "identite": ident,
                "conflit": conflit,
                "motif": motif,
                "survivant": _nom(gagnant) if gagnant else "",
                "fiches": [(_nom(v), _pseudo(v), compte.get(_nom(v).lower(), 0))
                           for v in groupe],
                "absorbes": [_nom(v) for v in absorbes],
                "comptes_deplaces": sum(compte.get(_nom(v).lower(), 0)
                                        for v in absorbes),
            })
    return plan


def _total_comptes(data: dict) -> int:
    return sum(len(e.get("accounts") or [])
               for e in (data or {}).values() if isinstance(e, dict))


def appliquer(plan: list) -> tuple:
    """Ecrit la fusion. Rend (ok, message)."""
    a_faire = [p for p in plan if not p["conflit"] and p["absorbes"]]
    if not a_faire:
        return True, "Rien a fusionner."

    horo = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    sauvegarde = jb.JAILBREAK_FILE.with_name(f"jailbreak.avant-fusion-{horo}.json")
    with jb.transaction():
        try:
            shutil.copy2(jb.JAILBREAK_FILE, sauvegarde)
        except Exception as e:
            return False, f"Sauvegarde impossible ({e}) — on n ecrit rien."

        data = jb._load()
        avant = _total_comptes(data)
        deplaces = 0

        for p in a_faire:
            entry = data.get(p["identite"])
            if not isinstance(entry, dict):
                continue
            gagnant = p["survivant"]
            absorbes_lc = {n.strip().lower() for n in p["absorbes"]}

            # 1. Re-etiqueter les comptes. On ne touche a rien d autre.
            for a in (entry.get("accounts") or []):
                if str(a.get("va") or "").strip().lower() in absorbes_lc:
                    a["va"] = gagnant
                    deplaces += 1

            # 2. Retirer les fiches absorbees. Surtout PAS
            #    remove_va_and_accounts : elle supprime les comptes.
            entry["vas"] = [v for v in (entry.get("vas") or [])
                            if _nom(v).strip().lower() not in absorbes_lc]

            # 3. Le survivant doit exister explicitement — il pouvait n etre
            #    qu une fiche implicite deduite de ses comptes.
            if not any(_nom(v).strip().lower() == gagnant.strip().lower()
                       for v in entry["vas"]):
                pseudo = ""
                for n, ps, _c in p["fiches"]:
                    if n == gagnant and ps:
                        pseudo = ps
                entry["vas"].append({"name": gagnant, "discord_username": pseudo})

            # 4. Pierre tombale sur chaque nom retire, AVANT la sauvegarde :
            #    sans elle le prochain pull du Sheet les fait revenir.
            try:
                jb.tomb_add("vas", p["identite"], *p["absorbes"])
            except Exception:
                pass

        apres = _total_comptes(data)
        if apres != avant:
            return False, (f"REFUS : {avant} comptes avant, {apres} apres. "
                           f"Rien n a ete ecrit, la sauvegarde reste "
                           f"({sauvegarde.name}).")
        jb._save(data)

    return True, (f"{len(a_faire)} groupe(s) fusionne(s), {deplaces} compte(s) "
                  f"re-etiquete(s). Total inchange : {avant}. "
                  f"Sauvegarde : {sauvegarde.name}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--appliquer", action="store_true",
                   help="ecrit reellement (par defaut : apercu seul)")
    p.add_argument("--identite", default="",
                   help="ne traiter qu une identite")
    a = p.parse_args(argv)

    data = jb._load()
    plan = analyser(data, a.identite.strip().lower())
    if not plan:
        print("Aucune fiche en double.")
        return 0

    total_deplaces = 0
    for e in plan:
        print()
        print("  %s" % e["identite"])
        for nom, pseudo, n in e["fiches"]:
            marque = "  <- survivant" if nom == e["survivant"] else ""
            print("      %-28s %-24s %3d compte(s)%s"
                  % (nom, ("@" + pseudo) if pseudo else "(pas de pseudo)",
                     n, marque))
        if e["conflit"]:
            print("      /!\\ NON FUSIONNE : %s — a trancher a la main"
                  % e["motif"])
        else:
            print("      -> %s ; %d compte(s) re-etiquete(s)"
                  % (e["motif"], e["comptes_deplaces"]))
            total_deplaces += e["comptes_deplaces"]

    conflits = sum(1 for e in plan if e["conflit"])
    print()
    print("  %d groupe(s), %d compte(s) a re-etiqueter, %d conflit(s) laisse(s) "
          "de cote." % (len(plan), total_deplaces, conflits))
    print("  Total de comptes actuel : %d" % _total_comptes(data))

    if not a.appliquer:
        print()
        print("  APERCU — rien n a ete ecrit.")
        print("  Pour appliquer : /sheetsync pause, puis")
        print("      python fusion_vas.py --appliquer")
        print("  puis /sheetsync push et /sheetsync resume.")
        return 0

    ok, msg = appliquer(plan)
    print()
    print("  " + msg)
    if ok:
        print("  Pense a /sheetsync push (force) puis /sheetsync resume.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
