# Passer YouL4b sur le MacBook

Ce fichier est dans le dépôt : il arrive tout seul sur le Mac avec le
`git clone`. Il est écrit pour être suivi dans l'ordre, et pour être donné
tel quel à une session Claude sur le Mac.

État au 12/09/2026, vérifié sur la machine Windows.

---

## 1. Ce qui n'existe QUE sur ce PC

C'est la seule partie irrattrapable. Tout le reste se re-télécharge.

| Quoi | Où | Poids | Pourquoi c'est unique |
|---|---|---|---|
| **Les clés du Parc** | `Downloads/youlab-phone-farm/data/admin/api-keys.json` | 1 Ko | GeeLark, SMSPool, Getatext, SMSBower, lien de rotation IP, GMS. Ignoré par git. |
| **Le registre du Parc** | `…/data/admin/phone-farm.json` | 1,5 Mo | Tous les conteneurs, leurs comptes Instagram, leur état, l'historique des tâches. Rien ne le régénère. |
| **Les comptes du Parc** | `…/data/users.json`, `…/data/sessions/`, `…/data/dl-tokens.json` | 45 Ko | Qui peut se connecter au Parc. |
| **Le reste de data/admin** | `ip-sorties.json`, `presence.json`, `journal-2026-09.jsonl` | 25 Ko | Sorties IP, présence, journal du mois. |
| **`.env` du Parc** | `Downloads/youlab-phone-farm/.env` | 148 o | |
| **`.env` du bot** | `VA AUTO/bot/.env` | 96 o | `DISCORD_TOKEN` + `PREFIX`. |
| **Les scénarios du rig** | `Downloads/RIG-INSTAGRAM/` | 38 Mo | **N'est pas un dépôt git.** Il n'existe nulle part ailleurs. |

**L'essentiel tient dans 2 Mo** (tout sauf RIG-INSTAGRAM). Ce qui pèse dans
`data/admin` — `phone-farm-shots` (31 Mo de captures) et `cache-site`
(25 Mo) — se régénère : inutile de le transporter.

À ne PAS copier : `node_modules/` (362 Mo), `.venv/`, `__pycache__/`. Ce
sont des binaires compilés pour Windows x86 ; sur Apple Silicon ils ne
servent à rien et gênent. On les réinstalle.

---

## 2. Ce qui suit tout seul

- **Le site et le bot Discord tournent sur le VPS**, pas ici. Ce PC n'est
  qu'un poste de développement : on y écrit, on `git push`, un cron du VPS
  tire et redémarre. Rien à déplacer, rien à couper.
- **Les deux dépôts GitHub** :
  `github.com/samaofm04/vabot` (bot + site) et
  `github.com/samaofm04/youlab-phone-farm` (Parc).
  Un `git clone` de chacun sur le Mac, et le code est là.
- **La vraie `data/` du bot est sur le VPS** — celle d'ici (2 Mo) n'est
  qu'une copie de travail. Le `.gitignore` le dit : *« Données du bot
  (spécifiques au VPS) »*.
- **Les clés des services** (MyPuls, GetMySocial, RapidAPI, Apify,
  Anthropic, Telegram) sont liées au compte, pas à la machine.

---

## 3. Ce qui ne marchera pas tel quel

| Ce qui casse | Pourquoi | Sur le Mac |
|---|---|---|
| `automation/pc/parc.ps1` | PowerShell, et il code en dur `C:\Users\Administrator\…\python.exe` | À réécrire en `.sh` + un **launchd** (voir ci-dessous, la moitié existe déjà) |
| Raccourci « Noctus - lancer le parc » | Démarrage Windows | `~/Library/LaunchAgents/` |
| `ios.exe` (go-ios), `usbmux forward` | binaires Windows | `go-ios` a une version macOS ; `usbmuxd` est **natif** sur macOS |
| `.venv\Scripts\python.exe` du rig | venv Windows | `python3 -m venv` sur place |
| `bcrypt`, `@napi-rs/canvas`, `ffmpeg-static`, `ffprobe-installer` | modules Node **natifs** | `npm install` les retélécharge en arm64 — ne jamais copier `node_modules` |

**Bonne nouvelle, déjà dans le dépôt du Parc** :
`automation/watcher/` contient le portage Mac — `install-mac.sh`
(installe un LaunchAgent), `com.noctus.wdawatcher.plist.template`,
`NoctusDevices.command`, `devices-server.py`, `bootstrap-worker-mac.py`.

Son README est honnête et il faut le lire comme tel : *« le chemin Mac vient
d'être écrit : sa logique serveur est testée, mais rien de tout ça n'a
encore tourné sur un vrai Mac. Portage raisonné, pas encore éprouvé. »*
C'est donc là qu'il faudra passer du temps — pas sur le reste.

**Et le pilotage iPhone sera PLUS simple sur Mac** : WebDriverAgent se
compile nativement avec Xcode, et `usbmuxd` est dans le système. C'est la
partie qui souffrait le plus sous Windows.

---

## 4. L'ordre des opérations

1. **Copier les 2 Mo du §1** sur une clé ou par AirDrop — avant tout le
   reste, et avant de toucher à quoi que ce soit sur le PC.
2. **Copier `RIG-INSTAGRAM`** (38 Mo).
3. Sur le Mac : Xcode + les outils en ligne de commande, `brew`,
   `python3`, `node`, `ffmpeg`, `git`.
4. `git clone` les deux dépôts.
5. Remettre les fichiers du §1 à leur place dans les deux arborescences.
6. `npm install` dans `youlab-phone-farm`, `pip install -r requirements.txt`
   pour le bot.
7. Lancer le Parc à la main (`node server.js`) et ouvrir `127.0.0.1:3001`
   avant d'automatiser quoi que ce soit.
8. Brancher un iPhone, `automation/watcher/install-mac.sh`, et corriger ce
   qui résiste — c'est l'étape qui n'a jamais tourné.

---

## 5. Les pièges

- **Ne pas laisser les deux machines piloter en même temps.** Le site et le
  bot sont sur le VPS, donc aucun risque de doublon de ce côté. Mais si le
  Parc tourne sur le PC *et* sur le Mac, les deux pousseront sur les mêmes
  iPhone et tireront sur les mêmes clés à quota.
- **La casse des noms de fichiers.** Windows ignore la casse, macOS aussi
  par défaut, **Linux non** — et le VPS est sous Linux. Un `import Foo` qui
  marche sur les deux postes peut casser au déploiement. Rien de nouveau,
  mais le déménagement ne le corrige pas.
- **Les fins de ligne.** Git convertit en CRLF sur Windows. Sur le Mac,
  `git config --global core.autocrlf input`.
- **Le PC garde une copie tant que le Mac n'a pas fait un cycle complet** :
  un scrape, une création de compte, un déploiement. On ne l'efface qu'après.
