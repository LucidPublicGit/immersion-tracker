from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TadokuMode(str, Enum):
    AUTO = "auto"
    PENDING = "pending"
    NEVER = "never"


class TadokuStatus(str, Enum):
    NA = "n/a"
    PENDING = "pending"
    READY = "ready"
    PUSHED = "pushed"
    FAILED = "failed"
    SKIPPED = "skipped"


class CatalogItem(Base):
    __tablename__ = "catalog_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_title: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(64), index=True)
    external_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    # Pipe/newline-separated alternate titles (Plex English names, etc.)
    # Used to link auto sources to this series_key and apply display_title.
    aliases: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tadoku_override: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    default_unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Progress page: active | finished | dropped | ignored
    progress_status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    # When True, auto-finish must not override user-set progress_status
    progress_status_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class LogEntry(Base):
    __tablename__ = "log_entries"
    __table_args__ = (
        UniqueConstraint("source", "source_ref", name="uq_source_ref"),
        Index("ix_logs_tadoku_status", "tadoku_status"),
        Index("ix_logs_timestamp", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    content_type: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512))  # show/work name only (no SxxExx)
    season: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    episode: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    series_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    source_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    amount: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32))
    language: Mapped[str] = mapped_column(String(16), default="ja")
    activity: Mapped[str] = mapped_column(String(32), default="listening")
    tadoku_mode: Mapped[str] = mapped_column(String(32), default="pending")
    tadoku_status: Mapped[str] = mapped_column(String(32), default="pending")
    tadoku_score_estimate: Mapped[float] = mapped_column(Float, default=0.0)
    tadoku_remote_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    watch_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SheetSyncState(Base):
    __tablename__ = "sheet_sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HoshiBookBucket(Base):
    """
    Per-book character bucket for Hoshi reading.

    Drive/ADB polls add deltas into pending_chars. A formal LogEntry is created
    only when auto-submit threshold is met or the user submits manually.
    """

    __tablename__ = "hoshi_book_buckets"
    __table_args__ = (
        UniqueConstraint("folder_id", name="uq_hoshi_bucket_folder"),
        Index("ix_hoshi_bucket_pending", "pending_chars"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    folder_id: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    series_key: Mapped[str] = mapped_column(String(255), default="", index=True)
    # Chars not yet submitted as a LogEntry
    pending_chars: Mapped[float] = mapped_column(Float, default=0.0)
    pending_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    session_count: Mapped[int] = mapped_column(Integer, default=0)
    # Last fragment added (for UI)
    last_session_chars: Mapped[float] = mapped_column(Float, default=0.0)
    last_session_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Bookmark position from Drive progress_ file (optional)
    position_chars: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    book_total_chars: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Bookmark position when we last created a formal log (path into Tadoku queue)
    last_logged_position_chars: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    # Farthest bookmark position already counted toward logs + unlogged buffer.
    # Prevents re-reads (Hoshi day charactersRead↑ without new progress) from
    # inflating pending chars. Credit only when position advances past this.
    credited_position_chars: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    # Lifetime totals for this book in the tracker (submitted only)
    total_logged_chars: Mapped[float] = mapped_column(Float, default=0.0)
    total_logged_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    submit_count: Mapped[int] = mapped_column(Integer, default=0)
    last_log_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Per-book auto-submit threshold; NULL = use global hoshi.min_submit_characters
    min_submit_characters: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class HoshiSessionFragment(Base):
    """
    One poll-detected character increase (approximate 'session' fragment).

    Hoshi only publishes daily totals; each positive delta we observe becomes
    a fragment until submitted into a LogEntry or discarded.
    """

    __tablename__ = "hoshi_session_fragments"
    __table_args__ = (
        Index("ix_hoshi_frag_bucket_status", "bucket_id", "status"),
        Index("ix_hoshi_frag_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bucket_id: Mapped[int] = mapped_column(Integer, index=True)
    folder_id: Mapped[str] = mapped_column(String(255), default="")
    title: Mapped[str] = mapped_column(String(512), default="")
    # Calendar day from Hoshi dateKey
    date_key: Mapped[str] = mapped_column(String(32), default="")
    chars: Mapped[float] = mapped_column(Float, default=0.0)
    seconds: Mapped[float] = mapped_column(Float, default=0.0)
    remote_total_for_day: Mapped[int] = mapped_column(Integer, default=0)
    # pending | logged | discarded
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    log_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MediaMetadata(Base):
    """
    Local cache of external media metadata (covers, total length).

    Prefer jiten.moe; fallbacks may set source to mal/vndb/imdb/none.
    Lookups are keyed by series_key so we never re-query the same work.
    """

    __tablename__ = "media_metadata"
    __table_args__ = (
        Index("ix_media_meta_content_type", "content_type"),
        Index("ix_media_meta_source", "source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    content_type: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(512), default="")
    # jiten | mal | vndb | imdb | none | manual
    source: Mapped[str] = mapped_column(String(32), default="none")
    external_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    external_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    cover_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    # Local relative path under data/media_cache (e.g. covers/jiten_18054.jpg)
    cover_local_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # episodes / volumes / chapters depending on type
    total_units: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # human label: episodes | volumes | chapters | characters | minutes
    total_units_label: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    total_characters: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # speech / runtime in whole minutes when known
    total_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # raw provider payload for debugging / future fields
    raw_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # last successful external lookup (or explicit none)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
