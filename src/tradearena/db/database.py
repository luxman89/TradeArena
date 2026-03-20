"""Database setup — SQLite for dev, Postgres-compatible schema."""

from __future__ import annotations

import os

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tradearena.db")

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=connect_args)

# Enable WAL mode and foreign keys for SQLite
if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class CreatorORM(Base):
    __tablename__ = "creators"

    id = Column(String(64), primary_key=True)
    display_name = Column(String(128), nullable=False)
    created_at = Column(DateTime, nullable=False)
    division = Column(String(32), nullable=False, default="crypto")  # crypto | polymarket | multi
    # api_key_dev: plaintext key, only populated by seed_demo.py for local dev.
    # In production this is null and api_key_hash is used for authentication.
    api_key_dev = Column(String(128), nullable=True)
    api_key_hash = Column(String(64), nullable=True)
    email = Column(String(256), nullable=True)
    strategy_description = Column(Text, nullable=True)
    password_hash = Column(String(128), nullable=True)  # bcrypt; NULL for bots
    avatar_index = Column(Integer, nullable=True, default=0)  # index into CHAR_DEFS (0-9)

    signals = relationship("SignalORM", back_populates="creator", lazy="select")
    score = relationship("CreatorScoreORM", back_populates="creator", uselist=False)


class SignalORM(Base):
    """Append-only — no UPDATE or DELETE permitted by application convention.

    The DB-level CHECK constraint prevents outcome columns from being set to
    impossible sentinel values during initial insert (they start NULL).
    The application layer never issues UPDATE statements on this table.
    """

    __tablename__ = "signals"
    __table_args__ = (
        CheckConstraint("confidence > 0.0 AND confidence < 1.0", name="ck_confidence_range"),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('WIN','LOSS','NEUTRAL')",
            name="ck_outcome_values",
        ),
        Index("ix_signals_creator_id", "creator_id"),
        Index("ix_signals_committed_at", "committed_at"),
    )

    signal_id = Column(String(64), primary_key=True)
    creator_id = Column(String(64), ForeignKey("creators.id"), nullable=False)
    asset = Column(String(20), nullable=False)
    action = Column(String(10), nullable=False)
    confidence = Column(Float, nullable=False)
    reasoning = Column(Text, nullable=False)
    supporting_data = Column(JSON, nullable=False)
    target_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    timeframe = Column(String(10), nullable=True)
    commitment_hash = Column(String(64), nullable=False, unique=True)
    committed_at = Column(DateTime, nullable=False)
    outcome = Column(String(10), nullable=True)
    outcome_price = Column(Float, nullable=True)
    outcome_at = Column(DateTime, nullable=True)

    creator = relationship("CreatorORM", back_populates="signals")


class BattleORM(Base):
    __tablename__ = "battles"
    __table_args__ = (
        CheckConstraint("creator1_id != creator2_id", name="ck_different_creators"),
        CheckConstraint(
            "status IN ('ACTIVE','RESOLVED')",
            name="ck_battle_status",
        ),
        CheckConstraint("battle_type IN ('MANUAL','AUTO')", name="ck_battle_type"),
        Index("ix_battles_status", "status"),
        Index("ix_battles_creator1", "creator1_id"),
        Index("ix_battles_creator2", "creator2_id"),
    )

    battle_id = Column(String(64), primary_key=True)
    creator1_id = Column(String(64), ForeignKey("creators.id"), nullable=False)
    creator2_id = Column(String(64), ForeignKey("creators.id"), nullable=False)
    status = Column(String(16), nullable=False, default="ACTIVE")
    window_days = Column(Integer, nullable=False, default=7)
    created_at = Column(DateTime, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    creator1_score = Column(Float, nullable=True)
    creator2_score = Column(Float, nullable=True)
    creator1_details = Column(JSON, nullable=True)
    creator2_details = Column(JSON, nullable=True)
    winner_id = Column(String(64), ForeignKey("creators.id"), nullable=True)
    margin = Column(Float, nullable=True)
    battle_type = Column(String(16), nullable=False, default="MANUAL")

    creator1 = relationship("CreatorORM", foreign_keys=[creator1_id])
    creator2 = relationship("CreatorORM", foreign_keys=[creator2_id])
    winner = relationship("CreatorORM", foreign_keys=[winner_id])


class CreatorScoreORM(Base):
    __tablename__ = "creator_scores"

    creator_id = Column(String(64), ForeignKey("creators.id"), primary_key=True)
    win_rate = Column(Float, nullable=False, default=0.0)
    risk_adjusted_return = Column(Float, nullable=False, default=0.0)
    consistency = Column(Float, nullable=False, default=0.0)
    confidence_calibration = Column(Float, nullable=False, default=0.0)
    composite_score = Column(Float, nullable=False, default=0.0)
    total_signals = Column(Integer, nullable=False, default=0)
    xp = Column(Integer, nullable=False, default=0)  # cumulative, never decreases
    level = Column(Integer, nullable=False, default=1)  # computed from XP thresholds
    updated_at = Column(DateTime, nullable=True)

    creator = relationship("CreatorORM", back_populates="score")


class TournamentORM(Base):
    __tablename__ = "tournaments"
    __table_args__ = (
        CheckConstraint(
            "format IN ('single_elimination', 'round_robin')",
            name="ck_tournament_format",
        ),
        CheckConstraint(
            "status IN ('registering', 'in_progress', 'completed')",
            name="ck_tournament_status",
        ),
        CheckConstraint("max_participants >= 2", name="ck_min_participants"),
    )

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    format = Column(String(32), nullable=False, default="single_elimination")
    status = Column(String(16), nullable=False, default="registering")
    max_participants = Column(Integer, nullable=False, default=8)
    current_round = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False)

    entries = relationship("TournamentEntryORM", back_populates="tournament")


class TournamentEntryORM(Base):
    __tablename__ = "tournament_entries"
    __table_args__ = (
        Index("ix_tournament_entries_tournament_id", "tournament_id"),
        Index("ix_tournament_entries_creator_id", "creator_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tournament_id = Column(String(64), ForeignKey("tournaments.id"), nullable=False)
    creator_id = Column(String(64), ForeignKey("creators.id"), nullable=False)
    seed = Column(Integer, nullable=True)
    eliminated_at = Column(DateTime, nullable=True)
    points = Column(Integer, nullable=False, default=0)

    tournament = relationship("TournamentORM", back_populates="entries")
    creator = relationship("CreatorORM")


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
