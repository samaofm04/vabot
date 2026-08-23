import pathlib
p = pathlib.Path('cogs/user.py')
l = p.read_text(encoding='utf-8').splitlines()

def bloc(depart, motif, neuf):
    i = next(k for k, x in enumerate(l) if k >= depart and motif in x)
    return i

# --- menu FR / US (lignes 2999-3006) ---
i = bloc(2990, 'Menu Jailbreak FR', None, None)
assert 'Menu Jailbreak US' in l[i + 1]
assert l[i + 6].strip() == '),', l[i + 6]
neuf = [
 '            title=("Menu Jailbreak FR — models FR" if marche == "fr"',
 '                   else "Menu Jailbreak US — models US"),',
 '            description=(',
 '                "Choisis une model ci-dessous, puis l\'action à réaliser : reel, "',
 '                "reel monté, story, post, story CTA, pseudo, name, bio ou pp.\n\n"',
 '                + (_clst + "\n\n" if _clst else "")',
 '                + "Ce menu est ouvert à tout le monde sur ce serveur."',
 '            ),',
]
l[i:i + 8] = neuf
print('  menu FR/US reecrit (ligne %d)' % (i + 1))

# --- menu « toutes les models » ---
j = bloc(3600, 'Menu Jailbreak — toutes les models', None, None)
assert 'description=(' in l[j + 1]
assert l[j + 5].strip() == '),', l[j + 5]
neuf2 = [
 '            title="Menu Jailbreak — toutes les models",',
 '            description=(',
 '                "Choisis une model dans le menu déroulant, puis l\'action à "',
 '                "réaliser : reel, reel monté, story, post, story CTA, pseudo, "',
 '                "name, bio ou pp.\n\n"',
 '                f"Réservé aux membres portant le rôle **{role_txt}**."',
 '            ),',
]
l[j:j + 6] = neuf2
print('  menu « toutes les models » reecrit (ligne %d)' % (j + 1))

p.write_text('\n'.join(l) + '\n', encoding='utf-8')
