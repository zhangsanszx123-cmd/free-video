"""Private temporary OSS objects. Use the official SDK, V4 signing, no public ACL."""
from pathlib import Path

from . import config
from .errors import TranscriptionError


class TemporaryStorage:
    def __init__(self):
        import oss2
        from oss2.credentials import StaticCredentialsProvider
        provider = StaticCredentialsProvider(config.OSS_ACCESS_KEY_ID, config.OSS_ACCESS_KEY_SECRET,
                                             config.OSS_SECURITY_TOKEN)
        auth = oss2.ProviderAuthV4(provider)
        self.bucket = oss2.Bucket(auth, config.OSS_ENDPOINT, config.OSS_BUCKET,
                                  region=config.OSS_REGION, connect_timeout=30)

    def upload(self, key: str, path: Path) -> str:
        self._validate(key)
        try:
            # Explicit private ACL, even if an operator accidentally selected a public bucket.
            self.bucket.put_object_from_file(key, str(path), headers={"x-oss-object-acl": "private"})
            return self.bucket.sign_url("GET", key, config.OSS_URL_TTL, slash_safe=True)
        except Exception:
            raise TranscriptionError("UPLOAD_FAILED", "临时音频上传失败，请检查 OSS 配置或稍后重试", True) from None

    def delete(self, key: str):
        self._validate(key)
        self.bucket.delete_object(key)

    @staticmethod
    def _validate(key):
        if not key.startswith(config.OSS_PREFIX) or ".." in key or "\\" in key:
            raise ValueError("invalid temporary object key")
