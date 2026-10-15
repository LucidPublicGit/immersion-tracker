import asyncio
import json
import time

import pytest

from app.media import ai_settings, local_ai, title_identity


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCAL_AI_SETTINGS_PATH',str(tmp_path/'options.json'))
    monkeypatch.delenv('LOCAL_AI_CATALOG_SPOOL',raising=False)
    ai_settings._ACTIVITY.clear()


def test_saved_switches_override_env_and_survive_read(client,monkeypatch):
    monkeypatch.setenv('LOCAL_AI_CATALOG_ENABLED','true')
    body=dict(local_ai_enabled=False,web_enabled=False,auto_suggest_enabled=False)
    response=client.put('/api/settings/local-ai',json=body)
    assert response.status_code==200 and response.json()['options']==body
    assert not local_ai.enabled() and not title_identity.web_enabled()
    assert client.get('/api/settings/local-ai').json()['worker']['online'] is False
    page=client.get('/settings')
    assert page.status_code==200 and 'Provider lookup' in page.text and 'Recent activity' in page.text
    assert 'href="/settings"' in client.get('/queue').text


def test_offline_model_save_rejected_without_changing_options(client):
    before=ai_settings.options()
    response=client.put('/api/settings/local-ai',json=dict(local_ai_enabled=True,web_enabled=True,auto_suggest_enabled=True,
        worker_config=dict(model_path='/some/model',minimum_similarity=.9,query_prefix='query: ',document_prefix='passage: '),expected_worker_config='a'*64))
    assert response.status_code==503 and ai_settings.options()==before


def test_invalid_threshold_and_unknown_options_rejected(client):
    body=dict(local_ai_enabled=True,web_enabled=True,auto_suggest_enabled=False)
    assert client.put('/api/settings/local-ai',json={**body,'secret':'not allowed'}).status_code==422
    assert client.put('/api/settings/local-ai',json={**body,'worker_config':dict(model_path='model',minimum_similarity=2,query_prefix='',document_prefix='')}).status_code==422


def test_worker_status_projects_only_safe_fields(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCAL_AI_CATALOG_SPOOL',str(tmp_path))
    (tmp_path/'health.json').write_text(json.dumps(dict(updated=time.time(),enabled=True,busy=False,settings_supported=True,config_digest='a'*64,config=dict(model_path='/model',secret='do not show',query_prefix='',document_prefix='',minimum_similarity=.9))))
    (tmp_path/'activity.json').write_text(json.dumps([dict(at=time.time(),available=True,suggestions=1,raw_query='do not show',seconds=16,peak_rss_gib=.9)]))
    status=ai_settings.worker_status()
    assert status['online'] and status['settings_supported']
    assert 'do not show' not in json.dumps(status)
    (tmp_path/'health.json').write_text(json.dumps(dict(updated=time.time()-30)))
    assert not ai_settings.worker_status()['online']


@pytest.mark.asyncio
async def test_settings_control_binding_cleanup_and_no_inference(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCAL_AI_CATALOG_SPOOL',str(tmp_path))
    async def responder():
        while not list(tmp_path.glob('*.control.request.json')):await asyncio.sleep(.01)
        path=next(tmp_path.glob('*.control.request.json'));value=json.loads(path.read_text())
        assert value['patch']=={'enabled':False}
        path.with_name(path.name.replace('.request.','.response.')).write_text(json.dumps({'ok':True,'fingerprint':value['fingerprint']}))
    task=asyncio.create_task(responder())
    await ai_settings.configure_worker({'enabled':False},'a'*64)
    await task
    assert not list(tmp_path.glob('*.json'))


def test_activity_tail_is_bounded():
    for i in range(70):ai_settings.record('provider',f'lookup {i}')
    assert len(ai_settings.activity())==30 and ai_settings.activity()[-1]['message']=='lookup 69'


def test_corrupt_saved_settings_fail_closed(monkeypatch):
    monkeypatch.setenv('LOCAL_AI_CATALOG_ENABLED','true')
    ai_settings.settings_path().write_text('{broken')
    assert not any(ai_settings.options().values())
