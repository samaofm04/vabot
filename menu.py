import pathlib

# ---------- 1) La phrase de classement, sans trophee ----------
p = pathlib.Path('identites_ordre.py'); s = p.read_text(encoding='utf-8')
v = ('    return ("\U0001F3C6 **Les numéros sont un classement** : la n°1 est celle qui "\n'
     '            "marche le mieux en ce moment. Commence par le haut de la liste.")\n')
assert s.count(v) == 1, 'phrase de classement introuvable'
s = s.replace(v,
 '    return ("**Les numéros sont un classement.** La n°1 est celle qui marche "\n'
 '            "le mieux en ce moment — commence par le haut.")\n')
p.write_text(s, encoding='utf-8')
print('  phrase de classement reecrite')

# ---------- 2) Les trois menus Jailbreak ----------
p = pathlib.Path('cogs/user.py'); s = p.read_text(encoding='utf-8')

# 2a) FR / US
v = ('            title=("\U0001F513 Menu Jailbreak FR — models FR" if marche == "fr"\n'
     '                   else "\U0001F513 Menu Jailbreak US — models US"),\n'
     '            description=(\n'
     '                "Clique **directement sur la model** \U0001F447 puis choisis l\'action "\n'
     '                "(reel, reel monté, story, post, story CTA, pseudo, name, bio, pp).\n\n"\n'
     '                + (_clst + "\n\n" if _clst else "")\n'
     '                + "✅ Ouvert à tout le monde sur ce serveur."\n'
     '            ),\n')
assert s.count(v) == 1, 'embed FR/US introuvable'
s = s.replace(v,
 '            title=("Menu Jailbreak FR — models FR" if marche == "fr"\n'
 '                   else "Menu Jailbreak US — models US"),\n'
 '            description=(\n'
 '                "Choisis une model ci-dessous, puis l\'action à réaliser : reel, "\n'
 '                "reel monté, story, post, story CTA, pseudo, name, bio ou pp.\n\n"\n'
 '                + (_clst + "\n\n" if _clst else "")\n'
 '                + "Ce menu est ouvert à tout le monde sur ce serveur."\n'
 '            ),\n')

# 2b) Le menu « toutes les models »
v2 = ('            title="\U0001F513 Menu Jailbreak — toutes les models",\n'
      '            description=(\n'
      '                "Choisis une **model** dans le menu déroulant \U0001F447 puis clique sur l\'action "\n'
      '                "voulue (reel, reel monté, story, post, story CTA, pseudo, name, bio, pp).\n\n"\n'
      '                f"\U0001F512 Réservé aux membres avec le rôle **{role_txt}**."\n'
      '            ),\n')
assert s.count(v2) == 1, 'embed « toutes les models » introuvable'
s = s.replace(v2,
 '            title="Menu Jailbreak — toutes les models",\n'
 '            description=(\n'
 '                "Choisis une model dans le menu déroulant, puis l\'action à réaliser : "\n'
 '                "reel, reel monté, story, post, story CTA, pseudo, name, bio ou pp.\n\n"\n'
 '                f"Réservé aux membres portant le rôle **{role_txt}**."\n'
 '            ),\n')

p.write_text(s, encoding='utf-8')
print('  trois menus Jailbreak reecrits')
