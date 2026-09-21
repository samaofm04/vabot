"""Explicit revenue groups: stable account IDs, never similar model names."""
OF_US_IDS = frozenset({3107, 3108, 3352})  # Jessye, Khloe, Emy
OF_FR_IDS = frozenset({3106, 3109})        # Amelia, Julia
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
