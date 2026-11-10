from io import BytesIO
import threading
import time
import zipfile

from fastapi.testclient import TestClient
import pytest

from app import asr, config, main, transcriptions
from app.errors import NoSubtitles, VideoError
from .test_transcriptions import cloud, SAMPLE


def wait_batch(client, job_id):
    for _ in range(400):
        response = client.get(f'/api/batch-transcriptions/{job_id}')
        assert response.status_code == 200, response.text
        value = response.json()
        if value['status'] in ('done', 'error'):
            return value
        time.sleep(.01)
    raise AssertionError('batch timeout')


def submit(client, urls):
    response = client.post('/api/batch-transcriptions', json={'urls': urls, 'allow_asr': True})
    assert response.status_code == 200, response.text
    return response.json()


def test_partial_subtitles_zip_and_owned_results(client, monkeypatch):
    def read(url, directory, lang):
        if 'bad' in url:
            raise VideoError('字幕下载网络失败')
        return {'title': '同名/视频'}, SAMPLE, {'source': 'platform_subtitle', 'language': 'zh'}
    monkeypatch.setattr(transcriptions, 'read_subtitles', read)
    monkeypatch.setattr(asr, 'get_provider', lambda: pytest.fail('native subtitles must not call ASR'))
    urls = ['https://example.com/1', 'https://example.com/2', 'https://example.com/bad']
    job = submit(client, urls + [urls[0]])
    result = wait_batch(client, job['id'])
    assert result['total'] == 3 and result['succeeded'] == 2 and result['failed'] == 1
    assert '你好' in result['items'][0]['result']['text']
    assert '网络失败' in result['items'][2]['error']
    response = client.get(f"/api/batch-transcriptions/{job['id']}/file")
    assert response.status_code == 200 and 'no-store' in response.headers['cache-control']
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        assert len(set(archive.namelist())) == 2
        assert all(name.endswith('.srt') and '/' not in name for name in archive.namelist())
        assert '你好' in archive.read(archive.namelist()[0]).decode('utf-8')
    assert submit(client, urls)['id'] == job['id']
    with TestClient(main.app) as outsider:
        assert outsider.get(f"/api/batch-transcriptions/{job['id']}").status_code == 404
        assert outsider.get(f"/api/batch-transcriptions/{job['id']}/file").status_code == 404


def test_missing_subtitles_use_existing_paid_queue_once(client, cloud):
    urls = ['https://example.com/video/1']
    job = submit(client, urls)
    result = wait_batch(client, job['id'])
    assert result['succeeded'] == 1 and result['items'][0]['result']['source'] == 'asr'
    assert cloud['submit'] == 1
    for _ in range(2):
        assert submit(client, urls)['id'] == job['id']
        assert client.get(f"/api/batch-transcriptions/{job['id']}/file").status_code == 200
    assert cloud['submit'] == 1


def test_login_required_does_not_charge(client, cloud, monkeypatch):
    def login(*args):
        raise NoSubtitles('字幕需要登录后访问')
    monkeypatch.setattr(transcriptions, 'read_subtitles', login)
    result = wait_batch(client, submit(client, ['https://example.com/login'])['id'])
    assert result['failed'] == 1 and '登录' in result['items'][0]['error']
    assert cloud['submit'] == 0


def test_budget_and_all_failed_archive(client, cloud, monkeypatch):
    monkeypatch.setattr(config, 'ASR_DAILY_BUDGET', '0')
    job = submit(client, ['https://example.com/video/1'])
    result = wait_batch(client, job['id'])
    assert result['status'] == 'error' and result['succeeded'] == 0
    assert cloud['submit'] == 0
    assert client.get(f"/api/batch-transcriptions/{job['id']}/file").status_code == 409


def test_running_export_and_expiry(client, monkeypatch):
    gate = threading.Event()
    def read(*args):
        gate.wait(3)
        return {'title': '字幕'}, SAMPLE, {'source': 'platform_subtitle'}
    monkeypatch.setattr(transcriptions, 'read_subtitles', read)
    job = submit(client, ['https://example.com/1'])
    try:
        assert client.get(f"/api/batch-transcriptions/{job['id']}/file").status_code == 409
    finally:
        gate.set()
    wait_batch(client, job['id'])
    main.batch_transcription_manager.jobs[job['id']].finished_at = time.time() - config.FILE_TTL_SECONDS - 1
    assert client.get(f"/api/batch-transcriptions/{job['id']}").status_code == 404


def test_validation_and_origin(client):
    for urls in ([], ['not a URL'], [f'https://example.com/{i}' for i in range(21)]):
        assert client.post('/api/batch-transcriptions', json={'urls': urls, 'allow_asr': True}).status_code in (400, 422)
    assert client.post('/api/batch-transcriptions', json={'urls': ['https://example.com/1']}).status_code == 422
    assert client.post('/api/batch-transcriptions', json={'urls': ['https://example.com/1'], 'allow_asr': True},
                       headers={'Origin': 'https://evil.example'}).status_code == 403
