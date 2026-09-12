"""
Shared types for isolated ingest integrations.

Each integration module (steam, anki, spotify, mpv, asbplayer, …) should:
  * Own its config under AppYamlConfig.<name>
  * Own its poll/ingest logic in app/ingest/<name>.py
  * Store watermarks via app.sheets.state get_state/set_state with a namespaced key
  * Return PollResult from poll_* functions used by the scheduler
  * Call create_log() from app.ingest.service (never write LogEntry directly)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class PollResult:
    """Standard result for scheduled / manual sync of a poll-based integration."""

    ok: bool
    source: str
    logs_created: int = 0
    skipped: int = 0
    message: str = ""
    errors: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class IngestResult:
    """Standard result for a single webhook / event ingest."""

    accepted: bool
    reason: str
    log_id: Optional[int] = None
    log: Optional[dict[str, Any]] = None
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
