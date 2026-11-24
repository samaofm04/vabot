"""tg_moi.py — Le bot Telegram perso du propriétaire (/tgmoi).

Même code que celui de Lola (tg_perso.py), rechargé avec un autre préfixe :
fichiers data/tg_moi*, adresses /tgmoi et /tm/..., réglages, fans,
exemples et entraînement séparés. Rien n'est partagé avec Lola. Son
cerveau se choisit sur sa page (par défaut : le modèle du PC du
propriétaire, via Ollama, par le tunnel SSH de Bamboula).
"""
import importlib.util
import os
import sys

_spec = importlib.util.spec_from_file_location(
    "tg_moi", os.path.join(os.path.dirname(os.path.abspath(__file__)), "tg_perso.py"))
_m = importlib.util.module_from_spec(_spec)
_m.PREFIXE_FORCE = "tgmoi"
sys.modules[__name__] = _m
_spec.loader.exec_module(_m)
