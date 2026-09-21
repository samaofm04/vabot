#!/bin/bash
# Auto-pull depuis GitHub, restart le bot si changements
cd /opt/va-bot
git fetch origin main > /dev/null 2>&1 || exit 0
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
if [ "$LOCAL" != "$REMOTE" ]; then
    echo "[$(date -Iseconds)] Update detecte: ${LOCAL:0:8} -> ${REMOTE:0:8}" >> /var/log/va-bot-deploy.log
    git reset --hard origin/main >> /var/log/va-bot-deploy.log 2>&1
    # Patchs perf locaux (voir /root/vabot-patches/README.md) : re-appliques
    # apres chaque reset TANT QU'ILS NE SONT PAS integres au depot GitHub.
    # Si un patch ne s'applique plus proprement (deja merge, ou conflit avec
    # un nouveau commit), il est IGNORE et note dans ce log — le deploiement
    # continue exactement comme avant, jamais bloque par un patch.
    for P in /root/vabot-patches/*.patch; do
        [ -e "$P" ] || continue
        if git apply --check "$P" 2>/dev/null; then
            if git apply "$P" 2>>/var/log/va-bot-deploy.log; then
                echo "[$(date -Iseconds)] patch local applique: $P" >> /var/log/va-bot-deploy.log
            else
                echo "[$(date -Iseconds)] patch local ECHEC A L'APPLICATION (apres check OK): $P" >> /var/log/va-bot-deploy.log
                date -Iseconds > "${P}.DROPPED"
            fi
        else
            echo "[$(date -Iseconds)] patch local IGNORE (deja integre ou conflit): $P" >> /var/log/va-bot-deploy.log
            # Sentinelle visible (le log tourne au bout de 7 jours, pas elle) :
            date -Iseconds > "${P}.DROPPED"
        fi
    done
    chown -R vabot:vabot /opt/va-bot/ 2>/dev/null
    if git diff --name-only ${LOCAL}..${REMOTE} | grep -q "requirements.txt"; then
        echo "[$(date -Iseconds)] requirements.txt change, reinstall deps" >> /var/log/va-bot-deploy.log
        /opt/va-bot/venv/bin/pip install -r /opt/va-bot/requirements.txt >> /var/log/va-bot-deploy.log 2>&1
    fi
    systemctl restart va-bot
    echo "[$(date -Iseconds)] Bot restarte" >> /var/log/va-bot-deploy.log
fi
