from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.session import get_engine
from app.ingest.registry import POLL_INTEGRATIONS, is_enabled, poll_seconds
from app.sheets.state import is_sheets_dirty, mark_sheets_dirty
from app.sheets.sync import (
    get_sheets_client,
    pull_user_edits,
    push_db_to_sheets,
    full_sync,
)
from app.tadoku.queue import process_ready

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _job_poll_integration(name: str) -> None:
    """Generic scheduled poll for registry-backed integrations (steam/anki/spotify/mpv)."""
    db = _db_session()
    try:
        from app.ingest.registry import run_poll

        result = run_poll(db, name)
        if result.logs_created or not result.ok:
            logger.info("%s poll: %s", name, result.to_dict())
            if result.logs_created:
                mark_sheets_dirty(db)
        else:
            logger.debug("%s poll: %s", name, result.message or "ok")
    except Exception:
        logger.exception("%s poll failed", name)
    finally:
        db.close()


def _db_session() -> Session:
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return SessionLocal()


def job_sheet_pull() -> None:
    """
    Frequent, cheap: sheet → DB only (user-edit priority).
    CPU is idle between ticks; work is a few Sheets *reads*.
    """
    db = _db_session()
    try:
        client = get_sheets_client()
        if not client.enabled:
            return
        result = pull_user_edits(db, client, include_type_tabs=False)
        # Log only when something actually changed
        changed = False
        for key in ("logs_pull", "queue_pull", "manual", "catalog_pull"):
            part = result.get(key) or {}
            if any(
                int(part.get(k) or 0) > 0
                for k in ("updated", "created", "deleted", "imported")
            ):
                changed = True
                break
        if changed:
            logger.info("sheet pull (user edits): %s", result)
        else:
            logger.debug("sheet pull: no changes")
    except Exception:
        logger.exception("sheet pull failed")
    finally:
        db.close()


def job_sheet_push() -> None:
    """
    Batched DB → sheet. Always pull first so user cells win, then write only
    tabs whose content hash changed. Skips entirely when clean (no dirty flag)
    except periodic force every Nth run is not needed — dirty covers local
    ingest; pull marks dirty on sheet-driven DB changes.
    """
    db = _db_session()
    try:
        client = get_sheets_client()
        if not client.enabled:
            return

        # User priority: always re-read editable tabs before any rewrite
        pull_user_edits(db, client, include_type_tabs=False)

        dirty = is_sheets_dirty(db)
        # Even if not dirty, still hash-check occasionally? We skip when clean
        # to avoid building large payloads every push interval with no local changes.
        # First boot / never pushed: dirty may be false and hashes empty — force
        # a push once so the sheet gets initial data.
        force_bootstrap = False
        if not dirty:
            from app.sheets.state import get_push_hash

            if not get_push_hash(db, "logs_all"):
                force_bootstrap = True

        if not dirty and not force_bootstrap:
            logger.debug("sheet push: clean, skip")
            return

        from app.sheets.sync import _should_apply_validations

        apply_vals = _should_apply_validations()
        # Type tabs only when dirty (not every validation hour alone)
        result = push_db_to_sheets(
            db,
            client,
            apply_validations=apply_vals,
            push_type_tabs=True,
            force=False,
            skip_if_clean=False,
        )
        logger.info("sheet push: %s", result)
    except Exception:
        logger.exception("sheet push failed")
    finally:
        db.close()


def job_sheet_sync() -> None:
    """Legacy full bidirectional sync (also used if only one interval is configured)."""
    db = _db_session()
    try:
        result = full_sync(db, run_tadoku=False, include_type_tabs=False)
        logger.info("sheet sync: %s", result)
    except Exception:
        logger.exception("sheet sync failed")
    finally:
        db.close()


def job_process_auto_tadoku() -> None:
    """Push READY (auto) entries on a schedule — independent of sheet writes."""
    db = _db_session()
    try:
        result = process_ready(db)
        if result.get("pushed") or result.get("failed") or result.get("promoted_auto"):
            logger.info("tadoku process: %s", result)
            if result.get("pushed") or result.get("promoted_auto"):
                mark_sheets_dirty(db)
    except Exception:
        logger.exception("tadoku process failed")
    finally:
        db.close()


def job_tadoku_upstream_check() -> None:
    """Infrequent GET-only canaries for contest leaderboard page + API."""
    try:
        from app.tadoku.upstream_monitor import run_minimal_probes

        run_minimal_probes()
    except Exception:
        logger.exception("tadoku upstream monitor job failed")


def job_hoshi_drive_poll() -> None:
    """Poll Hoshi/TTU Google Drive statistics into reading buckets."""
    db = _db_session()
    try:
        settings = get_settings()
        if not settings.yaml_config.hoshi.enabled:
            return
        from app.ingest.hoshi import poll_hoshi

        result = poll_hoshi(db)
        if (
            result.logs_created
            or result.sessions_added
            or not result.ok
        ):
            logger.info("hoshi poll: %s", result.to_dict())
    except Exception:
        logger.exception("hoshi drive poll failed")
    finally:
        db.close()


def job_hoshi_idle_auto_submit() -> None:
    """
    Auto-submit reading buckets that hit the char threshold and have been
    idle long enough (no mid-session logging while actively reading).
    """
    db = _db_session()
    try:
        settings = get_settings()
        hoshi = settings.yaml_config.hoshi
        if not hoshi.enabled:
            return
        from app.ingest.hoshi_buckets import (
            get_log_mode,
            process_auto_submit_idle_buckets,
        )
        from app.sheets.state import mark_sheets_dirty

        if get_log_mode(db) not in ("auto", "automatic"):
            return

        submitted = process_auto_submit_idle_buckets(db)
        if submitted:
            logger.info("hoshi idle auto-submit job: %s", submitted)
            mark_sheets_dirty(db)
    except Exception:
        logger.exception("hoshi idle auto-submit job failed")
    finally:
        db.close()


def job_gsm_auto_export() -> None:
    """
    Finish pending GSM export/cursor sync (any mode), then when log_mode=auto
    queue+submit games that meet min characters + idle quiet period.
    """
    db = _db_session()
    try:
        settings = get_settings()
        gsm = settings.yaml_config.gsm
        if not getattr(gsm, "enabled", True):
            return
        from app.ingest.gsm import process_auto_export
        from app.sheets.state import mark_sheets_dirty

        # Always run: process_auto_export finishes pending watermark work even
        # in manual mode (fixes stuck counters after locked GSM file writes).
        result = process_auto_export(db)
        if result.get("created") or (result.get("submitted") or {}).get("pushed"):
            logger.info("gsm auto-export job: %s", {
                k: result.get(k)
                for k in (
                    "message",
                    "created",
                    "submitted",
                    "cursor_advanced",
                    "skipped",
                    "reason",
                )
                if k in result
            })
            mark_sheets_dirty(db)
        elif result.get("finish") and (
            (result["finish"].get("advanced")) or (result["finish"].get("synced"))
        ):
            logger.info("gsm auto-export finish-only: %s", result.get("finish"))
    except Exception:
        logger.exception("gsm auto-export job failed")
    finally:
        db.close()


def job_gsm_daily_time_export() -> None:
    """
    Poll each minute; when local hour matches prefs and enabled, dump pending
    GSM games (≥ min characters) once per local day.
    """
    db = _db_session()
    try:
        settings = get_settings()
        gsm = settings.yaml_config.gsm
        if not getattr(gsm, "enabled", True):
            return
        from app.ingest.gsm import process_daily_time_export
        from app.sheets.state import mark_sheets_dirty

        result = process_daily_time_export(db)
        if result.get("skipped"):
            return
        if result.get("created") or (result.get("submitted") or {}).get("pushed"):
            logger.info("gsm daily time-export job: %s", result.get("message"))
            mark_sheets_dirty(db)
        elif result.get("ok"):
            logger.debug("gsm daily time-export: %s", result.get("message") or result)
    except Exception:
        logger.exception("gsm daily time-export job failed")
    finally:
        db.close()


def job_abs_auto_export() -> None:
    """Poll Audiobookshelf sessions; auto-submit when mode=auto + min + idle."""
    db = _db_session()
    try:
        settings = get_settings()
        abs_cfg = settings.yaml_config.audiobookshelf
        if not getattr(abs_cfg, "enabled", False):
            return
        from app.ingest.audiobookshelf import process_auto_export
        from app.sheets.state import mark_sheets_dirty

        result = process_auto_export(db)
        if result.get("created"):
            logger.info("abs auto-export job: %s", result.get("message"))
            mark_sheets_dirty(db)
        elif result.get("poll") and not result.get("skipped"):
            logger.debug("abs auto-export: %s", result.get("poll"))
    except Exception:
        logger.exception("abs auto-export job failed")
    finally:
        db.close()


def job_abs_daily_time_export() -> None:
    """Once per local day at hour: dump ABS pending minutes (≥ min)."""
    db = _db_session()
    try:
        settings = get_settings()
        abs_cfg = settings.yaml_config.audiobookshelf
        if not getattr(abs_cfg, "enabled", False):
            return
        from app.ingest.audiobookshelf import process_daily_time_export
        from app.sheets.state import mark_sheets_dirty

        result = process_daily_time_export(db)
        if result.get("skipped"):
            return
        if result.get("created"):
            logger.info("abs daily time-export job: %s", result.get("message"))
            mark_sheets_dirty(db)
        elif result.get("ok"):
            logger.debug("abs daily time-export: %s", result.get("message") or result)
    except Exception:
        logger.exception("abs daily time-export job failed")
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    settings = get_settings()
    if not settings.yaml_config.scheduler.enabled:
        logger.info("scheduler disabled")
        return None
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler()
    sheets_cfg = settings.yaml_config.sheets
    sched_cfg = settings.yaml_config.scheduler

    if sheets_cfg.enabled:
        # Frequent pull: poll_manual_seconds (user edits). Cheap reads only.
        pull_secs = max(15, int(sheets_cfg.poll_manual_seconds or 30))
        # Batched push: push_sync_seconds, fallback sheet_sync_seconds
        push_secs = int(
            sheets_cfg.push_sync_seconds
            or sched_cfg.sheet_sync_seconds
            or 180
        )
        push_secs = max(push_secs, pull_secs)  # push never faster than pull

        _scheduler.add_job(
            job_sheet_pull,
            "interval",
            seconds=pull_secs,
            id="sheet_pull",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(pull_secs, 30),
        )
        _scheduler.add_job(
            job_sheet_push,
            "interval",
            seconds=push_secs,
            id="sheet_push",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(push_secs, 60),
        )
        logger.info(
            "sheet jobs: pull every %ss, push every %ss (hash-skip unchanged tabs)",
            pull_secs,
            push_secs,
        )

    tadoku_secs = max(60, int(getattr(sched_cfg, "tadoku_process_seconds", 300) or 300))
    _scheduler.add_job(
        job_process_auto_tadoku,
        "interval",
        seconds=tadoku_secs,
        id="tadoku_process",
        max_instances=1,
        coalesce=True,
    )

    hoshi_cfg = settings.yaml_config.hoshi
    if hoshi_cfg.enabled:
        hoshi_secs = max(60, int(hoshi_cfg.poll_seconds or 300))
        _scheduler.add_job(
            job_hoshi_drive_poll,
            "interval",
            seconds=hoshi_secs,
            id="hoshi_drive_poll",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(hoshi_secs, 60),
            # First poll shortly after start so setup feedback is quick
            next_run_time=datetime.now(timezone.utc),
        )
        logger.info("hoshi Drive poll: every %ss", hoshi_secs)
        # Settle-check more often than Drive poll so idle sessions log promptly
        idle_check_secs = max(60, min(hoshi_secs, 120))
        _scheduler.add_job(
            job_hoshi_idle_auto_submit,
            "interval",
            seconds=idle_check_secs,
            id="hoshi_idle_auto_submit",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(idle_check_secs, 60),
        )
        logger.info(
            "hoshi idle auto-submit check: every %ss (idle wait %.0fm)",
            idle_check_secs,
            float(hoshi_cfg.auto_submit_idle_minutes or 0),
        )

    gsm_cfg = settings.yaml_config.gsm
    if getattr(gsm_cfg, "enabled", True):
        gsm_secs = max(60, int(getattr(gsm_cfg, "poll_seconds", 120) or 120))
        _scheduler.add_job(
            job_gsm_auto_export,
            "interval",
            seconds=gsm_secs,
            id="gsm_auto_export",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(gsm_secs, 60),
        )
        logger.info(
            "gsm auto-export check: every %ss (mode=%s, min=%s, idle=%.0fm)",
            gsm_secs,
            getattr(gsm_cfg, "log_mode", "manual"),
            getattr(gsm_cfg, "min_submit_characters", 10000),
            float(getattr(gsm_cfg, "auto_submit_idle_minutes", 30) or 0),
        )
        # Daily fixed-time dump: poll every minute; job no-ops unless enabled + hour match
        _scheduler.add_job(
            job_gsm_daily_time_export,
            "interval",
            seconds=60,
            id="gsm_daily_time_export",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=120,
        )
        logger.info(
            "gsm daily time-export: enabled=%s hour=%s tz=%s",
            bool(getattr(gsm_cfg, "auto_log_at_time_enabled", False)),
            int(getattr(gsm_cfg, "auto_log_at_hour", 4) or 4),
            getattr(gsm_cfg, "timezone", "") or os.environ.get("TZ") or "local",
        )

    abs_cfg = settings.yaml_config.audiobookshelf
    if getattr(abs_cfg, "enabled", False):
        abs_secs = max(60, int(getattr(abs_cfg, "poll_seconds", 120) or 120))
        _scheduler.add_job(
            job_abs_auto_export,
            "interval",
            seconds=abs_secs,
            id="abs_auto_export",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(abs_secs, 60),
        )
        logger.info(
            "abs auto-export check: every %ss (mode=%s, min=%.1fm, idle=%.0fm)",
            abs_secs,
            getattr(abs_cfg, "log_mode", "manual"),
            float(getattr(abs_cfg, "min_submit_minutes", 5) or 5),
            float(getattr(abs_cfg, "auto_submit_idle_minutes", 30) or 0),
        )
        _scheduler.add_job(
            job_abs_daily_time_export,
            "interval",
            seconds=60,
            id="abs_daily_time_export",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=120,
        )
        logger.info(
            "abs daily time-export: enabled=%s hour=%s tz=%s",
            bool(getattr(abs_cfg, "auto_log_at_time_enabled", False)),
            int(getattr(abs_cfg, "auto_log_at_hour", 4) or 4),
            getattr(abs_cfg, "timezone", "") or os.environ.get("TZ") or "local",
        )

    # Registry-backed poll integrations (steam, anki, spotify, mpv, …)
    cfg_root = settings.yaml_config
    for spec in POLL_INTEGRATIONS:
        if not is_enabled(cfg_root, spec.config_attr):
            continue
        secs = poll_seconds(cfg_root, spec)
        job_id = spec.job_id or f"{spec.name}_poll"
        # Bind name via default arg to avoid late-binding closure bugs
        def _make_job(n: str = spec.name) -> None:
            _job_poll_integration(n)

        _scheduler.add_job(
            _make_job,
            "interval",
            seconds=secs,
            id=job_id,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(secs, 60),
        )
        logger.info("%s poll: every %ss", spec.name, secs)

    # Minimal tadoku.app path monitor (leaderboard HTML + API only)
    if getattr(sched_cfg, "tadoku_upstream_check", True):
        hours = float(getattr(sched_cfg, "tadoku_upstream_check_hours", 12.0) or 12.0)
        hours = max(1.0, hours)
        upstream_secs = int(hours * 3600)
        _scheduler.add_job(
            job_tadoku_upstream_check,
            "interval",
            seconds=upstream_secs,
            id="tadoku_upstream",
            max_instances=1,
            coalesce=True,
            # Run once on start so a broken path shows up without waiting 12h
            next_run_time=datetime.now(timezone.utc),
        )
        logger.info(
            "tadoku upstream monitor: every %sh (minimal GET canaries)",
            hours,
        )

    _scheduler.start()
    logger.info("scheduler started")
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def tadoku_process_schedule() -> dict:
    """
    Safe status for the queue UI: interval + next auto process time.
    next_process_at is ISO-8601 UTC when the job is scheduled; null if off.
    """
    settings = get_settings()
    sched_cfg = settings.yaml_config.scheduler
    interval = max(60, int(getattr(sched_cfg, "tadoku_process_seconds", 300) or 300))
    enabled = bool(sched_cfg.enabled)
    next_at: str | None = None

    if enabled and _scheduler is not None:
        try:
            job = _scheduler.get_job("tadoku_process")
            if job and job.next_run_time is not None:
                nrt = job.next_run_time
                if nrt.tzinfo is None:
                    nrt = nrt.replace(tzinfo=timezone.utc)
                else:
                    nrt = nrt.astimezone(timezone.utc)
                next_at = nrt.isoformat().replace("+00:00", "Z")
        except Exception:  # noqa: BLE001
            logger.debug("could not read tadoku_process next_run_time", exc_info=True)

    return {
        "enabled": enabled,
        "interval_seconds": interval,
        "next_process_at": next_at,
    }


def tadoku_upstream_schedule() -> dict:
    """Status of the infrequent tadoku.app path monitor job."""
    from app.tadoku.upstream_monitor import load_last_report

    settings = get_settings()
    sched_cfg = settings.yaml_config.scheduler
    check_on = bool(getattr(sched_cfg, "tadoku_upstream_check", True))
    hours = float(getattr(sched_cfg, "tadoku_upstream_check_hours", 12.0) or 12.0)
    hours = max(1.0, hours)
    next_at: str | None = None

    if check_on and sched_cfg.enabled and _scheduler is not None:
        try:
            job = _scheduler.get_job("tadoku_upstream")
            if job and job.next_run_time is not None:
                nrt = job.next_run_time
                if nrt.tzinfo is None:
                    nrt = nrt.replace(tzinfo=timezone.utc)
                else:
                    nrt = nrt.astimezone(timezone.utc)
                next_at = nrt.isoformat().replace("+00:00", "Z")
        except Exception:  # noqa: BLE001
            logger.debug("could not read tadoku_upstream next_run_time", exc_info=True)

    return {
        "enabled": bool(sched_cfg.enabled and check_on),
        "interval_hours": hours,
        "next_check_at": next_at,
        "last": load_last_report(),
    }
