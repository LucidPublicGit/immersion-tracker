import asyncio
import json
import time

import pytest

from app.media import local_ai


ROWS = [{'id':'anime:one','title':'A real title','content_type':'anime','aliases':[]}]


def setup_spool(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCAL_AI_CATALOG_ENABLED','true')
    monkeypatch.setenv('LOCAL_AI_CATALOG_SPOOL',str(tmp_path))
    (tmp_path/'health.json').write_text(json.dumps({'updated':time.time(),'enabled':True,'busy':False}))


@pytest.mark.asyncio
async def test_off_and_scoped_requests_never_create_jobs(tmp_path,monkeypatch):
    monkeypatch.delenv('LOCAL_AI_CATALOG_ENABLED',raising=False)
    assert (await local_ai.suggestions('Title','anime',ROWS))['reason']=='disabled'
    setup_spool(tmp_path,monkeypatch)
    assert (await local_ai.suggestions('Title season 2','anime',ROWS))['reason']=='scope_unverified'
    assert not list(tmp_path.glob('*.request.json'))


@pytest.mark.asyncio
async def test_fresh_known_rows_return_only_catalog_text_and_cleanup(tmp_path,monkeypatch):
    setup_spool(tmp_path,monkeypatch)
    async def responder():
        while not list(tmp_path.glob('*.request.json')): await asyncio.sleep(.01)
        path=next(tmp_path.glob('*.request.json'));payload=json.loads(path.read_text())
        path.with_name(path.name.replace('.request.','.response.')).write_text(json.dumps({
            'available':True,'fingerprint':payload['fingerprint'],
            'suggestions':[{'id':'anime:one','score':.95,'title':'Generated false title'}]}))
    task=asyncio.create_task(responder())
    result=await local_ai.suggestions('Title','anime',ROWS)
    await task
    assert result['suggestions'][0]['display_title']=='A real title'
    assert not list(tmp_path.glob('*.request.json')) and not list(tmp_path.glob('*.response.json'))


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', ['unknown','duplicate','nan','stale'])
async def test_invalid_results_are_discarded(tmp_path,monkeypatch,bad):
    setup_spool(tmp_path,monkeypatch)
    async def responder():
        while not list(tmp_path.glob('*.request.json')): await asyncio.sleep(.01)
        path=next(tmp_path.glob('*.request.json'));payload=json.loads(path.read_text())
        rows=[{'id':'anime:one','score':.95}]
        if bad=='unknown':rows[0]['id']='other:unknown'
        if bad=='duplicate':rows*=2
        if bad=='nan':rows[0]['score']=float('nan')
        path.with_name(path.name.replace('.request.','.response.')).write_text(json.dumps({
            'available':True,'fingerprint':'wrong' if bad=='stale' else payload['fingerprint'],'suggestions':rows}))
    task=asyncio.create_task(responder())
    result=await local_ai.suggestions('Title','anime',ROWS);await task
    assert result['available'] is False and result['suggestions']==[]


@pytest.mark.asyncio
async def test_busy_and_disconnect_preserve_normal_workflow(tmp_path,monkeypatch):
    setup_spool(tmp_path,monkeypatch)
    (tmp_path/'health.json').write_text(json.dumps({'updated':time.time(),'enabled':True,'busy':True}))
    assert (await local_ai.suggestions('Title','anime',ROWS))['reason']=='busy'
    setup_spool(tmp_path,monkeypatch)
    async def disconnected():return True
    assert (await local_ai.suggestions('Title','anime',ROWS,disconnected))['reason']=='cancelled'
    assert not list(tmp_path.glob('*.request.json'))


def test_route_disabled_does_not_mutate_catalog(client,monkeypatch):
    monkeypatch.delenv('LOCAL_AI_CATALOG_ENABLED',raising=False)
    before=client.get('/api/catalog').json()
    result=client.post('/api/catalog/suggestions',json={'query':'Title','content_type':'anime'})
    assert result.status_code==200 and result.json()['reason']=='disabled'
    assert client.get('/api/catalog').json()==before


def test_route_rejects_changed_live_catalog(client,monkeypatch):
    monkeypatch.setenv('LOCAL_AI_CATALOG_ENABLED','true')
    from app.db.models import CatalogItem
    from app.db.session import get_engine
    from sqlalchemy.orm import Session
    with Session(get_engine()) as db:
        db.add(CatalogItem(series_key='anime:one',display_title='Before',content_type='anime'));db.commit()
    async def fake(*args):
        with Session(get_engine()) as db:
            row=db.query(CatalogItem).filter_by(series_key='anime:one').one();row.display_title='After';db.commit()
        return {'available':True,'suggestions':[{'series_key':'anime:one','display_title':'Before','content_type':'anime'}]}
    monkeypatch.setattr(local_ai,'suggestions',fake)
    result=client.post('/api/catalog/suggestions',json={'query':'Title','content_type':'anime'})
    assert result.json()['reason']=='stale'
