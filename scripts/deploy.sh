#!/bin/sh
# Copies the server code and the latest app build to the hosted machine and restarts Wingman.
# Settings (.env) and saved sign-ins on the server are left alone.
#
#   WINGMAN_HOST=user@host ./scripts/deploy.sh
#   WINGMAN_HOST=user@host WINGMAN_SSH_KEY=~/.ssh/id_ed25519 ./scripts/deploy.sh
#
# WINGMAN_HOST may also be set in .env.
set -e
cd "$(dirname "$0")/.."
HOST="${WINGMAN_HOST:-$(grep '^WINGMAN_HOST=' .env 2>/dev/null | cut -d= -f2)}"
KEY="${WINGMAN_SSH_KEY:-$(grep '^WINGMAN_SSH_KEY=' .env 2>/dev/null | cut -d= -f2)}"
[ -n "$HOST" ] || { echo "Set WINGMAN_HOST (user@host) in the environment or in .env"; exit 1; }
SSH="ssh -o BatchMode=yes"
[ -n "$KEY" ] && SSH="$SSH -o IdentitiesOnly=yes -i $(eval echo "$KEY")"
rsync -az -e "$SSH" --delete --exclude '__pycache__' wingman web models pyproject.toml uv.lock "$HOST":wingman/
APK=android/app/build/outputs/apk/debug/app-debug.apk
[ -f "$APK" ] && rsync -az -e "$SSH" "$APK" "$HOST":wingman/android/app/build/outputs/apk/debug/
$SSH "$HOST" 'cd ~/wingman && ~/.local/bin/uv sync --frozen -q && sudo systemctl restart wingman && sleep 8 && systemctl is-active wingman && curl -s -o /dev/null -w "server %{http_code}\n" localhost:8787/api/home'
