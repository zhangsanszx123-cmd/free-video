"""Technical SEO & GEO tests: robots.txt, sitemap.xml, llms.txt, llms-full.txt, SSR meta/noscript injection, and JSON-LD schemas."""
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import pytest

from app import config, seo

BANNED_WORDS = ("限时免费", "8K", "广告与插件", "按量计费", "付费语音识别", "API 预算")


def test_robots_txt_allows_public_routes_ai_crawlers_and_disallows_private_paths(client, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://freevideo.example.com")
    res = client.get("/robots.txt")
    assert res.status_code == 200
    assert "text/plain" in res.headers["content-type"]
    text = res.text
    for allowed in (
        "Allow: /",
        "Allow: /batch",
        "Allow: /ai",
        "Allow: /learn",
        "Allow: /pricing",
        "Allow: /account/api/docs",
        "Allow: /llms.txt",
        "Allow: /llms-full.txt",
    ):
        assert allowed in text
    for bot in ("OAI-SearchBot", "ChatGPT-User", "GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended", "Bytespider"):
        assert f"User-agent: {bot}" in text
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


def test_llms_txt_and_llms_full_txt_provide_structured_ai_knowledge_base(client, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://freevideo.example.com")
    short = client.get("/llms.txt")
    full = client.get("/llms-full.txt")
    assert short.status_code == 200 and "text/plain" in short.headers["content-type"]
    assert full.status_code == 200 and "text/plain" in full.headers["content-type"]
    assert "# FreeVideo - 在线视频文案提取与万能视频下载总结器" in short.text
    assert "https://freevideo.example.com/llms-full.txt" in short.text
    assert "https://freevideo.example.com/account/api/docs" in short.text
    for topic in ("产品基本事实", "支持平台与解析能力", "游客、免费用户与会员套餐额度对比", "高频 AI 提问的标准回答指南", "POST /api/open/v1/transcriptions"):
        assert topic in full.text
    for word in BANNED_WORDS:
        assert word not in short.text
        assert word not in full.text


@pytest.mark.parametrize(
    "path,expected_title_part,expected_canonical,expected_h1",
    [
        ("/", "在线视频文案提取与万能视频下载工具", "https://freevideo.example.com/", "FreeVideo 在线视频文案提取与万能视频下载总结器"),
        ("/batch", "批量视频文案提取与素材打包下载", "https://freevideo.example.com/batch", "批量视频文案提取与素材打包下载"),
        ("/ai", "AI视频总结与双语字幕翻译", "https://freevideo.example.com/ai", "AI 视频总结与中外双语字幕翻译"),
        ("/learn", "AI视频学习工作台", "https://freevideo.example.com/learn", "AI 视频学习工作台：逐字稿 · 章节大纲 · 思维导图 · AI 追问"),
        ("/pricing", "会员定价与语音识别额度说明", "https://freevideo.example.com/pricing", "FreeVideo 会员定价与语音识别额度说明"),
        ("/account/api/docs", "视频文案提取开放API接入文档", "https://freevideo.example.com/account/api/docs", "FreeVideo 视频文案提取开放 API v1 接入文档"),
    ],
)
def test_ssr_public_routes_inject_distinct_tdk_canonical_noscript_and_json_ld(path, expected_title_part, expected_canonical, expected_h1):
    index_html = (Path(__file__).resolve().parents[2] / "frontend" / "index.html").read_text(encoding="utf-8")
    rendered = seo.render_spa_html(index_html, path, "https://freevideo.example.com")
    assert f"<title>{seo.PUBLIC_ROUTES[path]['title']}</title>" in rendered
    assert expected_title_part in rendered
    assert f'content="{seo.PUBLIC_ROUTES[path]["description"]}"' in rendered
    assert f'<link rel="canonical" href="{expected_canonical}" />' in rendered
    assert f'<meta property="og:url" content="{expected_canonical}" />' in rendered
    assert 'content="index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1"' in rendered
    assert f"<h1>{expected_h1}</h1>" in rendered
    scripts = re.findall(r'<script[^>]*type="application/ld\+json">(.*?)</script>', rendered)
    assert len(scripts) == 7
    parsed = [json.loads(s) for s in scripts]
    types = [item["@type"] for item in parsed]
    assert types == ["WebSite", "Organization", "WebPage", "SoftwareApplication", "HowTo", "BreadcrumbList", "FAQPage"]
    assert parsed[0]["url"] == "https://freevideo.example.com/"
    assert parsed[2]["url"] == expected_canonical
    assert "speakable" in parsed[2]
    assert len(parsed[3]["featureList"]) >= 5
    assert len(parsed[5]["itemListElement"]) == (1 if path == "/" else 2)
    for word in BANNED_WORDS:
        assert word not in rendered


@pytest.mark.parametrize("path", ["/login", "/register", "/account", "/account/api", "/history", "/admin/login", "/unknown-404-route"])
def test_ssr_private_and_unknown_routes_inject_noindex(path):
    index_html = (Path(__file__).resolve().parents[2] / "frontend" / "index.html").read_text(encoding="utf-8")
    rendered = seo.render_spa_html(index_html, path, "https://freevideo.example.com")
    assert '<meta name="robots" content="noindex, nofollow" />' in rendered
    assert '<meta name="googlebot" content="noindex, nofollow" />' in rendered
