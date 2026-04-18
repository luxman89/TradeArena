#!/usr/bin/env python3
"""One-shot API key rotation: issues new ta- keys to all creators and stages them for delivery.

Usage:
    uv run python scripts/rotate_api_keys.py [--dry-run] [--creator-id CREATOR_ID]

Options:
    --dry-run           Print what would be done without writing to DB.
    --creator-id ID     Rotate only one creator (for targeted rotation).

Output:
    Writes a JSON manifest of rotated keys to stdout — pipe to a file for safekeeping.
    Each record: {creator_id, display_name, email, new_api_key}

    In dry-run mode prints the plan without modifying anything.

Runbook: docs/api-key-rotation-runbook.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from datetime import UTC, datetime

import bcrypt as _bcrypt

sys.path.insert(0, "src")

from tradearena.db.database import CreatorORM, SessionLocal, engine
from tradearena.db.database import Base  # noqa: F401 — ensures tables are known


def _hash_sha256(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _hash_bcrypt(key: str) -> str:
    return _bcrypt.hashpw(key.encode(), _bcrypt.gensalt()).decode()


def rotate(dry_run: bool = False, creator_id: str | None = None) -> None:
    db = SessionLocal()
    try:
        query = db.query(CreatorORM)
        if creator_id:
            query = query.filter(CreatorORM.id == creator_id)
        creators = query.all()

        if not creators:
            print("No creators found.", file=sys.stderr)
            return

        manifest = []
        for creator in creators:
            new_key = f"ta-{secrets.token_hex(16)}"
            record = {
                "creator_id": creator.id,
                "display_name": creator.display_name,
                "email": creator.email,
                "new_api_key": new_key,
                "rotated_at": datetime.now(UTC).isoformat(),
            }
            manifest.append(record)

            if not dry_run:
                creator.api_key_hash = _hash_sha256(new_key)
                creator.api_key_hash_v2 = _hash_bcrypt(new_key)
                creator.api_key_dev = None  # clear plaintext dev key
                db.add(creator)

        if not dry_run:
            db.commit()
            print(
                f"Rotated {len(manifest)} API key(s). Save the manifest securely.",
                file=sys.stderr,
            )
        else:
            print(f"[DRY RUN] Would rotate {len(manifest)} API key(s).", file=sys.stderr)

        json.dump(manifest, sys.stdout, indent=2)
        print()  # trailing newline

    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Rotate TradeArena API keys")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without writing")
    parser.add_argument("--creator-id", default=None, help="Rotate only this creator")
    args = parser.parse_args()
    rotate(dry_run=args.dry_run, creator_id=args.creator_id)


if __name__ == "__main__":
    main()
