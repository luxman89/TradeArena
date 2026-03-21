#!/usr/bin/env python3
"""Check database status."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow running as `uv run python scripts/check_db.py` from project root
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

os.environ.setdefault("DATABASE_URL", "sqlite:///./tradearena.db")

from tradearena.db.database import SessionLocal, CreatorORM, SignalORM

db = SessionLocal()

# Check creators
print("=== Registered Creators ===")
creators = db.query(CreatorORM).all()
for creator in creators:
    print(f"ID: {creator.id}")
    print(f"Display Name: {creator.display_name}")
    print(f"Division: {creator.division}")
    print(f"API Key: {creator.api_key_dev}")
    print(f"Created At: {creator.created_at}")
    print(f"Total Signals: {len(creator.signals)}")
    print()

# Check signals
print("=== Total Signals ===")
print(f"Total signals in database: {db.query(SignalORM).count()}")

db.close()
