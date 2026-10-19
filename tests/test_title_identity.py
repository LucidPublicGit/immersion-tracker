import time

import pytest
from sqlalchemy.orm import Session

from app.db.models import LogEntry, TitleIdentity
from app.db.session import get_engine
from app.media import title_identity as identity

RAW = 'Domestic na Kanojo (More Color Version) ドメスティックな彼女 よりぬきカラー版 (uploader)'
CANONICAL = 'ドメスティックな彼女'
CANDIDATES = [dict(provider_id='85802', title=CANONICAL, aliases=['Domestic Girlfriend', 'Domestic na Kanojo'], format='MANGA', provider_url='https://anilist.co/manga/85802', staff=['流石景']),
              dict(provider_id='163094', title=CANONICAL+' 公式薄い本', aliases=[], format='MANGA', provider_url='https://anilist.co/manga/163094', staff=['流石景'])]


def make_log(client, source='mokuro', content_type='manga', title=RAW):
    r = client.post('/api/logs', json=dict(title=title, content_type=content_type, source=source, amount=12, unit='pages' if content_type=='manga' else 'minutes', episode=3, source_ref=f'{source}-{content_type}-{time.time_ns()}'))
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv('TITLE_LOOKUP_WEB_ENABLED', 'true')
    async def lookup(query, kind):
        assert kind == 'manga'
        return CANDIDATES
    monkeypatch.setattr(identity, 'provider_candidates', lookup)
    return lookup


def preview(client, log):
    r = client.post(f"/api/logs/{log['id']}/title-preview", json={})
    assert r.status_code == 200, r.text
    return r.json()


def confirm(client, log, result):
    return client.post(f"/api/logs/{log['id']}/title-identity", json={'token': result['token'], 'provider_id':'85802'})


def test_mapped_show_keeps_episode_on_tadoku_title(client):
    """A confirmed show title replaces the raw name and still logs SxxExx."""
    from app.tadoku.client import TadokuClient

    created = client.post(
        "/api/logs",
        json={
            "title": "Gendai Shikaku Bunka Kenkyuu Kai",
            "content_type": "anime",
            "source": "jellyfin",
            "amount": 24,
            "unit": "minutes",
            "season": 2,
            "episode": 3,
            "source_ref": f"jellyfin-genshiken-{time.time_ns()}",
        },
    )
    assert created.status_code == 201, created.text
    with Session(get_engine()) as db:
        entry = db.get(LogEntry, created.json()["id"])
        db.add(
            TitleIdentity(
                source_key=identity.source_key(entry),
                source=entry.source,
                content_type=entry.content_type,
                original_title=entry.title,
                canonical_title="げんしけん",
                provider="anilist",
                provider_id="240",
                provider_url="https://anilist.co/anime/240",
            )
        )
        db.commit()
        db.refresh(entry)
        assert identity.export_title(entry) == "げんしけん S02E03"
        assert TadokuClient()._description_for(entry) == "げんしけん S02E03"
        assert entry.title == "Gendai Shikaku Bunka Kenkyuu Kai"
        assert entry.episode == 3


@pytest.mark.parametrize('content_type,season,episode,expected', [
    ('manga', None, 17, 'Vol 17'),
    ('book', None, 4, 'Vol 4'),
    ('comic', None, 2, 'Vol 2'),
    ('show', 2, 3, 'S02E03'),
    ('anime', None, 5, 'E05'),
    ('movie', 0, 0, ''),
    ('manga', None, None, ''),
])
def test_confirmed_identity_preserves_position(client, content_type, season, episode, expected):
    from app.tadoku.client import TadokuClient

    with Session(get_engine()) as db:
        entry = LogEntry(title=RAW, content_type=content_type, source='manual',
                         amount=12, unit='pages', season=season, episode=episode)
        db.add(entry)
        db.flush()
        db.add(TitleIdentity(source_key=identity.source_key(entry), source=entry.source,
                             content_type=content_type, original_title=RAW,
                             canonical_title=CANONICAL, provider='anilist',
                             provider_id='85802', provider_url=CANDIDATES[0]['provider_url']))
        db.commit()
        title = f'{CANONICAL} {expected}'.strip()
        assert identity.export_title(entry) == title
        assert TadokuClient()._description_for(entry) == title
        assert TadokuClient().to_local_payload(entry)['title'] == title


def test_existing_mokuro_log_recovers_volume_from_notes(client):
    from app.tadoku.client import TadokuClient

    with Session(get_engine()) as db:
        entry = LogEntry(title=RAW, content_type='manga', source='mokuro', amount=194,
                         unit='comic_pages', tadoku_status='pushed', tadoku_remote_id='existing',
                         notes='pages 0→194 (+194); completed; volume=作品 （０４） (wangson)')
        db.add(entry)
        db.flush()
        db.add(TitleIdentity(source_key=identity.source_key(entry), source=entry.source,
                             content_type=entry.content_type, original_title=RAW,
                             canonical_title=CANONICAL, provider='anilist',
                             provider_id='85802', provider_url=CANDIDATES[0]['provider_url']))
        db.commit()
        assert TadokuClient()._description_for(entry) == f'{CANONICAL} Vol 4'
        assert entry.episode is None and entry.amount == 194
        assert entry.tadoku_status == 'pushed' and entry.tadoku_remote_id == 'existing'
        entry.episode = 5
        assert identity.export_title(entry) == f'{CANONICAL} Vol 5'


def test_exact_export_persists_without_ai_or_web_and_retains_raw(client, provider, monkeypatch):
    log = make_log(client)
    result = preview(client, log)
    assert result['query'] == CANONICAL
    assert result['suggested_ids'] == []
    assert client.get(f"/api/logs/{log['id']}").json()['title_identity'] is None
    saved = confirm(client, log, result)
    assert saved.status_code == 200
    assert saved.json()['tadoku_title'] == f'{CANONICAL} Vol 3'
    assert saved.json()['title'] == RAW
    monkeypatch.setenv('TITLE_LOOKUP_WEB_ENABLED', 'false')
    monkeypatch.setenv('LOCAL_AI_CATALOG_ENABLED', 'false')
    future = make_log(client)
    assert future['tadoku_title'] == f'{CANONICAL} Vol 3'
    assert future['title_identity']['url'] == CANDIDATES[0]['provider_url']
    assert make_log(client, source='manual')['title_identity'] is None
    with Session(get_engine()) as db:
        # Bypass the existing general catalog resolver's cross-type fallback.
        other = LogEntry(title=RAW, content_type='anime', source='mokuro', amount=12, unit='pages')
        db.add(other); db.flush()
        assert identity.mapping_for(other) is None
        db.rollback()
    assert make_log(client, title=RAW+' another work')['title_identity'] is None
    from app.tadoku.client import TadokuClient
    with Session(get_engine()) as db:
        entry = db.get(LogEntry, log['id'])
        payload = TadokuClient().to_local_payload(entry)
        assert payload['title'] == f'{CANONICAL} Vol 3'
        assert payload['title_base'] == RAW
        assert TadokuClient()._description_for(entry) == f'{CANONICAL} Vol 3'
        assert entry.amount == 12 and entry.episode == 3 and entry.source_ref == log['source_ref']
        # A later importer fold restores raw source identity; the mapping still resolves it.
        from app.ingest.mokuro import _apply_identity
        entry.title = 'Temporary title'
        _apply_identity(entry, {'series_title':RAW, 'volume_title':'第3巻'}, 'test-volume')
        assert entry.title == RAW and entry.episode == 3 and entry.amount == 12
        db.commit()
        assert identity.export_title(entry) == f'{CANONICAL} Vol 3'
        assert db.query(TitleIdentity).count() == 1
    removed = client.delete(f"/api/logs/{log['id']}/title-identity")
    assert removed.status_code == 200 and removed.json()['title_identity'] is None
    assert client.get(f"/api/logs/{future['id']}").json()['title_identity'] is None


@pytest.mark.parametrize('bad', ['tampered', 'unknown', 'expired', 'changed'])
def test_confirmation_rejects_invalid_or_stale_preview(client, provider, monkeypatch, bad):
    log = make_log(client); result = preview(client, log)
    body = {'token':result['token'], 'provider_id':'85802'}
    if bad == 'tampered': body['token'] += '0'
    if bad == 'unknown': body['provider_id'] = '999'
    if bad == 'expired': monkeypatch.setattr(identity.time, 'time', lambda: time.time_ns()/1e9+700)
    if bad == 'changed': client.patch(f"/api/logs/{log['id']}", json={'title':'Another title'})
    assert client.post(f"/api/logs/{log['id']}/title-identity", json=body).status_code == 409
    with Session(get_engine()) as db: assert db.query(TitleIdentity).count() == 0


def test_offline_preview_and_pushed_log_never_resubmit(client, provider, monkeypatch):
    log = make_log(client)
    result = preview(client, log)
    with Session(get_engine()) as db:
        entry = db.get(LogEntry, log['id']);entry.tadoku_status='pushed';entry.tadoku_remote_id='existing';db.commit()
    assert confirm(client, log, result).status_code == 200
    with Session(get_engine()) as db:
        entry = db.get(LogEntry, log['id'])
        assert entry.tadoku_status == 'pushed' and entry.tadoku_remote_id == 'existing'
    monkeypatch.setenv('TITLE_LOOKUP_WEB_ENABLED', 'false')
    assert preview(client, log)['reason'] == 'web_disabled'


@pytest.mark.asyncio
async def test_provider_filters_medium_and_requires_native(monkeypatch):
    import httpx
    async def post(self, url, **kwargs):
        assert url == 'https://graphql.anilist.co'
        return httpx.Response(200, request=httpx.Request('POST', url), json={'data':{'Page':{'media':[
            {'id':85802,'type':'MANGA','format':'MANGA','title':{'native':CANONICAL,'english':'Domestic Girlfriend'}},
            {'id':1,'type':'MANGA','format':'NOVEL','title':{'native':'A novel'}},
            {'id':2,'type':'ANIME','format':'TV','title':{'native':'An anime'}},
            {'id':3,'type':'MANGA','format':'MANGA','title':{'native':None}},
        ]}}})
    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    rows = await identity.provider_candidates('Domestic Girlfriend','manga')
    assert [r['provider_id'] for r in rows] == ['85802']


def test_optional_ai_only_suggests_provider_ids(client, provider, monkeypatch):
    from app.media import local_ai
    async def suggest(query, kind, rows, disconnected):
        assert query == CANONICAL and len(rows) == 2
        return {'available':True,'reason':None,'suggestions':[{'series_key':'85802'}]}
    monkeypatch.setattr(local_ai, 'suggestions', suggest)
    log = make_log(client)
    result = client.post(f"/api/logs/{log['id']}/title-preview",json={'use_local_ai':True}).json()
    assert result['suggested_ids'] == ['85802']
    assert len(result['candidates']) == 2  # related publication stays visible for evidence review
    assert client.get(f"/api/logs/{log['id']}").json()['title_identity'] is None


def test_provider_failure_does_not_write_identity(client, monkeypatch):
    monkeypatch.setenv('TITLE_LOOKUP_WEB_ENABLED','true')
    async def fail(*args): raise ValueError('Provider failed')
    monkeypatch.setattr(identity, 'provider_candidates', fail)
    log=make_log(client)
    assert preview(client,log)['reason']=='provider_unavailable'
    with Session(get_engine()) as db: assert db.query(TitleIdentity).count()==0


def test_source_change_during_preview_rejected(client, monkeypatch):
    monkeypatch.setenv('TITLE_LOOKUP_WEB_ENABLED','true')
    log=make_log(client)
    async def changed(*args):
        with Session(get_engine()) as db:
            row=db.get(LogEntry,log['id']);row.title='Different work';db.commit()
        return CANDIDATES
    monkeypatch.setattr(identity,'provider_candidates',changed)
    assert client.post(f"/api/logs/{log['id']}/title-preview",json={}).status_code==409


def test_saved_mapping_does_not_resubmit_remote_log(client, provider):
    from app.tadoku.queue import _submit_entry
    log=make_log(client);result=preview(client,log)
    with Session(get_engine()) as db:
        row=db.get(LogEntry,log['id']);row.tadoku_status='pushed';row.tadoku_remote_id='existing';db.commit()
    assert confirm(client,log,result).status_code==200
    class NeverSubmit:
        def submit(self,*args): raise AssertionError('Must not submit an existing remote log')
    with Session(get_engine()) as db:
        outcome=_submit_entry(db,db.get(LogEntry,log['id']),NeverSubmit())
        assert outcome==(True,'existing','already_submitted')


@pytest.mark.parametrize('raw,expected', [
    ('3月のライオン','3月のライオン'),
    ('86―エイティシックス―','86―エイティシックス―'),
    ('ONE PIECE ワンピース','ワンピース'),
    ('Domestic Girlfriend (More Color Version) (uploader)','Domestic Girlfriend'),
    ('Domestic na Kanojo （More Color Version） ドメスティックな彼女 よりぬきカラー版 (uploader)',CANONICAL),
])
def test_lookup_hints_preserve_native_numeric_titles(raw,expected):
    assert identity.lookup_hint(raw)==expected


def test_exact_alias_is_evidence_and_prefix_is_not_identity():
    rows=identity.annotate_candidates('Domestic Girlfriend',list(reversed(CANDIDATES)))
    assert rows[0]['provider_id']=='85802' and rows[0]['text_match']=='alias_exact'
    assert rows[1]['text_match'] is None
    assert all(r['shared_title_prefix'] for r in rows)
    native=identity.annotate_candidates(CANONICAL,CANDIDATES)
    assert native[0]['text_match']=='native_exact'
    assert native[1]['text_match'] is None


def test_equal_title_candidates_still_require_review():
    rows=identity.annotate_candidates(CANONICAL,[CANDIDATES[0],dict(CANDIDATES[0],provider_id='other')])
    assert len(rows)==2 and all(r['text_match']=='native_exact' for r in rows)
    assert not any(r['shared_title_prefix'] for r in rows)


@pytest.mark.parametrize('ref,expected', [
    ('85802',85802),(' https://anilist.co/manga/85802/ ',85802),
    ('https://anilist.co/manga/85802/Domestic-na-Kanojo',85802),
])
def test_explicit_provider_reference(ref,expected):
    assert identity.parse_provider_reference(ref,'manga')==expected


@pytest.mark.parametrize('ref', ['0','-1','85802.0','https://anilist.co/anime/85802',
    'https://example.com/manga/85802','https://anilist.co.evil/manga/85802',
    'http://anilist.co/manga/85802','https://anilist.co/manga/85802?other=1'])
def test_provider_reference_rejects_wrong_medium_or_url(ref):
    with pytest.raises(ValueError): identity.parse_provider_reference(ref,'manga')


def test_direct_lookup_preview_requires_confirmation(client,monkeypatch):
    monkeypatch.setenv('TITLE_LOOKUP_WEB_ENABLED','true')
    async def direct(query,kind,provider_id=None):
        assert kind=='manga' and provider_id==85802
        return [CANDIDATES[0]]
    monkeypatch.setattr(identity,'provider_candidates',direct)
    log=make_log(client)
    r=client.post(f"/api/logs/{log['id']}/title-preview",json={'provider_reference':'https://anilist.co/manga/85802'})
    result=r.json();assert r.status_code==200 and result['lookup_mode']=='provider_id'
    assert len(result['candidates'])==1
    assert client.get(f"/api/logs/{log['id']}").json()['title_identity'] is None
    assert confirm(client,log,result).json()['tadoku_title']==f'{CANONICAL} Vol 3'


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', ['wrong_type','wrong_id','missing_native','not_found','valid'])
async def test_direct_provider_validates_returned_record(monkeypatch,bad):
    import httpx
    async def post(self,url,**kwargs):
        assert kwargs['json']['variables']=={'id':85802,'type':'MANGA'}
        assert 'Media(id:' in kwargs['json']['query']
        row={'id':85802,'type':'MANGA','format':'MANGA','title':{'native':CANONICAL}}
        if bad=='wrong_type':row.update(type='ANIME',format='TV')
        if bad=='wrong_id':row['id']=163094
        if bad=='missing_native':row['title']['native']=None
        return httpx.Response(404 if bad=='not_found' else 200,request=httpx.Request('POST',url),json={'data':{'Media':row}})
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    result=await identity.provider_candidates('Source title','manga',85802)
    assert bool(result)==(bad=='valid')


def test_invalid_reference_never_calls_provider(client,monkeypatch):
    monkeypatch.setenv('TITLE_LOOKUP_WEB_ENABLED','true')
    async def never(*args):raise AssertionError('Must reject before network access')
    monkeypatch.setattr(identity,'provider_candidates',never)
    log=make_log(client)
    r=client.post(f"/api/logs/{log['id']}/title-preview",json={'provider_reference':'https://anilist.co/anime/1'})
    assert r.status_code==422


def test_drama_hint_keeps_work_and_removes_release_tag():
    raw='  Terrace House Boys X Girls Next Door-IRENEBRO'
    assert identity.lookup_hint(raw)=='Terrace House Boys X Girls Next Door'


@pytest.mark.parametrize('kind,media_type,accepted', [
    ('show',2,True),('drama',2,True),('show',1,False),('show',3,False),
    ('movie',3,True),('movie',2,False),('book',4,True),('book',10,False),
    ('game',6,True),('visual_novel',7,True),('visual_novel',6,False),
])
@pytest.mark.asyncio
async def test_jiten_same_medium_only(monkeypatch,kind,media_type,accepted):
    import httpx
    async def get(self,url,**kwargs):
        assert url=='https://api.jiten.moe/api/media-deck/search-suggestions'
        return httpx.Response(200,request=httpx.Request('GET',url),json={'suggestions':[
            {'deckId':111215,'mediaType':media_type,'originalTitle':'テラスハウス ボーイズ ガールズ ネクストドア','englishTitle':'Terrace House: Boys × Girls Next Door'}]})
    monkeypatch.setattr(httpx.AsyncClient,'get',get)
    rows=await identity.provider_candidates('Terrace House Boys X Girls Next Door',kind)
    assert bool(rows)==accepted
    if rows:
        assert rows[0]['provider']=='jiten'
        assert identity.annotate_candidates('Terrace House Boys X Girls Next Door',rows)[0]['text_match']=='alias_normalized'


def test_jiten_reference_and_auto_off_by_default(monkeypatch):
    assert identity.parse_provider_reference('https://jiten.moe/decks/media/111215/detail','show')==111215
    with pytest.raises(ValueError):identity.parse_provider_reference('https://anilist.co/anime/1','show')
    monkeypatch.setenv('TITLE_LOOKUP_WEB_ENABLED','true')
    monkeypatch.delenv('TITLE_LOOKUP_AUTO_SUGGEST_ENABLED',raising=False)
    assert not identity.auto_enabled()
    monkeypatch.setenv('TITLE_LOOKUP_AUTO_SUGGEST_ENABLED','true')
    assert identity.auto_enabled()
    monkeypatch.setenv('TITLE_LOOKUP_WEB_ENABLED','false')
    assert not identity.auto_enabled()


def test_drama_confirmation_persists_jiten_provenance(client,monkeypatch):
    monkeypatch.setenv('TITLE_LOOKUP_WEB_ENABLED','true')
    async def lookup(query,kind):
        assert kind=='show' and query=='Terrace House Boys X Girls Next Door'
        return [dict(provider='jiten',provider_label='Jiten',provider_id='111215',title='テラスハウス ボーイズ ガールズ ネクストドア',aliases=['Terrace House: Boys × Girls Next Door'],format='Live-action series',provider_url='https://jiten.moe/decks/media/111215/detail',staff=[])]
    monkeypatch.setattr(identity,'provider_candidates',lookup)
    log=make_log(client,source='plex',content_type='show',title='Terrace House Boys X Girls Next Door-IRENEBRO')
    result=preview(client,log)
    assert result['provider']=='jiten' and result['candidates'][0]['text_match']=='alias_normalized'
    r=client.post(f"/api/logs/{log['id']}/title-identity",json={'token':result['token'],'provider_id':'111215'})
    assert r.status_code==200 and r.json()['title_identity']['provider']=='jiten'
    assert r.json()['tadoku_title']=='テラスハウス ボーイズ ガールズ ネクストドア E03'
    assert r.json()['title']==log['title']


@pytest.mark.parametrize('volume_title', ['第4巻', '作品 （０４） (wangson)'])
def test_saved_mapping_reused_by_mokuro_poll_and_fold_offline(client, provider, monkeypatch, volume_title):
    from app.core.config import get_settings
    from app.ingest.mokuro import get_progress_watermark, poll_mokuro
    from app.tadoku.client import TadokuClient

    seed = make_log(client)
    assert confirm(client, seed, preview(client, seed)).status_code == 200
    monkeypatch.setenv('TITLE_LOOKUP_WEB_ENABLED', 'false')
    monkeypatch.setenv('LOCAL_AI_CATALOG_ENABLED', 'false')
    cfg = get_settings().yaml_config.mokuro
    cfg.enabled, cfg.bootstrap, cfg.min_pages = True, False, 1
    cfg.content_type, cfg.unit, cfg.tadoku_default = 'manga', 'comic_pages', 'pending'
    rec = dict(series_title=RAW, volume_title=volume_title, progress=10, chars=1000,
               completed=False, lastProgressUpdate='2026-04-01T12:00:00Z')
    with Session(get_engine()) as db:
        assert poll_mokuro(db, snapshot={'offline-volume': rec}).logs_created == 0
        assert poll_mokuro(db, snapshot={'offline-volume': {**rec, 'progress': 15}}).logs_created == 1
        row = db.query(LogEntry).filter(LogEntry.source_ref == 'mokuro:offline-volume:15').one()
        first_id, first_key = row.id, row.series_key
        assert TadokuClient().to_local_payload(row)['title'] == f'{CANONICAL} Vol 4'
        assert poll_mokuro(db, snapshot={'offline-volume': {**rec, 'progress': 22}}).logs_created == 1
        db.refresh(row)
        assert row.id == first_id and row.series_key == first_key
        assert row.title == RAW and row.episode == 4 and row.amount == 12
        assert row.source_ref == 'mokuro:offline-volume:22'
        assert get_progress_watermark(db, 'offline-volume') == 22
        payload = TadokuClient().to_local_payload(row)
        assert payload['title'] == f'{CANONICAL} Vol 4' and payload['title_base'] == RAW
        assert TadokuClient()._description_for(row) == f'{CANONICAL} Vol 4'


def test_saved_mapping_reused_by_subsequent_plex_webhook_offline(client, monkeypatch):
    from app.tadoku.client import TadokuClient

    monkeypatch.setenv('TITLE_LOOKUP_WEB_ENABLED', 'true')
    async def lookup(query, kind):
        assert kind == 'anime'
        return CANDIDATES
    monkeypatch.setattr(identity, 'provider_candidates', lookup)
    event = dict(rating_key='offline-episode-1', title='Episode One',
                 grandparent_title=RAW, library_name='Anime', media_type='episode',
                 duration_ms=1_440_000, progress_percent=95, watched=True,
                 season_num=1, episode_num=1)
    first = client.post('/api/webhooks/plex', json=event).json()
    assert first['accepted']
    log = client.get(f"/api/logs/{first['log_id']}").json()
    assert confirm(client, log, preview(client, log)).status_code == 200
    monkeypatch.setenv('TITLE_LOOKUP_WEB_ENABLED', 'false')
    monkeypatch.setenv('LOCAL_AI_CATALOG_ENABLED', 'false')
    later = client.post('/api/webhooks/plex', json={**event, 'rating_key': 'offline-episode-2',
                                                 'title': 'Episode Two', 'episode_num': 2}).json()
    assert later['accepted'] and later['log_id'] != first['log_id']
    with Session(get_engine()) as db:
        row = db.get(LogEntry, later['log_id'])
        assert row.title == RAW and row.amount == 24 and row.unit == 'minutes'
        assert row.season == 1 and row.episode == 2
        assert row.source_ref.startswith('offline-episode-2:')
        assert f'plex_title={RAW}' in row.notes
        assert row.series_key == db.get(LogEntry, first['log_id']).series_key
        payload = TadokuClient().to_local_payload(row)
        assert payload['title'] == f'{CANONICAL} S01E02' and payload['title_base'] == RAW
        assert TadokuClient()._description_for(row) == f'{CANONICAL} S01E02'
