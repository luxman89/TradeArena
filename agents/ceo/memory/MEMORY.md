# CEO Memory

## Company
- Company ID: `570fac5f-58d8-4ece-bcc1-e52033151eb6`
- Company prefix: `TRAA`
- Goal: "Foster and manage a scalable interactive competitive trading environments for bots and agents" (id: `81114763`)

## Team
- **CEO** (me): `05caff43-6ed2-447d-bf7a-fc56930100ce`, urlKey: `ceo`
- **Founding Engineer**: `be0e7192-9499-4ab2-b711-45bf15175e15`, urlKey: `founding-engineer` (active)
- **Tooling Engineer**: `9abf37f1-8882-4c2f-97d1-a1b4f6e040e7`, urlKey: `tooling-engineer` (active, infra/DevOps)

## Active Work (as of 2026-03-23 03:33 UTC)
- **TRAA-2**: in_review, assigned to board — revised plan (no revenue), at TRAA-2#document-plan
- **TRAA-30**: in_review, assigned to board — tech roundup
- **TRAA-76**: todo, critical, unassigned (human action) — Rotate exposed PyPI token
- **TRAA-69/70/71**: todo, unassigned (human action) — GTM outreach posts (Reddit, Dev.to, HN)
- All engineers have empty queues — awaiting new assignments or board direction

## Completed (Sprint 1-2)
- Deploy (TRAA-4), Dockerize (TRAA-3), PostgreSQL (TRAA-5), Env hardening (TRAA-6)
- Landing page (TRAA-8), GitHub OAuth (TRAA-47), Google OAuth (TRAA-72), Twitter/X OAuth (TRAA-74), Discord OAuth (TRAA-73)
- CLI tool (TRAA-48), API docs (TRAA-44), Leaderboard page (TRAA-45), Onboarding email (TRAA-46)
- Rate limiting (TRAA-32), Load testing (TRAA-33), Ops runbook (TRAA-34)
- Discord server (TRAA-68), Discord bot + Phase 2 features (TRAA-77, 79-83)
- Community Manager agent (TRAA-78)
- Battle system (TRAA-59), ELO/matchmaking (TRAA-63), Tournaments (TRAA-64)
- Creator profiles (TRAA-60), Webhooks (TRAA-67), Starter bot templates (TRAA-66)
- BASE_URL fix (TRAA-75), Production deploy (TRAA-57)

## Board Directives
- 2026-03-21: Focus on users only, no revenue. 100 active users target. All features free.
- 2026-03-22: Board wants Discord Community Manager agent — needs bot built first (TRAA-77).

## Codebase
- Python/FastAPI project at `/opt/tradearena`
- Signal-tracking platform for crypto traders with cryptographic commitment
- SQLite dev, Postgres-compatible, Alembic migrations
- Phaser 3 UI at `scripts/arena.html`
- SDK at `sdk/client.py`, 3 built-in bots (RSI, EMA, BB Squeeze)
- Deployed to tradearena.duckdns.org
