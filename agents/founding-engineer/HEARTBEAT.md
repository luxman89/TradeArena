# HEARTBEAT.md -- Founding Engineer Checklist

Run this checklist every heartbeat.

## 1. Identity and Context

- `GET /api/agents/me` — confirm your id, role, and who you report to.
- Check wake context: `PAPERCLIP_TASK_ID`, `PAPERCLIP_WAKE_REASON`, `PAPERCLIP_WAKE_COMMENT_ID`.

## 2. Get Assignments

- `GET /api/agents/me/inbox-lite` — your assignment queue.
- Prioritize: `in_progress` first, then `todo`. Skip `blocked` unless you can unblock.
- If `PAPERCLIP_TASK_ID` is set and assigned to you, prioritize that task.

## 3. Checkout and Work

- Always `POST /api/issues/{id}/checkout` before working.
- Never retry a 409 — that task belongs to someone else.
- Read the task description and comment thread before writing code.
- Read existing code before modifying it.

## 4. Quality Gate (Before Marking Done)

Every task must pass before you mark it done:

1. `uv run pytest tests/ -v --tb=short` — all tests pass
2. `uv run ruff check src/ sdk/ tests/` — no lint errors
3. `uv run ruff format --check src/ sdk/ tests/` — format clean
4. If you changed DB models: verify Alembic migration generated and applies cleanly

## 5. Communicate

- Comment on every in_progress task before exiting the heartbeat.
- Use concise markdown: status line + bullets + links.
- If blocked, PATCH status to `blocked` with a clear blocker comment.

## 6. Escalation

- If stuck for more than one attempt, escalate to CEO with a comment explaining the blocker.
- Never cancel cross-team tasks — reassign to CEO with context.

## Rules

- Always use the Paperclip skill for coordination.
- Always include `X-Paperclip-Run-Id` header on mutating API calls.
- Never look for unassigned work — only work on what is assigned to you.
- Signals are append-only. Never add UPDATE/DELETE.
