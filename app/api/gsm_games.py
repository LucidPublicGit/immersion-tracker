"""Explicit game-name matches for shared GSM history; preview before repair."""
import difflib
import hashlib
import json
import os
import sqlite3
import time
import unicodedata
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.gsm_sync import _lock
from app.db.session import get_db
from app.ingest import gsm

router=APIRouter()


def _connect():
    path=Path(os.environ.get('GSM_SHARED_DB','/app/data/gsm-shared/gsm.db'))
    if not path.is_file():raise HTTPException(404,'Shared GSM history is not configured')
    con=sqlite3.connect(path,timeout=30)
    con.row_factory=sqlite3.Row
    con.executescript('''
        CREATE TABLE IF NOT EXISTS hub_aliases(alias TEXT PRIMARY KEY,game_id TEXT);
        CREATE TABLE IF NOT EXISTS hub_alias_origins(id TEXT PRIMARY KEY,game_id TEXT,source_name TEXT);
        CREATE TABLE IF NOT EXISTS hub_skipped_lines(id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS hub_ignored_sources(name TEXT PRIMARY KEY,discarded INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS hub_source_policy_audit(at REAL,name TEXT,action TEXT,lines INTEGER);
        CREATE TABLE IF NOT EXISTS hub_match_audit(at REAL,alias TEXT,before_id TEXT,after_id TEXT,lines INTEGER);
    ''')
    if 'source_name' not in {row['name'] for row in con.execute('PRAGMA table_info(hub_alias_origins)')}:
        con.execute('ALTER TABLE hub_alias_origins ADD COLUMN source_name TEXT')
    return con


def _normal(value):
    return ''.join(c for c in unicodedata.normalize('NFKC',value or '').casefold() if c.isalnum())


def _games(con):
    fields={row['name'] for row in con.execute('PRAGMA table_info(games)')}
    names=[n for n in ('title_original','title_romaji','title_english','obs_scene_name') if n in fields]
    games=[]
    for row in con.execute('SELECT * FROM games'):
        title=row['title_original'] or row['id']
        games.append({'id':row['id'],'title':title,'type':row['type'] if 'type' in fields else '',
                      'names':[row[n] for n in names if row[n]],
                      'vndb_id':row['vndb_id'] if 'vndb_id' in fields else None})
    return sorted(games,key=lambda game:game['title'].casefold())


def _suggest(name,games):
    value=_normal(name)
    ranked=[]
    for game in games:
        score=max((difflib.SequenceMatcher(None,value,_normal(n)).ratio() for n in game['names']),default=0)
        if score>=0.58:ranked.append({'id':game['id'],'title':game['title'],'score':round(score,2),'exact':any(value==_normal(n) for n in game['names'])})
    return sorted(ranked,key=lambda item:-item['score'])[:3]


@router.get('/gsm/game-matches')
def list_matches():
    with _lock,_connect() as con:
        games=_games(con)
        by_id={game['id']:game for game in games}
        aliases=dict(con.execute('SELECT alias,game_id FROM hub_aliases').fetchall())
        ignored=dict(con.execute('SELECT name,discarded FROM hub_ignored_sources').fetchall())
        sources=[]
        for row in con.execute('''SELECT COALESCE(game_name,'') AS game_name,COUNT(*) AS lines,
            COUNT(DISTINCT COALESCE(game_id,'')) AS ids,MIN(game_id) AS game_id
            FROM game_lines GROUP BY COALESCE(game_name,'') ORDER BY COUNT(*) DESC'''):
            name=row['game_name'] or ''
            game=by_id.get(row['game_id']) if row['ids']==1 else None
            sources.append({'name':name,'lines':row['lines'],'game_id':game['id'] if game else None,
                'title':game['title'] if game else None,'explicit':name in aliases,
                'ignored':name in ignored,'discarded':bool(ignored.get(name)),
                'suggestions':_suggest(name,games) if name.strip() and name not in ignored else [],
                'origin':'Source name recorded in shared GSM sync history' if name else 'GSM records arrived without a game name; (unnamed source) is only a display label'})
        names={source['name'] for source in sources}
        for name,discarded in ignored.items():
            if name not in names:sources.append({'name':name,'lines':0,'game_id':None,'title':None,'explicit':name in aliases,'ignored':True,'discarded':bool(discarded),'suggestions':[],'origin':'Ignored shared GSM source; local history was discarded'})
        return {'games':games,'sources':sources}


class MatchRequest(BaseModel):
    name:str=Field(min_length=1,max_length=512)
    game_id:str|None=None
    revision:str|None=None


def _preview(con,body,db):
    target=None
    if body.game_id:
        target=con.execute('SELECT id,title_original FROM games WHERE id=?',(body.game_id,)).fetchone()
        if not target:raise HTTPException(404,'Selected game no longer exists')
    rows=con.execute('''SELECT l.id,l.game_id,l.created_at,o.game_id AS original_id
        FROM game_lines l LEFT JOIN hub_alias_origins o ON o.id=l.id
        WHERE l.game_name=? ORDER BY l.id''',(body.name,)).fetchall()
    if not rows:raise HTTPException(404,'Source name no longer exists')
    floors=gsm._get_game_cursors(db)
    fingerprint=[body.name,body.game_id,[(row['id'],row['game_id'],row['original_id']) for row in rows],floors]
    revision=hashlib.sha256(json.dumps(fingerprint,sort_keys=True).encode()).hexdigest()
    changes=sum((row['game_id'] or '') != (body.game_id if body.game_id else
        (row['original_id'] if row['original_id'] is not None else row['game_id']) or '') for row in rows)
    skipped=sum(float(row['created_at'] or 0)<=floors.get(gsm._game_key(row['game_id'],body.name),-1) for row in rows)
    return {'name':body.name,'target':target['title_original'] if target else 'Original game associations',
            'lines':len(rows),'changed_lines':changes,'already_skipped':skipped,'revision':revision,
            'export_pending':bool(gsm._load_pending_export(db)),
            'samples':[row[0][:400] for row in con.execute(
                'SELECT line_text FROM game_lines WHERE game_name=? AND line_text IS NOT NULL ORDER BY created_at DESC LIMIT 2',
                (body.name,))]},rows,floors


@router.post('/gsm/game-matches/preview')
def preview_match(body:MatchRequest,db:Session=Depends(get_db)):
    with _lock,_connect() as con:return _preview(con,body,db)[0]


@router.post('/gsm/game-matches/apply')
def apply_match(body:MatchRequest,db:Session=Depends(get_db)):
    with _lock,_connect() as con:
        preview,rows,floors=_preview(con,body,db)
        if preview['export_pending']:
            raise HTTPException(409,'Finish or skip the pending GSM export before changing game matches')
        if not body.revision or body.revision!=preview['revision']:
            raise HTTPException(409,'History changed. Preview the match again before applying it')
        previous=con.execute('SELECT game_id FROM hub_aliases WHERE alias=?',(body.name,)).fetchone()
        if body.game_id:
            con.execute('INSERT OR REPLACE INTO hub_aliases VALUES(?,?)',(body.name,body.game_id))
        else:
            con.execute('DELETE FROM hub_aliases WHERE alias=?',(body.name,))
        for row in rows:
            old=row['game_id'] or ''
            # Capture only lines already excluded by this old game's skip floor.
            # Never copy the maximum floor to a newly merged group: that could
            # hide other aliases' genuinely unread/exportable history.
            floor=floors.get(gsm._game_key(old,body.name))
            if floor is not None and float(row['created_at'] or 0)<=floor:
                con.execute('INSERT OR IGNORE INTO hub_skipped_lines VALUES(?)',(row['id'],))
            con.execute('INSERT OR IGNORE INTO hub_alias_origins VALUES(?,?,?)',(row['id'],old,body.name))
            original=con.execute('SELECT game_id FROM hub_alias_origins WHERE id=?',(row['id'],)).fetchone()[0]
            con.execute('UPDATE game_lines SET game_id=? WHERE id=?',(body.game_id or original,row['id']))
        con.execute('INSERT INTO hub_match_audit VALUES(?,?,?,?,?)',
            (time.time(),body.name,previous[0] if previous else None,body.game_id,len(rows)))
        return {'ok':True,**preview}


class NewGame(BaseModel):
    title:str=Field(min_length=1,max_length=200)
    type:str='Visual Novel'
    vndb_id:str|None=None


@router.post('/gsm/game-matches/game')
def create_game(body:NewGame):
    if not body.title.strip():raise HTTPException(400,'Enter a game title')
    if body.type not in ('Visual Novel','Game'):raise HTTPException(400,'Choose Visual Novel or Game')
    if body.vndb_id:
        import re
        if not re.fullmatch(r'v\d+',body.vndb_id):raise HTTPException(400,'VNDB ID must look like v123')
    with _lock,_connect() as con:
        for game in _games(con):
            if _normal(game['title'])==_normal(body.title) or (body.vndb_id and body.vndb_id==game['vndb_id']):
                raise HTTPException(409,'This game is already available in the game selector')
        identity=str(uuid.uuid4())
        fields={row['name'] for row in con.execute('PRAGMA table_info(games)')}
        values={k:v for k,v in {'id':identity,'title_original':body.title.strip(),
            'type':body.type,'vndb_id':body.vndb_id}.items() if k in fields}
        con.execute('INSERT INTO games ('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',tuple(values.values()))
        return {'ok':True,'id':identity,'title':body.title.strip()}


class SourcePolicyRequest(BaseModel):
    name: str = Field(max_length=512)
    action: str = Field(pattern='^(ignore|discard|restore)$')
    revision: str | None = None


def source_policy_preview(con,body,db):
    rows=con.execute("SELECT id FROM game_lines WHERE COALESCE(game_name,'')=? ORDER BY id",(body.name,)).fetchall()
    ignored=con.execute('SELECT discarded FROM hub_ignored_sources WHERE name=?',(body.name,)).fetchone()
    if not rows and ignored is None:raise HTTPException(404,'Source no longer exists')
    revision=hashlib.sha256(json.dumps([body.name,body.action,[row['id'] for row in rows],list(ignored) if ignored else None]).encode()).hexdigest()
    return {'name':body.name,'lines':len(rows),'revision':revision,'export_pending':bool(gsm._load_pending_export(db))}


@router.post('/gsm/game-matches/source-preview')
def preview_source_policy(body:SourcePolicyRequest,db:Session=Depends(get_db)):
    with _lock,_connect() as con:return source_policy_preview(con,body,db)


@router.post('/gsm/game-matches/source-policy')
def apply_source_policy(body:SourcePolicyRequest,db:Session=Depends(get_db)):
    with _lock,_connect() as con:
        preview=source_policy_preview(con,body,db)
        if preview['export_pending']:raise HTTPException(409,'Finish or skip the pending GSM export before discarding or ignoring a source')
        if body.revision!=preview['revision']:raise HTTPException(409,'Source history changed. Preview again.')
        if body.action=='restore':
            con.execute('DELETE FROM hub_ignored_sources WHERE name=?',(body.name,))
        else:
            con.execute('INSERT INTO hub_ignored_sources VALUES(?,?) ON CONFLICT(name) DO UPDATE SET discarded=MAX(discarded,excluded.discarded)',(body.name,int(body.action=='discard')))
            if body.action=='discard':
                con.execute("DELETE FROM game_lines WHERE COALESCE(game_name,'')=?",(body.name,))
        con.execute('INSERT INTO hub_source_policy_audit VALUES(?,?,?,?)',(time.time(),body.name,body.action,preview['lines']))
        from app.media.ai_settings import record
        record('gsm', f'GSM source action {body.action}: {preview["lines"]} local lines. Original PC history unchanged.')
        return {'ok':True,**preview,'action':body.action}


class GameSuggestionRequest(BaseModel):
    name: str = Field(min_length=1,max_length=512)


@router.post('/gsm/game-matches/suggestions')
async def local_game_suggestions(body:GameSuggestionRequest,request:Request):
    from app.media import local_ai, ai_settings
    if not body.name.strip():raise HTTPException(422,'Unnamed source cannot be identified from a title')
    if not local_ai.enabled():return {'available':False,'reason':'disabled','suggestions':[]}
    with _lock,_connect() as con:
        games=_games(con)
        if len(games)>1000:return {'available':False,'reason':'catalog_bounds','suggestions':[]}
        snapshot=hashlib.sha256(json.dumps(games,sort_keys=True).encode()).hexdigest()
        if con.execute('SELECT 1 FROM hub_ignored_sources WHERE name=?',(body.name,)).fetchone():
            return {'available':False,'reason':'ignored','suggestions':[]}
    rows=[{'id':game['id'],'title':game['title'],'aliases':game['names'],'content_type':'game'} for game in games]
    ai_settings.record('gsm', f'GSM requested local comparison against {len(rows)} stored games. No provider API lookup.')
    result=await local_ai.suggestions(body.name,'game',rows,request.is_disconnected)
    with _lock,_connect() as con:
        if hashlib.sha256(json.dumps(_games(con),sort_keys=True).encode()).hexdigest()!=snapshot:
            return {'available':False,'reason':'stale','suggestions':[]}
    return result


@router.post('/gsm/game-matches/accept-suggestion')
def accept_exact_game_suggestion(body:MatchRequest,db:Session=Depends(get_db)):
    with _lock:
        with _connect() as con:
            if con.execute('SELECT 1 FROM hub_ignored_sources WHERE name=?',(body.name,)).fetchone():
                raise HTTPException(409,'Ignored sources cannot be matched')
            exact=[row for row in _suggest(body.name,_games(con)) if row['exact']]
            if len(exact)!=1 or body.game_id!=exact[0]['id']:
                raise HTTPException(409,'The exact suggestion changed or is ambiguous. Preview a match instead.')
            preview,_,_= _preview(con,body,db)
        return apply_match(MatchRequest(name=body.name,game_id=body.game_id,revision=preview['revision']),db)
