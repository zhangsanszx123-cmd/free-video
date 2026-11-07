"""Real-network smoke tests: python -m pytest -m network"""
import pytest

from app import downloader

pytestmark = pytest.mark.network
BILI = "https://www.bilibili.com/video/BV1GJ411x7h7"


def test_parse_bilibili():
    s = downloader.parse(f"【官方 MV】分享链接 {BILI} 快来看")
    assert s["platform"] == "BiliBili" and s["qualities"]


def test_download_bilibili_360_and_mp3(tmp_path):
    assert downloader.download(BILI, tmp_path / "v", 360).suffix == ".mp4"
    assert downloader.download(BILI, tmp_path / "a", kind="audio").suffix == ".mp3"


DOUYIN = "https://www.douyin.com/video/6915675899241450760"


def test_douyin_parse_and_download(tmp_path):
    s = downloader.parse(DOUYIN)
    assert s["platform"] == "Douyin" and s["direct"]["url"].startswith("http")
    video = downloader.download(DOUYIN, tmp_path / "v")
    assert video.suffix == ".mp4" and video.read_bytes()[4:8] == b"ftyp"
    assert downloader.download(DOUYIN, tmp_path / "a", kind="audio").suffix == ".mp3"
