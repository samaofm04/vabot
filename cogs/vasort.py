"""cogs/vasort.py — Range les salons VA + salons-séparateurs par groupe.

Ordre dans chaque catégorie :
  [salons non-VA : général, banger, exemple…]      (intouchés, en haut)
  ──🔗-lien-actif                                   (séparateur, staff only)
  1. 🔗 VA avec lien qui tourne — 🟢 puis 🟠 puis 🔴
  ──⚙️-lien-0-clic
  2. 🔗⚙️ VA avec lien à 0 clic (3 j) — 🟢 → 🔴
  ──😴-sans-lien
  3. VA sans lien — 🟢 → 🟠 → 🔵 → 🔴
Dans un groupe : la pastille (🟢, 🟠, 🔵, 🔴), puis — Va IG seulement — les
subs de la semaine, puis ceux de la quinzaine (du plus grand au plus petit),
puis le numéro du VA, puis le pseudo. Ailleurs, sans subs : pastille, numéro,
pseudo (des salons sans numéro y gardent l'ordre alphabétique d'avant).

Séparateurs : salons texte verrouillés, visibles UNIQUEMENT par le staff
(deny @everyone ; les rôles contenant « boss » / « manager » + admins voient).
Créés automatiquement quand le groupe existe, supprimés si le groupe se vide.

Auto : re-tri toutes les 20 min (1 appel bulk par catégorie, seulement si
l'ordre a changé). Manuel : /rangerva (aperçu) puis /rangerva confirmer:True.
"""
import asyncio
import datetime as dt
import re
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

import safe_json
from nom_ticket import numero as _numero

_VA_RE = re.compile(r"(?:^|[^a-z0-9])va-([a-z0-9_.]+)$")
#: 🔵 = arrivant ou lien neuf de moins de 3 jours (va_link_status, hors git).
#: Absent d'ici jusqu'au 31/10/2026, il tombait au rang « sans rond », donc
#: SOUS les 🔴 : un VA qui vient d'arriver était rangé derrière ceux qui ne
#: font plus rien. Même ordre que tickets_discord.ORDRE_RONDS (Threads).
DOT_RANK = {"🟢": 0, "🟠": 1, "🔵": 2, "🔴": 3}
#: Sans numéro dans le nom : après les numérotés (comme tickets_discord._cle_tri).
SANS_NUMERO = 10 ** 6

_RACINE = Path(__file__).resolve().parent.parent
USERS_FILE = _RACINE / "data" / "users.json"
PODIUM_FILE = _RACINE / "data" / "podium.json"       # podium_discord.ETAT_FICHIER
VA_IG_ID = "1505418484052394004"                     # podium_discord.VA_IG_ID

SEP_LINK = "──🔗-lien-actif"
SEP_GEAR = "──⚙️-lien-0-clic"
SEP_NONE = "──😴-sans-lien"
SEP_BY_GROUP = {0: SEP_LINK, 1: SEP_GEAR, 2: SEP_NONE}


def _norm(s):
    """Compare sans le variation selector (⚙️ = ⚙ + U+FE0F) — anti-doublon."""
    return (s or "").replace("️", "")


def _is_sep(name):
    return _norm(name) in {_norm(s) for s in SEP_BY_GROUP.values()}


def _va_handle(name):
    m = _VA_RE.search((name or "").lower())
    return m.group(1) if m else None


def _sort_key(name: str, subs=(0, 0)):
    """(groupe, rond, -subs semaine, -subs quinzaine, numéro, pseudo) — plus
    petit = plus haut. `subs` : (semaine, quinzaine) du VA du salon
    (_subs_par_salon) ; (0, 0) hors Va IG : rond, numéro, pseudo.

    Propriétaire, 31/10/2026 : « mets en avant qui bosse et ceux qui font le
    plus de subs, tu vois comme ça on les voit en premier ». La pastille
    d'abord (qui bosse), puis les subs. La semaine repart à 0 le lundi : à
    égalité (tout le monde à 0 en début de semaine), la quinzaine départage
    encore ceux qui ramènent des abonnés, puis le numéro, puis le pseudo."""
    n = name or ""
    handle = _va_handle(n) or ""
    idx = n.lower().find("va-")
    prefix = n[:idx] if idx > 0 else ""
    dot = DOT_RANK.get(n[:1], len(DOT_RANK))
    has_link = "🔗" in prefix
    has_gear = "⚙" in prefix
    if has_link and not has_gear:
        group = 0
    elif has_link:
        group = 1
    else:
        group = 2
    semaine, quinzaine = (tuple(subs or ()) + (0, 0))[:2]
    num = _numero(n)
    return (group, dot, -int(semaine or 0), -int(quinzaine or 0),
            int(num) if num else SANS_NUMERO, handle)


def _sans_salons_va(guild) -> bool:
    """Serveurs US (Youl4b, YouCham) : un VA y a un dossier <pseudo>-menu,
    jamais de salon va-<pseudo>. Un « va-… » y est un salon du staff.

    Observé le 30/10/2026 sur YouCham, où Rem est administrateur et voit
    donc va-managers (sur Youl4b, il ne le voit pas) : le tri l'a pris pour
    le salon d'un VA « managers » et a posé un « ──😴-sans-lien » dans
    📊・SUIVI DES VA à 09:01 UTC, puis de nouveau à 09:41 après sa
    suppression : il revient au tour suivant (20 min) tant que Rem le voit.
    Ici, plus aucun salon VA : un séparateur déjà posé y est retiré comme
    orphelin (sort_guild), et rien d'autre ne bouge."""
    try:
        import guild_features as gf
        return gf.is_us_guild(guild)
    except Exception:                                        # noqa: BLE001
        return False


def _split(category, subs_map=None):
    """(others, groupes {0:[ch],1:[],2:[]}, separateurs existants {group: ch})
    `subs_map` : {id du salon: (subs semaine, subs quinzaine)} (_subs_par_salon),
    vide hors Va IG."""
    subs_map = subs_map or {}
    txts = list(category.text_channels)
    others, seps = [], {}
    groups = {0: [], 1: [], 2: []}
    sans_va = _sans_salons_va(getattr(category, "guild", None))
    for c in txts:
        if _is_sep(c.name):
            for g, sname in SEP_BY_GROUP.items():
                if _norm(c.name) == _norm(sname):
                    seps[g] = c
            continue
        if not sans_va and _va_handle(c.name):
            groups[_sort_key(c.name)[0]].append(c)
        else:
            others.append(c)
    for g in groups:
        groups[g].sort(key=lambda c: _sort_key(c.name, subs_map.get(c.id, (0, 0))))
    return others, groups, seps


# ─── Va IG : les subs du VA de chaque salon, pour le tri ─────────────────
# Propriétaire, 31/10/2026 : « mets en avant qui bosse et ceux qui font le
# plus de subs, tu vois comme ça on les voit en premier ». Le podium ne range
# les subs ni par VA ni par salon : une ligne par ENTITÉ (« Amelia VA 3 » =
# un VA dans une model), et un VA en a jusqu'à six. Chemin : salon -> uid
# (users.json) -> ses fiches liens_fr « uid:model » (numéro) -> ses entités,
# additionnées. Rien que des fichiers que le podium réécrit chaque heure :
# aucun appel MyPuls ni GetMySocial, alors que le tri passe toutes les 20 min.

def _serveur_va_ig(guild) -> bool:
    """Va IG (cogs/outils.SERVEURS) : ses tickets sont dans users.json et ses
    VA ont des subs au podium. Ailleurs, pas de subs : l'ordre ne change pas."""
    try:
        from cogs.outils import serveur_outils
        return serveur_outils(guild)
    except Exception:                                        # noqa: BLE001
        return False


def _salons_va(guild) -> list:
    """[(id, nom)] des salons de VA du serveur. Pris dans la boucle
    d'événements, avant asyncio.to_thread : lire guild.categories depuis un
    autre fil pendant que discord.py les met à jour n'est pas sûr."""
    sans_va = _sans_salons_va(guild)
    return [(c.id, c.name) for cat in guild.categories for c in cat.text_channels
            if not sans_va and not _is_sep(c.name) and _va_handle(c.name)]


def _proprietaires(users) -> tuple:
    """({id du salon: uid}, {id du salon: [uids]}) d'après users.json.
    Un salon revendiqué par deux fiches n'est rattaché à personne, comme dans
    va_link_status.ticket_owners : lui donner les subs de l'une plutôt que
    de l'autre serait deviner. Il est compté à part (_lire_subs)."""
    par_salon = {}
    for uid, fiche in (users or {}).items():
        if not isinstance(fiche, dict) or not str(uid).isdigit():
            continue
        cid = str(fiche.get("channel_id") or "")
        if cid.isdigit():
            par_salon.setdefault(int(cid), []).append(str(uid))
    uniques = {cid: u[0] for cid, u in par_salon.items() if len(u) == 1}
    doubles = {cid: u for cid, u in par_salon.items() if len(u) > 1}
    return uniques, doubles


def _lundi_paris() -> str:
    """Le lundi de la semaine en cours, à l'heure de Paris comme le podium
    (podium_discord._maintenant : le VPS tourne en UTC)."""
    try:
        from zoneinfo import ZoneInfo
        j = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    except Exception:                                        # noqa: BLE001
        j = dt.date.today()
    return (j - dt.timedelta(days=j.weekday())).isoformat()


def _subs_par_uid(podium, liens, models, lundi=None) -> tuple:
    """({uid: [subs semaine, subs quinzaine]}, bilan) d'après le dernier relevé
    du podium de Va IG : vivants[Va IG] = la semaine, subs[Va IG] = la
    quinzaine. « clics » y porte les abonnés (mesure « abonnes » de Va IG).
    Une ligne qui ne se rattache à personne est comptée dans le bilan, jamais
    laissée de côté sans trace."""
    bilan = {"lignes": 0, "sans_fiche": [], "partagees": [], "internes": [],
             "illisibles": 0, "semaine_passee": ""}
    par_entite = {}
    for cle, f in (liens or {}).items():
        if not isinstance(f, dict) or ":" not in str(cle):
            continue
        uid, model = str(cle).split(":", 1)
        n = f.get("numero")
        if model not in models or not str(n or "").isdigit():
            continue
        # le libellé de subs_va.entites_va_ig, celui des lignes du relevé
        par_entite.setdefault(f'{models[model]["nom"]} VA {int(n)}', set()).add(uid)
    out = {}
    for i, bloc in enumerate(("vivants", "subs")):
        garde = ((podium or {}).get(bloc) or {}).get(VA_IG_ID) or {}
        if not isinstance(garde, dict):
            continue
        if i == 0 and lundi and garde.get("semaine") and str(garde["semaine"]) != lundi:
            # le lundi, jusqu'au podium de 09h, le relevé gardé est celui de
            # la semaine FINIE : la semaine en cours, elle, repart à 0
            bilan["semaine_passee"] = str(garde["semaine"])
            continue
        for x in (garde.get("dernier") or {}).get("lignes") or []:
            if not isinstance(x, dict):
                bilan["illisibles"] += 1
                continue
            nom = str(x.get("va") or "")
            if x.get("interne") or x.get("youl4b") or x.get("cle_ig"):
                # comptes internes, VA d'un autre serveur (podium_discord) :
                # aucun n'a de salon ici
                bilan["internes"].append(nom)
                continue
            uids = par_entite.get(nom)
            if not uids:
                bilan["sans_fiche"].append(nom)
                continue
            if len(uids) > 1:
                # deux fiches au même numéro dans la même model : le podium
                # additionne leurs trackings, on ne sait pas à qui sont ces subs
                bilan["partagees"].append(nom)
                continue
            try:
                v = int(x.get("clics") or 0)
            except (TypeError, ValueError):
                bilan["illisibles"] += 1
                continue
            bilan["lignes"] += 1
            out.setdefault(next(iter(uids)), [0, 0])[i] += v
    # une même entité est souvent dans la semaine ET dans la quinzaine
    for cle in ("sans_fiche", "partagees", "internes"):
        bilan[cle] = sorted(set(bilan[cle]))
    return out, bilan


def _lire_subs(guild, salons=None) -> tuple:
    """(table {id du salon: (subs semaine, subs quinzaine)}, bilan). Lecture
    de fichiers seulement : à appeler hors de la boucle d'événements
    (asyncio.to_thread). `salons` : [(id, nom)] des salons de VA du serveur
    (_salons_va), pour compter ceux qu'aucune fiche ne revendique."""
    if not _serveur_va_ig(guild):
        return {}, {}
    import liens_fr
    users = safe_json.load(USERS_FILE, default={}) or {}
    podium = safe_json.load(PODIUM_FILE, default={}) or {}
    liens = (liens_fr._etat() or {}).get("liens") or {}
    proprio, doubles = _proprietaires(users if isinstance(users, dict) else {})
    par_uid, bilan = _subs_par_uid(podium if isinstance(podium, dict) else {},
                                   liens if isinstance(liens, dict) else {},
                                   liens_fr.MODELS, lundi=_lundi_paris())
    table = {cid: tuple(par_uid.get(uid, (0, 0))) for cid, uid in proprio.items()}
    salons = list(salons or [])
    bilan["salons"] = len(salons)
    bilan["avec_subs"] = sum(1 for cid, _n in salons if any(table.get(cid, (0, 0))))
    # sans propriétaire : rangé à 0 sub (pastille, numéro, pseudo), et dit
    bilan["sans_proprietaire"] = [nom for cid, nom in salons
                                  if cid not in proprio and cid not in doubles]
    bilan["deux_fiches"] = [nom for cid, nom in salons if cid in doubles]
    a_un_salon = set(proprio.values())
    bilan["subs_sans_salon"] = sorted(u for u, v in par_uid.items()
                                      if any(v) and u not in a_un_salon)
    return table, bilan


#: Le dernier bilan journalisé, par serveur : une ligne quand il change, pas
#: la même toutes les 20 min.
_BILANS = {}


def _texte_bilan(bilan) -> str:
    parts = [f"{bilan.get('avec_subs', 0)}/{bilan.get('salons', 0)} salon(s) de VA avec des subs"]
    for cle, quoi in (("sans_proprietaire", "sans propriétaire dans users.json (rangés à 0)"),
                      ("deux_fiches", "revendiqués par plusieurs fiches (rangés à 0)"),
                      ("sans_fiche", "lignes du podium sans fiche liens_fr"),
                      ("partagees", "lignes du podium à plusieurs VA"),
                      ("internes", "lignes internes / autre serveur écartées"),
                      ("subs_sans_salon", "VA avec des subs sans salon")):
        v = sorted(set(bilan.get(cle) or []))
        if v:
            parts.append(f"{quoi} : {len(v)} {ascii(v[:8])}")
    if bilan.get("illisibles"):
        parts.append(f"lignes illisibles : {bilan['illisibles']}")
    if bilan.get("semaine_passee"):
        parts.append(f"relevé de la semaine du {bilan['semaine_passee']} (finie) : semaine comptée 0")
    return " ; ".join(parts)


def _subs_par_salon(guild, salons=None) -> dict:
    """{id du salon: (subs semaine, subs quinzaine)} du VA de chaque ticket de
    Va IG ; {} sur les autres serveurs. Journalise ce qui ne se rattache pas
    (salon sans propriétaire, ligne du podium sans fiche…)."""
    if salons is None:
        salons = _salons_va(guild)
    table, bilan = _lire_subs(guild, salons)
    if bilan:
        texte = _texte_bilan(bilan)
        gid = getattr(guild, "id", 0)
        if _BILANS.get(gid) != texte:
            _BILANS[gid] = texte
            print(f"[vasort] subs {ascii(getattr(guild, 'name', '?'))} : {texte}", flush=True)
    return table


async def _table_subs(guild) -> dict:
    """_subs_par_salon, une fois par tri de serveur, hors de la boucle
    d'événements. {} hors Va IG ; {} aussi si la lecture échoue : le tri se
    fait alors sans les subs (pastille, numéro, pseudo), et c'est dit."""
    if not _serveur_va_ig(guild):
        return {}
    try:
        return await asyncio.to_thread(_subs_par_salon, guild, _salons_va(guild))
    except Exception as e:                                   # noqa: BLE001
        print(f"[vasort] subs illisibles sur {ascii(getattr(guild, 'name', '?'))} "
              f"({type(e).__name__}: {e}) : tri sans les subs", flush=True)
        return {}


def _texte_subs(subs) -> str:
    """« · 12 subs semaine, 53 quinzaine » pour l'aperçu ; rien à 0."""
    semaine, quinzaine = (tuple(subs or ()) + (0, 0))[:2]
    if not semaine and not quinzaine:
        return ""
    return f" · {semaine} subs semaine, {quinzaine} quinzaine"


async def _staff_overwrites(guild):
    """Séparateurs visibles staff only : deny @everyone, allow boss/manager."""
    ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    for role in guild.roles:
        rn = role.name.lower()
        if "boss" in rn or "manager" in rn or "staff" in rn:
            ow[role] = discord.PermissionOverwrite(view_channel=True, send_messages=False)
    return ow


async def _sync_separators(guild, category, groups, seps, allow_create=True):
    """Crée les séparateurs manquants (groupe non vide) / supprime les inutiles."""
    changed = False
    for g in (0, 1, 2):
        need = bool(groups[g])
        have = seps.get(g)
        if need and not have and allow_create:
            try:
                ow = await _staff_overwrites(guild)
                ch = await guild.create_text_channel(
                    SEP_BY_GROUP[g], category=category, overwrites=ow,
                    reason="Séparateur tri VA")
                seps[g] = ch
                changed = True
            except Exception as e:
                print(f"[vasort] create sep {SEP_BY_GROUP[g]}: {e}", flush=True)
        elif not need and have:
            try:
                await have.delete(reason="Groupe VA vide — séparateur retiré")
                seps.pop(g, None)
                changed = True
            except Exception:
                pass
    return changed


def _desired(others, groups, seps):
    """Ordre voulu (avec les séparateurs qui EXISTENT)."""
    out = list(others)
    for g in (0, 1, 2):
        if not groups[g]:
            continue
        if seps.get(g):
            out.append(seps[g])
        out.extend(groups[g])
    return out


async def _apply_order(guild, category, desired):
    """(déplacés, échecs). Les deux comptent des salons REELLEMENT bougés :
    l'ancien code renvoyait la taille du payload même quand l'appel groupé ET
    la reprise salon par salon avaient échoué (permission manquante) — /rangerva
    annonçait alors « N salon(s) déplacé(s) » sans que rien n'ait bougé."""
    current = list(category.text_channels)
    if [c.id for c in current] == [c.id for c in desired]:
        return 0, 0
    positions = sorted(c.position for c in current)
    payload = []
    for i, ch in enumerate(desired):
        if i < len(positions) and ch.position != positions[i]:
            payload.append({"id": ch.id, "position": positions[i]})
    if not payload:
        return 0, 0
    try:
        await guild._state.http.bulk_channel_update(
            guild.id, payload, reason="Tri VA (liens/activité)")
        return len(payload), 0
    except Exception as e:
        print(f"[vasort] tri groupe impossible dans {ascii(category.name)} : {e}", flush=True)
    done = fails = 0
    for i, ch in enumerate(desired):
        try:
            await ch.move(category=category, beginning=True, offset=i)
            done += 1
        except Exception as e:
            fails += 1
            print(f"[vasort] deplacement #{ascii(getattr(ch, 'name', '?'))} : {e}", flush=True)
    return done, fails


def _sans_separateurs(guild) -> bool:
    """Serveur FR (cogs/outils.SERVEURS) : pas de separateurs. Proprietaire,
    03/10/2026 : « pas besoin de mettre lien actif, sans lien etc., il y a
    deja [le 🔗] dans le nom ». Le tri par groupe reste."""
    try:
        from cogs.outils import serveur_outils
        return serveur_outils(guild)
    except Exception:                                        # noqa: BLE001
        return False


async def sort_guild(guild, create_seps=True) -> tuple:
    """Trie toutes les catégories avec des salons VA.
    -> (cats_modifiées, moves, echecs)"""
    cats = moves = fails = 0
    sans_seps = _sans_separateurs(guild)
    # une seule lecture des subs pour tout le serveur ({} hors Va IG)
    subs_map = await _table_subs(guild)
    for cat in guild.categories:
        others, groups, seps = _split(cat, subs_map)
        n_vas = sum(len(v) for v in groups.values())
        if n_vas < 1 or sans_seps:
            # plus de VA : retire les séparateurs orphelins
            # (serveur sans separateurs : ils partent aussi -- salons vides
            # du bot, reserves au staff, qu'il recree sinon)
            for g_, ch in list(seps.items()):
                try:
                    await ch.delete(reason="Plus de salons VA ici" if n_vas < 1
                                    else "Serveur sans separateurs (le 🔗 est dans le nom)")
                    seps.pop(g_, None)
                except Exception as e:
                    print(f"[vasort] suppression separateur #{ascii(getattr(ch, 'name', '?'))} : {e}",
                          flush=True)
            if n_vas < 1:
                continue
            n, nf = await _apply_order(guild, cat, _desired(others, groups, seps))
            fails += nf
            if n:
                cats += 1
                moves += n
            continue
        sep_changed = await _sync_separators(guild, cat, groups, seps, allow_create=create_seps)
        desired = _desired(others, groups, seps)
        n, nf = await _apply_order(guild, cat, desired)
        fails += nf
        if n or sep_changed:
            cats += 1
            moves += n
    return cats, moves, fails


class VASort(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.auto_sort.start()

    def cog_unload(self):
        if self.auto_sort.is_running():
            self.auto_sort.cancel()

    @tasks.loop(minutes=20)
    async def auto_sort(self):
        import guild_features as gf
        for g in self.bot.guilds:
            if gf.numero_seul(g):
                continue   # le bot n'y est que pour le numero
            try:
                _c, _m, _f = await sort_guild(g)
                if _f:
                    # Sans cette ligne, un tri qui echoue toutes les 20 min ne
                    # laissait aucune trace : « les salons ne se rangent plus »
                    # sans rien a lire dans les logs.
                    print(f"[vasort] {ascii(g.name)}: {_f} deplacement(s) refuse(s) "
                          "(permission « Gérer les salons » ?)", flush=True)
            except Exception as e:
                print(f"[vasort] {g.name}: {e}", flush=True)

    @auto_sort.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="rangerva",
        description="Range les salons VA : liens en haut, puis 0 clic, puis 🟢🟠🔵🔴 et les subs",
    )
    @app_commands.describe(
        confirmer="Laisse vide = APERÇU (rien n'est déplacé). Mets True = range pour de vrai.",
    )
    async def rangerva(self, interaction: discord.Interaction, confirmer: bool = False):
        perms = getattr(interaction.user, "guild_permissions", None)
        if not (perms and perms.manage_channels):
            await interaction.response.send_message(
                "Il faut la permission « Gérer les salons ».", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not confirmer:
            # ---- APERÇU : montre le nouvel ordre, sans rien créer ni déplacer ----
            # Les mêmes subs que le tri réel (sort_guild) : sans eux, l'aperçu
            # de Va IG montrait un ordre que le tri ne ferait pas.
            table, bilan = {}, {}
            if _serveur_va_ig(interaction.guild):
                try:
                    table, bilan = await asyncio.to_thread(
                        _lire_subs, interaction.guild, _salons_va(interaction.guild))
                except Exception as e:                       # noqa: BLE001
                    bilan = {"erreur": f"{type(e).__name__}: {e}"}
            blocks = []
            for cat in interaction.guild.categories:
                others, groups, seps = _split(cat, table)
                if sum(len(v) for v in groups.values()) < 1:
                    continue
                # position actuelle (hors séparateurs) pour marquer ce qui bougerait
                cur_wo = [c for c in cat.text_channels if not _is_sep(c.name)]
                pos = {c.id: i for i, c in enumerate(cur_wo)}
                des_idx = 0
                rows = [f"\n📂 **{cat.name}**"]
                for c in others:
                    rows.append(f"▫️ {c.name}")
                    des_idx += 1
                for g in (0, 1, 2):
                    if not groups[g]:
                        continue
                    tag = "" if seps.get(g) else " _(sera créé)_"
                    rows.append(f"➖ `{SEP_BY_GROUP[g]}`{tag}")
                    for c in groups[g]:
                        mark = "🔀" if pos.get(c.id) != des_idx else "▫️"
                        rows.append(f"{mark} {c.name}{_texte_subs(table.get(c.id))}")
                        des_idx += 1
                blocks.append("\n".join(rows))
            if not blocks:
                await interaction.followup.send("Aucune catégorie avec des salons VA.", ephemeral=True)
                return
            header = ("👀 **APERÇU — rien n'est déplacé ni créé.**\n"
                      "Séparateurs visibles STAFF uniquement (boss/manager/admin).\n")
            if bilan and not bilan.get("erreur"):
                header += ("Ordre : 🟢 → 🟠 → 🔵 → 🔴, puis subs de la semaine, puis de la "
                           "quinzaine, puis numéro.\n")
            footer = "\n\nSi c'est bon : `/rangerva confirmer:True`"
            # ce qui n'a pas pu être rattaché est dit ici aussi, pas seulement
            # dans les journaux du VPS
            if bilan.get("erreur"):
                footer = (f"\n\n⚠️ Subs illisibles ({bilan['erreur']}) : ordre sans les subs."
                          + footer)
            elif bilan:
                manquent = [f"{len(bilan[k])} {quoi}" for k, quoi in (
                    ("sans_proprietaire", "salon(s) sans propriétaire"),
                    ("deux_fiches", "salon(s) revendiqué(s) par plusieurs fiches"),
                    ("sans_fiche", "ligne(s) du podium sans fiche"),
                    ("partagees", "ligne(s) du podium à plusieurs VA")) if bilan.get(k)]
                if bilan.get("semaine_passee"):
                    manquent.append("semaine en cours pas encore relevée (comptée 0)")
                if manquent:
                    footer = ("\n\n-# Non rattaché aux subs (compté 0) : " + ", ".join(manquent)
                              + "." + footer)
            text = header + "\n".join(blocks) + footer
            chunks, buf = [], ""
            for line in text.split("\n"):
                if len(buf) + len(line) + 1 > 1900:
                    chunks.append(buf)
                    buf = line
                else:
                    buf += ("\n" if buf else "") + line
            if buf:
                chunks.append(buf)
            for c in chunks[:6]:
                await interaction.followup.send(c, ephemeral=True)
            # Au-dela de 6 messages l'apercu etait coupe sans le dire : on
            # annonce ce qui n'a pas ete montre (le tri, lui, prend tout).
            if len(chunks) > 6:
                await interaction.followup.send(
                    f"… +{len(chunks) - 6} bloc(s) non affiché(s) (aperçu trop long) — "
                    "le rangement, lui, traitera **toutes** les catégories.",
                    ephemeral=True)
            return

        try:
            cats, moves, fails = await sort_guild(interaction.guild)
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur : {e}", ephemeral=True)
            return
        # « fails » = déplacements refusés par Discord. Sans ça, un tri
        # entièrement refusé (rôle du bot trop bas) répondait « tout est déjà
        # dans le bon ordre » alors que rien n'avait bougé.
        avert = ""
        if fails:
            avert = (f"\n🚫 **{fails} déplacement(s) refusé(s)** — le bot a besoin de "
                     "**Gérer les salons** et son rôle doit être **au-dessus** "
                     "(Paramètres serveur → Rôles).")
        if not cats:
            if fails:
                await interaction.followup.send(
                    "⚠️ **Rien n'a pu être rangé.**" + avert, ephemeral=True)
            else:
                await interaction.followup.send(
                    "✅ Tout est déjà dans le bon ordre (séparateurs + 🔗 → 🔗⚙️ → 🟢🟠🔵🔴).",
                    ephemeral=True)
        else:
            await interaction.followup.send(
                f"✅ **{cats}** catégorie(s) rangée(s) ({moves} salon(s) déplacé(s)).\n"
                "Séparateurs staff-only en place. Le tri se refait tout seul toutes les 20 min."
                + avert,
                ephemeral=True)


async def setup(bot):
    await bot.add_cog(VASort(bot))
