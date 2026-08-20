# VA AUTO — dashboard OFM + bot Discord

Agence OFM (YouL4b / Youl4b US). Un dépôt, deux programmes qui partagent le
même dossier `data/` :

- **le bot Discord** (`main.py` + `cogs/`) — menus VA, onboarding, jailbreak ;
- **le dashboard web** (`web_upload.py`) — Flask, lancé *dans le même
  processus* que le bot. C'est le gros morceau : ~49 000 lignes.

## Déployer

```bash
git push origin main
```

Il n'y a rien d'autre à faire : le VPS a un cron qui tire la branche `main` et
redémarre `va-bot` en moins d'une minute. `youl4b.com/version` dit quel commit
tourne et depuis quand — à consulter avant de conclure qu'un correctif « ne
marche pas ».

## Tester

```bash
python tests_site.py
```

Environ 350 vérifications, quelques secondes. **Relever le total AVANT de
modifier** : un échec préexistant (`plus aucune écriture non atomique`) traîne
depuis longtemps. Un correctif est bon quand le nombre d'échecs n'a pas bougé.

Rien ne remplace un rendu réel. Beaucoup d'erreurs de cette base ne se voient
ni à la lecture ni dans les tests : rendre la page avec le client de test
Flask, extraire le HTML produit et le regarder.

## Ce qui n'est pas dans git

`.env` (clés API), `data/` (identités, médias, ventes, cookies MyPuls, état
Drive), `assets/`. À copier à la main pour monter un poste. **Ne jamais les
committer** — `.env` porte les clés Anthropic, Discord et MyPuls.

## Pièges — chacun a déjà coûté une régression

**Le JavaScript vit dans des chaînes Python.** `UPLOAD_HTML` est assemblé par
concaténation ; une apostrophe mal échappée ne casse pas Python, elle casse le
script de la page *entière*, en silence. Une insertion dans
`go.textContent='⬇️ Importer '` a tué le bouton d'import du Drive sans une
erreur. Après toute modification du JS embarqué : extraire le `<script>` rendu
et le passer à `node --check`.

**Écritures atomiques obligatoires.** Jamais `write_text(json.dumps(...))` :
`safe_json.write()`. Une coupure au mauvais moment laissait un JSON tronqué et
perdait des identités.

**Toute route d'écriture est refusée par défaut.** Un `before_request` bloque
les POST pour les rôles restreints, sauf allow-list (`_RESTRICTED_WRITE_ALLOW`)
— sinon un chatteur pouvait appeler `/settings/role/add` depuis la console.
Une nouvelle route POST renvoie 403 tant qu'elle n'est pas déclarée.
`is_auth()` rejette aussi un `username` de session absent du fichier des
comptes : pour un test, `admin`.

**Thème clair : la spécificité prime sur `!important`.** Une règle générale
assombrit tout texte blanc en style inline. Les règles qui protègent les textes
posés sur une vignette doivent être **plus spécifiques**, pas seulement
`!important` — sinon c'est du sombre sur du noir. Calculer la spécificité,
ne pas l'estimer. Attention aussi aux fonds *translucides* (`rgba(...)`) : un
bouton translucide est posé sur une image, il doit rester clair.

**Rendu serveur ET rendu client.** Beaucoup d'écrans sont produits par Flask
*puis* reconstruits en JS. Un correctif appliqué d'un seul côté réapparaît au
premier rafraîchissement.

**Deux mappings valent deux comportements.** Le Drive avait deux tables de
correspondance de noms de dossiers : un dossier accepté d'un côté était ignoré
de l'autre, et 598 fichiers restaient invisibles sans message. Quand deux
endroits décident la même chose, les fusionner.

**Ne jamais écarter en silence.** `if len(row) < 7: continue`, un dossier au
nom inconnu, un fichier sans miniature : compter et remonter. La plupart des
« ça ne marche pas » de ce projet venaient de quelque chose d'ignoré sans trace.

## Fichiers principaux

| Fichier | Rôle |
|---|---|
| `web_upload.py` | tout le dashboard : routes, HTML, CSS, JS |
| `mypuls.py` | scraping MyPuls (ventes, chatteurs) + API officielle |
| `gdrive_sync.py` | synchro Google Drive, montante et descendante |
| `ventes_export.py` | registre des ventes en Excel |
| `ventes_sheet.py` | même registre, poussé dans un Google Sheet |
| `safe_json.py` | lecture/écriture atomique — à utiliser partout |
| `i18n_en.py` | traduction FR → EN de l'interface |
| `cogs/` | commandes et menus Discord |

## Sources de données, et leurs travers

**MyPuls** expose deux tableaux qui ne concordent pas toujours : le log de
transactions (détail vente par vente) et la table de performance (agrégats).
Il écrit littéralement `Indéterminé (Créatrice)` dans la colonne chatteur quand
une vente n'est rattachée à personne — c'est un libellé, pas un nom : ne jamais
le traiter comme un chatteur, ni le payer.

**Google Drive** ne garantit pas l'unicité des noms dans un dossier. Comparer
sur `md5Checksum`, jamais sur la seule taille, avant tout regroupement ou
suppression. Ce module ne supprime rien : garde-fou volontaire, la corbeille
Google sert de filet.

**Le site n'efface jamais un média.** Toute suppression passe par une
corbeille locale ou celle de Drive.

## Conventions

Les commentaires expliquent **pourquoi**, pas quoi — de préférence ce qui a été
observé (« sans ça, X arrivait »). Le code et les messages de commit sont en
français, sans accents dans les messages de commit.

Les métadonnées d'un média sont des fichiers voisins : `<stem>.txt` (caption),
`<stem>.desc.txt` (description), `<stem>.acheck.txt` (description reprise d'un
post, en attente de relecture), `<stem>.montage.json` (brouillon d'édition),
`<stem>.analyse.json` (analyse automatique). Supprimer un média doit emporter
**tous** ses voisins.
