"""Pair Windows/Linux/macOS GSM with a private Immersion Tracker sync hub.

Use GSM's own encrypted protocol modules, never replace its live database.
The pairing JSON is a secret; keep it outside this repository.
"""
import argparse
import datetime
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import types
from pathlib import Path
from urllib.request import Request, urlopen


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pairing',required=True,type=Path)
    parser.add_argument('--gsm-data',required=True,type=Path)
    parser.add_argument('--configure-only',action='store_true')
    parser.add_argument('--device-name',default=None)
    args=parser.parse_args()
    pairing=json.loads(args.pairing.read_text())
    data=args.gsm_data.expanduser().resolve()
    config=data/'config.json'
    database=data/'gsm.db'
    if not config.is_file() or not database.is_file():
        raise SystemExit('Run GSM once first, then supply its active data folder.')
    settings={"enabled":True,"auto_sync":True,"protocol":"relay-v2",
              "api_url":pairing['url'],"api_token":pairing['token'],
              "sync_key":pairing['key'],"interval_seconds":60,"settings_groups":[]}
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup=data/'backup'/'device-sync'/stamp
    backup.mkdir(parents=True,exist_ok=False)
    shutil.copy2(config,backup/'config.json')
    with sqlite3.connect(f'file:{database.as_posix()}?mode=ro',uri=True) as src:
        with sqlite3.connect(backup/'gsm.db') as dst: src.backup(dst)
    # Prefer GSM's own config writer when its local backend is running.
    cfg=json.loads(config.read_text(encoding='utf-8-sig'))
    port=cfg.get('configs',{}).get(cfg.get('current_profile','Default'),{}).get('general',{}).get('texthooker_port',55000)
    local=f'http://127.0.0.1:{port}/api/cloud-sync'
    running=False
    try:
        with urlopen(local+'/status',timeout=3) as response:
            running=isinstance(json.load(response),dict)
    except Exception:
        pass
    if running:
        req=Request(local+'/settings',data=json.dumps(settings).encode(),headers={'Content-Type':'application/json'})
        with urlopen(req,timeout=30) as response:
            result=json.load(response)
        if not result.get('configured'):raise SystemExit('GSM rejected device sync configuration.')
    else:
        for profile in cfg['configs'].values():
            advanced=profile.setdefault('advanced',{})
            for key,value in settings.items():
                field='key' if key=='sync_key' else key
                advanced['cloud_sync_'+field]=value
        incoming=config.with_suffix('.sync-incoming')
        incoming.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(incoming,config)
    print('Paired GSM. Automatic sync runs every 60 seconds while GSM is open. Backup:',backup)
    if args.configure_only:return
    if running:
        req=Request(local+'/run',data=json.dumps({'max_rounds':50,'publish_snapshot':True}).encode(),headers={'Content-Type':'application/json'})
        with urlopen(req,timeout=1800) as response:result=json.load(response)
    else:
        # Only load protocol modules. Importing the desktop service would also
        # initialize GUI/config components and could open the wrong data folder.
        spec=importlib.util.find_spec('GameSentenceMiner')
        if not spec or not spec.submodule_search_locations:
            raise SystemExit('Use GSM\'s Python environment to perform the initial sync.')
        pkg=Path(next(iter(spec.submodule_search_locations)))/'util/cloud_sync'
        for name in ('GameSentenceMiner','GameSentenceMiner.util','GameSentenceMiner.util.cloud_sync'):
            module=types.ModuleType(name);module.__path__=[];sys.modules[name]=module
        for name in ('store','crypto','relay_client'):
            full='GameSentenceMiner.util.cloud_sync.'+name
            module_spec=importlib.util.spec_from_file_location(full,pkg/(name+'.py'))
            module=importlib.util.module_from_spec(module_spec)
            sys.modules[full]=module;module_spec.loader.exec_module(module)
        native=sys.modules['GameSentenceMiner.util.cloud_sync.relay_client']
        crypto=sys.modules['GameSentenceMiner.util.cloud_sync.crypto']
        store=sys.modules['GameSentenceMiner.util.cloud_sync.store']
        import hashlib,uuid
        class Database:
            def __init__(self):
                # Like GSM's normal writer, retain one connection. Closing the
                # last WAL connection after every event forces costly checkpoints.
                self.connection=sqlite3.connect(database,timeout=60)
            def run_transaction(self,fn):
                with self.connection:return fn(self.connection)
        cipher=crypto.SyncCipher(pairing['key'])
        # Matches GSM service.py: URL | empty legacy identity | room.
        scope=hashlib.sha256(f"{pairing['url']}||{cipher.room}".encode()).hexdigest()
        database_adapter=Database()
        native_store=store.RelayStore(database_adapter,scope,uuid.uuid4().hex)
        database_adapter.run_transaction(lambda con:con.execute(
            'CREATE INDEX IF NOT EXISTS tracker_sync_outbox_lookup ON sync_v2_outbox(scope,kind,record_id)'))
        client=native.RelayClient(native_store,cipher,
                                 pairing['url'],pairing['token'],timeout=60)
        result=client.sync(max_rounds=None,publish_snapshot=True)
    print('Initial sync:',result.get('status'),'sent:',result.get('sent_changes'),
          'received:',result.get('received_changes'),'pending:',result.get('pending_changes_after'))
    if result.get('status')!='success':raise SystemExit(1)
    import platform,hashlib,base64,uuid
    device_file=data/'tracker-sync-device-id'
    if not device_file.exists():device_file.write_text(uuid.uuid4().hex)
    room=hashlib.sha256(b'gsm-sync-room-v2\0'+base64.urlsafe_b64decode(pairing['key'][5:]+'=')).hexdigest()
    with sqlite3.connect(f'file:{database.as_posix()}?mode=ro',uri=True) as con:
        count=con.execute('SELECT COUNT(*) FROM game_lines').fetchone()[0]
    document={'id':device_file.read_text().strip(),'name':args.device_name or platform.node(),
              'platform':platform.system(),'lines':count}
    req=Request(pairing['url']+'/api/sync/v2/'+room+'/device',data=json.dumps(document).encode(),
                headers={'Content-Type':'application/json','Authorization':'Bearer '+pairing['token']})
    with urlopen(req,timeout=30) as response:json.load(response)
    print('Tracker confirmed this paired device:',document['name'])


if __name__=='__main__':main()
