# -*- coding: utf-8 -*-
"""Qui est present aux sessions vocales des VA.

CE QUE FAIT CE COG, ET RIEN D'AUTRE

Chaque minute, il regarde qui se trouve dans les salons vocaux suivis et le
dit a `sessions_voc`. Tout le raisonnement -- a quelle session cette minute
appartient, a partir de combien de temps on est « present », qui manquait --
vit dans `sessions_voc.py`, qui se teste sans bot et sans reseau. Ici il n'y
a que la lecture de Discord et l'envoi du resume.

AUCUNE COMMANDE SLASH, ET C'EST OBLIGATOIRE

Le bot principal est a 100 commandes sur 100, le plafond d'une application
Discord. Un cog qui en declare une seule echoue ENTIEREMENT, en silence :
quatre cogs du projet sont deja morts ainsi (`vaactivity`, `vasort`,
`tgrouter`, `numeros`). On suit donc le modele de `reportcomptes` : zero
commande, les salons trouves par convention de nom, et le declenchement
manuel depuis le tableau de bord.

POURQUOI ON SONDE AU LIEU D'ECOUTER LES ENTREES ET SORTIES

`on_voice_state_update` ne survit pas a un redemarrage : ceux qui etaient
deja connectes n'existent plus pour le bot, et un evenement perdu laisse
quelqu'un « present » indefiniment. Relever la liste chaque minute mesure du
temps reellement passe, et se repare tout seul au tour suivant.
"""
import datetime as _dt
import time as _t

import discord
from discord.ext import commands, tasks

import sessions_voc as sv


# Une seule definition du nettoyage de nom, dans sessions_voc : deux copies,
# c'est deux comportements le jour ou l'une des deux change.
_sans_accent = sv.sans_accent


class SessionsVoc(commands.Cog):
    """Pointage des sessions vocales. Zero commande slash."""

    def __init__(self, bot):
        self.bot = bot
        # Ce qu'on a deja poste, pour ne pas resservir le meme resume a chaque
        # tour de boucle : { "<guild>:<jour>" : True }
        self._resumes_faits = {}
        self.boucle.start()

    def cog_unload(self):
        self.boucle.cancel()

    # ------------------------------------------------------------------ #
    # Les salons suivis
    # ------------------------------------------------------------------ #
    def _vocaux(self) -> list:
        """Les salons vocaux a surveiller.

        Trois facons de les designer, de la plus precise a la plus souple :
        une liste d'identifiants, une categorie, un motif de nom. Le
        proprietaire hesitait entre « un salon par session » et « un seul
        salon pour toutes » : les deux marchent sans rien changer ici, parce
        que c'est l'HORLOGE qui decide de la session, jamais le salon.

        `hasattr(c, "send")` ne sert a rien pour filtrer : en discord.py 2.x
        un salon vocal a aussi un `send`. Seul `isinstance` tranche.
        """
        cfg = sv.config()
        out = []
        for c in self.bot.get_all_channels():
            if not isinstance(c, (discord.VoiceChannel, discord.StageChannel)):
                continue
            if sv.salon_suivi(c.id, getattr(c, "name", ""),
                              getattr(getattr(c, "category", None), "name", ""), cfg):
                out.append(c)
        return out

    # ------------------------------------------------------------------ #
    # La boucle
    # ------------------------------------------------------------------ #
    @tasks.loop(minutes=1)
    async def boucle(self):
        try:
            self._pointer()
        except Exception as e:                       # noqa: BLE001
            print(f"[sessions] pointage : {e}", flush=True)
        try:
            await self._resume_si_lheure()
        except Exception as e:                       # noqa: BLE001
            print(f"[sessions] resume : {e}", flush=True)

    @boucle.before_loop
    async def _avant(self):
        await self.bot.wait_until_ready()

    def _pointer(self):
        """Une minute de presence pour chacun de ceux qui sont la.

        On ne compte NI les bots NI les gens sourds cote serveur : un compte
        laisse connecte toute la nuit dans un salon n'a assiste a rien, et le
        faire figurer parmi les presents fausserait le seul chiffre que le
        proprietaire va regarder.
        """
        if sv.session_a(_t.time()) is None:
            return                                    # hors creneau : rien a noter
        vus, deja = [], set()
        for ch in self._vocaux():
            for m in getattr(ch, "members", []) or []:
                if getattr(m, "bot", False) or m.id in deja:
                    continue
                etat = getattr(m, "voice", None)
                if etat is not None and getattr(etat, "deaf", False):
                    continue
                deja.add(m.id)
                vus.append({"id": str(m.id),
                            "nom": getattr(m, "display_name", None) or str(m)})
        if vus:
            sv.pointer(vus, 60)

    # ------------------------------------------------------------------ #
    # Le resume du jour
    # ------------------------------------------------------------------ #
    async def _resume_si_lheure(self):
        cfg = sv.config()
        if not cfg.get("resume_actif"):
            return
        maintenant = _dt.datetime.now(sv._tz())
        if maintenant.hour != int(cfg.get("resume_heure", 8)):
            return
        # Le resume porte sur la journee ECOULEE : a huit heures du matin, ce
        # qui interesse le proprietaire est la nuit qui vient de passer, pas
        # la journee qui commence et dont aucune session n'a encore eu lieu.
        hier = (maintenant.date() - _dt.timedelta(days=1)).isoformat()
        for salon in self._salons_resume():
            cle = "%s:%s" % (getattr(salon.guild, "id", 0), hier)
            if self._resumes_faits.get(cle):
                continue
            try:
                await salon.send(embed=self.embed_resume(hier))
                self._resumes_faits[cle] = True
            except Exception as e:                   # noqa: BLE001
                print(f"[sessions] envoi resume : {e}", flush=True)

    def _salons_resume(self) -> list:
        """Les salons TEXTE ou poster, par convention de nom."""
        prefixe = _sans_accent(sv.config().get("salon_resume") or "session")
        out = []
        for c in self.bot.get_all_channels():
            if not isinstance(c, discord.TextChannel):
                continue
            if _sans_accent(getattr(c, "name", "")).startswith(prefixe):
                out.append(c)
        return out

    def embed_resume(self, jour: str) -> discord.Embed:
        """Le resume d'une journee, lisible d'un coup d'oeil.

        Public : c'est ce que le proprietaire lit le matin. On dit les
        presents, et on ne dit les absents QUE si on sait qui etait attendu --
        sinon « aucun absent » serait un mensonge tranquille.
        """
        att = self._attendus_enrichis()
        r = sv.resume_jour(jour, attendus=att)
        e = discord.Embed(
            title=f"Sessions du {jour}",
            description=(f"Heures en {r['fuseau']}. "
                         f"{len(att)} VA attendu(s)." if att else
                         f"Heures en {r['fuseau']}. Liste des VA attendus inconnue : "
                         f"seuls les presents sont fiables."),
            color=0x5865F2)
        for s in r["sessions"]:
            hl = s.get("heures_locales") or {}
            entete = "%s — %s" % (s["nom"], s["heure"])
            if hl.get("MG"):
                entete += "  (BJ %s · MG %s)" % (hl.get("BJ", "?"), hl["MG"])
            lignes = []
            if s["presents"]:
                lignes.append("**Présents (%d)** : %s" % (
                    len(s["presents"]),
                    ", ".join("%s (%d min)" % (p["nom"], p["secondes"] // 60)
                              for p in s["presents"][:20])))
            else:
                lignes.append("*Personne*")
            if s["partiels"]:
                lignes.append("Passés vite : " + ", ".join(
                    p["nom"] for p in s["partiels"][:12]))
            if s["attendus_connus"]:
                lignes.append("**Absents (%d)** : %s" % (
                    len(s["absents"]),
                    ", ".join(a["nom"] for a in s["absents"][:20]) or "aucun"))
            e.add_field(name=entete, value="\n".join(lignes)[:1000], inline=False)
        return e

    def _attendus_enrichis(self) -> list:
        """La liste des attendus, avec le vrai pseudo affiche sur Discord.

        users.json garde un nom qui peut dater. Le membre, lui, porte son nom
        actuel : c'est celui-la qu'on veut lire dans le resume.
        """
        att = sv.attendus()
        for a in att:
            try:
                for g in self.bot.guilds:
                    m = g.get_member(int(a["id"]))
                    if m is not None:
                        a["nom"] = getattr(m, "display_name", None) or a["nom"]
                        break
            except Exception:                        # noqa: BLE001
                pass
        return att

    async def poster_resume(self, jour: str = "") -> int:
        """Poste le resume sur demande (bouton du tableau de bord).

        Rend le nombre de salons servis : zero veut dire « aucun salon ne
        correspond a la convention de nom », ce que l'ecran doit pouvoir dire
        au lieu d'afficher un succes silencieux.
        """
        if not jour:
            jour = sv.jour_de(_t.time())
        n = 0
        for salon in self._salons_resume():
            try:
                await salon.send(embed=self.embed_resume(jour))
                n += 1
            except Exception as e:                   # noqa: BLE001
                print(f"[sessions] envoi manuel : {e}", flush=True)
        return n

    def etat_direct(self) -> dict:
        """Qui est dans les salons MAINTENANT, pour le bandeau du site.

        Lu a la demande : le registre ne sait que ce qui est deja compte, il
        ne peut pas dire « en ce moment ».
        """
        salons = []
        for ch in self._vocaux():
            gens = [{"id": str(m.id),
                     "nom": getattr(m, "display_name", None) or str(m)}
                    for m in (getattr(ch, "members", []) or [])
                    if not getattr(m, "bot", False)]
            salons.append({"salon": getattr(ch, "name", "?"),
                           "id": ch.id, "gens": gens})
        s = sv.en_cours()
        return {"session": s, "salons": salons,
                "total": sum(len(x["gens"]) for x in salons)}


async def setup(bot):
    await bot.add_cog(SessionsVoc(bot))
