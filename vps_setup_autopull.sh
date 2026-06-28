#!/bin/bash
# Setup auto-deploy depuis GitHub sur le VPS - v2 avec fix safe.directory
# A coller dans le Terminal Hostinger UNE SEULE FOIS.

set -e

REPO_URL="https://github.com/samaofm04/vabot.git"
BOT_DIR="/opt/va-bot"
LOG_DEPLOY="/var/log/va-bot-deploy.log"

echo "==========================================="
echo " VA Bot - Setup auto-deploy GitHub"
echo "==========================================="

# FIX: autoriser git a travailler dans un dossier dont root n'est pas owner
git config --global --add safe.directory $BOT_DIR

# 1. Install git
echo "[1/7] Installation de git..."
apt install -y git > /dev/null 2>&1

# 2. Stop bot
echo "[2/7] Arret du bot (si pas deja stoppe)..."
systemctl stop va-bot 2>/dev/null || true

# 3. Backup .env
echo "[3/7] Backup .env..."
cp $BOT_DIR/.env /tmp/va-bot.env.backup 2>/dev/null || true

# 4. Init git si pas deja, configurer remote
echo "[4/7] Configuration git..."
cd $BOT_DIR

if [ ! -d ".git" ]; then
    git init -b main > /dev/null
fi

git remote remove origin 2>/dev/null || true
git remote add origin $REPO_URL

# 5. Pull
echo "[5/7] Pull du code depuis GitHub..."
git fetch origin main
git reset --hard origin/main

# Restaurer .env si besoin
if [ ! -f $BOT_DIR/.env ] && [ -f /tmp/va-bot.env.backup ]; then
    cp /tmp/va-bot.env.backup $BOT_DIR/.env
    chmod 600 $BOT_DIR/.env
fi

# 6. Auto-pull script
echo "[6/7] Creation du script auto-pull..."
cat > $BOT_DIR/auto_pull.sh << 'PULLEOF'
#!/bin/bash
# Auto-pull depuis GitHub, restart le bot si changements
git config --global --add safe.directory /opt/va-bot 2>/dev/null
cd /opt/va-bot
git fetch origin main > /dev/null 2>&1 || exit 0
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
if [ "$LOCAL" != "$REMOTE" ]; then
    echo "[$(date -Iseconds)] Update detecte: ${LOCAL:0:8} -> ${REMOTE:0:8}" >> /var/log/va-bot-deploy.log
    git reset --hard origin/main >> /var/log/va-bot-deploy.log 2>&1
    chown -R vabot:vabot /opt/va-bot/ 2>/dev/null
    if git diff --name-only ${LOCAL}..${REMOTE} | grep -q "requirements.txt"; then
        echo "[$(date -Iseconds)] requirements.txt change, reinstall deps" >> /var/log/va-bot-deploy.log
        /opt/va-bot/venv/bin/pip install -r /opt/va-bot/requirements.txt >> /var/log/va-bot-deploy.log 2>&1
    fi
    systemctl restart va-bot
    echo "[$(date -Iseconds)] Bot restarte" >> /var/log/va-bot-deploy.log
fi
PULLEOF
chmod +x $BOT_DIR/auto_pull.sh
touch $LOG_DEPLOY

# 7. Cron
echo "[7/7] Configuration du cron..."
(crontab -l 2>/dev/null | grep -v 'auto_pull.sh' ; echo "* * * * * /opt/va-bot/auto_pull.sh") | crontab -

# Permissions + restart
chown -R vabot:vabot $BOT_DIR/
systemctl start va-bot

sleep 6
echo ""
echo "==========================================="
echo " RESULTAT"
echo "==========================================="
echo "Repo configure: $REPO_URL"
echo ""
echo "Status bot:"
systemctl is-active va-bot
echo ""
echo "Cron actif:"
crontab -l | grep auto_pull || echo "AUCUN CRON !"
echo ""
echo "Derniers logs du bot:"
tail -8 /var/log/va-bot.log
echo ""
echo "==========================================="
echo " C EST FAIT, tu peux fermer le terminal."
echo " Plus jamais de copier-coller VPS."
echo "==========================================="
