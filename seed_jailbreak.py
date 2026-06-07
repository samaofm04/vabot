"""seed_jailbreak.py - Seed des VAs Jailbreak par identite au boot du bot.

Memes principes que seed_media_pools :
- Hardcode dans le code (versionne git)
- Idempotent : ne re-ajoute pas un VA deja present
- N ecrase pas les modifs manuelles de l user

Pour rajouter un VA : ajouter une entree dans VAS_SEEDS ci-dessous.
"""
from __future__ import annotations

# Mapping identity (lowercase) -> liste de VAs a seeder
# Chaque VA = {"name": "Nom affiche", "discord_username": "handle_discord"}
VAS_SEEDS = {
    "jessye": [
        {"name": "Safidy", "discord_username": "safidy0356_08105"},
        {"name": "BOSS LA BOULE", "discord_username": "laboule.8"},
        {"name": "Noum", "discord_username": "noum0075"},
    ],
}


def seed_vas(force: bool = False) -> dict:
    """Seed les VAs depuis VAS_SEEDS si pas deja presents.
    force=True : ecrase le discord_username meme si le VA existe.
    Returns : {identity: {va_name: 'added' | 'skipped' | 'updated'}}
    """
    result: dict = {}
    try:
        import jailbreak as jb
    except Exception as e:
        return {"error": str(e)}

    for identity, vas_list in VAS_SEEDS.items():
        result[identity] = {}
        existing = {v["name"].lower(): v for v in jb.list_vas_for_identity(identity)}
        for va in vas_list:
            name = va["name"]
            discord_username = va.get("discord_username", "")
            key = name.lower()
            try:
                if key in existing:
                    # Deja la
                    if force and discord_username and existing[key].get("discord_username") != discord_username:
                        if jb.update_va(identity, name, discord_username=discord_username):
                            result[identity][name] = "updated"
                        else:
                            result[identity][name] = "update_failed"
                    else:
                        result[identity][name] = "skipped"
                else:
                    if jb.add_va(identity, name, discord_username=discord_username):
                        result[identity][name] = "added"
                    else:
                        result[identity][name] = "add_failed"
            except Exception as e:
                result[identity][name] = f"error: {e}"
    return result


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    print("Seeding Jailbreak VAs...", "(FORCE mode)" if force else "")
    res = seed_vas(force=force)
    for identity, vas in res.items():
        if isinstance(vas, str):  # error string
            print(f"  {identity}: {vas}")
            continue
        print(f"  {identity}:")
        for name, status in vas.items():
            print(f"    {name}: {status}")
    n_added = sum(1 for vas in res.values() if isinstance(vas, dict) for s in vas.values() if s == "added")
    print(f"\nDone: {n_added} VAs ajoutes.")
