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
            await self._direct()
        except Exception as e:                       # noqa: BLE001
            print(f"[sessions] direct : {e}", flush=True)
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

    def _salons_texte(self, motif: str, exclure: str = "") -> list:
        """Les salons TEXTE dont le nom porte `motif` (et pas `exclure`).

        L'exclusion n'est pas une precaution theorique : des que le
        proprietaire cree « session-bilan », ce salon porte AUSSI « session ».
        Sans l'exclure, le message en direct de chaque session irait
        s'empiler dans le salon du bilan.
        """
        out = []
        for c in self.bot.get_all_channels():
            if not isinstance(c, discord.TextChannel):
                continue
            if sv.salon_texte_ok(getattr(c, "name", ""), motif, exclure):
                out.append(c)
        return out

    def _salons_resume(self) -> list:
        """Ou va le BILAN de la journee."""
        return self._salons_texte(sv.config().get("salon_bilan") or "bilan")

    def _salons_direct(self) -> list:
        """Ou va le message EN DIRECT — jamais dans le salon du bilan."""
        cfg = sv.config()
        return self._salons_texte(cfg.get("salon_direct") or "session",
                                  exclure=cfg.get("salon_bilan") or "bilan")

    def embed_direct(self, session: dict, fige: bool = False) -> discord.Embed:
        """Ce qui s'affiche pendant la session, et ce qui reste apres.

        Le MEME message sert aux deux : tant que la session tourne il est
        reecrit, et au dernier passage il devient le compte rendu definitif.
        Deux messages -- un « en cours » puis un « bilan » -- auraient laisse
        le premier mentir pour toujours dans l'historique du salon.
        """
        import time as _tD
        jour, sid = session["jour"], session["id"]
        brut = sv.presences(jour, sid)
        maintenant = _tD.time()
        gens = sorted(
            ({"id": k, "nom": v.get("nom") or k,
              "secondes": int(v.get("secondes") or 0),
              "premiere": v.get("premiere"), "derniere": v.get("derniere")}
             for k, v in brut.items()),
            key=lambda g: -g["secondes"])
        seuil = sv.config()["presence_min_secondes"]
        presents = [g for g in gens if g["secondes"] >= seuil]
        partiels = [g for g in gens if g["secondes"] < seuil]
        hl = sv.heures_locales(session)
        e = discord.Embed(
            title="%s — %02d:%02d" % (session["nom"], session["heure"], session["minute"]),
            color=0x9AA0A6 if fige else 0x22C55E)
        e.description = ("Terminée." if fige else "En cours…") + \
            "  ·  BJ %s · MG %s" % (hl.get("BJ", "?"), hl.get("MG", "?"))
        if presents:
            e.add_field(
                name="Présents (%d)" % len(presents),
                value="\n".join(self._ligne_presence(g, maintenant, fige)
                                for g in presents[:25])[:1020],
                inline=False)
        else:
            e.add_field(name="Présents (0)", value="*personne pour l'instant*",
                        inline=False)
        if partiels:
            # LE TEMPS AUSSI, ICI. Une liste de noms nus laisse croire que
            # tous ont fait la meme chose : deux minutes et quarante secondes
            # ne se valent pas, et c'est ce chiffre qui dit s'il faut leur en
            # parler.
            e.add_field(
                name="Passés vite (%d)" % len(partiels),
                value=", ".join("%s (%d min)" % (g["nom"], g["secondes"] // 60)
                                for g in partiels[:25])[:1020],
                inline=False)
        if fige:
            att = self._attendus_enrichis()
            if att:
                vus = {g["id"] for g in gens}
                absents = [a["nom"] for a in att if str(a["id"]) not in vus]
                e.add_field(name="Absents (%d)" % len(absents),
                            value=(", ".join(absents[:30]) or "aucun")[:1020],
                            inline=False)
            e.set_footer(text="Compte définitif — ce message ne bouge plus.")
        else:
            e.set_footer(text="Mis à jour toutes les %d min."
                              % sv.config()["maj_minutes"])
        return e

    def _ligne_presence(self, g, maintenant: float, fige: bool = False) -> str:
        """« Ana · arrivé 23:12 · 47 min » — et « parti 00:05 » s'il est sorti.

        TROIS FAITS, PAS UN. Le pseudo seul ne dit pas si quelqu'un a fait
        acte de presence ou s'il a tenu la session ; la duree seule ne dit pas
        s'il etait la au debut ou s'il est arrive a la fin. Et sans l'heure de
        SORTIE, un message fige laisserait croire que tout le monde etait
        encore la quand il s'est arrete.

        « Encore la » se lit sur le dernier relevé : le pointage passe chaque
        minute, donc au-dela de deux minutes sans etre vu, la personne est
        partie. On ne se fie pas a un evenement de deconnexion, qui se perd.
        """
        import datetime as _dL
        tz = sv._tz()

        def _h(ts):
            try:
                return _dL.datetime.fromtimestamp(float(ts), tz).strftime("%H:%M")
            except (TypeError, ValueError):
                return "?"

        bouts = ["**%s**" % g["nom"]]
        if g.get("premiere"):
            bouts.append("arrivé %s" % _h(g["premiere"]))
        minutes = int(g.get("secondes") or 0) // 60
        bouts.append("%d min" % minutes if minutes < 60
                     else "%d h %02d" % (minutes // 60, minutes % 60))
        derniere = g.get("derniere")
        try:
            parti = derniere is not None and (maintenant - float(derniere)) > 120
        except (TypeError, ValueError):
            parti = False
        if parti or fige:
            bouts.append("parti %s" % _h(derniere))
        else:
            bouts.append("**encore là**")
        return "• " + " · ".join(bouts)

    async def _direct(self):
        """Poser le message, le reecrire, puis le figer. Dans cet ordre.

        Le gel passe AVANT la mise a jour : une session qui vient de se
        terminer doit recevoir son dernier compte, meme si une autre commence
        dans la foulee.
        """
        import time as _tD
        cfg = sv.config()
        if not cfg.get("direct_actif"):
            return
        maintenant = _tD.time()

        # --- ce qui est termine : un dernier passage, puis plus jamais -----
        for cle, fiche in sv.direct_a_figer(maintenant):
            msg = await self._retrouver(fiche)
            jour, sid = str(cle).split(":", 1)
            sess = next((x for x in sv.sessions_du_jour(jour) if x["id"] == sid), None)
            if msg is not None and sess is not None:
                try:
                    await msg.edit(embed=self.embed_direct(sess, fige=True))
                except Exception as e:               # noqa: BLE001
                    print(f"[sessions] gel : {e}", flush=True)
            sv.direct_poser(cle, dict(fiche, fige=True, maj=maintenant))

        # --- ce qui tourne : poser, ou reecrire si l'heure est venue ------
        sess = sv.session_a(maintenant)
        if sess is None:
            return
        cle = sv.direct_cle(sess)
        fiche = sv.direct_charger().get(cle)
        if fiche is None:
            for salon in self._salons_direct():
                try:
                    msg = await salon.send(embed=self.embed_direct(sess))
                except Exception as e:               # noqa: BLE001
                    print(f"[sessions] pose direct : {e}", flush=True)
                    continue
                sv.direct_poser(cle, {"salon": salon.id, "message": msg.id,
                                      "fin": sess["fin"], "maj": maintenant,
                                      "fige": False})
                break                                 # un seul message, pas un par salon
            return
        if fiche.get("fige"):
            return
        if (maintenant - float(fiche.get("maj") or 0)) < cfg["maj_minutes"] * 60:
            return
        msg = await self._retrouver(fiche)
        if msg is None:
            return
        try:
            await msg.edit(embed=self.embed_direct(sess))
            sv.direct_poser(cle, dict(fiche, maj=maintenant))
        except Exception as e:                       # noqa: BLE001
            print(f"[sessions] maj direct : {e}", flush=True)

    async def _retrouver(self, fiche: dict):
        """Le message deja poste, ou None s'il a ete supprime.

        Supprimer le message a la main est un droit : on ne le reposte pas,
        on laisse la session sans direct. Le registre des presences, lui,
        continue de compter -- l'affichage n'est pas la mesure.
        """
        try:
            salon = self.bot.get_channel(int(fiche.get("salon") or 0))
            if salon is None:
                return None
            return await salon.fetch_message(int(fiche.get("message") or 0))
        except Exception:                            # noqa: BLE001
            return None

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
