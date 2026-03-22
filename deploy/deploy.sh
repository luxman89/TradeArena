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

# 1. Pull latest code
echo "==> Pulling latest from main..."
git pull origin main

# 2. Tag current image for rollback
echo "==> Tagging current image for rollback..."
CURRENT_IMAGE=$(docker compose -f "$COMPOSE_FILE" images app --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | head -1)
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

# 4. Health check
echo "==> Waiting for health check..."
ELAPSED=0
while [ $ELAPSED -lt $HEALTH_TIMEOUT ]; do
    if curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
        echo "==> Health check passed after ${ELAPSED}s"
        echo "==> Deploy complete at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
        exit 0
    fi
    sleep 3
    ELAPSED=$((ELAPSED + 3))
done

echo "ERROR: Health check failed after ${HEALTH_TIMEOUT}s"
echo "==> Auto-rolling back..."
bash deploy/deploy.sh --rollback
exit 1
