# TradeArena Deploy Guide

## How Deploys Work

Pushes to `main` trigger the CI/CD pipeline:

1. **CI** — `ci.yml` runs lint + tests
2. **Deploy** — `deploy.yml` fires on CI success, SSHes into production, runs `deploy/deploy.sh`

The deploy script:
- Pulls latest code from `main`
- Tags the current Docker image for rollback
- Rebuilds the `app` container (`--no-cache`)
- Restarts the app (Alembic migrations run automatically on container start)
- Waits up to 60s for `/health` to return 200
- Auto-rolls back if health check fails

## Required GitHub Secrets

| Secret | Description |
|--------|-------------|
| `DEPLOY_HOST` | Production server IP or hostname |
| `DEPLOY_USER` | SSH user (must have docker access) |
| `DEPLOY_SSH_KEY` | Private SSH key for the deploy user |

## Manual Deploy

```bash
ssh deploy@your-server 'cd /opt/tradearena && bash deploy/deploy.sh'
```

## Rollback

### Automatic
If the health check fails after deploy, the script auto-rolls back to the previous image.

### Manual
```bash
ssh deploy@your-server 'cd /opt/tradearena && bash deploy/deploy.sh --rollback'
```

This restores the Docker image that was running before the last deploy. The rollback image is tagged as `tradearena-rollback:latest` on each deploy.

### Database Rollback
If a migration needs reverting:
```bash
docker compose -f docker-compose.prod.yml exec app alembic downgrade -1
```

## Concurrency
The deploy workflow uses `concurrency: production-deploy` to prevent overlapping deploys. Only one deploy runs at a time.
