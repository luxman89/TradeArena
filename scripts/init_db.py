#!/usr/bin/env python3
"""Initialize the database with clean tables."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow running as `uv run python scripts/init_db.py` from project root
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

os.environ.setdefault("DATABASE_URL", "sqlite:///./tradearena.db")

from tradearena.db.database import create_tables

print("Creating database tables...")
create_tables()
print("Database initialized successfully!")
