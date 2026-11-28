"""Technical & on-page SEO: robots.txt, sitemap.xml, and route-aware SSR meta injection."""
from html import escape
import re
from urllib.parse import urlsplit

from fastapi import Request

from . import config

DEFAULT_KEYWORDS = (
    "视频文案提取, 在线视频文案提取, 视频文案在线提取, 视频转文字, 视频语音转文字, 视频字幕提取, "
    "音频转文字, 视频转音频, MP3提取, 万能视频下载, 在线视频下载, 高清视频下载, AI视频总结, "
    "视频思维导图, 抖音视频下载, 抖音文案提取, B站视频文案提取, B站字幕提取, B站视频下载, "
    "B站音频提取, YouTube视频下载, 小红书视频文案提取, 批量文案提取, 内容素材整理"
)

DEFAULT_DESCRIPTION = (
    "FreeVideo在线视频文案提取与万能视频下载总结器，支持抖音、B站、YouTube等1800+平台高清视频下载、"
    "视频转文字、视频语音转文字、平台字幕提取、视频转音频MP3及AI视频总结。免安装网页即用，"
    "适合短视频创作者、学生与自媒体运营高效整理素材。"
)

INDEX_ROBOTS = "index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1"
NOINDEX_ROBOTS = "noindex, nofollow"

PUBLIC_ROUTES = {
    "/": {
        "title": "FreeVideo - 在线视频文案提取与万能视频下载工具，支持AI视频总结与音频MP3提取",
        "description": DEFAULT_DESCRIPTION,
        "keywords": DEFAULT_KEYWORDS,
        "changefreq": "daily",
        "priority": "1.0",
    },
    "/batch": {
        "title": "批量视频文案提取与素材打包下载 - 在线批量字幕转文字工具 - FreeVideo",
        "description": "支持一次粘贴多条视频链接，在线批量提取视频文案、平台字幕与语音转文字，或批量下载高清视频与MP3音频并一键打包导出ZIP压缩包，自动去重、后台高效处理。",
        "keywords": "批量文案提取, 批量视频文案提取, 批量字幕提取, 批量视频转文字, 批量视频下载, 批量提取MP3, 视频素材整理, FreeVideo",
        "changefreq": "weekly",
        "priority": "0.9",
    },
    "/ai": {
        "title": "AI视频总结与双语字幕翻译 - 在线提取视频大纲与SRT字幕翻译 - FreeVideo",
        "description": "在线AI视频总结与字幕翻译工具：粘贴视频链接即可快速提取视频字幕并生成核心要点总结，或将外语字幕一键翻译为中外双语SRT字幕文件，助力外语学习与内容二创。",
        "keywords": "AI视频总结, 视频AI摘要, 视频字幕翻译, 双语字幕生成, SRT字幕翻译, 在线视频总结, 视频文案总结, FreeVideo",
        "changefreq": "weekly",
        "priority": "0.9",
    },
    "/learn": {
        "title": "AI视频学习工作台 - 视频文案转文字 · 章节大纲总结 · 思维导图 · AI追问 - FreeVideo",
        "description": "集视频预览、逐字稿时间戳联动、多视角AI深度总结、交互式思维导图与AI自由追问于一体的视频学习工作台。无字幕视频支持语音识别生成文稿，大幅提升网课与长视频学习效率。",
        "keywords": "AI视频学习工作台, 视频思维导图, 视频大纲总结, 视频转文字笔记, 视频语音转文字, B站网课总结, YouTube视频总结, FreeVideo",
        "changefreq": "weekly",
        "priority": "0.9",
    },
    "/pricing": {
        "title": "会员定价与语音识别额度说明 - FreeVideo Pro",
        "description": "查看FreeVideo免费版、月卡与年卡会员权益对比：包含每月视频语音转文字识别时长、AI视频总结次数、每日AI追问额度、单次批量提取条数及开发者开放API调用权限。",
        "keywords": "FreeVideo会员定价, 视频转文字额度, 语音识别时长, 视频文案提取API价格, FreeVideo Pro",
        "changefreq": "weekly",
        "priority": "0.8",
    },
    "/account/api/docs": {
        "title": "视频文案提取开放API接入文档 - 支持口播原文、SRT字幕与媒体地址提取 - FreeVideo",
        "description": "FreeVideo视频文案提取开放API（Open API v1）官方接入文档：支持通过REST接口异步提取抖音、B站、YouTube视频口播原文、带时间戳文本、SRT字幕及临时媒体地址，提供Python与Node.js示例。",
        "keywords": "视频文案提取API, 视频转文字API, 抖音文案提取API, B站字幕提取API, SRT字幕接口, 小程序视频文案提取接口, FreeVideo Open API",
        "changefreq": "weekly",
        "priority": "0.8",
    },
}

PRIVATE_ROUTES = {
    "/account/api": ("API 密钥 - FreeVideo", "管理FreeVideo视频文案提取开放API密钥。"),
    "/login": ("登录 - FreeVideo", "登录FreeVideo账号，使用在线视频文案提取、语音转文字、批量提取与AI视频总结功能。"),
    "/register": ("注册账号 - FreeVideo", "注册FreeVideo账号，免费获取每月语音识别额度与AI视频总结次数。"),
    "/verify-email": ("验证邮箱 - FreeVideo", "验证FreeVideo注册邮箱。"),
    "/forgot-password": ("找回密码 - FreeVideo", "通过注册邮箱找回FreeVideo账号密码。"),
    "/reset-password": ("设置新密码 - FreeVideo", "设置FreeVideo账号新密码。"),
    "/account": ("个人中心 - FreeVideo", "管理FreeVideo账号资料、会员与语音识别额度。"),
    "/history": ("任务记录 - FreeVideo", "查看和导出FreeVideo视频字幕提取与语音转文字历史记录。"),
    "/pay/result": ("支付结果 - FreeVideo", "查看FreeVideo会员订单支付结果。"),
    "/admin": ("注册用户管理 - FreeVideo 后台", "FreeVideo管理后台。"),
    "/admin/login": ("后台登录 - FreeVideo", "FreeVideo管理后台登录。"),
    "/admin/users": ("注册用户管理 - FreeVideo 后台", "FreeVideo管理后台。"),
    "/admin/staff": ("后台账号管理 - FreeVideo 后台", "FreeVideo管理后台。"),
    "/admin/pricing": ("会员价格管理 - FreeVideo 后台", "FreeVideo管理后台。"),
    "/admin/limits": ("套餐额度管理 - FreeVideo 后台", "FreeVideo管理后台。"),
    "/admin/history": ("提取记录 - FreeVideo 后台", "FreeVideo管理后台。"),
}


def resolve_base_url(request: Request | None = None) -> str:
    configured = (config.PUBLIC_BASE_URL or "").strip().rstrip("/")
    parsed = urlsplit(configured)
    if configured and parsed.hostname not in (None, "127.0.0.1", "localhost", "testserver"):
        return configured
    if request is not None:
        req_base = str(request.base_url).rstrip("/")
        if req_base:
            return req_base
    return configured or "http://127.0.0.1:8000"


def render_robots_txt(base_url: str) -> str:
    base = base_url.rstrip("/")
    lines = [
        "User-agent: *",
        "Allow: /",
        "Allow: /batch",
        "Allow: /ai",
        "Allow: /learn",
        "Allow: /pricing",
        "Allow: /account/api/docs",
        "Disallow: /api/",
        "Disallow: /admin",
        "Disallow: /account",
        "Disallow: /history",
        "Disallow: /pay/",
        "Disallow: /login",
        "Disallow: /register",
        "Disallow: /verify-email",
        "Disallow: /forgot-password",
        "Disallow: /reset-password",
        "",
        f"Sitemap: {base}/sitemap.xml",
        "",
    ]
    return "\n".join(lines)


def render_sitemap_xml(base_url: str) -> str:
    base = base_url.rstrip("/")
    items = []
    for path, meta in PUBLIC_ROUTES.items():
        loc = escape(f"{base}/" if path == "/" else f"{base}{path}")
        items.append(
            "  <url>\n"
            f"    <loc>{loc}</loc>\n"
            f"    <changefreq>{meta['changefreq']}</changefreq>\n"
            f"    <priority>{meta['priority']}</priority>\n"
            "  </url>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(items)
        + "\n</urlset>\n"
    )


def _normalize_path(raw_path: str) -> str:
    clean = "/" + (raw_path or "").strip("/")
    return "/" if clean == "/" else clean


def _replace_meta(html: str, attr_name: str, attr_val: str, content: str) -> str:
    escaped = escape(content, quote=True)
    pattern = rf'(<meta\s+{attr_name}="{re.escape(attr_val)}"\s+content=")[^"]*(")'
    return re.sub(pattern, rf"\g<1>{escaped}\g<2>", html, count=1)


def render_spa_html(html_template: str, raw_path: str, base_url: str) -> str:
    base = base_url.rstrip("/")
    path = _normalize_path(raw_path)

    if path in PUBLIC_ROUTES:
        meta = PUBLIC_ROUTES[path]
        title = meta["title"]
        description = meta["description"]
        keywords = meta["keywords"]
        noindex = False
        canonical_url = f"{base}/" if path == "/" else f"{base}{path}"
    elif path in PRIVATE_ROUTES or path.startswith("/admin/"):
        title, description = PRIVATE_ROUTES.get(path, ("后台页面不存在 - FreeVideo", "FreeVideo管理后台。"))
        keywords = DEFAULT_KEYWORDS
        noindex = True
        canonical_url = f"{base}{path}"
    else:
        title = "页面不存在 - FreeVideo"
        description = "访问的页面不存在，请返回FreeVideo首页继续使用视频下载与文案提取。"
        keywords = DEFAULT_KEYWORDS
        noindex = True
        canonical_url = f"{base}{path}"

    robots = NOINDEX_ROBOTS if noindex else INDEX_ROBOTS
    googlebot = NOINDEX_ROBOTS if noindex else "index, follow"
    image_url = f"{base}/og-cover.svg"

    html = re.sub(r"<title>.*?</title>", f"<title>{escape(title)}</title>", html_template, count=1, flags=re.DOTALL)
    html = _replace_meta(html, "name", "description", description)
    html = _replace_meta(html, "name", "keywords", keywords)
    html = _replace_meta(html, "name", "robots", robots)
    html = _replace_meta(html, "name", "googlebot", googlebot)
    html = _replace_meta(html, "property", "og:title", title)
    html = _replace_meta(html, "property", "og:description", description)
    html = _replace_meta(html, "property", "og:url", canonical_url)
    html = _replace_meta(html, "property", "og:image", image_url)
    html = _replace_meta(html, "name", "twitter:title", title)
    html = _replace_meta(html, "name", "twitter:description", description)
    html = _replace_meta(html, "name", "twitter:image", image_url)
    html = re.sub(
        r'(<link\s+rel="canonical"\s+href=")[^"]*(")',
        rf"\g<1>{escape(canonical_url, quote=True)}\g<2>",
        html,
        count=1,
    )
    html = html.replace('"url":"/"', f'"url":"{escape(base, quote=True)}/"')
    html = html.replace('"logo":"/logo.svg"', f'"logo":"{escape(base, quote=True)}/logo.svg"')
    html = html.replace(
        '"urlTemplate":"/?url={search_term_string}"',
        f'"urlTemplate":"{escape(base, quote=True)}/?url={{search_term_string}}"',
    )
    return html
