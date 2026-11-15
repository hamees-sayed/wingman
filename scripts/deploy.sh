#!/bin/sh
# Copies the server code and the latest app build to the hosted machine and restarts Wingman.
# Settings (.env) and saved sign-ins on the server are left alone.
set -e
cd "$(dirname "$0")/.."
HOST=ubuntu@151.185.34.130
SSH="ssh -o BatchMode=yes -o IdentitiesOnly=yes -i $HOME/.ssh/id_rsa_rsa"
rsync -az -e "$SSH" --delete --exclude '__pycache__' wingman web models pyproject.toml uv.lock "$HOST":wingman/
rsync -az -e "$SSH" android/app/build/outputs/apk/debug/app-debug.apk "$HOST":wingman/android/app/build/outputs/apk/debug/
$SSH "$HOST" 'cd ~/wingman && ~/.local/bin/uv sync --frozen -q && sudo systemctl restart wingman && sleep 8 && systemctl is-active wingman && curl -s -o /dev/null -w "server %{http_code}\n" localhost:8787/api/home'
