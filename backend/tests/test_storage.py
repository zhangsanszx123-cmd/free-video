from urllib.parse import urlparse, parse_qs

from app import config
from app.storage import TemporaryStorage


def test_real_sdk_v4_signing_and_private_upload(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "OSS_ACCESS_KEY_ID", "test-id")
    monkeypatch.setattr(config, "OSS_ACCESS_KEY_SECRET", "test-secret")
    monkeypatch.setattr(config, "OSS_BUCKET", "test-bucket")
    storage = TemporaryStorage()
    calls = []
    monkeypatch.setattr(storage.bucket, "put_object_from_file", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(storage.bucket, "delete_object", lambda key: calls.append(key))
    source = tmp_path / "input.mp3"
    source.write_bytes(b"audio")
    signed = storage.upload("freevideo-asr/test.mp3", source)
    query = parse_qs(urlparse(signed).query)
    assert query["x-oss-signature-version"] == ["OSS4-HMAC-SHA256"]
    assert calls[0][1]["headers"]["x-oss-object-acl"] == "private"
    storage.delete("freevideo-asr/test.mp3")
    assert calls[1] == "freevideo-asr/test.mp3"
