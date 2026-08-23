import pathlib
p = pathlib.Path('cogs/user.py')
l = p.read_text(encoding='utf-8').splitlines()

def trouver(depart, motif):
    return next(k for k, x in enumerate(l) if k >= depart and motif in x)

i = trouver(2990, 'Menu Jailbreak FR')
assert 'Menu Jailbreak US' in l[i + 1]
assert l[i + 6].strip() == '),', repr(l[i + 6])
l[i:i + 7] = [
 '            title=("Menu Jailbreak FR — models FR" if marche == "fr"',
 '                   else "Menu Jailbreak US — models US"),',
 '            description=(',
 '                "Choisis une model ci-dessous, puis l\'action à réaliser : reel, "',
 '                "reel monté, story, post, story CTA, pseudo, name, bio ou pp.\n\n"',
 '                + (_clst + "\n\n" if _clst else "")',
 '                + "Ce menu est ouvert à tout le monde sur ce serveur."',
 '            ),',
]
print('  menu FR/US reecrit (ligne %d)' % (i + 1))

j = trouver(3600, 'Menu Jailbreak — toutes les models')
assert 'description=(' in l[j + 1], repr(l[j + 1])
assert l[j + 5].strip() == '),', repr(l[j + 5])
l[j:j + 6] = [
 '            title="Menu Jailbreak — toutes les models",',
 '            description=(',
 '                "Choisis une model dans le menu déroulant, puis l\'action à "',
 '                "réaliser : reel, reel monté, story, post, story CTA, pseudo, "',
 '                "name, bio ou pp.\n\n"',
 '                f"Réservé aux membres portant le rôle **{role_txt}**."',
 '            ),',
]
print('  menu « toutes les models » reecrit (ligne %d)' % (j + 1))
p.write_text('\n'.join(l) + '\n', encoding='utf-8')
