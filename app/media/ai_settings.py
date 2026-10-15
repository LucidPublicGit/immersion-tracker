"""Small persistent app controls and bounded, structured activity for local AI."""
from __future__ import annotations

import asyncio
from collections import deque
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid

_FIELDS = {'local_ai_enabled': 'LOCAL_AI_CATALOG_ENABLED', 'web_enabled': 'TITLE_LOOKUP_WEB_ENABLED',
           'auto_suggest_enabled': 'TITLE_LOOKUP_AUTO_SUGGEST_ENABLED'}
_ACTIVITY = deque(maxlen=50)
_LOCK = threading.RLock()


def settings_path():
    return Path(os.getenv('LOCAL_AI_SETTINGS_PATH', '/app/data/local-ai-settings.json' if Path('/app/data').is_dir() else 'data/local-ai-settings.json'))


def read_overrides():
    path = settings_path()
    try:
        if path.is_symlink() or path.stat().st_size > 4096: return {}
        value = json.loads(path.read_text())
        return {k: v for k, v in value.items() if k in _FIELDS and type(v) is bool}
    except (OSError, ValueError, AttributeError): return {}


def options():
    value = {k: os.getenv(env, '').lower() in {'1', 'true', 'yes'} for k, env in _FIELDS.items()}
    overrides=read_overrides()
    path=settings_path()
    if (path.exists() or path.is_symlink()) and set(overrides)!=set(_FIELDS):
        return {k:False for k in _FIELDS}
    value.update(overrides)
    return value


def save_options(value):
    if set(value) != set(_FIELDS) or any(type(v) is not bool for v in value.values()):
        raise ValueError('Invalid settings')
    path = settings_path()
    with _LOCK:
        if path.is_symlink(): raise ValueError('Invalid settings file')
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.ai-settings-', dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, 'w') as target: json.dump(value, target)
            temporary.replace(path)
        finally: temporary.unlink(missing_ok=True)


def record(kind, message):
    with _LOCK: _ACTIVITY.append({'at': time.time(), 'kind': kind, 'message': message[:400]})


def activity():
    with _LOCK: return list(_ACTIVITY)[-30:]


def worker_status():
    from app.media.local_ai import read_json
    unavailable = {'online': False, 'busy': False, 'enabled': False, 'config': None, 'activity': [], 'settings_supported': False}
    try:
        spool = Path(os.environ['LOCAL_AI_CATALOG_SPOOL'])
        if spool.is_symlink(): return unavailable
        health = read_json(spool / 'health.json')
        updated = health.get('updated')
        if type(updated) not in (int, float) or not -1 <= time.time()-updated < 5: return unavailable
        config = health.get('config')
        fields = {'model_path','query_prefix','document_prefix','minimum_similarity'}
        config = {k: config[k] for k in fields if k in config} if isinstance(config, dict) else None
        try: tail = read_json(spool / 'activity.json')
        except (OSError, ValueError): tail = []
        return {'online': True, 'busy': health.get('busy') is True, 'enabled': health.get('enabled') is True,
                'config': config, 'config_digest': health.get('config_digest'),
                'settings_supported': health.get('settings_supported') is True,
                'activity': [{k: row.get(k) for k in ('at','available','reason','suggestions','seconds','peak_rss_gib')} for row in tail[-20:] if isinstance(row, dict)] if isinstance(tail, list) else []}
    except (OSError, ValueError, KeyError, TypeError): return unavailable


async def configure_worker(patch, expected_config):
    from app.media.local_ai import digest, read_json
    spool = Path(os.environ['LOCAL_AI_CATALOG_SPOOL'])
    binding = digest({'patch': patch, 'expected_config': expected_config})
    key = uuid.uuid4().hex
    request = spool / (key+'.control.request.json')
    response = spool / (key+'.control.response.json')
    temporary = spool / (key+'.control.tmp')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as target:
            json.dump({'version':1, 'expires':time.time()+10, 'patch':patch, 'expected_config':expected_config, 'fingerprint':binding}, target)
        temporary.replace(request)
        deadline = time.monotonic()+10
        while time.monotonic() < deadline:
            if response.exists():
                value = read_json(response)
                if value.get('fingerprint') != binding: raise ValueError('Invalid settings response')
                if value.get('ok') is not True: raise ValueError(value.get('error', 'Settings rejected'))
                return
            await asyncio.sleep(.1)
        raise ValueError('Worker did not confirm settings; reload to check its state')
    finally:
        for path in (request,response,temporary): path.unlink(missing_ok=True)
