# TradeArena Operations Runbook

Production incident procedures for the TradeArena platform.

**Stack**: FastAPI + PostgreSQL + Redis + Docker Compose on Hetzner VPS
**Compose file**: `docker-compose.prod.yml`
**Health endpoint**: `GET /health`

---

## 1. Resolver (Oracle) Stalls

The oracle runs as a background task inside the FastAPI app, resolving pending signals every 5 minutes via Binance kline data.

### Symptoms

- `GET /oracle/status` shows growing count of pending signals with past-due `next_eligible_at` times
- No new outcomes appearing on the leaderboard
- App logs show Binance API errors or timeouts

### Diagnosis

```bash
# Check pending signal count and next resolution times
curl -s http://localhost:8000/oracle/status | python3 -m json.tool

# Check app logs for oracle errors
docker compose -f docker-compose.prod.yml logs --tail=200 app | grep -i -E "oracle|resolve|binance|error"

# Verify Binance API is reachable from the container
docker compose -f docker-compose.prod.yml exec app python3 -c "import httpx; r = httpx.get('https://api.binance.com/api/v3/ping'); print(r.status_code)"
```

### Resolution

**Option A — Manual trigger** (resolves backlog without restart):
```bash
curl -X POST http://localhost:8000/oracle/resolve
```
This forces an immediate resolution cycle. Check `/oracle/status` again after a few seconds.

**Option B — Restart the app** (resets the background loop):
```bash
docker compose -f docker-compose.prod.yml restart app
```
The background loop restarts on boot and will pick up pending signals within 5 minutes.

**Option C — Binance is down or rate-limiting**:
1. Check Binance status: https://www.binance.com/en/support/announcement
2. The oracle caches kline data to reduce API calls. If rate-limited, wait 5–10 minutes.
3. If Binance is fully down, signals remain pending and resolve on the next successful cycle. No data is lost.

### Prevention

- Monitor `/oracle/status` — pending count should stay low (< 20 in normal operation)
- Set up an alert if pending count exceeds threshold for > 15 minutes

---

## 2. Bot Restart

Three strategy bots (RSI Ranger, EMA Crossover, BB Squeeze) run in-process as part of the background loop, generating signals hourly.

### Symptoms

- No new bot signals appearing on the leaderboard
- App logs show bot-related errors
- Bot creators missing from `/leaderboard/bots`

### Diagnosis

```bash
# Check if bots are registered (look for bot creator IDs)
docker compose -f docker-compose.prod.yml exec app python3 -c "
from tradearena.db.database import get_db
from tradearena.db.models import CreatorORM
db = next(get_db())
bots = db.query(CreatorORM).filter(CreatorORM.creator_id.like('%-b0t%')).all()
for b in bots:
    print(f'{b.creator_id} | {b.display_name} | active={b.is_active}')
"

# Check recent bot signal activity
docker compose -f docker-compose.prod.yml logs --tail=100 app | grep -i "bot"
```

### Resolution

**Restart bots by restarting the app**:
```bash
docker compose -f docker-compose.prod.yml restart app
```
On startup, `ensure_bots_registered()` re-registers all three bots (idempotent). The hourly bot signal loop resumes automatically.

**Disable bots temporarily** (if bot signals are causing issues):
1. Edit `src/tradearena/api/main.py`
2. Comment out the `ensure_bots_registered()` call in the lifespan context
3. Rebuild and restart:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build app
   ```

**Re-enable bots**: Reverse the edit above and rebuild.

### Notes

- Bots use a minute-based RNG seed for deterministic but varied signals
- Bot signals are written directly to the DB (no HTTP calls)
- Disabling bots does not affect existing bot signals or scores

---

## 3. Database Recovery

Production uses PostgreSQL 16 (Alpine) running in Docker. The `signals` table is append-only by design.

### Backup Procedures

**Manual backup**:
```bash
docker compose -f docker-compose.prod.yml exec postgres \
  pg_dump -U tradearena tradearena > "backup_$(date +%Y%m%d_%H%M%S).sql"
```

**Automated daily backup** (add to host crontab):
```bash
0 3 * * * cd /opt/tradearena && docker compose -f docker-compose.prod.yml exec -T postgres pg_dump -U tradearena tradearena | gzip > /opt/tradearena/backups/tradearena_$(date +\%Y\%m\%d).sql.gz
```

Create the backup directory first:
```bash
mkdir -p /opt/tradearena/backups
```

### Recovery from Backup

**Full restore** (replaces all data):
```bash
# Stop the app to prevent writes
docker compose -f docker-compose.prod.yml stop app

# Drop and recreate the database
docker compose -f docker-compose.prod.yml exec postgres \
  psql -U tradearena -c "DROP DATABASE tradearena; CREATE DATABASE tradearena;"

# Restore from backup
cat backup_YYYYMMDD_HHMMSS.sql | docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U tradearena tradearena

# Restart the app (runs alembic migrations on boot)
docker compose -f docker-compose.prod.yml start app
```

**Partial restore** (e.g., recover specific table):
```bash
# Extract specific table from backup
grep -A 999999 "^COPY public.signals" backup.sql | sed '/^\\./q' > signals_data.sql

# Import into running database
cat signals_data.sql | docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U tradearena tradearena
```

### PostgreSQL Container Won't Start

```bash
# Check postgres logs
docker compose -f docker-compose.prod.yml logs --tail=50 postgres

# Check if data volume is corrupted
docker compose -f docker-compose.prod.yml exec postgres pg_isready -U tradearena

# Nuclear option: recreate postgres container (DATA LOSS if no backup)
docker compose -f docker-compose.prod.yml down postgres
docker volume rm tradearena_postgres_data  # WARNING: destroys all data
docker compose -f docker-compose.prod.yml up -d postgres
# Then restore from backup (see above)
```

### Schema Migration Issues

```bash
# Check current migration state
docker compose -f docker-compose.prod.yml exec app alembic current

# Downgrade one migration (if the latest migration broke something)
docker compose -f docker-compose.prod.yml exec app alembic downgrade -1

# Re-run migrations
docker compose -f docker-compose.prod.yml exec app alembic upgrade head
```

---

## 4. Deployment Rollback

### Standard Rollback (Docker Compose on Hetzner)

**Quick rollback** (revert to previous image):
```bash
cd /opt/tradearena

# Check git log for the last known-good commit
git log --oneline -5

# Revert to a known-good commit
git checkout <commit-hash>

# Rebuild and restart
docker compose -f docker-compose.prod.yml up -d --build app
```

**Rollback with database migration downgrade**:
```bash
# 1. Stop the app
docker compose -f docker-compose.prod.yml stop app

# 2. Downgrade database if the bad deploy included a migration
docker compose -f docker-compose.prod.yml run --rm app alembic downgrade -1

# 3. Revert code
git checkout <known-good-commit>

# 4. Rebuild and start
docker compose -f docker-compose.prod.yml up -d --build app
```

### Fly.io Rollback

```bash
# List recent deployments
fly releases -a tradearena

# Rollback to previous release
fly deploy -a tradearena --image <previous-image-ref>
```

### Railway Rollback

Railway supports rollback from the dashboard:
1. Go to the TradeArena service in Railway
2. Click "Deployments"
3. Find the last successful deployment and click "Rollback"

### Post-Rollback Verification

After any rollback, verify the system is healthy:

```bash
# 1. Health check
curl -s http://localhost:8000/health

# 2. Check oracle is resolving
curl -s http://localhost:8000/oracle/status

# 3. Verify database connectivity
docker compose -f docker-compose.prod.yml exec app python3 -c "
from tradearena.db.database import get_db
db = next(get_db())
print('DB connection OK')
"

# 4. Check app logs for errors
docker compose -f docker-compose.prod.yml logs --tail=20 app

# 5. Verify leaderboard loads
curl -s http://localhost:8000/leaderboard/open | head -c 200
```

---

## 5. PyPI Publishing

The `tradearena` CLI is packaged for PyPI distribution. End users install with `pip install tradearena`.

### Prerequisites

- Python 3.12+
- `uv` (or `pip install build twine`)
- A PyPI API token (create at https://pypi.org/manage/account/token/ — scope to the `tradearena` project)

### Build

```bash
cd /opt/tradearena

# Clean previous builds
rm -rf dist/

# Build sdist + wheel
uv build
# Produces: dist/tradearena-X.Y.Z.tar.gz and dist/tradearena-X.Y.Z-py3-none-any.whl
```

### Verify Before Publishing

```bash
# Test install in a fresh venv
uv venv /tmp/test-ta && source /tmp/test-ta/bin/activate
uv pip install dist/tradearena-*.whl
tradearena --version
tradearena --help
deactivate && rm -rf /tmp/test-ta
```

### Publish to PyPI

```bash
# First time: configure token
# Option A: environment variable
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-your-api-token-here

# Option B: use uv publish (recommended)
uv publish --token pypi-your-api-token-here

# Option C: use twine
pip install twine
twine upload dist/*
```

### Publish to TestPyPI (dry run)

```bash
uv publish --publish-url https://test.pypi.org/legacy/ --token pypi-your-test-token-here

# Verify: pip install -i https://test.pypi.org/simple/ tradearena
```

### Version Bumping

1. Update `version` in `pyproject.toml`
2. Update `__version__` in `src/tradearena/__init__.py`
3. Commit, tag, build, publish:
   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   rm -rf dist/ && uv build
   uv publish --token $PYPI_TOKEN
   ```

### Troubleshooting

| Issue | Fix |
|-------|-----|
| `twine` reports "file already exists" | Bump the version — PyPI does not allow re-uploading the same version |
| Missing metadata on PyPI page | Check `pyproject.toml` fields and rebuild |
| Install fails with dependency error | Verify `requires-python` and dependency version bounds |

---

---

## 6. Redis Down

### Symptoms

- `/health` reports `"redis": "error"`
- Rate limit state resets on next request (in-memory fallback activates)
- JWT logout revocations are not persisted across app restarts

### Diagnosis

```bash
# Check Redis container
docker compose -f docker-compose.prod.yml logs --tail=50 redis

# Manual ping
docker compose -f docker-compose.prod.yml exec redis redis-cli ping
```

### Resolution

**Restart Redis** (data is persisted to volume via AOF):
```bash
docker compose -f docker-compose.prod.yml restart redis
```

**Impact while Redis is down**: The app falls back to in-memory rate limiting (lost on restart) and in-memory JWT blacklist (logout tokens survive only until next restart). No user data is affected.

**If Redis volume is corrupted**:
```bash
docker compose -f docker-compose.prod.yml stop redis
docker volume rm tradearena_redisdata  # WARNING: clears cached rate-limit state
docker compose -f docker-compose.prod.yml up -d redis
```

Rate-limit and JWT blacklist state is rebuilt automatically on the next requests. No user-visible data loss.

---

## 7. Anthropic API Down

### Symptoms

- `POST /signal/reasoning` returns 502 or 503
- App logs show `anthropic` client errors

### Diagnosis

```bash
docker compose -f docker-compose.prod.yml logs --tail=100 app | grep -i "anthropic\|reasoning"
```

Check [https://status.anthropic.com](https://status.anthropic.com) for ongoing incidents.

### Resolution

The reasoning endpoint is non-critical. The rest of the platform (signal submission, leaderboard, oracle) is unaffected.

1. **Communicate**: Post a status update on Discord (`#announcements`).
2. **Wait for upstream recovery** — do not restart the app, it will not help.
3. **Once recovered**: reasoning endpoint resumes automatically. No backfill needed.

Optional — disable the endpoint temporarily to suppress confusing errors:
```bash
# Set ANTHROPIC_API_KEY="" in .env, then rebuild
docker compose -f docker-compose.prod.yml up -d --build app
```

---

## 8. GDPR Data Deletion Request (Art. 17)

A creator requests deletion of their account and all associated data.

**SLA target**: 30 days (Art. 17(1) GDPR). Aim for 5 business days.

### Steps

1. **Verify identity**: Creator must confirm via the registered email address (or OAuth provider). Reply to the deletion request from `privacy@tradearena.io` (or the registered contact address). Ask them to reply from their registered email.

2. **Confirm scope**: Standard deletion covers: account record, signals, scores, comments, follows, battle records, API keys, email preferences. Backups are purged at next rotation (within 7 days).

3. **Run the deletion** (as admin):
```bash
# Connect to the running app container
docker compose -f docker-compose.prod.yml exec app python3 - <<'EOF'
from tradearena.db.database import SessionLocal, CreatorORM, SignalORM, CreatorScoreORM
from tradearena.db.database import FollowORM, SignalCommentORM

CREATOR_ID = "REPLACE_WITH_CREATOR_ID"

db = SessionLocal()
try:
    # Delete in dependency order
    db.query(SignalCommentORM).filter(SignalCommentORM.creator_id == CREATOR_ID).delete()
    db.query(FollowORM).filter(
        (FollowORM.follower_id == CREATOR_ID) | (FollowORM.followed_id == CREATOR_ID)
    ).delete()
    db.query(CreatorScoreORM).filter(CreatorScoreORM.creator_id == CREATOR_ID).delete()
    db.query(SignalORM).filter(SignalORM.creator_id == CREATOR_ID).delete()
    db.query(CreatorORM).filter(CreatorORM.id == CREATOR_ID).delete()
    db.commit()
    print("Deleted:", CREATOR_ID)
finally:
    db.close()
EOF
```

4. **Confirm deletion**: Send the creator a written confirmation with the date. Log the event in `deploy/gdpr-deletions.log` (date, creator_id, confirmation email).

5. **Backup rotation**: The next nightly backup will not contain the deleted data. Backups older than 7 days are automatically pruned by `deploy/backup.sh`.

**Note on signals**: Signals are cryptographically committed (SHA-256). The commitment hash remains in any audit log but contains no PII. The creator's display name and email are deleted. This satisfies Art. 17 — hashes are not personal data.

---

## 9. Harmful Signal / Content Report

A user reports a signal containing harmful, misleading, or harmful content.

**Target response**: Acknowledge within 24h, resolve within 72h.

### Steps

1. **Assess the report**: Does the signal violate ToS? (financial advice framing, market manipulation intent, personal attacks, spam.) Signals are prediction entries — "Buy BTC" is not harmful. "BTC will crash because I'll sell my holdings" could be.

2. **Do not delete the signal** (it is append-only by design). Instead, flag the creator account:
```bash
docker compose -f docker-compose.prod.yml exec app python3 - <<'EOF'
from tradearena.db.database import SessionLocal, CreatorORM

CREATOR_ID = "REPLACE_WITH_CREATOR_ID"
db = SessionLocal()
try:
    creator = db.query(CreatorORM).filter(CreatorORM.id == CREATOR_ID).first()
    if creator:
        creator.is_active = False  # Prevents new signals and hides from leaderboard
        db.commit()
        print("Flagged:", CREATOR_ID)
finally:
    db.close()
EOF
```

3. **Respond to reporter**: Acknowledge receipt within 24h. State that the content is under review. Do not reveal the action taken.

4. **If escalation needed**: Contact a BaFin-aware lawyer if the report involves potential MiFID II violations or market manipulation claims. Log the consultation.

5. **DSA compliance**: Under the Digital Services Act, document the decision and rationale. Store in `deploy/content-reports/YYYY-MM-DD-<report-id>.md`.

---

## Quick Reference

| Scenario | First action | Escalation |
|----------|-------------|------------|
| Oracle not resolving | `curl -X POST localhost:8000/oracle/resolve` | Restart app container |
| Bots not generating signals | Restart app container | Check bot registration in DB |
| Database unreachable | Check postgres container logs | Restore from backup |
| Redis unreachable | Restart Redis container | Check volume, recreate if corrupted |
| Anthropic API down | Check status.anthropic.com | Post Discord notice, wait for recovery |
| GDPR deletion request | Verify identity, run deletion script | Legal review if creator disputes |
| Harmful content report | Flag creator account | Legal review for MiFID/DSA issues |
| Bad deployment | `git checkout <good-commit>` + rebuild | Downgrade alembic migration |
| App won't start | Check `docker compose logs app` | Verify `.env` and DB connectivity |
| SSL cert expired | `bash deploy/setup-hetzner.sh --ssl` | Check certbot logs |

## Service Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Application health check (DB + Redis status) |
| `GET /status` | Public status page |
| `GET /oracle/status` | Pending signals and next resolution times |
| `POST /oracle/resolve` | Manual oracle trigger |
| `GET /leaderboard/{division}` | Verify leaderboard data |
| `ws://host/ws` | WebSocket real-time feed |

## Container Management

```bash
# View all containers
docker compose -f docker-compose.prod.yml ps

# Restart specific service
docker compose -f docker-compose.prod.yml restart <service>

# Full stack restart
docker compose -f docker-compose.prod.yml down && docker compose -f docker-compose.prod.yml up -d

# Rebuild and restart (after code changes)
docker compose -f docker-compose.prod.yml up -d --build

# View live logs
docker compose -f docker-compose.prod.yml logs -f app
```
