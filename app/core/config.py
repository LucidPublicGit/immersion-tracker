from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class ContentTypeDefault(BaseModel):
    activity: str = "listening"
    unit: str = "minutes"
    tadoku_mode: str = "pending"


class YouTubeConfig(BaseModel):
    completion_threshold: float = 0.90
    # Require this much actual watch progress (seconds) in addition to ratio.
    # Blocks short clips and end-seeks on short videos from counting.
    min_watched_seconds: float = 300.0
    # Uploader/channel filters (who made the video)
    channel_allowlist: list[str] = Field(default_factory=list)
    channel_blocklist: list[str] = Field(default_factory=list)
    # Signed-in YouTube *viewer* accounts allowed to log (UC… or @handle).
    # Empty = accept any account (rely on who has the extension installed).
    viewer_allowlist: list[str] = Field(default_factory=list)
    tadoku_default: str = "pending"


class PlexConfig(BaseModel):
    watch_threshold: float = 0.90
    library_map: dict[str, str] = Field(
        default_factory=lambda: {
            "Anime": "anime",
            "Movies": "show",
            "TV Shows": "show",
        }
    )
    # Optional per-library language (ISO-ish: ja / en). Used for Progress Japanese-only filter.
    # e.g. {"TV Shows": "en", "Movies": "en", "Anime": "ja"}
    library_language: dict[str, str] = Field(default_factory=dict)
    tadoku_default: str = "pending"


class ProgressConfig(BaseModel):
    """Progress / library shelf rules."""

    # Hide non-Japanese works (English TV, etc.) from the Progress shelf
    japanese_only: bool = True
    # Allowed media languages on the shelf (log.language / catalog)
    languages: list[str] = Field(
        default_factory=lambda: ["ja", "jpn", "japanese", "jp"]
    )
    # Extra hard excludes (substring match on title or series_key), case-insensitive
    exclude_titles: list[str] = Field(default_factory=list)
    exclude_series_keys: list[str] = Field(default_factory=list)
    # If true, works where every log is tadoku_mode=never are also hidden
    # (useful when you mark English shows as Never for Tadoku)
    hide_tadoku_never: bool = True


class SheetsConfig(BaseModel):
    enabled: bool = False
    spreadsheet_id: str = ""
    # Auth (first match wins): service account JSON env → SA file → OAuth user token
    service_account_file: str = ""
    # Desktop OAuth client secrets (when org blocks SA keys)
    oauth_client_secrets_file: str = "/app/data/google-oauth-client.json"
    # Saved user refresh token from scripts/google_oauth_login.py
    oauth_token_file: str = "/app/data/google-oauth-token.json"
    tabs: dict[str, str] = Field(
        default_factory=lambda: {
            "logs": "Logs",
            "manual": "Manual Entry",
            "catalog": "Catalog",
            "rules": "Rules",
            "queue": "Tadoku Queue",
            "metrics": "Metrics",
        }
    )
    # How often to poll sheet for user edits (reads only; keep low, ≥15s)
    poll_manual_seconds: int = 30
    # How often to push DB → sheet when dirty (writes; hash-skips unchanged tabs)
    push_sync_seconds: int = 180
    # Type tabs / Queue / Metrics as live FILTER formulas over Logs (All).
    # True = no duplicated row dumps; browser updates views instantly.
    formula_views: bool = True


class HoshiAdbConfig(BaseModel):
    """ADB access to Hoshi on a Boox / Android device."""

    # adb binary name or absolute path
    binary: str = "adb"
    # Optional device serial (adb devices). Empty = first online device.
    serial: str = ""
    # Wireless ADB target, e.g. "192.168.1.50:5555" (adb connect before poll)
    connect: str = ""
    package: str = "moe.antimony.hoshi"
    # Override Books directory on device if auto-detect fails
    books_path: str = ""


class HoshiConfig(BaseModel):
    """
    Hoshi Reader character tracking.

    Polls Drive/ADB for stats deltas, **buckets** them per book, and only
    creates formal logs when:
      - log_mode=auto and pending ≥ min_submit_characters, or
      - the user submits from the Reading UI.
    """

    enabled: bool = False
    # drive (default) | adb | auto (try ADB, then Drive)
    source: str = "drive"
    adb: HoshiAdbConfig = Field(default_factory=HoshiAdbConfig)
    root_folder_name: str = "ttu-reader-data"
    root_folder_id: str = ""
    poll_seconds: int = 300
    content_type: str = "book"
    unit: str = "characters"
    # Ignore remote day-total noise below this when computing a delta (usually 1)
    min_characters: int = 1
    # First sight of a day: false = baseline only (recommended); true = treat as full delta
    bootstrap: bool = False
    # manual = only UI submit; auto = submit when pending ≥ threshold AND idle
    log_mode: str = "manual"
    # Auto-submit threshold (characters pending on a book bucket)
    min_submit_characters: int = 500
    # Wait this long after the last session fragment before auto-submitting.
    # Prevents logging mid-read if Hoshi uploads stats on every page turn.
    # 0 = submit as soon as min_submit_characters is reached (not recommended).
    auto_submit_idle_minutes: float = 30.0
    # Optional tadoku mode override for hoshi source (empty = content_type default)
    tadoku_default: str = ""


class GsmConfig(BaseModel):
    """
    GameSentenceMiner line DB → character logs → Tadoku.

    Reads game_lines (never deletes). Optionally advances GSM's
    stats_export_state tadoku_incremental cursor after a full successful export
    so GSM's own Tadoku preview stays in sync.
    """

    enabled: bool = True
    # Empty = auto-detect (GSM_DB_PATH, /gsm/gsm.db, %APPDATA%/GameSentenceMiner/gsm.db)
    db_path: str = ""
    # Default content_type when GSM game.type is missing/unknown
    content_type: str = "visual_novel"
    tadoku_default: str = "pending"  # auto | pending | never
    # Write GSM tadoku_incremental watermark after batch is fully pushed/skipped
    advance_cursor: bool = True
    # manual = only Queue UI; auto = scheduler posts when per-game min + idle met
    log_mode: str = "manual"
    # Per-game pending characters required before auto export
    min_submit_characters: int = 10000
    # Wait this long after the newest line for a game before auto-logging it
    auto_submit_idle_minutes: float = 30.0
    # Default for preview / auto export (export-only; lines stay in GSM)
    deduplicate: bool = False
    # Match GSM stats/Tadoku cleaning: strip Unicode punctuation, symbols, separators
    # (GSM clean_text_for_stats: [\p{P}\p{S}\p{Z}]) before counting characters.
    strip_punctuation: bool = True
    # Collapse a single line that is the same block pasted many times (e.g. MAGES
    # mail hook emitting one email × N in one game_lines row). Count one copy.
    collapse_repeated_blocks: bool = True
    # Skip clipboard/code/English lines with almost no Japanese (JP immersion).
    require_japanese: bool = True
    # Soft cap per line after collapse (0 = no cap). Safety net for other hook spam.
    max_line_characters: int = 0
    # How often the continuous auto-export job checks (seconds)
    poll_seconds: int = 120
    # Daily dump at a fixed local hour (independent of continuous auto idle)
    auto_log_at_time_enabled: bool = False
    auto_log_at_hour: int = 4  # 0–23 local
    # IANA timezone for the daily time (also used if TZ env is unset)
    timezone: str = "America/Los_Angeles"


class AudiobookshelfConfig(BaseModel):
    """
    Audiobookshelf listening sessions → minutes (rolling + daily dump).

    Same shape as GSM: manual rolling submit, optional auto after idle,
    optional once-per-day dump at a fixed local hour.
    """

    enabled: bool = False
    # e.g. http://host.docker.internal:13378 or http://127.0.0.1:13378
    base_url: str = ""
    # User API token (Settings → API). Or env AUDIOBOOKSHELF_TOKEN / ABS_TOKEN.
    api_token: str = ""
    poll_seconds: int = 120
    timeout_seconds: float = 30.0
    content_type: str = "audiobook"
    podcast_content_type: str = "podcast"
    include_books: bool = True
    include_podcasts: bool = True
    # Empty = all libraries; otherwise ABS library UUIDs
    library_ids: list[str] = Field(default_factory=list)
    # Ignore per-session deltas smaller than this (0 = bank all; yaabsa syncs small chunks)
    min_session_seconds: float = 0.0
    unit: str = "minutes_high_density"  # tadoku dense listening minutes
    activity: str = "listening"
    tadoku_default: str = "pending"
    # First poll baselines watermarks (skip ancient history)
    bootstrap: bool = True
    # Playhead (currentTime) credits, capped by wall clock × this (1.5x–2.5x speed)
    use_position: bool = True
    max_play_speed: float = 2.5
    # ABS /api/me/listening-stats lifetime timeListening per item (floor)
    use_listening_stats: bool = True
    log_mode: str = "manual"  # manual | auto
    min_submit_minutes: float = 5.0
    auto_submit_idle_minutes: float = 30.0
    auto_log_at_time_enabled: bool = False
    auto_log_at_hour: int = 4
    timezone: str = "America/Los_Angeles"


class SteamConfig(BaseModel):
    """
    Steam Web API playtime deltas → game logs (minutes).

    Requires STEAM_API_KEY (or api_key) + steam_id (64-bit).
    Prefer app_allowlist so non-JP / non-immersion titles are ignored.
    """

    enabled: bool = False
    api_key: str = ""  # or env STEAM_API_KEY
    steam_id: str = ""  # SteamID64
    poll_seconds: int = 600
    # Empty allowlist = all owned games with playtime (noisy). Prefer explicit appids.
    app_allowlist: list[int] = Field(default_factory=list)
    app_blocklist: list[int] = Field(default_factory=list)
    # Optional name substrings (case-insensitive) to include when allowlist empty
    name_allowlist: list[str] = Field(default_factory=list)
    name_blocklist: list[str] = Field(default_factory=list)
    min_delta_minutes: float = 1.0
    content_type: str = "game"
    unit: str = "minutes"
    activity: str = "reading"  # VN-like; override per catalog if needed
    tadoku_default: str = "never"
    # First sight of an app: baseline only (recommended) vs log full lifetime playtime
    bootstrap: bool = False
    include_played_free_games: bool = True
    include_appinfo: bool = True


class AnkiConfig(BaseModel):
    """
    AnkiConnect → study logs (review time as minutes).

    Anki must be running with AnkiConnect (default http://127.0.0.1:8765).
    From Docker, use host.docker.internal and allow the origin in AnkiConnect config.
    """

    enabled: bool = False
    connect_url: str = "http://host.docker.internal:8765"
    poll_seconds: int = 300
    # Empty = all decks; otherwise only these deck names (exact or prefix*)
    deck_allowlist: list[str] = Field(default_factory=list)
    deck_blocklist: list[str] = Field(default_factory=list)
    min_delta_minutes: float = 0.5
    content_type: str = "study"
    unit: str = "minutes"
    activity: str = "study"
    tadoku_default: str = "never"
    # Title used for aggregated study logs
    title: str = "Anki"
    series_key: str = "anki"
    # Request timeout seconds
    timeout_seconds: float = 10.0


class SpotifyConfig(BaseModel):
    """
    Spotify recently-played podcast episodes → listening minutes.

    OAuth: set client_id/client_secret (or env), run token setup script once.
    Prefer show_allowlist (show ids or names) so music/noise is ignored.
    """

    enabled: bool = False
    client_id: str = ""  # or env SPOTIFY_CLIENT_ID
    client_secret: str = ""  # or env SPOTIFY_CLIENT_SECRET
    # Refresh token JSON path (written by scripts/spotify_oauth_setup.py)
    token_file: str = "/app/data/spotify-oauth-token.json"
    poll_seconds: int = 300
    # Show IDs (Spotify URI tail) and/or name substrings
    show_allowlist: list[str] = Field(default_factory=list)
    show_blocklist: list[str] = Field(default_factory=list)
    # Only log podcast episodes (skip music tracks)
    podcasts_only: bool = True
    # Minimum progress ratio to count a play as "listened" (recently-played has no ratio;
    # we log full episode duration when it appears in recently played).
    completion_threshold: float = 0.0
    content_type: str = "podcast"
    unit: str = "minutes"
    activity: str = "listening"
    tadoku_default: str = "pending"
    market: str = "US"


class MpvConfig(BaseModel):
    """
    mpv watch history / JSONL session files → anime/show minutes.

    Primary path: poll a watch-history JSON/JSONL written by mpv or our lua helper.
    Secondary: POST /api/webhooks/mpv from scripts/mpv/immersion-tracker.lua
    """

    enabled: bool = False
    # Path inside container or host; empty tries common defaults
    history_path: str = ""
    poll_seconds: int = 120
    completion_threshold: float = 0.90
    min_watched_seconds: float = 60.0
    content_type: str = "anime"
    unit: str = "minutes"
    activity: str = "listening"
    tadoku_default: str = "pending"
    # Path substrings that force content_type=show instead of anime
    show_path_markers: list[str] = Field(
        default_factory=lambda: ["jdrama", "drama", "live-action", "shows"]
    )


class AsbplayerConfig(BaseModel):
    """
    asbplayer / local subtitled media → anime minutes via webhook.

    asbplayer has no stable server-side stats export; use the companion userscript
    or POST /api/webhooks/asbplayer when a video is finished.
    """

    enabled: bool = True  # webhook always available; flag gates default tadoku only
    completion_threshold: float = 0.90
    min_watched_seconds: float = 60.0
    content_type: str = "anime"
    unit: str = "minutes"
    activity: str = "listening"
    tadoku_default: str = "pending"


class SchedulerConfig(BaseModel):
    enabled: bool = True
    # Legacy alias used as push interval fallback if push_sync_seconds unset
    sheet_sync_seconds: int = 180
    # Tadoku live submit batch interval (independent of sheets)
    tadoku_process_seconds: int = 300
    # Minimal public tadoku.app path canaries (leaderboard HTML + API). GET-only.
    tadoku_upstream_check: bool = True
    # How often to run (hours). Floor 1h; default 12h keeps load tiny.
    tadoku_upstream_check_hours: float = 12.0


class MetadataConfig(BaseModel):
    """External media lookup (covers, episode totals) for Progress."""

    # Re-try works cached as source=none after this many days
    none_retry_days: int = 14
    min_match_score: int = 75
    # Free key from themoviedb.org — enables Western TV/movie posters + episode counts
    tmdb_api_key: str = ""  # or env TMDB_API_KEY
    # Optional VNDB token (search works without it)
    vndb_token: str = ""
    jikan_min_interval_ms: int = 400
    open_library: bool = True
    vndb: bool = True
    tmdb: bool = True
    jiten: bool = True
    jikan: bool = True
    anilist: bool = True
    steam: bool = True  # store search for game covers (no key)
    wikipedia: bool = True  # free cover fallback
    tvmaze: bool = True  # Western TV covers + episode counts (no key)


class TadokuContestConfig(BaseModel):
    """Default contest selected on tadoku.app Manual log form."""

    name: str = ""
    # Contest UUID from URL /contests/{id}/leaderboard/1
    contest_id: str = ""
    # Your registration UUID for that contest (sent as registration_ids on create)
    registration_id: str = ""


class TadokuConfig(BaseModel):
    """Live tadoku.app submit + contest defaults."""

    # When true and auth (credentials or cookie) is available, POST to tadoku.app
    live_submit: bool = True
    # Approve button also calls submit immediately
    auto_submit_on_approve: bool = True
    api_base: str = "https://tadoku.app/api/internal/immersion"
    language_code: str = "jpn"  # ISO-639-3
    # Prefer Queue UI credentials (encrypted) or env TADOKU_USERNAME/PASSWORD.
    # Legacy cookie still supported:
    session_cookie_env: str = "TADOKU_COOKIE"
    session_cookie: str = ""  # optional fallback (not recommended)
    # Your Tadoku account UUID (for Progress → Pull from Tadoku).
    # Auto-discovered from data/tadoku_export when empty.
    user_id: str = ""
    contest: TadokuContestConfig = Field(default_factory=TadokuContestConfig)
    # Optional unit UUID overrides: minutes / page / comic page / character
    unit_ids: dict[str, str] = Field(default_factory=dict)


class AppYamlConfig(BaseModel):
    language_default: str = "ja"
    youtube: YouTubeConfig = Field(default_factory=YouTubeConfig)
    plex: PlexConfig = Field(default_factory=PlexConfig)
    hoshi: HoshiConfig = Field(default_factory=HoshiConfig)
    gsm: GsmConfig = Field(default_factory=GsmConfig)
    audiobookshelf: AudiobookshelfConfig = Field(default_factory=AudiobookshelfConfig)
    steam: SteamConfig = Field(default_factory=SteamConfig)
    anki: AnkiConfig = Field(default_factory=AnkiConfig)
    spotify: SpotifyConfig = Field(default_factory=SpotifyConfig)
    mpv: MpvConfig = Field(default_factory=MpvConfig)
    asbplayer: AsbplayerConfig = Field(default_factory=AsbplayerConfig)
    content_type_defaults: dict[str, ContentTypeDefault] = Field(default_factory=dict)
    tadoku_scores: dict[str, dict[str, float]] = Field(default_factory=dict)
    tadoku: TadokuConfig = Field(default_factory=TadokuConfig)
    sheets: SheetsConfig = Field(default_factory=SheetsConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    metadata: MetadataConfig = Field(default_factory=MetadataConfig)
    progress: ProgressConfig = Field(default_factory=ProgressConfig)
    api: dict[str, Any] = Field(default_factory=dict)


class Settings(BaseSettings):
    database_url: str = "sqlite:////app/data/immersion.db"
    config_path: str = "/app/config/settings.yaml"
    webhook_secret: str = ""
    # Optional HTTP Basic Auth for HTML + most API (empty = off).
    # Webhooks + /api/youtube/* stay on WEBHOOK_SECRET only.
    ui_username: str = "admin"
    ui_password: str = ""
    host: str = "0.0.0.0"
    port: int = 8000
    google_service_account_json: str = ""
    tadoku_cookie: str = ""  # maps TADOKU_COOKIE via env

    model_config = {"env_file": ".env", "extra": "ignore"}

    yaml_config: AppYamlConfig = Field(default_factory=AppYamlConfig)

    def load_yaml(self) -> None:
        path = Path(self.config_path)
        # Dev fallback: repo config/settings.yaml or example
        candidates = [
            path,
            Path("config/settings.yaml"),
            Path("config/settings.example.yaml"),
        ]
        data: dict[str, Any] = {}
        for candidate in candidates:
            if candidate.is_file():
                with candidate.open(encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                break
        self.yaml_config = AppYamlConfig.model_validate(data)
        # Env secret wins over yaml
        if not self.webhook_secret:
            self.webhook_secret = str(self.yaml_config.api.get("webhook_secret") or "")
        if not self.ui_password:
            self.ui_password = str(self.yaml_config.api.get("ui_password") or "")
        if self.ui_username == "admin":
            yaml_user = str(self.yaml_config.api.get("ui_username") or "").strip()
            if yaml_user:
                self.ui_username = yaml_user
        if os.getenv("DATABASE_URL"):
            self.database_url = os.environ["DATABASE_URL"]
        # TMDB free key from env when yaml empty
        meta = self.yaml_config.metadata
        if not (meta.tmdb_api_key or "").strip() and os.getenv("TMDB_API_KEY"):
            meta.tmdb_api_key = os.environ["TMDB_API_KEY"].strip()
        # Inject cookie into yaml config path used by client
        if self.tadoku_cookie and not self.yaml_config.tadoku.session_cookie:
            self.yaml_config.tadoku.session_cookie = self.tadoku_cookie
        if os.getenv("TADOKU_COOKIE") and not self.yaml_config.tadoku.session_cookie:
            self.yaml_config.tadoku.session_cookie = os.environ["TADOKU_COOKIE"]

    def sqlite_file_path(self) -> Path | None:
        """Filesystem path for sqlite URL, or None if not sqlite."""
        url = (self.database_url or "").strip()
        if not url.startswith("sqlite:"):
            return None
        # sqlite:////abs  or  sqlite:///rel
        if url.startswith("sqlite:////"):
            return Path("/" + url[len("sqlite:////") :])
        if url.startswith("sqlite:///"):
            return Path(url[len("sqlite:///") :])
        return None


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.load_yaml()
    return s


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
