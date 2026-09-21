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
import json
from pathlib import Path
import time as _t

import discord
from discord.ext import commands, tasks

import sessions_voc as sv


# Une seule definition du nettoyage de nom, dans sessions_voc : deux copies,
# c'est deux comportements le jour ou l'une des deux change.
_sans_accent = sv.sans_accent

FICHIER_APERCUS = Path("data") / "sessions_apercus.json"


class SessionAbsentsView(discord.ui.View):
    """Bouton persistant des essais de mise en page, liés à un message précis.

    Les identifiants sont figés avec le bilan : un clic ne recalcule jamais
    les absences historiques avec la liste des VA du jour.
    """

    def __init__(self, count=None):
        super().__init__(timeout=None)
        if count is not None:
            self.absents.label = "Voir les %d absents" % count

    @discord.ui.button(label="Voir les absents", style=discord.ButtonStyle.secondary,
                       custom_id="sessions:absents:v1")
    async def absents(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            data = json.loads(FICHIER_APERCUS.read_text(encoding="utf-8"))
            message = interaction.message
            record = data["messages"][str(message.id)]
            ids = record["absent_ids"]
            valide = (
                data.get("schema") == 1
                and interaction.guild_id == sv.SUIVI_GUILD_ID
                and str(interaction.guild_id) == record["guild_id"]
                and str(interaction.channel_id) == record["channel_id"]
                and str(message.author.id) == record["author_id"]
                and message.author.id == interaction.client.user.id
                and isinstance(ids, list) and len(ids) <= 100
                and all(isinstance(uid, str) and uid.isdigit() and 16 <= len(uid) <= 20 for uid in ids)
                and len(ids) == len(set(ids))
            )
            if not valide:
                raise ValueError("Contexte du bilan invalide")
            titre = str(record["session"])[:100]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            await interaction.followup.send(
                "La liste de ce bilan est indisponible pour le moment.",
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            return
        embed = discord.Embed(title="Absents · %s" % titre, color=0x9AA0A6)
        SessionsVoc._ajouter_lignes(embed, "%d absent(s)" % len(ids),
                                   ["<@%s>" % uid for uid in ids] or ["Aucun"])
        embed.set_footer(text="Jessye US · Youl4b")
        await interaction.followup.send(embed=embed, ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())
        print("[sessions] détail des absents affiché : message %s, %d personnes"
              % (message.id, len(ids)), flush=True)


class SessionBilanView(discord.ui.View):
    """Quatre boutons persistants, avec les détails figés du bilan affiché."""

    def __init__(self):
        super().__init__(timeout=None)

    @staticmethod
    def detail_embed(record, sid):
        if record.get("kind") != "bilan" or sid not in {"s1", "s2", "s3", "s4"}:
            raise ValueError("Type de bilan invalide")
        jour = _dt.date.fromisoformat(record["jour"])
        session = record["sessions"][sid]
        heure = _dt.time.fromisoformat(session["heure"]).strftime("%H:%M")
        presents, partiels, absents = (session[k] for k in ("presents", "partiels", "absent_ids"))
        if not all(isinstance(rows, list) for rows in (presents, partiels, absents)):
            raise ValueError("Listes invalides")
        ids = [row["id"] for row in presents + partiels] + absents
        if (len(ids) > 100 or len(ids) != len(set(ids)) or
                not all(isinstance(uid, str) and uid.isdigit() and 16 <= len(uid) <= 20 for uid in ids)):
            raise ValueError("Identifiants invalides")
        for row in presents + partiels:
            if type(row["minutes"]) is not int or not 0 <= row["minutes"] <= 1440:
                raise ValueError("Durée invalide")

        def ligne(row):
            minutes = row["minutes"]
            duree = "%d min" % minutes if minutes < 60 else "%d h %02d" % divmod(minutes, 60)
            return "<@%s> — **%s**" % (row["id"], duree)

        embed = discord.Embed(title="Session %s · %s" % (sid[1:], heure),
            description="%s · heure du Bénin" % jour.strftime("%d/%m/%Y"), color=0x9AA0A6)
        SessionsVoc._ajouter_lignes(embed, "Présents (%d)" % len(presents),
                                   [ligne(row) for row in presents] or ["Aucun"])
        if partiels:
            SessionsVoc._ajouter_lignes(embed, "Passages courts (%d)" % len(partiels),
                                       [ligne(row) for row in partiels])
        SessionsVoc._ajouter_lignes(embed, "Absents (%d)" % len(absents),
                                   ["<@%s>" % uid for uid in absents] or ["Aucun"])
        embed.set_footer(text="Jessye US · Youl4b · bilan définitif")
        if len(embed) > 6000 or len(embed.fields) > 25:
            raise ValueError("Bilan trop long")
        return embed

    async def _afficher(self, interaction, sid):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            data = json.loads(FICHIER_APERCUS.read_text(encoding="utf-8"))
            message = interaction.message
            record = data["messages"][str(message.id)]
            if not (data.get("schema") == 1
                    and interaction.guild_id == sv.SUIVI_GUILD_ID
                    and str(interaction.guild_id) == record["guild_id"]
                    and str(interaction.channel_id) == record["channel_id"]
                    and str(message.author.id) == record["author_id"]
                    and message.author.id == interaction.client.user.id):
                raise ValueError("Contexte du bilan invalide")
            embed = self.detail_embed(record, sid)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            await interaction.followup.send("Les détails de cette session sont indisponibles pour le moment.",
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            return
        await interaction.followup.send(embed=embed, ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())
        print("[sessions] détail du bilan affiché : message %s, %s" % (message.id, sid), flush=True)

    @discord.ui.button(label="Session 1", style=discord.ButtonStyle.secondary, custom_id="sessions:bilan:v1:s1")
    async def session1(self, interaction, button):
        await self._afficher(interaction, "s1")

    @discord.ui.button(label="Session 2", style=discord.ButtonStyle.secondary, custom_id="sessions:bilan:v1:s2")
    async def session2(self, interaction, button):
        await self._afficher(interaction, "s2")

    @discord.ui.button(label="Session 3", style=discord.ButtonStyle.secondary, custom_id="sessions:bilan:v1:s3")
    async def session3(self, interaction, button):
        await self._afficher(interaction, "s3")

    @discord.ui.button(label="Session 4", style=discord.ButtonStyle.secondary, custom_id="sessions:bilan:v1:s4")
    async def session4(self, interaction, button):
        await self._afficher(interaction, "s4")


class SessionsVoc(commands.Cog):
    """Pointage des sessions vocales. Zero commande slash."""

    def __init__(self, bot):
        self.bot = bot
        # Ce qu'on a deja poste, pour ne pas resservir le meme resume a chaque
        # tour de boucle : { "<guild>:<jour>" : True }
        self._resumes_faits = {}
        self.boucle.start()

    async def cog_load(self):
        self._absents_view = SessionAbsentsView()
        self.bot.add_view(self._absents_view)
        self._bilan_view = SessionBilanView()
        self.bot.add_view(self._bilan_view)
        print("[sessions] bouton des absents enregistré", flush=True)
        print("[sessions] boutons du bilan enregistrés", flush=True)

    def cog_unload(self):
        self.boucle.cancel()
        if getattr(self, "_absents_view", None) is not None:
            self._absents_view.stop()
        if getattr(self, "_bilan_view", None) is not None:
            self._bilan_view.stop()

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
            if getattr(getattr(c, "guild", None), "id", None) != sv.SUIVI_GUILD_ID:
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
        if not self.bot.is_ready():
            return  # Le cache vocal déconnecté ne constitue pas une présence.
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
        self._attendus_enrichis()

    def _pointer(self):
        """Une minute de presence pour chacun de ceux qui sont la.

        On ne compte NI les bots NI les gens sourds cote serveur : un compte
        laisse connecte toute la nuit dans un salon n'a assiste a rien, et le
        faire figurer parmi les presents fausserait le seul chiffre que le
        proprietaire va regarder.
        """
        if sv.session_a(_t.time()) is None:
            return                                    # hors creneau : rien a noter
        attendus = {a["id"]: a for a in self._attendus_enrichis()}
        vus, deja = [], set()
        for ch in self._vocaux():
            for m in getattr(ch, "members", []) or []:
                if getattr(m, "bot", False) or m.id in deja or str(m.id) not in attendus:
                    continue
                etat = getattr(m, "voice", None)
                if etat is not None and getattr(etat, "deaf", False):
                    continue
                deja.add(m.id)
                vus.append({"id": str(m.id),
                            "nom": attendus[str(m.id)]["nom"]})
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
                # Un redémarrage pendant l'heure du bilan vide la mémoire.
                # Retrouver le message déjà publié avant d'en créer un autre.
                deja_publie = False
                async for msg in salon.history(limit=20):
                    if msg.author.id == self.bot.user.id and any(
                            e.title == "Sessions du %s" % hier for e in msg.embeds):
                        deja_publie = True
                        break
                if deja_publie:
                    self._resumes_faits[cle] = True
                    continue
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
            if getattr(getattr(c, "guild", None), "id", None) != sv.SUIVI_GUILD_ID:
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
        att = self._attendus_enrichis()
        noms = {a["id"]: a["nom"] for a in att}
        maintenant = _tD.time()
        gens = sorted(
            ({"id": k, "nom": noms[k],
              "secondes": int(v.get("secondes") or 0),
              "premiere": v.get("premiere"), "derniere": v.get("derniere")}
             for k, v in brut.items() if k in noms),
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
            self._ajouter_lignes(e, "Présents (%d)" % len(presents),
                                 [self._ligne_presence(g, maintenant, fige) for g in presents])
        else:
            e.add_field(name="Présents (0)", value="*personne pour l'instant*",
                        inline=False)
        if partiels:
            # LE TEMPS AUSSI, ICI. Une liste de noms nus laisse croire que
            # tous ont fait la meme chose : deux minutes et quarante secondes
            # ne se valent pas, et c'est ce chiffre qui dit s'il faut leur en
            # parler.
            self._ajouter_lignes(e, "Passés vite (%d)" % len(partiels),
                                 ["%s (%d min)" % (self._personne(g), g["secondes"] // 60)
                                  for g in partiels])
        if fige:
            if att:
                vus = {g["id"] for g in gens}
                absents = [a for a in att if str(a["id"]) not in vus]
                self._ajouter_lignes(e, "Absents (%d)" % len(absents),
                                     [self._personne(a) for a in absents] or ["aucun"])
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

        bouts = [self._personne(g)]
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
            salon = self.bot.get_channel(int(fiche.get("salon") or 0))
            if getattr(getattr(salon, "guild", None), "id", None) != sv.SUIVI_GUILD_ID:
                continue
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
            if salon is None or getattr(getattr(salon, "guild", None), "id", None) != sv.SUIVI_GUILD_ID:
                return None
            return await salon.fetch_message(int(fiche.get("message") or 0))
        except Exception:                            # noqa: BLE001
            return None

    def embed_resume(self, jour: str) -> discord.Embed:
        """Le bilan d'une journee : une ligne par personne, une pastille.

        LE PREMIER BILAN ETAIT ILLISIBLE. Les absents arrivaient en une seule
        phrase separee par des virgules -- cent soixante-dix-neuf noms colles,
        qu'on ne pouvait ni parcourir ni compter. Le proprietaire a demande
        des retours a la ligne et des pastilles ; c'est la bonne forme, parce
        qu'on lit une liste de gens en la balayant, pas en la lisant.

        Vert = present. Rouge = absent. Orange = passe sans rester.
        """
        att = self._attendus_enrichis()
        r = sv.resume_jour(jour, attendus=att, limiter_aux_attendus=True)
        e = discord.Embed(
            title="Sessions du %s" % jour,
            description=("Jessye US · Youl4b. Heures en %s. %d VA attendu(s)." % (r["fuseau"], len(att))
                         if att else
                         "Heures en %s. Liste des VA attendus inconnue : seuls "
                         "les presents sont fiables." % r["fuseau"]),
            color=0x5865F2)
        for s2 in r["sessions"]:
            hl = s2.get("heures_locales") or {}
            entete = "%s — %s" % (s2["nom"], s2["heure"])
            if hl.get("MG"):
                entete += "  (BJ %s · MG %s)" % (hl.get("BJ", "?"), hl["MG"])
            self._ajouter_lignes(e, entete, self._corps_session(s2, complet=True).splitlines())
        return e

    def _corps_session(self, s2: dict, complet=False) -> str:
        """Le contenu d'une session : une personne par ligne, ou un mot.

        Discord plafonne un champ a 1024 caracteres. On coupe donc, mais on
        DIT combien de lignes manquent : une liste tronquee en silence se lit
        comme une liste complete, et c'est elle qu'on croira.
        """
        if not s2.get("surveillee", True):
            return ("*Session non surveillée — le suivi ne tournait pas encore. "
                    "Aucun absent ne peut en être déduit.*")
        if not s2.get("terminee", True):
            # ELLE N'A PAS ENCORE EU LIEU, ou elle est en cours. Le premier
            # bilan accusait 179 personnes d'avoir manque une session qui
            # commencait huit heures plus tard.
            if s2["presents"] or s2["partiels"]:
                lignes = [self._ligne_pastille(g, "🟢") for g in s2["presents"]]
                lignes += [self._ligne_pastille(g, "🟠") for g in s2["partiels"]]
                return "\n".join(["*En cours…*"] + lignes) if complet else self._plafonner(["*En cours…*"] + lignes)
            return "*Pas encore commencée.*"
        lignes = [self._ligne_pastille(g, "🟢") for g in s2["presents"]]
        lignes += [self._ligne_pastille(g, "🟠") for g in s2["partiels"]]
        if s2.get("attendus_connus"):
            lignes += ["🔴 %s" % self._personne(a) for a in s2["absents"]]
        if not lignes:
            return "*Personne.*"
        if not s2.get("attendus_connus"):
            lignes.append("*Liste des VA attendus inconnue : les absents ne "
                          "peuvent pas être établis.*")
        return "\n".join(lignes) if complet else self._plafonner(lignes)

    @staticmethod
    def _personne(g: dict) -> str:
        nom = discord.utils.escape_mentions(discord.utils.escape_markdown(str(g.get("nom") or "")))
        uid = str(g.get("id") or "")
        return "%s · <@%s>" % (nom, uid) if uid.isdigit() else nom

    @staticmethod
    def _ajouter_lignes(embed, titre, lignes):
        """Découpe entre les personnes : une mention n'est jamais tronquée."""
        morceaux, courant = [], []
        for ligne in lignes:
            if len(ligne) > 1024:
                raise ValueError("Une ligne du bilan dépasse la limite Discord")
            if courant and len("\n".join(courant + [ligne])) > 1024:
                morceaux.append("\n".join(courant))
                courant = []
            courant.append(ligne)
        if courant:
            morceaux.append("\n".join(courant))
        for i, texte in enumerate(morceaux):
            embed.add_field(name=titre if i == 0 else titre + " (suite)", value=texte, inline=False)

    @staticmethod
    def _ligne_pastille(g: dict, pastille: str) -> str:
        m = int(g.get("secondes") or 0) // 60
        duree = "%d min" % m if m < 60 else "%d h %02d" % (m // 60, m % 60)
        return "%s %s — %s" % (pastille, SessionsVoc._personne(g), duree)

    @staticmethod
    def _plafonner(lignes, limite: int = 1010) -> str:
        """Colle les lignes sans depasser le champ, et dit ce qui manque."""
        out, total = [], 0
        for i, l in enumerate(lignes):
            if total + len(l) + 1 > limite - 40:
                reste = len(lignes) - i
                out.append("*… et %d de plus (voir la page Sessions)*" % reste)
                break
            out.append(l)
            total += len(l) + 1
        return "\n".join(out)

    def _attendus_enrichis(self) -> list:
        """Les personnes de Jessye, nommées comme sur le site, sur Youl4b."""
        if self.bot is None or not self.bot.is_ready():
            return []
        guilde = self.bot.get_guild(sv.SUIVI_GUILD_ID)
        if guilde is None or not guilde.chunked:
            return []  # Ne pas établir une liste avec un cache incomplet.
        attendus = sv.attendus_jessye(guilde.members)
        signature = tuple((a["id"], a["nom"]) for a in attendus)
        if signature != getattr(self, "_roster_signature", None):
            self._roster_signature = signature
            print("[sessions] Jessye US / Youl4b : %d personnes attendues" % len(attendus), flush=True)
        return attendus

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
        noms = {a["id"]: a["nom"] for a in self._attendus_enrichis()}
        for ch in self._vocaux():
            gens = [{"id": str(m.id), "nom": noms[str(m.id)]}
                    for m in (getattr(ch, "members", []) or [])
                    if str(m.id) in noms and not getattr(m, "bot", False)
                    and not getattr(getattr(m, "voice", None), "deaf", False)]
            salons.append({"salon": getattr(ch, "name", "?"),
                           "id": ch.id, "gens": gens})
        s = sv.en_cours()
        return {"session": s, "salons": salons,
                "total": sum(len(x["gens"]) for x in salons)}


async def setup(bot):
    await bot.add_cog(SessionsVoc(bot))
