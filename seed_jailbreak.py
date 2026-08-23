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

    try:
        tombes = (jb.tombstones() or {}).get("vas") or {}
    except Exception:
        tombes = {}

    for identity, vas_list in VAS_SEEDS.items():
        result[identity] = {}
        existing = {v["name"].lower(): v for v in jb.list_vas_for_identity(identity)}
        # Un VA RENOMME n'est plus reconnaissable a son nom — c'est par la que
        # le seed faisait des degats : il le croyait disparu et le recreait,
        # sous son ancien nom, avec son pseudo. Quatre fiches @noum0075 sont
        # nees comme ca, une par redemarrage du bot. Le pseudo Discord, lui,
        # survit au renommage : on s'en sert comme d'un identifiant.
        pseudos_pris = {(v.get("discord_username") or "").strip().lower()
                        for v in existing.values()
                        if (v.get("discord_username") or "").strip()}
        for va in vas_list:
            name = va["name"]
            discord_username = va.get("discord_username", "")
            key = name.lower()
            try:
                if discord_username and discord_username.strip().lower() in pseudos_pris:
                    # Meme personne, sous un autre nom : ne rien toucher.
                    result[identity][name] = "renomme"
                    continue
                if f"{identity}|{key}" in tombes:
                    # Supprime ou renomme sur le site il y a peu. Le recreer
                    # ici annulerait la decision — et add_va leverait au
                    # passage la pierre tombale qui protege du meme coup la
                    # synchro Sheets.
                    result[identity][name] = "pierre_tombale"
                    continue
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
