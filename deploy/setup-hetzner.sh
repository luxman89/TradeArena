#!/usr/bin/env bash
# Hetzner VPS setup script for TradeArena
#
# IP-only mode (default — no domain yet):
#   scp -r . user@server:/opt/tradearena
#   ssh user@server 'cd /opt/tradearena && sudo bash deploy/setup-hetzner.sh'
#
# SSL mode (after domain + DNS configured):
#   ssh user@server 'cd /opt/tradearena && sudo bash deploy/setup-hetzner.sh --ssl'
#
# Prerequisites: .env file with at least POSTGRES_PASSWORD and TRADEARENA_SECRET_KEY.
# For SSL mode, DOMAIN must also be set.

set -euo pipefail

APP_DIR="/opt/tradearena"
ENV_FILE="$APP_DIR/.env"
SSL_MODE=false

if [ "${1:-}" = "--ssl" ]; then
    SSL_MODE=true
fi

# ---- Validate env ----
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found. Copy .env.production and fill in values."
    exit 1
fi

source "$ENV_FILE"

if [ -z "${POSTGRES_PASSWORD:-}" ]; then
    echo "ERROR: POSTGRES_PASSWORD not set in $ENV_FILE"
    exit 1
fi

if [ -z "${TRADEARENA_SECRET_KEY:-}" ]; then
    echo "ERROR: TRADEARENA_SECRET_KEY not set in $ENV_FILE"
    exit 1
fi

if $SSL_MODE && [ -z "${DOMAIN:-}" ]; then
    echo "ERROR: DOMAIN not set in $ENV_FILE (required for --ssl mode)"
    exit 1
fi

echo "==> Setting up TradeArena on $(hostname)"
echo "    Mode: $(if $SSL_MODE; then echo "SSL ($DOMAIN)"; else echo "IP-only (HTTP)"; fi)"

# ---- Install Docker if needed ----
if ! command -v docker &> /dev/null; then
    echo "==> Installing Docker..."
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    echo "==> Docker installed."
else
    echo "==> Docker already installed."
fi

# ---- Firewall ----
if command -v ufw &> /dev/null; then
    echo "==> Configuring firewall..."
    ufw allow 22/tcp
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw --force enable
fi

cd "$APP_DIR"

if $SSL_MODE; then
    # ---- SSL mode: obtain cert then launch with --profile ssl ----
    echo "==> Obtaining SSL certificate for $DOMAIN..."

    # Stop any running nginx to free port 80
    docker compose -f docker-compose.prod.yml stop nginx nginx-ssl 2>/dev/null || true

    docker run --rm \
        -v tradearena_certbot-certs:/etc/letsencrypt \
        -v tradearena_certbot-webroot:/var/www/certbot \
        -p 80:80 \
        certbot/certbot certonly \
        --standalone \
        --non-interactive \
        --agree-tos \
        --email "admin@$DOMAIN" \
        -d "$DOMAIN" \
        -d "www.$DOMAIN"

    echo "==> SSL certificate obtained."
    echo "==> Starting all services (SSL mode)..."

    # Stop IP-only nginx if running, start SSL stack
    docker compose -f docker-compose.prod.yml stop nginx 2>/dev/null || true
    docker compose -f docker-compose.prod.yml --profile ssl up -d --build

    echo ""
    echo "==> TradeArena is live!"
    echo "    https://$DOMAIN/health"
else
    # ---- IP-only mode: just launch with default nginx ----
    echo "==> Starting all services (IP-only mode)..."
    docker compose -f docker-compose.prod.yml up -d --build

    SERVER_IP=$(hostname -I | awk '{print $1}')
    echo ""
    echo "==> TradeArena is live!"
    echo "    http://$SERVER_IP/health"
    echo ""
    echo "    To enable SSL later:"
    echo "    1. Set DOMAIN in .env"
    echo "    2. Point DNS A record to $SERVER_IP"
    echo "    3. Run: sudo bash deploy/setup-hetzner.sh --ssl"
fi

echo ""
echo "    Useful commands:"
echo "    docker compose -f docker-compose.prod.yml logs -f app"
echo "    docker compose -f docker-compose.prod.yml exec app alembic current"
echo "    docker compose -f docker-compose.prod.yml restart app"
