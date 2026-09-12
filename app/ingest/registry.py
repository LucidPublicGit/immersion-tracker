"""
Lightweight registry of pollable integrations for the scheduler.

Each entry maps a config attribute name on AppYamlConfig to a poll callable.
Integrations remain isolated modules; this only wires scheduling + status.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.ingest.base import PollResult

logger = logging.getLogger(__name__)

PollFn = Callable[[Session], PollResult]


@dataclass(frozen=True)
class IntegrationSpec:
    """Metadata for a poll-based integration."""

    name: str
    # Attribute on AppYamlConfig (e.g. "steam")
    config_attr: str
    # Import path "app.ingest.steam:poll_steam"
    poll_path: str
    # Default poll interval seconds if config.poll_seconds missing
    default_poll_seconds: int = 300
    # Scheduler job id
    job_id: str = ""

    def resolve_poll(self) -> PollFn:
        module_path, _, attr = self.poll_path.partition(":")
        if not module_path or not attr:
            raise ValueError(f"bad poll_path for {self.name}: {self.poll_path}")
        import importlib

        mod = importlib.import_module(module_path)
        fn = getattr(mod, attr)
        return fn  # type: ignore[return-value]


# Poll-based integrations (webhook-only sources like youtube/plex/asbplayer stay out)
POLL_INTEGRATIONS: list[IntegrationSpec] = [
    IntegrationSpec(
        name="steam",
        config_attr="steam",
        poll_path="app.ingest.steam:poll_steam",
        default_poll_seconds=600,
        job_id="steam_poll",
    ),
    IntegrationSpec(
        name="anki",
        config_attr="anki",
        poll_path="app.ingest.anki:poll_anki",
        default_poll_seconds=300,
        job_id="anki_poll",
    ),
    IntegrationSpec(
        name="spotify",
        config_attr="spotify",
        poll_path="app.ingest.spotify:poll_spotify",
        default_poll_seconds=300,
        job_id="spotify_poll",
    ),
    IntegrationSpec(
        name="mpv",
        config_attr="mpv",
        poll_path="app.ingest.mpv:poll_mpv",
        default_poll_seconds=120,
        job_id="mpv_poll",
    ),
]


def get_integration_config(cfg: Any, attr: str) -> Any:
    return getattr(cfg, attr, None)


def is_enabled(cfg: Any, attr: str) -> bool:
    section = get_integration_config(cfg, attr)
    if section is None:
        return False
    return bool(getattr(section, "enabled", False))


def poll_seconds(cfg: Any, spec: IntegrationSpec) -> int:
    section = get_integration_config(cfg, spec.config_attr)
    raw = getattr(section, "poll_seconds", None) if section is not None else None
    try:
        secs = int(raw if raw is not None else spec.default_poll_seconds)
    except (TypeError, ValueError):
        secs = spec.default_poll_seconds
    return max(60, secs)


def run_poll(db: Session, name: str) -> PollResult:
    """Run a named poll integration by registry name."""
    for spec in POLL_INTEGRATIONS:
        if spec.name == name:
            fn = spec.resolve_poll()
            return fn(db)
    return PollResult(ok=False, source=name, message=f"unknown integration: {name}")


def list_poll_status(cfg: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in POLL_INTEGRATIONS:
        section = get_integration_config(cfg, spec.config_attr)
        out.append(
            {
                "name": spec.name,
                "enabled": is_enabled(cfg, spec.config_attr),
                "poll_seconds": poll_seconds(cfg, spec) if section else spec.default_poll_seconds,
                "job_id": spec.job_id or f"{spec.name}_poll",
            }
        )
    return out
