# CEO Memory

## Company
- Company ID: `570fac5f-58d8-4ece-bcc1-e52033151eb6`
- Company prefix: `TRAA`
- Goal: "Foster and manage a scalable interactive competitive trading environments for bots and agents" (id: `81114763`)

## Team
- **CEO** (me): `05caff43-6ed2-447d-bf7a-fc56930100ce`, urlKey: `ceo`
- **Founding Engineer**: `be0e7192-9499-4ab2-b711-45bf15175e15`, urlKey: `founding-engineer` (approved, active)

## Active Work
- **TRAA-1**: done — CEO setup, FE hired, roadmap tasks created
- **TRAA-2**: in_review, assigned to board — revised plan (no revenue), at TRAA-2#document-plan
- **TRAA-3**: done — Dockerize
- **TRAA-4**: blocked — Deploy to cloud (needs cloud credentials)
- **TRAA-5**: done — PostgreSQL migration
- **TRAA-6**: in_progress — Environment hardening → Founding Engineer
- **TRAA-7**: cancelled — Stripe (board: no revenue this sprint)
- **TRAA-8**: todo — Landing page (updated: no pricing) → Founding Engineer

## Board Directives
- 2026-03-21: Focus on users only, no revenue. 100 active users target. All features free.

## Codebase
- Python/FastAPI project at `C:\Users\aless\Development\Python\tradearena`
- Signal-tracking platform for crypto traders with cryptographic commitment
- SQLite dev, Postgres-compatible, Alembic migrations
- Phaser 3 UI at `scripts/arena.html`
- 172 tests passing, CI via GitHub Actions
- SDK at `sdk/client.py`
- 3 built-in bots (RSI, EMA, BB Squeeze)
- Missing: Docker, billing, landing page, email, deployment
