"""Explicit revenue groups: stable account IDs, never similar model names."""
# Seren (3867) est la moitie Twitter d'Emy (liens_va.VARIANTE_TWITTER), un
# compte US : absente d'ici, elle tombait en OF FR par la regle de plateforme
# ci-dessous (1 240,77 $ de septembre ranges du mauvais cote, audit du 26/10).
# Lia (3992, ex-« Emma 💗 » chez MyPuls) remplace Emy dans ce 50/50 depuis le
# 28/10/2026 : absente d'ici, la regle de plateforme la rangeait en OF FR.
OF_US_IDS = frozenset({3107, 3108, 3352, 3867, 3992})  # Jessye, Khloe, Emy, Seren, Lia
OF_FR_IDS = frozenset({3106, 3109})        # Amelia, Julia

# LE PSEUDO ONLYFANS EST LE SEUL LIEN ENTRE MYPULS ET INFLOWW. MyPuls ne donne
# pas le pseudo OF de ses creatrices, Infloww ne connait pas leur id MyPuls :
# sans cette table, une creatrice des deux cotes serait comptee deux fois.
# Le nom sert au bandeau « Total PARTIEL » quand le compte manque partout.
COMPTES_OF = {
    3107: ("Jessye", "jessyewdiference"),
    3108: ("Khloé", "khloecute"),
    3352: ("Emy", "emy.brw"),
    3867: ("Seren", "seren.vale"),
    3992: ("Lia", "liasxcret"),
}

# Creatrices annoncees chez Infloww mais pas encore lisibles par la cle du
# site : tant qu'elles manquent, le total est PARTIEL et le bandeau le dit.
# Valeur : leur marche ('of_us' / 'of_fr'), None tant qu'il n'est pas confirme
# (elles sont alors comptees en OF FR, comme toute OnlyFans non classee, et
# l'ecran le signale). Proprietaire, 26/10/2026 : « maintenant il y a aussi Luna »,
# puis « OF US ».
ATTENDUES_INFLOWW = {"luna": "of_us"}
# Last verified MYM accounts; API metadata also covers newly added accounts.
KNOWN_MYM_IDS = frozenset({679, 769, 1116, 1121, 1141, 1317, 1469, 1733, 2896})


def creator_segment(cid, platform=''):
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        return 'other'
    if cid in OF_US_IDS:
        return 'of_us'
    if cid in OF_FR_IDS:
        return 'of_fr'
    # LA PLATEFORME FAIT FOI, comme dans mypuls.api_overview (mypuls.py:800) :
    #     seg["of_us" if c["id"] in OF_US_CREATOR_IDS else "of_fr"]
    # Les deux endroits decidaient la meme chose et ne la decidaient pas pareil.
    # Ici, une creatrice OnlyFans absente des deux listes ci-dessus tombait en
    # 'other' — un segment qui n'existe dans AUCUN filtre (dashboard_cache.py:15
    # GROUPS = {'all','mym','of_us','of_fr'}). Elle disparaissait donc de l'ecran
    # des qu'un filtre plateforme etait choisi, sans erreur et sans bandeau.
    #
    # Mesure du 21/09/2026 : Lola (3673), ajoutee le jour meme, n'etait dans
    # aucune liste. En vue « Toutes » OF FR affichait 4 004,58 $ ; en cliquant
    # « OF FR », 1 678,02 $. 2 326,56 $ evapores, soit tout son chiffre. Et 130
    # transactions sur 1 843 sortaient du classement des chatteurs. Sur aout,
    # le meme trou valait 4 924,82 $.
    #
    # Les listes d'identifiants restent utiles quand la plateforme n'est pas
    # connue de l'appelant, mais elles ne sont plus la seule porte d'entree :
    # toute nouvelle creatrice OnlyFans est desormais classee, pas perdue.
    if platform == 'onlyfans':
        return 'of_fr'
    if platform == 'mym' or cid in KNOWN_MYM_IDS:
        return 'mym'
    return 'other'


def creator_segments(creators, accounts=()):
    by_id = {str(c.get('id')): creator_segment(c.get('id'), c.get('platform')) for c in accounts}
    result = {str(name): by_id.get(str(cid), creator_segment(cid)) for name, cid in (creators or {}).items()}
    for c in accounts:
        if c.get('pseudo'):
            result[str(c['pseudo'])] = by_id[str(c.get('id'))]
    return result
