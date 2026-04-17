#!/usr/bin/env bash
# Nightly encrypted PostgreSQL backup for TradeArena.
#
# Usage:
#   ./deploy/backup.sh              # run normally
#   ./deploy/backup.sh --restore    # list available backups + restore instructions
#
# Environment variables (set in /etc/environment or .env):
#   POSTGRES_PASSWORD   — required: postgres superuser password
#   BACKUP_ENCRYPTION_KEY — required: passphrase for AES-256 encryption
#   BACKUP_DIR          — optional: local backup directory (default: /opt/tradearena/backups)
#   BACKUP_RETENTION_DAYS — optional: days to keep local backups (default: 7)
#   BACKUP_S3_BUCKET    — optional: s3://bucket/path or rclone remote:path for off-box upload
#
# Add to host crontab for nightly runs:
#   0 3 * * * /bin/bash /opt/tradearena/deploy/backup.sh >> /var/log/tradearena-backup.log 2>&1

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/tradearena/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/tradearena_${TIMESTAMP}.sql.gz.enc"
COMPOSE_FILE="/opt/tradearena/docker-compose.prod.yml"

# ── Preflight checks ──────────────────────────────────────────────────────

if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  echo "[backup] ERROR: POSTGRES_PASSWORD is not set" >&2
  exit 1
fi

if [[ -z "${BACKUP_ENCRYPTION_KEY:-}" ]]; then
  echo "[backup] ERROR: BACKUP_ENCRYPTION_KEY is not set" >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"

# ── Restore mode ──────────────────────────────────────────────────────────

if [[ "${1:-}" == "--restore" ]]; then
  echo "[backup] Available backups in ${BACKUP_DIR}:"
  ls -lh "${BACKUP_DIR}"/*.sql.gz.enc 2>/dev/null || echo "  (none found)"
  echo ""
  echo "[backup] To restore a backup:"
  echo "  1. Stop the app:  docker compose -f ${COMPOSE_FILE} stop app"
  echo "  2. Decrypt + decompress:"
  echo "     openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_ENCRYPTION_KEY \\"
  echo "       -in /path/to/backup.sql.gz.enc | gunzip > /tmp/restore.sql"
  echo "  3. Drop + recreate DB:"
  echo "     docker compose -f ${COMPOSE_FILE} exec postgres \\"
  echo "       psql -U tradearena -c 'DROP DATABASE tradearena; CREATE DATABASE tradearena;'"
  echo "  4. Restore:"
  echo "     cat /tmp/restore.sql | docker compose -f ${COMPOSE_FILE} exec -T postgres \\"
  echo "       psql -U tradearena tradearena"
  echo "  5. Restart:  docker compose -f ${COMPOSE_FILE} start app"
  exit 0
fi

# ── Dump ──────────────────────────────────────────────────────────────────

echo "[backup] Starting backup at ${TIMESTAMP}"

PGPASSWORD="${POSTGRES_PASSWORD}" \
  docker compose -f "${COMPOSE_FILE}" exec -T postgres \
    pg_dump -U tradearena tradearena \
  | gzip \
  | openssl enc -aes-256-cbc -pbkdf2 -pass env:BACKUP_ENCRYPTION_KEY \
  > "${BACKUP_FILE}"

BACKUP_SIZE=$(du -sh "${BACKUP_FILE}" | cut -f1)
echo "[backup] Backup written: ${BACKUP_FILE} (${BACKUP_SIZE})"

# ── Off-box upload ────────────────────────────────────────────────────────

if [[ -n "${BACKUP_S3_BUCKET:-}" ]]; then
  if command -v aws &>/dev/null; then
    aws s3 cp "${BACKUP_FILE}" "${BACKUP_S3_BUCKET}/$(basename "${BACKUP_FILE}")"
    echo "[backup] Uploaded to S3: ${BACKUP_S3_BUCKET}"
  elif command -v rclone &>/dev/null; then
    rclone copy "${BACKUP_FILE}" "${BACKUP_S3_BUCKET}"
    echo "[backup] Uploaded via rclone: ${BACKUP_S3_BUCKET}"
  else
    echo "[backup] WARNING: BACKUP_S3_BUCKET set but neither aws nor rclone found — skipping upload" >&2
  fi
fi

# ── Rotate old backups ────────────────────────────────────────────────────

find "${BACKUP_DIR}" -name "tradearena_*.sql.gz.enc" -mtime "+${RETENTION_DAYS}" -delete
REMAINING=$(ls "${BACKUP_DIR}"/tradearena_*.sql.gz.enc 2>/dev/null | wc -l)
echo "[backup] Rotation complete. Retained ${REMAINING} backup(s) (${RETENTION_DAYS}-day window)."

echo "[backup] Done."
