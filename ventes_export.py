# -*- coding: utf-8 -*-
"""Registre des ventes des chatteurs, exportable en Excel.

But : pouvoir verifier une vente contestee. Un chatteur affirme avoir fait
une vente -> on ouvre le fichier, on cherche, et on voit l'heure exacte, la
creatrice concernee, le fan, le montant et le type.

La source est le tableau de transactions de MyPuls (scraping) : c'est le seul
endroit qui donne le detail vente par vente. L'API officielle, elle, ne rend
que des agregats — d'ou l'ecart possible entre les deux, signale dans l'onglet
« Controle ».
"""
from __future__ import annotations

import datetime as _dt
import io
import re
from collections import defaultdict

# Colonnes du registre, dans l'ordre d'affichage
COLONNES = ["Date", "Heure", "Quinzaine", "Chatteur", "Creatrice", "Fan",
            "Montant", "Devise", "Type"]


def quinzaine(date_iso: str) -> str:
    """« 2026-08 (1-15) » ou « 2026-08 (16-fin) » — la maille de paie."""
    t = (date_iso or "").strip()
    if len(t) < 10:
        return ""
    try:
        jour = int(t[8:10])
    except ValueError:
        return ""
    return "%s (%s)" % (t[:7], "1-15" if jour <= 15 else "16-fin")


def _quand(brut: str):
    """Coupe la date MyPuls en (date, heure). Formats rencontres :
    « 16/08/2026 14:32 », « 2026-08-16 14:32:05 », ou une date seule."""
    t = (brut or "").strip()
    if not t:
        return "", ""
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M"):
        try:
            d = _dt.datetime.strptime(t, fmt)
            return d.strftime("%Y-%m-%d"), d.strftime("%H:%M")
        except ValueError:
            pass
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(t, fmt).strftime("%Y-%m-%d"), ""
        except ValueError:
            pass
    # format inconnu : on garde le brut plutot que de perdre l'information
    m = re.match(r"(\S+)\s+(\S+)", t)
    return (m.group(1), m.group(2)) if m else (t, "")


def lignes_ventes(transactions) -> list:
    """Transactions MyPuls -> lignes du registre, triees par date decroissante."""
    lignes = []
    for t in (transactions or []):
        d, h = _quand(t.get("date"))
        try:
            montant = round(float(t.get("amount") or 0), 2)
        except (TypeError, ValueError):
            montant = 0.0
        lignes.append([
            d, h, quinzaine(d),
            (t.get("chatter") or "").strip() or "(non attribue)",
            (t.get("creator") or "").strip(),
            (t.get("fan") or "").strip(),
            montant,
            (t.get("currency") or "").strip().upper() or "EUR",
            (t.get("type") or "").strip(),
        ])
    lignes.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return lignes


def recap_par_chatteur(lignes) -> list:
    """Total par chatteur et par devise — la base d'un calcul de paie."""
    par = defaultdict(lambda: defaultdict(float))
    nb = defaultdict(int)
    for r in lignes:
        par[r[3]][r[7]] += r[6]      # [3]=chatteur, [7]=devise, [6]=montant
        nb[r[3]] += 1
    devises = sorted({d for v in par.values() for d in v})
    out = []
    for chatteur in sorted(par, key=lambda c: -sum(par[c].values())):
        ligne = [chatteur, nb[chatteur]]
        ligne += [round(par[chatteur].get(d, 0.0), 2) for d in devises]
        out.append(ligne)
    return ["Chatteur", "Ventes"] + ["Total " + d for d in devises], out


def recap_par_quinzaine(lignes) -> tuple:
    """Total par chatteur ET par quinzaine : c'est ce qui sert a payer."""
    par = defaultdict(lambda: defaultdict(float))
    for r in lignes:
        if r[2]:
            par[r[3]][r[2]] += r[6]
    quinz = sorted({q for v in par.values() for q in v})
    out = []
    for chatteur in sorted(par, key=lambda c: -sum(par[c].values())):
        out.append([chatteur] + [round(par[chatteur].get(q, 0.0), 2) for q in quinz]
                   + [round(sum(par[chatteur].values()), 2)])
    return (["Chatteur"] + quinz + ["Total"]), out


def controle(lignes, total_annonce=None) -> list:
    """Compare la somme du registre au total affiche ailleurs.

    C'est ce qui repond a « des fois il y a des trucs qui ne montent pas » :
    si l'ecart n'est pas nul, une vente manque quelque part.
    """
    par_devise = defaultdict(float)
    sans_chatteur = sans_date = 0
    for r in lignes:
        par_devise[r[7]] += r[6]
        if r[3] == "(non attribue)":
            sans_chatteur += 1
        if not r[0]:
            sans_date += 1
    ctrl = [["Ventes enregistrees", len(lignes)]]
    for d, v in sorted(par_devise.items()):
        ctrl.append(["Total " + d, round(v, 2)])
    ctrl.append(["Ventes sans chatteur identifie", sans_chatteur])
    ctrl.append(["Ventes sans date exploitable", sans_date])
    if total_annonce is not None:
        somme = round(sum(par_devise.values()), 2)
        ctrl.append(["Total annonce par le dashboard", round(total_annonce, 2)])
        ctrl.append(["Ecart", round(somme - total_annonce, 2)])
    return ctrl


def construire_xlsx(transactions, periode: str = "", total_annonce=None) -> bytes:
    """Le classeur : Ventes / Par chatteur / Controle."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    lignes = lignes_ventes(transactions)
    wb = Workbook()

    gras = Font(bold=True, color="FFFFFF")
    fond = PatternFill("solid", fgColor="1C1C1E")
    centre = Alignment(horizontal="center")

    def _entete(ws, cols):
        ws.append(cols)
        for i in range(1, len(cols) + 1):
            c = ws.cell(row=1, column=i)
            c.font, c.fill, c.alignment = gras, fond, centre
        ws.freeze_panes = "A2"

    # --- feuille 1 : le registre ---
    ws = wb.active
    ws.title = "Ventes"
    _entete(ws, COLONNES)
    for r in lignes:
        ws.append(r)
    if lignes:
        ws.auto_filter.ref = "A1:%s%d" % (get_column_letter(len(COLONNES)), len(lignes) + 1)
    for i, c in enumerate(COLONNES, start=1):
        largeur = {"Date": 12, "Heure": 8, "Quinzaine": 16, "Chatteur": 22,
                   "Creatrice": 20, "Fan": 24, "Montant": 12, "Devise": 9,
                   "Type": 16}.get(c, 14)
        ws.column_dimensions[get_column_letter(i)].width = largeur
    for row in ws.iter_rows(min_row=2, min_col=7, max_col=7):
        for c in row:
            c.number_format = "#,##0.00"

    # --- feuille 2 : recap par chatteur ---
    ws2 = wb.create_sheet("Par chatteur")
    cols2, recap = recap_par_chatteur(lignes)
    _entete(ws2, cols2)
    for r in recap:
        ws2.append(r)
    ws2.column_dimensions["A"].width = 22
    for i in range(2, len(cols2) + 1):
        ws2.column_dimensions[get_column_letter(i)].width = 14
    for row in ws2.iter_rows(min_row=2, min_col=3):
        for c in row:
            c.number_format = "#,##0.00"

    # --- feuille 3 : par quinzaine (la maille de paie) ---
    ws4 = wb.create_sheet("Par quinzaine")
    cols4, recap4 = recap_par_quinzaine(lignes)
    _entete(ws4, cols4)
    for r in recap4:
        ws4.append(r)
    ws4.column_dimensions["A"].width = 22
    for i in range(2, len(cols4) + 1):
        ws4.column_dimensions[get_column_letter(i)].width = 16
    for row in ws4.iter_rows(min_row=2, min_col=2):
        for c in row:
            c.number_format = "#,##0.00"

    # --- feuille 4 : controle ---
    ws3 = wb.create_sheet("Controle")
    _entete(ws3, ["Verification", "Valeur"])
    if periode:
        ws3.append(["Periode", periode])
    for r in controle(lignes, total_annonce):
        ws3.append(r)
    ws3.column_dimensions["A"].width = 34
    ws3.column_dimensions["B"].width = 18

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
