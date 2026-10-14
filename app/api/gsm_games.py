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

from fastapi import APIRouter, Depends, HTTPException
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
        if score>=0.58:ranked.append({'id':game['id'],'title':game['title'],'score':round(score,2)})
    return sorted(ranked,key=lambda item:-item['score'])[:3]


@router.get('/gsm/game-matches')
def list_matches():
    with _lock,_connect() as con:
        games=_games(con)
        by_id={game['id']:game for game in games}
        aliases=dict(con.execute('SELECT alias,game_id FROM hub_aliases').fetchall())
        sources=[]
        for row in con.execute('''SELECT game_name,COUNT(*) AS lines,
            COUNT(DISTINCT COALESCE(game_id,'')) AS ids,MIN(game_id) AS game_id
            FROM game_lines GROUP BY game_name ORDER BY COUNT(*) DESC'''):
            name=row['game_name'] or ''
            game=by_id.get(row['game_id']) if row['ids']==1 else None
            sources.append({'name':name,'lines':row['lines'],'game_id':game['id'] if game else None,
                'title':game['title'] if game else None,'explicit':name in aliases,
                'suggestions':_suggest(name,games)})
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
