#!/bin/sh
# One-time setup of a fresh Ubuntu 24.04 machine (an EC2 t3.medium is enough) to host Wingman:
# a local Convex backend, the Wingman server, and Caddy in front for https.
#
#   ssh ubuntu@HOST 'sh -s' < scripts/ec2-setup.sh DOMAIN
#
# DOMAIN is the name the phones use, e.g. 52-43-194-6.sslip.io for the address 52.43.194.6.
# Run scripts/deploy.sh afterwards to copy the code, the models and .env across.
set -eu
DOMAIN="${1:?usage: ec2-setup.sh DOMAIN}"
ARCH=x86_64
[ "$(uname -m)" = aarch64 ] && ARCH=aarch64

sudo apt-get update -q
sudo apt-get install -yq curl rsync xz-utils

# uv, for the Python server
if [ ! -x "$HOME/.local/bin/uv" ]; then
    mkdir -p "$HOME/.local/bin"
    curl -fsSL "https://github.com/astral-sh/uv/releases/latest/download/uv-$ARCH-unknown-linux-gnu.tar.gz" \
        | tar -xz --strip-components=1 -C "$HOME/.local/bin"
fi

# Node 22, for the Convex CLI and its local backend
if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]; then
    NODE_ARCH=x64; [ "$ARCH" = aarch64 ] && NODE_ARCH=arm64
    NODE=$(curl -fsSL https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt | grep -o "node-v[0-9.]*-linux-$NODE_ARCH.tar.xz" | head -1)
    curl -fsSL "https://nodejs.org/dist/latest-v22.x/$NODE" | sudo tar -xJ --strip-components=1 -C /usr/local
fi

# Caddy, for https with a certificate it fetches by itself
if ! command -v caddy >/dev/null; then
    CADDY_ARCH=amd64; [ "$ARCH" = aarch64 ] && CADDY_ARCH=arm64
    curl -fsSL "https://github.com/caddyserver/caddy/releases/download/v2.10.2/caddy_2.10.2_linux_$CADDY_ARCH.tar.gz" \
        | sudo tar -xz -C /usr/local/bin caddy
fi

mkdir -p "$HOME/wingman"

# Convex runs locally on 127.0.0.1:3210; `convex dev` also pushes convex/ whenever it changes.
sudo tee /etc/systemd/system/convex.service >/dev/null <<EOF
[Unit]
Description=Convex local backend for Wingman
After=network-online.target

[Service]
User=$USER
WorkingDirectory=$HOME/wingman
Environment=CONVEX_AGENT_MODE=anonymous
ExecStart=/usr/local/bin/npx convex dev --tail-logs disable
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/wingman.service >/dev/null <<EOF
[Unit]
Description=Wingman server
After=network-online.target convex.service

[Service]
User=$USER
WorkingDirectory=$HOME/wingman
ExecStart=$HOME/.local/bin/uv run uvicorn wingman.server:app --host 127.0.0.1 --port 8787 --proxy-headers
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/caddy.service >/dev/null <<EOF
[Unit]
Description=Caddy
After=network-online.target

[Service]
ExecStart=/usr/local/bin/caddy run --config /etc/caddy/Caddyfile
Restart=always
AmbientCapabilities=CAP_NET_BIND_SERVICE
Environment=HOME=/var/lib/caddy

[Install]
WantedBy=multi-user.target
EOF

sudo mkdir -p /etc/caddy /var/lib/caddy
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
$DOMAIN {
    reverse_proxy 127.0.0.1:8787
}
EOF

sudo systemctl daemon-reload
sudo systemctl enable convex wingman caddy
sudo systemctl restart caddy
echo "Set up. Now run scripts/deploy.sh to copy the code across."
