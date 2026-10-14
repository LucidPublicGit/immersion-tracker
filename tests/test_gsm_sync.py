"""Protocol, shared-history counting, retries, and offline arrival regressions."""
import base64
import json
import os
import sqlite3
import time
import uuid

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient

from app.api import gsm_sync
from app.main import app


@pytest.fixture
def sync(tmp_path, monkeypatch):
    key = "gsm2_" + base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
    monkeypatch.setenv("GSM_SYNC_TOKEN", "isolated-test-token")
    monkeypatch.setenv("GSM_SYNC_KEY", key)
    monkeypatch.setenv("GSM_SYNC_DIR", str(tmp_path / "relay"))
    path = tmp_path / "gsm.db"
    monkeypatch.setenv("GSM_SHARED_DB", str(path))
    with sqlite3.connect(path) as con:
        con.executescript("""
            CREATE TABLE game_lines (id TEXT PRIMARY KEY,game_name TEXT,line_text TEXT,
                language TEXT,timestamp REAL,note_ids TEXT,last_modified REAL,
                original_game_name TEXT,game_id TEXT,created_at REAL,audio_path TEXT);
            CREATE TABLE games(id TEXT PRIMARY KEY,title_original TEXT,obs_scene_name TEXT);
            INSERT INTO games VALUES('original-game','Test VN','Test VN');
            INSERT INTO game_lines VALUES('existing','Test VN','古い','ja',900,'[]',900,
                'Test VN','original-game',900,'keep-local-audio');
        """)
    cipher = gsm_sync.Cipher(key)
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer isolated-test-token"
    prefix = f"/api/sync/v2/{cipher.room}"
    return client, prefix, cipher, path


def record(identity="new", version=None, deleted=False):
    return {"kind":"line","id":identity,"version":version or [1,"pc-a"],
            "deleted":deleted,"data":None if deleted else {
                "game_name":"Test VN","line_text":"新しい","language":"ja",
                "timestamp":1000.0,"last_modified":1000.0,"note_ids":[]}}


def encrypt(cipher, document, context):
    nonce = os.urandom(12)
    aad = f"gsm-sync/v2/{cipher.room}/{context}".encode()
    return base64.b64encode(nonce+cipher.aes.encrypt(nonce,json.dumps(document).encode(),aad)).decode()


def event(cipher, rec):
    identity = uuid.uuid4().hex
    return {"id":identity,"payload":encrypt(cipher,{"protocol":2,"records":[rec]},"event:"+identity)}


def exchange(sync, changes, cursor=0):
    client,prefix,_,_ = sync
    state = client.get(prefix+"/state").json()
    return client.post(prefix+"/exchange",json={"generation":state["generation"],
        "cursor":cursor,"changes":changes,"limit":100})


def test_auth_required_even_when_ui_auth_disabled(sync):
    client,prefix,_,_ = sync
    assert client.get(prefix+"/state",headers={"Authorization":"Bearer wrong"}).status_code == 401
    assert client.get(prefix.replace(prefix.split('/')[-1],'wrong')+"/state").status_code == 404


def test_repeat_event_no_double_count_no_sequence_gap(sync):
    _,_,cipher,path = sync
    first = event(cipher,record())
    assert exchange(sync,[first]).json()["cursor"] == 1
    assert exchange(sync,[first]).json()["cursor"] == 1
    later = exchange(sync,[event(cipher,record('second'))],cursor=1).json()
    assert later["changes"][0]["seq"] == 2
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT count(*) FROM game_lines WHERE id='new'").fetchone()[0] == 1


def test_offline_line_uses_arrival_time_and_preserves_existing_history(sync):
    _,_,cipher,path = sync
    before=time.time()
    assert exchange(sync,[event(cipher,record())]).status_code == 200
    assert exchange(sync,[event(cipher,record('existing'))]).status_code == 200
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT timestamp,game_id FROM game_lines WHERE id='new'").fetchone() == (1000.0,'original-game')
        assert con.execute("SELECT created_at FROM game_lines WHERE id='new'").fetchone()[0]>=before
        assert con.execute("SELECT created_at,audio_path FROM game_lines WHERE id='existing'").fetchone()==(900,'keep-local-audio')


def test_versions_tombstones_and_newer_edits_converge(sync):
    _,_,cipher,path=sync
    for value in (record(),record(version=[3,'pc-b'],deleted=True),record(version=[2,'pc-a'])):
        assert exchange(sync,[event(cipher,value)]).status_code==200
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT count(*) FROM game_lines WHERE id='new'").fetchone()[0]==0
    assert exchange(sync,[event(cipher,record(version=[4,'pc-a']))]).status_code==200
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT count(*) FROM game_lines WHERE id='new'").fetchone()[0]==1


def test_bad_crypto_is_atomic_and_event_ids_are_immutable(sync):
    client,prefix,cipher,path=sync
    valid=event(cipher,record())
    bad={"id":uuid.uuid4().hex,"payload":"invalid"}
    assert exchange(sync,[valid,bad]).status_code==400
    assert client.get(prefix+'/state').json()['head']==0
    assert exchange(sync,[valid]).status_code==200
    changed={"id":valid['id'],"payload":encrypt(cipher,{"protocol":2,"records":[record('other')]},'event:'+valid['id'])}
    assert exchange(sync,[changed]).status_code==409


def test_complete_authenticated_transfer_only(sync):
    client,prefix,cipher,path=sync
    state=client.get(prefix+'/state').json()
    identity=uuid.uuid4().hex
    manifest={"id":identity,"generation":state['generation'],"base":0,"parts":2}
    assert client.post(prefix+'/snapshot/start',json=manifest).status_code==200
    assert client.post(prefix+f'/snapshot/{identity}/commit',json={}).status_code==409
    for part in range(2):
        metadata={**manifest,"part":part}
        payload=encrypt(cipher,{"protocol":2,"records":[record(f'part-{part}')],"snapshot":metadata},f'snapshot:{identity}:{part}')
        assert client.put(prefix+f'/snapshot/{identity}/{part}',json={"payload":payload}).status_code==200
    assert client.post(prefix+f'/snapshot/{identity}/commit',json={}).status_code==200
    assert client.get(prefix+'/state').json()['snapshot']['id']==identity
    assert client.get(prefix+f'/snapshot/{identity}/1').status_code==200
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT count(*) FROM game_lines WHERE id LIKE 'part-%'").fetchone()[0]==2


def test_expiry_requires_transfer_not_silent_skip(sync):
    client,prefix,cipher,_=sync
    assert exchange(sync,[event(cipher,record())]).status_code==200
    with gsm_sync._connect() as con:
        con.execute('UPDATE events SET expires=0')
    state=client.get(prefix+'/state').json()
    assert state['floor']==1
    assert exchange(sync,[],cursor=0).status_code==409


def test_history_write_failure_does_not_acknowledge_upload(sync,monkeypatch):
    client,prefix,cipher,_=sync
    value=event(cipher,record())
    def fail(records):
        raise RuntimeError('isolated failure')
    with monkeypatch.context() as patch:
        patch.setattr(gsm_sync,'_mirror',fail)
        with pytest.raises(RuntimeError):
            exchange(sync,[value])
    assert client.get(prefix+'/state').json()['head']==0
    assert exchange(sync,[value]).json()['cursor']==1


def test_copied_desktop_dirty_triggers_cannot_break_history_import(sync):
    _,_,cipher,path=sync
    with sqlite3.connect(path) as con:
        con.executescript("""CREATE TABLE sync_v2_dirty(id TEXT PRIMARY KEY);
            INSERT INTO sync_v2_dirty VALUES('existing');
            CREATE TRIGGER gsm_sync_v2_update AFTER UPDATE ON game_lines BEGIN
                INSERT OR IGNORE INTO sync_v2_dirty VALUES(NEW.id); END;""")
    assert exchange(sync,[event(cipher,record('existing'))]).status_code==200
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT COUNT(*) FROM game_lines WHERE id='existing'").fetchone()[0]==1


def test_device_registration_and_status_do_not_expose_pairing_secrets(sync):
    client,prefix,_,_=sync
    body={'id':uuid.uuid4().hex,'name':'test-pc','platform':'Windows','lines':10}
    assert client.post(prefix+'/device',json=body).status_code==200
    result=gsm_sync.device_status()
    assert result['devices'][0]['name']=='test-pc'
    assert 'token' not in json.dumps(result) and 'gsm2_' not in json.dumps(result)
    assert client.post(prefix+'/device',json={**body,'lines':-1}).status_code==400


@pytest.fixture
def matches(sync,monkeypatch):
    from app.ingest import gsm
    monkeypatch.setattr(gsm,'_load_pending_export',lambda db:None)
    monkeypatch.setattr(gsm,'_get_game_cursors',lambda db:{'old-game':1200})
    client,_,_,path=sync
    with sqlite3.connect(path) as con:
        con.executescript("""ALTER TABLE games ADD COLUMN type TEXT;
            UPDATE games SET type='Visual Novel';
            INSERT INTO games VALUES('old-game','STEINS GATE','STEINS GATE','Visual Novel');
            CREATE TABLE stats_export_state(format_key TEXT PRIMARY KEY,last_successful_export_at TEXT);
            INSERT INTO stats_export_state VALUES('tadoku_incremental','0');
            INSERT INTO game_lines VALUES('alias-skipped','STEINS GATE','日本語','ja',1100,'[]',1100,'STEINS GATE','old-game',1100,'');
            INSERT INTO game_lines VALUES('alias-pending','STEINS GATE','あいうえお','ja',1300,'[]',1300,'STEINS GATE','old-game',1300,'');""")
    monkeypatch.setenv('GSM_DB_PATH',str(path))
    return sync


def match_request(sync,target='original-game'):
    client,_,_,_=sync
    body={'name':'STEINS GATE','game_id':target}
    preview=client.post('/api/gsm/game-matches/preview',json=body)
    assert preview.status_code==200
    return {**body,'revision':preview.json()['revision']}


def test_match_merges_ids_without_recounting_skipped_lines_and_can_undo(matches):
    from app.ingest import gsm
    client,_,_,path=matches
    before=gsm.build_preview(deduplicate=False)['total_characters']
    request=match_request(matches)
    assert client.post('/api/gsm/game-matches/apply',json=request).status_code==200
    after=gsm.build_preview(deduplicate=False)
    assert after['total_characters']==before
    assert after['total_entries']==1
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT game_id FROM game_lines WHERE id='alias-pending'").fetchone()[0]=='original-game'
        assert con.execute("SELECT COUNT(*) FROM hub_skipped_lines WHERE id='alias-skipped'").fetchone()[0]==1
    assert client.post('/api/gsm/game-matches/apply',json=match_request(matches,None)).status_code==200
    assert gsm.build_preview(deduplicate=False)['total_characters']==before
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT game_id FROM game_lines WHERE id='alias-pending'").fetchone()[0]=='old-game'


def test_saved_match_applies_to_future_syncs_and_preserves_sentence_identity(matches):
    client,_,cipher,path=matches
    assert client.post('/api/gsm/game-matches/apply',json=match_request(matches)).status_code==200
    value=record('future-from-other-pc');value['data']['game_name']='STEINS GATE'
    assert exchange(matches,[event(cipher,value)]).status_code==200
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT game_id,game_name FROM game_lines WHERE id='future-from-other-pc'").fetchone()==('original-game','STEINS GATE')


def test_history_change_requires_new_preview(matches):
    client,_,cipher,_=matches
    request=match_request(matches)
    value=record('new-arrival');value['data']['game_name']='STEINS GATE'
    assert exchange(matches,[event(cipher,value)]).status_code==200
    assert client.post('/api/gsm/game-matches/apply',json=request).status_code==409


def test_pending_export_blocks_game_reassociation(matches,monkeypatch):
    from app.ingest import gsm
    client,_,_,path=matches
    request=match_request(matches)
    monkeypatch.setattr(gsm,'_load_pending_export',lambda db:{'source_refs':['unfinished']})
    assert client.post('/api/gsm/game-matches/apply',json=request).status_code==409
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT game_id FROM game_lines WHERE id='alias-pending'").fetchone()[0]=='old-game'


def test_suggestions_and_missing_game_creation(matches):
    client,_,_,_=matches
    result=client.get('/api/gsm/game-matches').json()
    alias=next(source for source in result['sources'] if source['name']=='STEINS GATE')
    assert alias['suggestions'][0]['id']=='old-game'
    created=client.post('/api/gsm/game-matches/game',json={'title':'Another game','type':'Game'})
    assert created.status_code==200
    assert client.post('/api/gsm/game-matches/game',json={'title':'Another game','type':'Game'}).status_code==409


def test_late_skip_on_original_game_still_excludes_remapped_history(matches,monkeypatch):
    from app.ingest import gsm
    client,_,_,_=matches
    assert gsm.build_preview(deduplicate=False)['total_characters']==len('あいうえお')
    assert client.post('/api/gsm/game-matches/apply',json=match_request(matches)).status_code==200
    monkeypatch.setattr(gsm,'_get_game_cursors',lambda db:{'old-game':2000})
    preview=gsm.build_preview(deduplicate=False)
    # The unchanged two-character seed line is below the Japanese minimum.
    assert preview['total_characters']==0
