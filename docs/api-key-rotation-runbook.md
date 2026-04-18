# API Key Rotation Runbook

## Background

API keys were originally stored as plain SHA-256 hashes (`api_key_hash`). A bcrypt column
(`api_key_hash_v2`) was added in migration `55de4aad29f5`. All new registrations write both
hashes. Existing accounts are lazily upgraded to bcrypt on their next successful authentication.

## Verification path (deps.py)

1. **Dev plaintext** — matched first against `api_key_dev` (null in production).
2. **SHA-256 lookup** — `api_key_hash` used as the DB index (bcrypt cannot be indexed).
3. **bcrypt verify** — if `api_key_hash_v2` present, `bcrypt.checkpw()` must pass.
4. **Lazy upgrade** — if `api_key_hash_v2` absent, it is written on the first successful SHA-256 auth.

## One-shot rotation (all creators)

Generates fresh `ta-` keys for every creator and writes both `api_key_hash` (SHA-256) and
`api_key_hash_v2` (bcrypt). The manifest is printed as JSON on stdout.

```bash
# Dry run — shows what would change without touching the DB
uv run python scripts/rotate_api_keys.py --dry-run > /dev/null

# Rotate all creators; save manifest securely before distributing
uv run python scripts/rotate_api_keys.py > /tmp/rotation-manifest.json 2>&1

# Rotate a single creator
uv run python scripts/rotate_api_keys.py --creator-id alice-quantsworth-a1b2
```

**Important:** The manifest contains plaintext API keys. Treat it like a secrets file:
- Never commit it to git.
- Transmit to each creator over an authenticated channel (email with TLS, or in-app).
- Delete the manifest file after keys have been distributed.

## Confirming migration status

Check how many creators still lack a bcrypt hash:

```sql
SELECT COUNT(*) FROM creators WHERE api_key_hash_v2 IS NULL AND api_key_dev IS NULL;
```

When this returns 0, every production creator has been bcrypt-upgraded and the SHA-256
column can be considered a lookup-only index (not a credential store).

## Future: dropping SHA-256 (Phase 2)

Once all rows have `api_key_hash_v2`, the SHA-256 column (`api_key_hash`) can be repurposed
as a key-prefix index or removed entirely in favour of a separate lookup token. This requires
a coordinated migration and is deferred until post-launch.
