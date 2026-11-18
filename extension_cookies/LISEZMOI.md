# Cookies → youl4b (extension Chrome)

Remet à youl4b.com les deux cookies de session que le site emprunte au
navigateur du propriétaire :

| Service | Cookie | Durée | À quoi il sert sur le site |
|---|---|---|---|
| GetMySocial | `authToken` | 30 jours | A/B des liens VA (API privée) |
| MyPuls | `REMEMBERME` | 7 jours, renouvelé seul par le site | photos des models, pushs, factures |

Un clic sur l'icône montre l'état des deux cookies **du site** (les mêmes
phrases que Réglages › Cookies GetMySocial / Cookies MyPuls). Le bouton
« Envoyer les deux cookies » les remet tout de suite.

Sans clic, l'extension envoie aussi :

- le cookie GetMySocial quand il est neuf dans Chrome (après une reconnexion) ;
- le cookie MyPuls seulement quand celui du site ne va plus (mot de passe
  changé). Tant qu'il va, le site le renouvelle seul.

La pastille sur l'icône : rien = tout va bien, `3j` orange = GetMySocial expire
bientôt, `!` rouge = un cookie du site est mort, `?` gris = pas connecté à
youl4b.com.

## Installer (une fois)

1. Dans Chrome, ouvrir `chrome://extensions`.
2. En haut à droite, activer **Mode développeur**.
3. Cliquer **Charger l'extension non empaquetée** et choisir ce dossier
   (`extension_cookies`).
4. Cliquer l'icône puzzle de Chrome, puis l'épingle à côté de
   « Cookies → youl4b » pour garder l'icône visible.
5. Être connecté à youl4b.com avec un compte admin, dans ce même Chrome.

Après une mise à jour de ce dossier : `chrome://extensions`, flèche ronde
« Actualiser » sur la carte de l'extension.

## Ce qu'elle ne fait jamais

- Les cookies ne partent que vers `https://youl4b.com`, sur
  `/gms/set_session_cookie` et `/mypuls/save_cookies`. Nulle part ailleurs.
- Aucune valeur n'est affichée, écrite dans la console ni gardée : l'extension
  ne note qu'une empreinte, pour ne pas renvoyer dix fois le même cookie.
- Le cookie d'un **autre compte** (un deuxième compte GetMySocial ou MyPuls
  ouvert dans ce Chrome) est refusé par le site. Le popup le dit et propose
  « Remplacer le compte du site par celui-ci » : à ne cliquer que si c'est voulu.
- Pour MyPuls, seul le `REMEMBERME` part. Il n'existe que si la case
  « Se souvenir de moi » était cochée à la connexion sur mypuls.app.

## Vérifier

```bash
python tests_cookies_extension.py
```

Les décisions de l'extension y sont jouées dans un faux Chrome
(`tests_cookies_extension.js`), sans réseau.
