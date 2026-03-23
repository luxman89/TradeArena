#!/usr/bin/env bash
# Start the TradeArena Community Manager Discord bot.
# Usage: ./services/discord_bot/run.sh
#
# Requires DISCORD_BOT_TOKEN in /opt/tradearena/.env or environment.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Load .env if present
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

if [ -z "${DISCORD_BOT_TOKEN:-}" ]; then
    echo "ERROR: DISCORD_BOT_TOKEN is not set" >&2
    exit 1
fi

cd "$PROJECT_DIR"
exec "$PROJECT_DIR/.venv/bin/python" -m services.discord_bot.bot
