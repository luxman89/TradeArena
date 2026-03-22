"""Database setup — SQLite for dev, Postgres-compatible schema."""

from __future__ import annotations

import os

from sqlalchemy import (
    JSON,
    Boolean,
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

# Railway/Fly.io/Heroku often provide postgres:// but SQLAlchemy requires postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

_pool_kwargs: dict = {}
if not DATABASE_URL.startswith("sqlite"):
    _pool_kwargs.update(pool_size=5, max_overflow=10, pool_recycle=1800)

engine = create_engine(DATABASE_URL, connect_args=connect_args, **_pool_kwargs)

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
    github_id = Column(String(64), nullable=True, unique=True, index=True)
    github_username = Column(String(128), nullable=True)
    google_id = Column(String(64), nullable=True, unique=True, index=True)
    twitter_id = Column(String(64), nullable=True, unique=True, index=True)
    twitter_handle = Column(String(128), nullable=True)
    discord_id = Column(String(64), nullable=True, unique=True, index=True)
    discord_username = Column(String(128), nullable=True)
    unsubscribe_token = Column(String(64), nullable=True, unique=True, index=True)
    email_opted_out = Column(Boolean, nullable=False, default=False)
    webhook_url = Column(String(512), nullable=True)

    signals = relationship("SignalORM", back_populates="creator", lazy="select")
    score = relationship("CreatorScoreORM", back_populates="creator", uselist=False)
    email_events = relationship("EmailEventORM", back_populates="creator", lazy="select")


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
    outcome = Column(String(10), nullable=True)  # see Outcome enum in models.signal
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
    start_time = Column(DateTime, nullable=True)
    created_by = Column(String(64), ForeignKey("creators.id"), nullable=True)
    created_at = Column(DateTime, nullable=False)

    entries = relationship("TournamentEntryORM", back_populates="tournament")
    matches = relationship("TournamentMatchORM", back_populates="tournament")
    owner = relationship("CreatorORM")


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


class TournamentMatchORM(Base):
    """Tracks individual matches within a tournament round."""

    __tablename__ = "tournament_matches"
    __table_args__ = (
        Index("ix_tournament_matches_tournament_id", "tournament_id"),
        Index("ix_tournament_matches_battle_id", "battle_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tournament_id = Column(String(64), ForeignKey("tournaments.id"), nullable=False)
    round = Column(Integer, nullable=False)
    match_order = Column(Integer, nullable=False)
    battle_id = Column(String(64), ForeignKey("battles.battle_id"), nullable=True)
    winner_bot_id = Column(String(64), ForeignKey("creators.id"), nullable=True)

    tournament = relationship("TournamentORM", back_populates="matches")
    battle = relationship("BattleORM")
    winner = relationship("CreatorORM")


class BotRatingORM(Base):
    """ELO rating for each bot/creator. One row per creator."""

    __tablename__ = "bot_ratings"

    bot_id = Column(String(64), ForeignKey("creators.id"), primary_key=True)
    elo = Column(Float, nullable=False, default=1200.0)
    matches_played = Column(Integer, nullable=False, default=0)
    wins = Column(Integer, nullable=False, default=0)
    losses = Column(Integer, nullable=False, default=0)
    draws = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=True)

    creator = relationship("CreatorORM", backref="bot_rating")


class RatingHistoryORM(Base):
    """Historical ELO snapshots after each match for charting."""

    __tablename__ = "rating_history"
    __table_args__ = (
        Index("ix_rating_history_bot_id", "bot_id"),
        Index("ix_rating_history_timestamp", "timestamp"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(64), ForeignKey("creators.id"), nullable=False)
    elo = Column(Float, nullable=False)
    match_id = Column(String(64), ForeignKey("battles.battle_id"), nullable=False)
    timestamp = Column(DateTime, nullable=False)

    creator = relationship("CreatorORM")
    battle = relationship("BattleORM")


class MatchmakingQueueORM(Base):
    """Bots/creators currently queued for matchmaking."""

    __tablename__ = "matchmaking_queue"
    __table_args__ = (Index("ix_matchmaking_queue_bot_id", "bot_id", unique=True),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(String(64), ForeignKey("creators.id"), nullable=False, unique=True)
    queued_at = Column(DateTime, nullable=False)

    creator = relationship("CreatorORM")


class EmailEventORM(Base):
    """Tracks onboarding drip emails sent to creators."""

    __tablename__ = "email_events"
    __table_args__ = (
        CheckConstraint(
            "step IN ('welcome', 'first_score', 'battle_invite', 'weekly_recap')",
            name="ck_email_step",
        ),
        CheckConstraint(
            "status IN ('sent', 'failed')",
            name="ck_email_status",
        ),
        Index("ix_email_events_creator_id", "creator_id"),
        Index("ix_email_events_step", "step"),
    )

    id = Column(String(64), primary_key=True)
    creator_id = Column(String(64), ForeignKey("creators.id"), nullable=False)
    step = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False, default="sent")
    sent_at = Column(DateTime, nullable=False)
    opened_at = Column(DateTime, nullable=True)
    clicked_at = Column(DateTime, nullable=True)

    creator = relationship("CreatorORM", back_populates="email_events")


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
