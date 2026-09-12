from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class BatchIds(BaseModel):
    ids: list[int] = Field(..., min_length=1)


class TadokuCookieIn(BaseModel):
    """Browser Cookie header from tadoku.app (legacy session refresh)."""

    cookie: str = Field(..., min_length=8, description="Full Cookie header value")


class TadokuCredentialsIn(BaseModel):
    """
    Tadoku username/password for automatic browser login.

    Omit password or send blank to keep the previously saved password.
    """

    username: str = Field(..., min_length=1, description="Tadoku username or email")
    password: Optional[str] = Field(
        default=None,
        description="Password; blank/omitted keeps the saved password",
    )


class YouTubeVideoIdsIn(BaseModel):
    """Bulk check which YouTube video_ids are already logged."""

    video_ids: list[str] = Field(..., min_length=1, max_length=500)


class LogCreate(BaseModel):
    content_type: str
    title: str  # show/work name only
    amount: float = Field(..., gt=0)
    unit: Optional[str] = None
    activity: Optional[str] = None
    series_key: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    source: str = "manual"
    source_ref: Optional[str] = None
    language: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[str] = None
    timestamp: Optional[datetime] = None
    tadoku_mode: Optional[str] = None


class LogUpdate(BaseModel):
    """Partial log edit. Only set fields are applied; writes SQLite + dirties Sheets."""

    content_type: Optional[str] = None
    title: Optional[str] = None
    amount: Optional[float] = Field(default=None, gt=0)
    unit: Optional[str] = None
    activity: Optional[str] = None
    series_key: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    source: Optional[str] = None
    language: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[str] = None
    timestamp: Optional[datetime] = None
    tadoku_mode: Optional[str] = None
    tadoku_status: Optional[str] = None
    # When true (or when demoting from pushed), clear tadoku_remote_id
    clear_remote_id: Optional[bool] = None


class LogOut(BaseModel):
    id: int
    timestamp: datetime
    content_type: str
    title: str
    season: Optional[int] = None
    episode: Optional[int] = None
    series_key: Optional[str]
    source: str
    source_ref: Optional[str]
    amount: float
    unit: str
    language: str
    activity: str
    tadoku_mode: str
    tadoku_status: str
    tadoku_score_estimate: float
    tadoku_remote_id: Optional[str]
    notes: Optional[str]
    tags: Optional[str]
    watch_ratio: Optional[float]
    tadoku_title: Optional[str] = None
    # When the row last changed (submit/push sets this; useful for recent-sent lists)
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class CatalogCreate(BaseModel):
    series_key: str
    display_title: str
    content_type: str
    # Pipe-separated alternate titles (Plex names) that resolve to this series_key
    aliases: Optional[str] = None
    tadoku_override: Optional[str] = None
    default_unit: Optional[str] = None
    notes: Optional[str] = None


class CatalogUpdate(BaseModel):
    display_title: Optional[str] = None
    aliases: Optional[str] = None
    content_type: Optional[str] = None
    tadoku_override: Optional[str] = None
    default_unit: Optional[str] = None
    notes: Optional[str] = None


class CatalogOut(BaseModel):
    id: int
    series_key: str
    display_title: str
    content_type: str
    aliases: Optional[str] = None
    tadoku_override: Optional[str]
    default_unit: Optional[str]
    notes: Optional[str]

    model_config = {"from_attributes": True}


class CatalogLinkBody(BaseModel):
    """
    Link a Plex/raw title to an existing catalog series (or create one).

    - series_key + display_title: canonical identity (manual entry target)
    - alias: the Plex show name to match (added to aliases)
    - relink_logs: retarget existing logs that match alias/old auto keys
    """

    series_key: str
    display_title: str
    content_type: str = "anime"
    alias: Optional[str] = None  # Plex title to match
    aliases: Optional[str] = None  # extra pipe-separated aliases
    tadoku_override: Optional[str] = None
    relink_logs: bool = True


class MetricsOut(BaseModel):
    total_logs: int
    total_minutes: float
    total_hours: float
    tadoku_score_estimate: float
    tadoku_pending: int
    tadoku_ready: int
    tadoku_pushed: int
    by_content_type: dict[str, dict[str, float]]
    # unit -> sum of amounts (e.g. minutes, characters, pages)
    by_unit: dict[str, float]
    # activity -> unit -> sum of amounts
    by_activity: dict[str, dict[str, float]]


class TimelineDay(BaseModel):
    """Daily immersion totals (sparse — only days with logs)."""

    date: str  # YYYY-MM-DD
    hours: float = 0.0  # minutes + high-density → hours
    characters: float = 0.0
    pages: float = 0.0  # pages + two_column_pages
    comic_pages: float = 0.0
    sentences: float = 0.0
    score: float = 0.0
    logs: int = 0


class TimelineOut(BaseModel):
    year: int
    days: list[TimelineDay]
    totals: dict[str, float]


class ProgressMediaMeta(BaseModel):
    series_key: str
    content_type: str = ""
    title: str = ""
    display_title: Optional[str] = None
    source: str = "none"
    external_id: Optional[str] = None
    external_url: Optional[str] = None
    cover_url: Optional[str] = None
    cover_local: Optional[str] = None
    total_units: Optional[int] = None
    total_units_label: Optional[str] = None
    total_characters: Optional[int] = None
    total_minutes: Optional[int] = None
    fetched_at: Optional[str] = None
    # season number (str) → episode/volume count
    season_totals: dict[str, int] = Field(default_factory=dict)
    seasons_locked: bool = False


class ProgressSeasonOut(BaseModel):
    season: Optional[int] = None
    label: str = ""
    episodes_logged: int = 0
    progress_episodes: int = 0
    max_episode: Optional[int] = None
    total_episodes: Optional[int] = None
    percent_complete: Optional[float] = None
    is_done: bool = False
    log_count: int = 0
    minutes: Optional[float] = None


class ProgressItemOut(BaseModel):
    series_key: str
    title: str
    content_type: str
    progress_status: str = "active"  # active | finished | dropped | ignored
    log_count: int
    sources: list[str] = Field(default_factory=list)
    score_estimate: float = 0.0
    amounts: dict[str, float] = Field(default_factory=dict)
    primary_amount: Optional[float] = None
    primary_unit: Optional[str] = None
    progress_season: Optional[int] = None
    progress_episode: Optional[int] = None
    progress_label: Optional[str] = None
    episodes_logged: int = 0
    current_display: Optional[str] = None
    total_display: Optional[str] = None
    # Longer length breakdown for tooltips (franchise S1:n + S2:m, full unit names)
    total_display_detail: Optional[str] = None
    total_units: Optional[int] = None
    total_units_label: Optional[str] = None
    percent_complete: Optional[float] = None
    first_logged: Optional[str] = None
    last_logged: Optional[str] = None
    metadata: Optional[ProgressMediaMeta] = None
    has_metadata: bool = False
    has_cover: bool = False
    # True when cover and/or total length cannot be auto-calculated
    needs_user_input: bool = False
    # Machine tags: no_cover | no_length | lookup_failed
    meta_issues: list[str] = Field(default_factory=list)
    # Open-in-browser search links for this type + title
    provider_hints: list[dict[str, str]] = Field(default_factory=list)
    # Season breakdown
    season_mode: str = "none"  # none | unscoped | single | multi | mixed
    is_multi_season: bool = False
    seasons: list[ProgressSeasonOut] = Field(default_factory=list)
    seasons_summary: Optional[str] = None
    season_totals: dict[str, int] = Field(default_factory=dict)
    franchise_total_episodes: Optional[int] = None
    franchise_done_episodes: Optional[int] = None


class ProgressListOut(BaseModel):
    items: list[ProgressItemOut]
    total: int
    content_types: dict[str, int] = Field(default_factory=dict)
    status_counts: dict[str, int] = Field(default_factory=dict)


class TadokuPullOut(BaseModel):
    ok: bool
    imported: int = 0
    skipped: int = 0
    remote_total: int = 0
    # How many remote logs matched title_query / series_key (before skip/import)
    matched: int = 0
    already_local: int = 0
    user_id: Optional[str] = None
    dry_run: bool = False
    error: Optional[str] = None
    samples: list[str] = Field(default_factory=list)
    matched_samples: list[str] = Field(default_factory=list)
    query: Optional[str] = None
    series_key: Optional[str] = None
    # Fresh progress snapshot so the UI can update without a separate GET
    progress: Optional[ProgressListOut] = None


class EnrichBody(BaseModel):
    """Request media metadata for one or many series_keys."""

    series_keys: Optional[list[str]] = None
    force: bool = False
    limit: int = Field(default=80, ge=1, le=300)
    # After pull: only fill works still missing covers (default true path from UI)
    only_missing: bool = True
    # Re-query source=none even inside TTL (same as force for negatives only)
    retry_none: bool = False


class ProgressFixupBody(BaseModel):
    """
    Quick Progress edits for selected works.

    actions:
      - set_type: change content_type on logs + catalog
      - rename: set display title (optional episode peel from old titles)
      - merge: collapse many series_keys into one (groupings / GTO / Yugi)
      - refetch_cover: force jiten lookup with clean title
      - set_metadata: manual cover / totals / import provider URL
    """

    action: str = Field(
        ...,
        description=(
            "set_type | rename | merge | refetch_cover | recover_notes | "
            "set_status | set_metadata"
        ),
    )
    # Required for most actions; optional/empty for recover_notes (scans all)
    series_keys: list[str] = Field(default_factory=list)
    content_type: Optional[str] = None
    title: Optional[str] = None
    target_series_key: Optional[str] = None
    # active | finished | dropped | ignored
    progress_status: Optional[str] = None
    parse_episodes: bool = True
    refetch_meta: bool = True
    # set_metadata / import_url
    import_url: Optional[str] = None
    cover_url: Optional[str] = None
    total_units: Optional[int] = None
    total_units_label: Optional[str] = None
    total_characters: Optional[int] = None
    total_minutes: Optional[int] = None
    external_url: Optional[str] = None
    # "1:12, 2:13" or JSON map — episodes/volumes per season
    season_totals: Optional[str] = None


