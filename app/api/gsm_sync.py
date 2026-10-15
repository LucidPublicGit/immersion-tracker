"""Personal GSM v2 relay and a paired, local history copy for the tracker.

Wire format: GSM docs/ENCRYPTED_SYNC.md. Clients keep their own SQLite writers;
immutable encrypted events and checkpoints travel over authenticated HTTPS.
The Mac is a paired device, so it can materialize the history for counting.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()
_lock = threading.RLock()
MAX_BODY = 1_000_000
QUOTA = 256 * 1024 * 1024
RETENTION = 30 * 86400


class Cipher:
    def __init__(self, key: str):
        if not key.startswith("gsm2_") or len(key) != 48:
            raise ValueError("Invalid pairing key")
        raw = base64.b64decode(key[5:] + "=", altchars=b"-_", validate=True)
        if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode().rstrip("=") != key[5:]:
            raise ValueError("Invalid pairing key")
        self.room = hashlib.sha256(b"gsm-sync-room-v2\0" + raw).hexdigest()
        derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                       info=b"gsm-sync-aes256-v2").derive(raw)
        self.aes = AESGCM(derived)

    def decrypt(self, payload: str, context: str) -> dict:
        if not isinstance(payload, str) or len(payload) > 700_000:
            raise ValueError("Invalid encrypted payload")
        blob = base64.b64decode(payload, validate=True)
        aad = f"gsm-sync/v2/{self.room}/{context}".encode()
        raw = self.aes.decrypt(blob[:12], blob[12:], aad)
        if len(raw) > 500_000:
            raise ValueError("Payload too large")
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("protocol") != 2:
            raise ValueError("Invalid document")
        return value


def _records(document: dict) -> list[dict]:
    records = document.get("records")
    if not isinstance(records, list) or len(records) > 5000:
        raise ValueError("Invalid records")
    for record in records:
        if not isinstance(record, dict) or set(record) != {"kind", "id", "version", "deleted", "data"}:
            raise ValueError("Invalid record")
        version = record["version"]
        if (record["kind"] not in {"line", "setting"}
                or not isinstance(record["id"], str) or not 1 <= len(record["id"]) <= 512
                or not isinstance(version, list) or len(version) != 2
                or type(version[0]) is not int or not 0 <= version[0] < 2**53 - 1
                or not isinstance(version[1], str) or not 1 <= len(version[1]) <= 128
                or type(record["deleted"]) is not bool):
            raise ValueError("Invalid record identity/version")
        if record["kind"] == "setting":
            # Clients enforce their portable-preference allowlist. The paired
            # tracker never applies preferences to its own runtime settings.
            continue
        data = record["data"]
        if record["deleted"]:
            if data is not None:
                raise ValueError("Invalid tombstone")
            continue
        if not isinstance(data, dict) or set(data) != {
                "game_name", "line_text", "language", "timestamp", "note_ids", "last_modified"}:
            raise ValueError("Invalid line fields")
        if any(not isinstance(data[k], str) for k in ("game_name", "line_text", "language")):
            raise ValueError("Invalid line text")
        if any(type(data[k]) not in (int, float) or not math.isfinite(data[k])
               for k in ("timestamp", "last_modified")):
            raise ValueError("Invalid timestamp")
        if not isinstance(data["note_ids"], list) or any(not isinstance(n, str) for n in data["note_ids"]):
            raise ValueError("Invalid note IDs")
    return records


def _root() -> Path:
    return Path(os.environ.get("GSM_SYNC_DIR", "/app/data/gsm-sync"))


def _connect() -> sqlite3.Connection:
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(root / "relay.db", timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT UNIQUE, payload TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS transfers (id TEXT PRIMARY KEY, base INTEGER,
            parts INTEGER, expires REAL, committed INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS chunks (id TEXT, part INTEGER, payload TEXT,
            PRIMARY KEY(id,part));
        CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, name TEXT,
            platform TEXT, lines INTEGER, paired_at REAL);
    """)
    for key, value in (("generation", uuid.uuid4().hex), ("floor", "0"), ("head", "0")):
        con.execute("INSERT OR IGNORE INTO meta VALUES (?,?)", (key, value))
    con.commit()
    return con


def _meta(con, key):
    return con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()[0]


def _prune(con):
    now = time.time()
    expired = con.execute("SELECT MAX(seq) FROM events WHERE expires<=?", (now,)).fetchone()[0]
    if expired is not None:
        floor = max(int(_meta(con, "floor")), expired)
        con.execute("DELETE FROM events WHERE seq<=?", (floor,))
        con.execute("UPDATE meta SET value=? WHERE key='floor'", (str(floor),))
    con.execute("DELETE FROM chunks WHERE id IN (SELECT id FROM transfers WHERE expires<=?)", (now,))
    con.execute("DELETE FROM transfers WHERE expires<=?", (now,))


def _state(con):
    row = con.execute("SELECT id,base,parts FROM transfers WHERE committed=1").fetchone()
    return {"protocol": 2, "generation": _meta(con, "generation"),
            "head": int(_meta(con, "head")), "floor": int(_meta(con, "floor")),
            "snapshot": dict(row) if row else None}


def _mirror(records):
    """Apply deterministic registers; keep existing timestamps/media/game links.

    New remote rows get their *arrival* time as created_at. Thus offline activity
    received after an export cannot fall behind the tracker's counting cursor.
    The original game timestamp remains unchanged for GSM history/statistics.
    """
    path = Path(os.environ.get("GSM_SHARED_DB", "/app/data/gsm-shared/gsm.db"))
    if not path.is_file():
        raise RuntimeError("Shared GSM history has not been initialized")
    with sqlite3.connect(path, timeout=30) as con:
        con.execute("CREATE TABLE IF NOT EXISTS hub_versions (id TEXT PRIMARY KEY, counter INTEGER, writer TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS hub_aliases(alias TEXT PRIMARY KEY,game_id TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS hub_ignored_sources(name TEXT PRIMARY KEY,discarded INTEGER DEFAULT 0)")
        con.execute("CREATE TABLE IF NOT EXISTS hub_alias_origins(id TEXT PRIMARY KEY,game_id TEXT,source_name TEXT)")
        if 'source_name' not in {row[1] for row in con.execute('PRAGMA table_info(hub_alias_origins)')}:
            con.execute('ALTER TABLE hub_alias_origins ADD COLUMN source_name TEXT')
        # A consistent seed can include the desktop's upload triggers/outbox.
        # This paired history is not a desktop uploader; its versions are tracked
        # above. Retaining copied triggers can both echo imports and collide with
        # dirty IDs already present in the source snapshot.
        for name in ("gsm_sync_v2_insert", "gsm_sync_v2_update", "gsm_sync_v2_delete",
                     "trg_game_lines_sync_insert", "trg_game_lines_sync_update", "trg_game_lines_sync_delete"):
            con.execute(f'DROP TRIGGER IF EXISTS "{name}"')
        for record in records:
            if record["kind"] != "line":
                continue
            identity, version = record["id"], record["version"]
            old = con.execute("SELECT counter,writer FROM hub_versions WHERE id=?", (identity,)).fetchone()
            if old and tuple(old) >= tuple(version):
                continue
            con.execute("INSERT OR REPLACE INTO hub_versions VALUES(?,?,?)", (identity, *version))
            if record["deleted"]:
                con.execute("DELETE FROM game_lines WHERE id=?", (identity,))
                continue
            data = record["data"]
            if con.execute("SELECT 1 FROM hub_ignored_sources WHERE name=?", (data["game_name"],)).fetchone():
                continue
            # Reuse known game metadata by title; new scenes remain VN by default.
            game = con.execute("SELECT id FROM games WHERE title_original=? OR obs_scene_name=? LIMIT 1",
                               (data["game_name"], data["game_name"])).fetchone()
            game_id = game[0] if game else ""
            alias=con.execute('SELECT game_id FROM hub_aliases WHERE alias=?',(data['game_name'],)).fetchone()
            if alias:
                existing=con.execute('SELECT game_id,game_name FROM game_lines WHERE id=?',(identity,)).fetchone()
                con.execute('INSERT OR IGNORE INTO hub_alias_origins VALUES(?,?,?)',
                            (identity,(existing[0] or '') if existing else game_id,
                             existing[1] if existing else data['game_name']))
                game_id=alias[0]
            con.execute("""INSERT INTO game_lines
                (id,game_name,line_text,language,timestamp,note_ids,last_modified,
                 original_game_name,game_id,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                game_name=excluded.game_name,line_text=excluded.line_text,
                language=excluded.language,timestamp=excluded.timestamp,
                note_ids=excluded.note_ids,last_modified=excluded.last_modified,
                game_id=COALESCE((SELECT game_id FROM hub_aliases WHERE alias=excluded.game_name),game_lines.game_id)""",
                (identity, data["game_name"], data["line_text"], data["language"],
                 data["timestamp"], json.dumps(data["note_ids"]), data["last_modified"],
                 data["game_name"], game_id, time.time()))


def _auth(request, room):
    token, key = os.environ.get("GSM_SYNC_TOKEN", ""), os.environ.get("GSM_SYNC_KEY", "")
    if not token or not key:
        raise HTTPException(503, "GSM device sync is not configured")
    header = request.headers.get("authorization", "")
    if not secrets.compare_digest(header.encode(), f"Bearer {token}".encode()):
        raise HTTPException(401, "Invalid sync access token")
    cipher = Cipher(key)
    if room != cipher.room:
        raise HTTPException(404, "Unknown sync group")
    return cipher


async def _body(request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_BODY:
            raise HTTPException(413, "Sync request too large")
    try:
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError
        return body
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Invalid JSON") from None


def _quota(con):
    size = con.execute("SELECT COALESCE(SUM(length(payload)),0) FROM events").fetchone()[0]
    size += con.execute("SELECT COALESCE(SUM(length(payload)),0) FROM chunks").fetchone()[0]
    if size > QUOTA:
        raise HTTPException(413, "Sync group storage quota exceeded")


def _check_generation(body, state):
    if body.get("generation") != state["generation"]:
        raise HTTPException(409, {"error": "resync_required"})


@router.get("/sync/v2/{room}/state")
def sync_state(room: str, request: Request):
    _auth(request, room)
    with _lock, _connect() as con:
        _prune(con)
        return _state(con)


@router.post("/sync/v2/{room}/exchange")
async def sync_exchange(room: str, request: Request):
    cipher, body = _auth(request, room), await _body(request)
    changes = body.get("changes")
    if not isinstance(changes, list) or len(changes) > 100:
        raise HTTPException(400, "Invalid change batch")
    decoded = []
    try:
        for item in changes:
            if not isinstance(item, dict) or not re.fullmatch(r"[a-f0-9]{32}", str(item.get("id", ""))):
                raise ValueError
            decoded.extend(_records(cipher.decrypt(item.get("payload"), "event:" + item["id"])))
    except Exception:
        raise HTTPException(400, "Cannot authenticate sync changes") from None
    with _lock, _connect() as con:
        _prune(con)
        state = _state(con)
        _check_generation(body, state)
        cursor = body.get("cursor")
        if type(cursor) is not int or not state["floor"] <= cursor <= state["head"]:
            raise HTTPException(409, {"error": "resync_required"})
        for item in changes:
            old = con.execute("SELECT payload FROM events WHERE id=?", (item["id"],)).fetchone()
            if old and old[0] != item["payload"]:
                raise HTTPException(409, "Event identity already has a different payload")
            if not old:
                # IGNORE on an AUTOINCREMENT table consumes a sequence number;
                # replayed uploads must not leave holes in contiguous pages.
                con.execute("INSERT INTO events(id,payload,expires) VALUES(?,?,?)",
                            (item["id"], item["payload"], time.time() + RETENTION))
        head = con.execute("SELECT COALESCE(MAX(seq),?) FROM events", (state["head"],)).fetchone()[0]
        con.execute("UPDATE meta SET value=? WHERE key='head'", (str(head),))
        _quota(con)
        # A failed history write leaves events unacknowledged; retries are safe.
        _mirror(decoded)
        page = [dict(row) for row in con.execute(
            "SELECT seq,id,payload FROM events WHERE seq>? ORDER BY seq LIMIT 100", (cursor,))]
        last = page[-1]["seq"] if page else cursor
        return {"protocol": 2, "generation": state["generation"],
                "accepted_ids": [item["id"] for item in changes], "changes": page,
                "cursor": last, "has_more": last < head}


@router.post("/sync/v2/{room}/snapshot/start")
async def snapshot_start(room: str, request: Request):
    _auth(request, room)
    body = await _body(request)
    identity, parts, base = body.get("id"), body.get("parts"), body.get("base")
    if (not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity)
            or type(parts) is not int or not 1 <= parts <= 1024 or type(base) is not int):
        raise HTTPException(400, "Invalid transfer manifest")
    with _lock, _connect() as con:
        _prune(con)
        state = _state(con)
        _check_generation(body, state)
        if not state["floor"] <= base <= state["head"]:
            raise HTTPException(409, "Transfer base is outside retained history")
        if con.execute("SELECT 1 FROM transfers WHERE id=?", (identity,)).fetchone():
            raise HTTPException(409, "Transfer identity already exists")
        con.execute("INSERT INTO transfers VALUES(?,?,?,?,0)", (identity, base, parts, time.time()+3600))
        return {"ok": True}


@router.put("/sync/v2/{room}/snapshot/{identity}/{part}")
async def snapshot_put(room: str, identity: str, part: int, request: Request):
    cipher, body = _auth(request, room), await _body(request)
    with _lock, _connect() as con:
        _prune(con)
        transfer = con.execute("SELECT * FROM transfers WHERE id=? AND committed=0", (identity,)).fetchone()
        if not transfer or not 0 <= part < transfer["parts"]:
            raise HTTPException(404, "Unknown transfer part")
        try:
            document = cipher.decrypt(body.get("payload"), f"snapshot:{identity}:{part}")
            expected = {"id": identity, "generation": _meta(con, "generation"),
                        "base": transfer["base"], "parts": transfer["parts"], "part": part}
            if document.get("snapshot") != expected:
                raise ValueError
            _records(document)
        except Exception:
            raise HTTPException(400, "Cannot authenticate transfer part") from None
        old = con.execute("SELECT payload FROM chunks WHERE id=? AND part=?", (identity,part)).fetchone()
        if old and old[0] != body["payload"]:
            raise HTTPException(409, "Transfer part is immutable")
        con.execute("INSERT OR IGNORE INTO chunks VALUES(?,?,?)", (identity,part,body["payload"]))
        _quota(con)
        return {"ok": True}


@router.post("/sync/v2/{room}/snapshot/{identity}/commit")
def snapshot_commit(room: str, identity: str, request: Request):
    cipher = _auth(request, room)
    with _lock, _connect() as con:
        _prune(con)
        transfer = con.execute("SELECT * FROM transfers WHERE id=?", (identity,)).fetchone()
        if not transfer:
            raise HTTPException(404, "Unknown transfer")
        if transfer["committed"]:
            return {"snapshot": {k:transfer[k] for k in ("id","base","parts")}}
        rows = con.execute("SELECT part,payload FROM chunks WHERE id=? ORDER BY part", (identity,)).fetchall()
        if len(rows) != transfer["parts"]:
            raise HTTPException(409, "Transfer is incomplete")
        if transfer["base"] < int(_meta(con,"floor")):
            raise HTTPException(409, "Transfer history expired")
        records = []
        for row in rows:
            records.extend(_records(cipher.decrypt(row["payload"], f"snapshot:{identity}:{row['part']}")))
        _mirror(records)
        con.execute("DELETE FROM chunks WHERE id IN (SELECT id FROM transfers WHERE committed=1)")
        con.execute("DELETE FROM transfers WHERE committed=1")
        con.execute("UPDATE transfers SET committed=1,expires=? WHERE id=?", (time.time()+RETENTION, identity))
        return {"snapshot": {k:transfer[k] for k in ("id","base","parts")}}


@router.get("/sync/v2/{room}/snapshot/{identity}/{part}")
def snapshot_get(room: str, identity: str, part: int, request: Request):
    _auth(request, room)
    with _lock, _connect() as con:
        _prune(con)
        row = con.execute("""SELECT c.payload FROM chunks c JOIN transfers t ON t.id=c.id
            WHERE c.id=? AND c.part=? AND t.committed=1""", (identity,part)).fetchone()
        if not row:
            raise HTTPException(404, "Transfer part expired or missing")
        return {"payload": row[0]}


@router.post("/sync/v2/{room}/device")
async def register_device(room: str, request: Request):
    _auth(request, room)
    body=await _body(request)
    identity,name,platform,lines=(body.get(k) for k in ("id","name","platform","lines"))
    if (not isinstance(identity,str) or not re.fullmatch(r"[a-f0-9]{32}",identity)
            or not isinstance(name,str) or not 1<=len(name)<=100
            or not isinstance(platform,str) or len(platform)>50
            or type(lines) is not int or lines<0):
        raise HTTPException(400,"Invalid device information")
    with _lock,_connect() as con:
        con.execute("INSERT OR REPLACE INTO devices VALUES(?,?,?,?,?)",
                    (identity,name,platform,lines,time.time()))
    return {"ok":True,"device":name}


def device_status():
    enabled=bool(os.environ.get("GSM_SYNC_TOKEN") and os.environ.get("GSM_SYNC_KEY"))
    if not enabled:return {"enabled":False,"devices":[]}
    with _lock,_connect() as con:
        return {"enabled":True,"devices":[dict(row) for row in con.execute(
            "SELECT name,platform,lines,paired_at FROM devices ORDER BY name")]}
