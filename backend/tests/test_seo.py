"""Technical & on-page SEO tests: robots.txt, sitemap.xml, SSR meta injection, and JSON-LD schema."""
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import pytest

from app import config, seo


def test_robots_txt_allows_public_routes_and_disallows_private_paths(client, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://freevideo.example.com")
    res = client.get("/robots.txt")
    assert res.status_code == 200
    assert "text/plain" in res.headers["content-type"]
    text = res.text
    for allowed in ("Allow: /", "Allow: /batch", "Allow: /ai", "Allow: /learn", "Allow: /pricing", "Allow: /account/api/docs"):
        assert allowed in text
    for disallowed in ("Disallow: /api/", "Disallow: /admin", "Disallow: /account", "Disallow: /history", "Disallow: /pay/"):
        assert disallowed in text
    assert "Sitemap: https://freevideo.example.com/sitemap.xml" in text


def test_sitemap_xml_contains_all_canonical_public_pages(client, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://freevideo.example.com")
    res = client.get("/sitemap.xml")
    assert res.status_code == 200
    assert "application/xml" in res.headers["content-type"]
    root = ET.fromstring(res.text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [el.text for el in root.findall("sm:url/sm:loc", ns)]
    assert locs == [
        "https://freevideo.example.com/",
        "https://freevideo.example.com/batch",
        "https://freevideo.example.com/ai",
        "https://freevideo.example.com/learn",
        "https://freevideo.example.com/pricing",
        "https://freevideo.example.com/account/api/docs",
    ]


@pytest.mark.parametrize(
    "path,expected_title_part,expected_canonical",
    [
        ("/", "在线视频文案提取与万能视频下载工具", "https://freevideo.example.com/"),
        ("/batch", "批量视频文案提取与素材打包下载", "https://freevideo.example.com/batch"),
        ("/ai", "AI视频总结与双语字幕翻译", "https://freevideo.example.com/ai"),
        ("/learn", "AI视频学习工作台", "https://freevideo.example.com/learn"),
        ("/pricing", "会员定价与语音识别额度说明", "https://freevideo.example.com/pricing"),
        ("/account/api/docs", "视频文案提取开放API接入文档", "https://freevideo.example.com/account/api/docs"),
    ],
)
def test_ssr_public_routes_inject_distinct_tdk_canonical_and_json_ld(path, expected_title_part, expected_canonical):
    index_html = (Path(__file__).resolve().parents[2] / "frontend" / "index.html").read_text(encoding="utf-8")
    rendered = seo.render_spa_html(index_html, path, "https://freevideo.example.com")
    assert f"<title>{seo.PUBLIC_ROUTES[path]['title']}</title>" in rendered
    assert expected_title_part in rendered
    assert f'content="{seo.PUBLIC_ROUTES[path]["description"]}"' in rendered
    assert f'<link rel="canonical" href="{expected_canonical}" />' in rendered
    assert f'<meta property="og:url" content="{expected_canonical}" />' in rendered
    assert 'content="index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1"' in rendered
    scripts = re.findall(r'<script type="application/ld\+json">(.*?)</script>', rendered)
    assert len(scripts) == 5
    types = [json.loads(s)["@type"] for s in scripts]
    assert types == ["WebSite", "Organization", "WebPage", "SoftwareApplication", "FAQPage"]
    assert json.loads(scripts[0])["url"] == "https://freevideo.example.com/"


@pytest.mark.parametrize("path", ["/login", "/register", "/account", "/account/api", "/history", "/admin/login", "/unknown-404-route"])
def test_ssr_private_and_unknown_routes_inject_noindex(path):
    index_html = (Path(__file__).resolve().parents[2] / "frontend" / "index.html").read_text(encoding="utf-8")
    rendered = seo.render_spa_html(index_html, path, "https://freevideo.example.com")
    assert '<meta name="robots" content="noindex, nofollow" />' in rendered
    assert '<meta name="googlebot" content="noindex, nofollow" />' in rendered
