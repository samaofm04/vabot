"""Seed des media pools MyPuls par createur.

But : restaurer automatiquement les media_id MyPuls pour chaque modele au
boot du bot, SI le pool de ce createur est vide. Idempotent.

Pourquoi un seed in-code (pas juste un JSON dans data/) :
- data/ est gitignored (specifique au VPS)
- Si le data/mypuls_creator_settings.json se vide ou se corrompt, on a
  perdu la liste -> tu serais oblige de tout retaper
- Avec ce seed, les listes sont commitees dans git ; au prochain boot
  apres deploy, elles sont remises automatiquement.

Le seed N ECRASE PAS un pool existant : il populate UNIQUEMENT si vide.
Pour forcer un re-seed, vide les media_pool_posts via l UI puis restart.

Pour rajouter un createur : ajoute son entry dans MEDIA_SEEDS ci-dessous.
"""
from __future__ import annotations
from pathlib import Path
import json


# (creator_id MyPuls) -> liste de media_id (str)
# IDs verifies via mypuls.list_creators() :
#   Julia_dv=679, Amelia_xoxo=769, Lolatacrush=1116, Talittlechloe=1121,
#   Maria_coco=1407, Sarahmycrush=1469, Emmabrn=1733
MEDIA_SEEDS = {
    1733: [  # EMMA / Emmabrn (29)
        "75114546", "75114545", "75114544", "75114543", "75114541",
        "75114540", "75114538", "75114537", "75114536", "75114535",
        "75114534", "75114533", "75114532", "75114530", "75114528",
        "75114527", "75114526", "75114525", "75114524", "75114523",
        "75114522", "75114521", "75114519", "75114518", "75114517",
        "75114516", "75114515", "75114513", "75114512",
    ],
    769: [  # AMELIA / Amelia_xoxo (40)
        "75113819", "75113817", "75113815", "75113814", "75113810",
        "75113808", "75113805", "75113804", "75113802", "75113800",
        "75113799", "75113798", "75113797", "75113795", "75113794",
        "75113793", "75113792", "75113789", "75113788", "75113787",
        "75113785", "75113784", "75113780", "75113779", "75113778",
        "75113777", "75113775", "75113774", "75113773", "75113771",
        "75113770", "75113767", "75113765", "75113762", "75113761",
        "75113760", "75113759", "75113758", "75113756", "75113754",
    ],
    679: [  # JULIA / Julia_dv (36)
        "75114035", "75114037", "75114040", "75114042", "75114045",
        "75114046", "75114050", "75114053", "75114054", "75114057",
        "75114060", "75114061", "75114062", "75114064", "75114065",
        "75114068", "75114072", "75114075", "75114077", "75114079",
        "75114082", "75114086", "75114088", "75114091", "75114094",
        "75114098", "75114100", "75114103", "75114104", "75114106",
        "75114109", "75114111", "75114112", "75114114", "75114115",
        "75114120",
    ],
    1469: [  # SARAH / Sarahmycrush (20, le 75644229 etait dedoublonne)
        "75644255", "75644254", "75644253", "75644252", "75644251",
        "75644249", "75644248", "75644247", "75644246", "75644239",
        "75644237", "75644235", "75644234", "75644233", "75644231",
        "75644229", "75644226", "75644224", "75644222", "75644221",
    ],
    1116: [  # LOLA / Lolatacrush (36)
        "74394842", "74394846", "74394848", "74394849", "74394850",
        "74394854", "74394857", "74394858", "74394865", "74394867",
        "74394868", "74394869", "74394871", "74394872", "74394874",
        "74394875", "74394876", "74394877", "74394878", "74394880",
        "74394881", "74394884", "74394885", "74394886", "74394887",
        "74394888", "74394889", "74394890", "74394891", "74394894",
        "74394895", "74394896", "74394898", "74394900", "74394901",
        "74394905",
    ],
    1407: [  # MARIA / Maria_coco (19)
        "74698498", "74698499", "74698500", "74698501", "74698502",
        "74698503", "74698505", "74698506", "74698507", "74698508",
        "74698509", "74698510", "74698512", "74698518", "74698520",
        "74698521", "74698523", "74698537", "74698539",
    ],
    1121: [  # CHLOE / Talittlechloe (18)
        "74168580", "74183144", "74183217", "74183226", "74183316",
        "74183326", "74183347", "74183352", "74183357", "74183486",
        "74183510", "74183516", "74183671", "74183678", "74183683",
        "74183711", "74186526", "74186590",
    ],
}

# CAMILLE : creator_id MyPuls inconnu pour l instant. On stocke ses medias
# a part dans un fichier orphelin pour que le user puisse les rattacher
# quand il aura son creator_id.
CAMILLE_MEDIAS = [
    "74168342", "74168373", "74295578", "74295588", "74295596",
    "74295631", "74295669", "74295677", "74295688", "74295702",
    "74295711", "74295716", "74295795", "74295797", "74295802",
]


def seed_media_pools(force: bool = False) -> dict:
    """Restaure les media_pool_posts depuis MEDIA_SEEDS si vides.

    force=True : ecrase meme si non vide (a utiliser avec precaution).
    Returns : {creator_id: 'seeded'|'skipped'|'error'}
    """
    result: dict = {}
    try:
        import mypuls_creator_settings as mcs
    except Exception as e:
        print(f"[seed] import mypuls_creator_settings failed: {e}", flush=True)
        return {"error": str(e)}

    for cid, medias in MEDIA_SEEDS.items():
        try:
            current = mcs.get_creator_settings(cid)
            existing = current.get("media_pool_posts") or []
            if existing and not force:
                result[cid] = "skipped"  # pool deja peuple, on touche pas
                continue
            payload = dict(current)
            payload["media_pool_posts"] = list(medias)
            ok = mcs.save_creator_settings(cid, payload)
            result[cid] = "seeded" if ok else "error"
        except Exception as e:
            result[cid] = f"error: {e}"

    # CAMILLE orphan
    try:
        orphan_file = Path("data/orphan_media_pools.json")
        orphan_file.parent.mkdir(parents=True, exist_ok=True)
        orphan_data = {}
        if orphan_file.exists():
            try:
                orphan_data = json.loads(orphan_file.read_text(encoding="utf-8"))
            except Exception:
                orphan_data = {}
        if not orphan_data.get("CAMILLE", {}).get("media_pool_posts") or force:
            orphan_data["CAMILLE"] = {
                "media_pool_posts": list(CAMILLE_MEDIAS),
                "note": "creator_id MyPuls inconnu - rattacher quand connu",
            }
            orphan_file.write_text(
                json.dumps(orphan_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            result["CAMILLE_orphan"] = "seeded"
        else:
            result["CAMILLE_orphan"] = "skipped"
    except Exception as e:
        result["CAMILLE_orphan"] = f"error: {e}"

    return result


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    print("Seeding media pools...", "(FORCE mode)" if force else "")
    res = seed_media_pools(force=force)
    for cid, status in res.items():
        print(f"  #{cid}: {status}")
    n_seeded = sum(1 for v in res.values() if v == "seeded")
    n_skipped = sum(1 for v in res.values() if v == "skipped")
    print(f"\nDone: {n_seeded} seeded, {n_skipped} skipped.")
