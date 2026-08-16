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
COLONNES = ["Date", "Heure", "Chatteur", "Creatrice", "Fan", "Montant",
            "Devise", "Type"]


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
            d, h,
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
        par[r[2]][r[6]] += r[5]
        nb[r[2]] += 1
    devises = sorted({d for v in par.values() for d in v})
    out = []
    for chatteur in sorted(par, key=lambda c: -sum(par[c].values())):
        ligne = [chatteur, nb[chatteur]]
        ligne += [round(par[chatteur].get(d, 0.0), 2) for d in devises]
        out.append(ligne)
    return ["Chatteur", "Ventes"] + ["Total " + d for d in devises], out


def controle(lignes, total_annonce=None) -> list:
    """Compare la somme du registre au total affiche ailleurs.

    C'est ce qui repond a « des fois il y a des trucs qui ne montent pas » :
    si l'ecart n'est pas nul, une vente manque quelque part.
    """
    par_devise = defaultdict(float)
    sans_chatteur = sans_date = 0
    for r in lignes:
        par_devise[r[6]] += r[5]
        if r[2] == "(non attribue)":
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
        largeur = {"Date": 12, "Heure": 8, "Chatteur": 20, "Creatrice": 20,
                   "Fan": 24, "Montant": 12, "Devise": 9, "Type": 16}.get(c, 14)
        ws.column_dimensions[get_column_letter(i)].width = largeur
    for row in ws.iter_rows(min_row=2, min_col=6, max_col=6):
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

    # --- feuille 3 : controle ---
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
