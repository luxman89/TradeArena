#!/usr/bin/env bash
# deploy/deploy.sh — Automated production deploy for TradeArena
#
# Called by GitHub Actions deploy workflow via SSH.
# Can also be run manually: cd /opt/tradearena && bash deploy/deploy.sh
#
# What it does:
#   1. Pulls latest code from main
#   2. Tags current image for rollback
#   3. Rebuilds and restarts containers (alembic runs on startup via Dockerfile CMD)
#   4. Waits for health check
#
# Rollback: bash deploy/deploy.sh --rollback

set -euo pipefail

APP_DIR="/opt/tradearena"
COMPOSE_FILE="docker-compose.prod.yml"
HEALTH_URL="http://localhost:80/health"
HEALTH_TIMEOUT=60
ROLLBACK_TAG="tradearena-rollback"

cd "$APP_DIR"

# ---- Rollback mode ----
if [ "${1:-}" = "--rollback" ]; then
    echo "==> Rolling back to previous image..."
    if docker image inspect "$ROLLBACK_TAG:latest" &>/dev/null; then
        docker tag "$ROLLBACK_TAG:latest" "$(docker compose -f $COMPOSE_FILE images app --format '{{.Repository}}'):latest" 2>/dev/null || true
        docker compose -f "$COMPOSE_FILE" up -d --no-build app
        echo "==> Rollback complete. Check: curl $HEALTH_URL"
    else
        echo "ERROR: No rollback image found. Manual intervention required."
        exit 1
    fi
    exit 0
fi

# ---- Normal deploy ----
echo "==> Starting deploy at $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# 1. Pull latest code (force-sync to match remote exactly)
echo "==> Syncing to latest main..."
git fetch origin main
git reset --hard origin/main
git clean -fd

# 2. Tag current image for rollback
echo "==> Tagging current image for rollback..."
CURRENT_IMAGE=$(docker compose -f "$COMPOSE_FILE" images app --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | head -1 || true)
if [ -n "$CURRENT_IMAGE" ] && [ "$CURRENT_IMAGE" != ":" ]; then
    docker tag "$CURRENT_IMAGE" "$ROLLBACK_TAG:latest" 2>/dev/null || true
    echo "    Tagged $CURRENT_IMAGE as $ROLLBACK_TAG:latest"
else
    echo "    No existing image to tag (first deploy?)"
fi

# 3. Rebuild and restart
echo "==> Rebuilding and restarting containers..."
docker compose -f "$COMPOSE_FILE" build --no-cache app
docker compose -f "$COMPOSE_FILE" up -d app

# 4. Health check (internal — via nginx on port 80)
echo "==> Waiting for health check..."
ELAPSED=0
while [ $ELAPSED -lt $HEALTH_TIMEOUT ]; do
    if curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
        echo "==> Health check passed after ${ELAPSED}s"
        break
    fi
    sleep 3
    ELAPSED=$((ELAPSED + 3))
done

if [ $ELAPSED -ge $HEALTH_TIMEOUT ]; then
    echo "ERROR: Health check failed after ${HEALTH_TIMEOUT}s"
    echo "==> Auto-rolling back..."
    bash deploy/deploy.sh --rollback
    exit 1
fi

# 5. Reload Caddy config so X-Forwarded-Proto is forwarded correctly.
#    Caddy terminates TLS; without this header the app's security middleware
#    cannot know the connection is HTTPS, breaking HSTS and CORS.
#    This step is best-effort — a failure here does NOT roll back the deploy.
echo "==> Reloading Caddy config..."
CADDY_CADDYFILE="$APP_DIR/deploy/Caddyfile"
CADDY_RELOADED=false

if [ -f "$CADDY_CADDYFILE" ]; then
    # Find the Caddy container (try common names / image filter)
    CADDY_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E '^caddy$|^deploy[-_]caddy' | head -1 || true)
    if [ -z "$CADDY_CONTAINER" ]; then
        CADDY_CONTAINER=$(docker ps --filter ancestor=caddy --format '{{.Names}}' | head -1 || true)
    fi

    if [ -n "$CADDY_CONTAINER" ]; then
        echo "    Found Caddy container: $CADDY_CONTAINER"
        if docker cp "$CADDY_CADDYFILE" "$CADDY_CONTAINER:/etc/caddy/Caddyfile"; then
            echo "    Caddyfile copied. Validating..."
            docker exec "$CADDY_CONTAINER" caddy validate --config /etc/caddy/Caddyfile 2>&1 || true
            echo "    Attempting graceful reload (caddy reload)..."
            if docker exec "$CADDY_CONTAINER" caddy reload --config /etc/caddy/Caddyfile 2>&1; then
                CADDY_RELOADED=true
                echo "    Caddy config reloaded gracefully."
            else
                echo "    Graceful reload failed — falling back to container restart..."
                if docker restart "$CADDY_CONTAINER"; then
                    CADDY_RELOADED=true
                    echo "    Caddy container restarted."
                    # Brief wait for Caddy to come back and acquire TLS certs
                    sleep 5
                fi
            fi
        else
            echo "    WARNING: docker cp failed — cannot update Caddyfile"
        fi
    elif command -v caddy &>/dev/null && [ -d /etc/caddy ]; then
        # Caddy running as a host service
        cp "$CADDY_CADDYFILE" /etc/caddy/Caddyfile
        systemctl reload caddy 2>/dev/null && CADDY_RELOADED=true && echo "    Host Caddy reloaded." || true
    fi

    if [ "$CADDY_RELOADED" = "false" ]; then
        echo "    WARNING: Could not auto-reload Caddy. Run manually:"
        echo "      docker cp $CADDY_CADDYFILE <caddy-container>:/etc/caddy/Caddyfile"
        echo "      docker exec <caddy-container> caddy reload --config /etc/caddy/Caddyfile"
    fi
else
    echo "    No Caddyfile found at $CADDY_CADDYFILE — skipping."
fi

# 6. Network diagnostics (informational — confirms app is on Caddy network)
echo "==> Container network info:"
APP_CONTAINER=$(docker compose -f "$COMPOSE_FILE" ps --format '{{.Name}}' app 2>/dev/null | head -1 || echo "tradearena-app-1")
docker inspect "$APP_CONTAINER" --format '    Networks: {{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' 2>/dev/null || true

echo "==> Deploy complete at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
