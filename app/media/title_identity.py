"""Confirmed source identities; raw import titles and accounting remain untouched."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import unicodedata

import httpx
from sqlalchemy.orm import object_session

from app.db.models import TitleIdentity
from app.media.title_format import tadoku_title

_PREVIEW_KEY = secrets.token_bytes(32)
JITEN_TYPES = {'show': {2}, 'drama': {2}, 'movie': {3}, 'book': {4, 5, 8},
               'novel': {4}, 'nonfiction': {5}, 'web_novel': {8},
               'visual_novel': {7}, 'vn': {7}, 'game': {6}}
SUPPORTED_TYPES = ['anime', 'manga', *JITEN_TYPES]


def provider_for(content_type):
    return 'anilist' if content_type in {'anime', 'manga'} else 'jiten'


def auto_enabled():
    from app.media.ai_settings import options
    return web_enabled() and options()['auto_suggest_enabled']


def web_enabled():
    from app.media.ai_settings import options
    return options()['web_enabled']


def normalized(title):
    return ' '.join(unicodedata.normalize('NFKC', title).casefold().split())


def source_key(entry):
    return hashlib.sha256(json.dumps([entry.source, entry.content_type, normalized(entry.title)], ensure_ascii=False).encode()).hexdigest()


def lookup_hint(title):
    # A search hint only, never an automatic canonical name or saved identity.
    hint = re.sub(r'\([^)]*\)|（[^）]*）', ' ', title)
    hint = re.sub(r'よりぬきカラー版|\bmore color version\b', ' ', hint, flags=re.I)
    hint = re.sub(r'-[A-Z][A-Z0-9]{3,}$', '', hint.strip())
    hint = ' '.join(hint.split())
    # Prefer one script over a combined romaji/native filename for provider search.
    native = re.search(r'[一-龯ぁ-んァ-ヶ].*', hint)
    if native and re.search(r'[A-Za-z]', hint[:native.start()]):
        hint = native.group(0)
    return hint[:160].strip()


def search_text_key(text):
    return ''.join(c for c in normalized(text).replace('×', 'x') if c.isalnum())


def annotate_candidates(query, candidates):
    """Search-text evidence only; neither equality nor prefixes establish identity."""
    query_key = normalized(query)
    output = []
    for candidate in candidates:
        row = dict(candidate)
        title_key = normalized(row['title'])
        row['text_match'] = ('native_exact' if title_key == query_key else
                             'alias_exact' if any(normalized(a) == query_key for a in row['aliases']) else
                             'alias_normalized' if any(search_text_key(a) == search_text_key(query) for a in row['aliases']) else None)
        row['shared_title_prefix'] = any(title_key != normalized(other['title']) and
                                        (title_key.startswith(normalized(other['title'])) or
                                         normalized(other['title']).startswith(title_key))
                                        for other in candidates)
        output.append(row)
    return sorted(output, key=lambda r: {'native_exact': 0, 'alias_exact': 1, 'alias_normalized': 2, None: 3}[r['text_match']])


def mapping_for(entry):
    db = object_session(entry)
    return db.get(TitleIdentity, source_key(entry)) if db else None


def export_title(entry):
    mapping = mapping_for(entry)
    if mapping:
        return mapping.canonical_title
    return tadoku_title(entry.title, season=entry.season, episode=entry.episode, content_type=entry.content_type)


def sign_preview(entry, candidates):
    body = json.dumps({'key': source_key(entry), 'expires': time.time()+600, 'candidates': candidates}, ensure_ascii=False, separators=(',', ':')).encode()
    return base64.urlsafe_b64encode(body).decode()+'.'+hmac.new(_PREVIEW_KEY, body, hashlib.sha256).hexdigest()


def verify_preview(entry, token, provider_id):
    try:
        if len(token) > 24000:
            raise ValueError()
        encoded, signature = token.split('.')
        body = base64.urlsafe_b64decode(encoded)
        if not hmac.compare_digest(signature, hmac.new(_PREVIEW_KEY, body, hashlib.sha256).hexdigest()):
            raise ValueError()
        value = json.loads(body)
        if value['key'] != source_key(entry) or value['expires'] < time.time():
            raise ValueError()
        return next(row for row in value['candidates'] if row['provider_id'] == provider_id)
    except (ValueError, KeyError, TypeError, StopIteration):
        raise ValueError('Preview expired or source title changed; search again.') from None


def parse_provider_reference(reference, content_type):
    reference = reference.strip()
    if re.fullmatch(r'[1-9][0-9]{0,8}', reference):
        return int(reference)
    if provider_for(content_type) == 'jiten':
        match = re.fullmatch(r'https://jiten\.moe/decks/media/([1-9][0-9]{0,8})/detail/?', reference)
        if match: return int(match.group(1))
        raise ValueError('Use a Jiten media-deck link or numeric ID.')
    match = re.fullmatch(r'https://(?:www\.)?anilist\.co/(manga|anime)/([1-9][0-9]{0,8})(?:/[^?#\s]*)?', reference)
    if match and match.group(1) == content_type:
        return int(match.group(2))
    raise ValueError('Use an AniList link for this medium or a numeric AniList ID.')


async def provider_candidates(query, content_type, provider_id=None):
    if content_type in JITEN_TYPES:
        return await jiten_candidates(query, content_type, provider_id)
    if content_type not in {'manga', 'anime'}:
        return []
    fields = """id type format title { native romaji english }
        staff(perPage: 3) { edges { role node { name { full native } } } }"""
    if provider_id is None:
        gql = 'query ($search: String!, $type: MediaType!) { Page(perPage: 5) { media(search: $search, type: $type) { '+fields+' } } }'
        variables = {'search': query, 'type': content_type.upper()}
    else:
        gql = 'query ($id: Int!, $type: MediaType!) { Media(id: $id, type: $type) { '+fields+' } }'
        variables = {'id': provider_id, 'type': content_type.upper()}
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        response = await client.post('https://graphql.anilist.co', json={'query': gql, 'variables': variables})
        if provider_id is not None and response.status_code == 404:
            return []
        response.raise_for_status()
        if len(response.content) > 128000:
            raise ValueError('Provider response too large')
        data = response.json()
    if data.get('errors'):
        raise ValueError('Provider unavailable')
    output = []
    rows = ([data['data']['Media']] if data.get('data', {}).get('Media') else []) if provider_id is not None else (data.get('data', {}).get('Page', {}).get('media') or [])[:5]
    for row in rows:
        title = (row.get('title') or {}).get('native')
        # MANGA can contain novels; same-medium means actual manga here.
        allowed = {'MANGA', 'ONE_SHOT'} if content_type == 'manga' else {'TV', 'TV_SHORT', 'MOVIE', 'SPECIAL', 'OVA', 'ONA', 'MUSIC'}
        if row.get('type') != content_type.upper() or row.get('format') not in allowed or not isinstance(title, str) or not title.strip() or len(title) > 512 or type(row.get('id')) is not int or (provider_id is not None and row['id'] != provider_id):
            continue
        aliases = [s for s in (row['title'].get('romaji'), row['title'].get('english')) if isinstance(s, str) and s.strip() and len(s) <= 512]
        output.append({'provider': 'anilist', 'provider_label': 'AniList', 'provider_id': str(row['id']), 'title': title.strip(), 'aliases': aliases, 'format': row['format'], 'provider_url': f"https://anilist.co/{content_type}/{row['id']}", 'staff': [e['node']['name'].get('native') or e['node']['name'].get('full') for e in (row.get('staff') or {}).get('edges', []) if e.get('node', {}).get('name')]})
    return output


async def jiten_candidates(query, content_type, provider_id=None):
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        if provider_id is None:
            response = await client.get('https://api.jiten.moe/api/media-deck/search-suggestions', params={'query': query, 'limit': 5})
        else:
            response = await client.get(f'https://api.jiten.moe/api/media-deck/{provider_id}/detail', params={'offset': 0})
        if provider_id is not None and response.status_code == 404: return []
        response.raise_for_status()
        if len(response.content) > 128000: raise ValueError('Provider response too large')
        data = response.json()
    rows = (data.get('suggestions') or [])[:5] if provider_id is None else [data.get('data', {}).get('mainDeck') or {}]
    output = []
    for row in rows:
        title = row.get('originalTitle'); key = row.get('deckId')
        if type(key) is not int or key <= 0 or row.get('mediaType') not in JITEN_TYPES[content_type] or (provider_id is not None and key != provider_id): continue
        if not isinstance(title, str) or not title.strip() or len(title) > 512 or not re.search(r'[一-龯ぁ-んァ-ヶ]', title): continue
        aliases = [row.get('romajiTitle'), row.get('englishTitle')]
        output.append({'provider': 'jiten', 'provider_label': 'Jiten', 'provider_id': str(key), 'title': title.strip(),
                       'aliases': list(dict.fromkeys(a for a in aliases if isinstance(a, str) and a.strip() and len(a) <= 512)),
                       'format': {2:'Live-action series',3:'Movie',4:'Novel',5:'Nonfiction',6:'Game',7:'Visual novel',8:'Web novel'}[row['mediaType']],
                       'provider_url': f'https://jiten.moe/decks/media/{key}/detail', 'staff': []})
    return output
