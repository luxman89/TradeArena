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

## Quick Reference

| Scenario | First action | Escalation |
|----------|-------------|------------|
| Oracle not resolving | `curl -X POST localhost:8000/oracle/resolve` | Restart app container |
| Bots not generating signals | Restart app container | Check bot registration in DB |
| Database unreachable | Check postgres container logs | Restore from backup |
| Bad deployment | `git checkout <good-commit>` + rebuild | Downgrade alembic migration |
| App won't start | Check `docker compose logs app` | Verify `.env` and DB connectivity |
| SSL cert expired | `bash deploy/setup-hetzner.sh --ssl` | Check certbot logs |

## Service Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Application health check |
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
