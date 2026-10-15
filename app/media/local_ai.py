"""Optional native-worker client; failures never change catalog or logging state."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import uuid


def enabled() -> bool:
    from app.media.ai_settings import options
    return options()['local_ai_enabled']


def requires_scope(query: str) -> bool:
    # No structured season/edition facts exist on catalog rows. Do not guess them.
    return bool(re.search(r'\bseason\b|\bs\d{1,2}(?:e\d+)?\b|\d+\s*[期巻版]|\bedition\b|\bvol(?:ume)?\.?\s*\d', query, re.I))


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def read_json(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError('Invalid worker file')
    return json.loads(path.read_text())


async def suggestions(query: str, content_type: str, candidates: list[dict], disconnected=None) -> dict:
    from app.media.ai_settings import record
    started = time.monotonic()
    def unavailable(reason):
        record('local_model', f'Local comparison: {reason} ({time.monotonic()-started:.1f}s). No title was changed.')
        return {'available': False, 'reason': reason, 'suggestions': []}
    if not enabled():
        return unavailable('disabled')
    if requires_scope(query):
        return unavailable('scope_unverified')
    request_path = response_path = None
    try:
        spool = Path(os.environ['LOCAL_AI_CATALOG_SPOOL'])
        if spool.is_symlink() or not spool.is_dir():
            return unavailable('offline')
        health = read_json(spool / 'health.json')
        updated = health.get('updated')
        # Host and Colima clocks can differ by milliseconds. Large skew/stale health fails closed.
        if type(updated) not in (int, float) or not math.isfinite(updated) or not -1 <= time.time()-updated < 5:
            return unavailable('offline')
        if health.get('enabled') is not True:
            return unavailable('disabled')
        if health.get('busy') is not False:
            return unavailable('busy')
        timeout = float(os.getenv('LOCAL_AI_CATALOG_TIMEOUT_SECONDS', '25'))
        if not math.isfinite(timeout) or not 1 <= timeout <= 30:
            return unavailable('configuration')
        if not candidates or len(candidates) > 1000:
            return unavailable('catalog_bounds')
        record('local_model', f'Starting local embedding comparison: {len(candidates)} {content_type} candidates. No provider API request from the model.')
        payload = {'query': query, 'content_type': content_type, 'candidates': candidates}
        binding = digest(payload)
        payload.update(version=1, fingerprint=binding, expires=time.time()+timeout)
        encoded = json.dumps(payload, ensure_ascii=False).encode()
        if len(encoded) > 1024 * 1024:
            return unavailable('catalog_bounds')
        key = uuid.uuid4().hex
        request_path = spool / (key+'.request.json')
        response_path = spool / (key+'.response.json')
        temporary = spool / (key+'.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'wb') as target: target.write(encoded)
            temporary.replace(request_path)
        finally: temporary.unlink(missing_ok=True)
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            if not enabled(): return unavailable('disabled')
            if disconnected and await disconnected():
                return unavailable('cancelled')
            if response_path.exists():
                result = read_json(response_path)
                if result.get('available') is not True:
                    return unavailable('unavailable')
                if result.get('fingerprint') != binding:
                    return unavailable('stale')
                known = {row['id']: row for row in candidates}
                rows = result.get('suggestions')
                if not isinstance(rows, list) or len(rows) > 5:
                    return unavailable('invalid')
                ids = set(); output = []
                for row in rows:
                    key = row.get('id'); score = row.get('score')
                    if key not in known or key in ids or type(score) not in (int, float) or not math.isfinite(score) or not -1 <= score <= 1:
                        return unavailable('invalid')
                    ids.add(key)
                    # Titles/type come from the app snapshot, never generated worker text.
                    candidate = known[key]
                    if candidate['content_type'] != content_type:
                        return unavailable('invalid')
                    output.append({'series_key': key, 'display_title': candidate['title'], 'content_type': content_type})
                record('local_model', f'Local comparison completed: {len(output)} suggestions from {len(candidates)} candidates ({time.monotonic()-started:.1f}s).')
                return {'available': True, 'reason': None, 'suggestions': output}
            await asyncio.sleep(.1)
        return unavailable('timeout')
    except (OSError, KeyError, ValueError, TypeError, AttributeError):
        return unavailable('offline')
    finally:
        for path in (request_path, response_path):
            if path is not None:
                try: path.unlink(missing_ok=True)
                except OSError: pass
