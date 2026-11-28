const DEFAULT_KEYWORDS = '视频文案提取, 在线视频文案提取, 视频文案在线提取, 视频转文字, 视频语音转文字, 视频字幕提取, 音频转文字, 视频转音频, MP3提取, 万能视频下载, 在线视频下载, 高清视频下载, AI视频总结, 视频思维导图, 抖音视频下载, 抖音文案提取, B站视频文案提取, B站字幕提取, B站视频下载, B站音频提取, YouTube视频下载, 小红书视频文案提取, 批量文案提取, 内容素材整理'

const DEFAULT_DESCRIPTION = 'FreeVideo在线视频文案提取与万能视频下载总结器，支持抖音、B站、YouTube等1800+平台高清视频下载、视频转文字、视频语音转文字、平台字幕提取、视频转音频MP3及AI视频总结。免安装网页即用，适合短视频创作者、学生与自媒体运营高效整理素材。'

const INDEX_ROBOTS = 'index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1'
const NOINDEX_ROBOTS = 'noindex, nofollow'

export const ROUTE_SEO = {
  home: {
    path: '/',
    title: 'FreeVideo - 在线视频文案提取与万能视频下载工具，支持AI视频总结与音频MP3提取',
    description: DEFAULT_DESCRIPTION,
    keywords: DEFAULT_KEYWORDS,
    noindex: false,
  },
  batch: {
    path: '/batch',
    title: '批量视频文案提取与素材打包下载 - 在线批量字幕转文字工具 - FreeVideo',
    description: '支持一次粘贴多条视频链接，在线批量提取视频文案、平台字幕与语音转文字，或批量下载高清视频与MP3音频并一键打包导出ZIP压缩包，自动去重、后台高效处理。',
    keywords: '批量文案提取, 批量视频文案提取, 批量字幕提取, 批量视频转文字, 批量视频下载, 批量提取MP3, 视频素材整理, FreeVideo',
    noindex: false,
  },
  ai: {
    path: '/ai',
    title: 'AI视频总结与双语字幕翻译 - 在线提取视频大纲与SRT字幕翻译 - FreeVideo',
    description: '在线AI视频总结与字幕翻译工具：粘贴视频链接即可快速提取视频字幕并生成核心要点总结，或将外语字幕一键翻译为中外双语SRT字幕文件，助力外语学习与内容二创。',
    keywords: 'AI视频总结, 视频AI摘要, 视频字幕翻译, 双语字幕生成, SRT字幕翻译, 在线视频总结, 视频文案总结, FreeVideo',
    noindex: false,
  },
  learn: {
    path: '/learn',
    title: 'AI视频学习工作台 - 视频文案转文字 · 章节大纲总结 · 思维导图 · AI追问 - FreeVideo',
    description: '集视频预览、逐字稿时间戳联动、多视角AI深度总结、交互式思维导图与AI自由追问于一体的视频学习工作台。无字幕视频支持语音识别生成文稿，大幅提升网课与长视频学习效率。',
    keywords: 'AI视频学习工作台, 视频思维导图, 视频大纲总结, 视频转文字笔记, 视频语音转文字, B站网课总结, YouTube视频总结, FreeVideo',
    noindex: false,
  },
  pricing: {
    path: '/pricing',
    title: '会员定价与语音识别额度说明 - FreeVideo Pro',
    description: '查看FreeVideo免费版、月卡与年卡会员权益对比：包含每月视频语音转文字识别时长、AI视频总结次数、每日AI追问额度、单次批量提取条数及开发者开放API调用权限。',
    keywords: 'FreeVideo会员定价, 视频转文字额度, 语音识别时长, 视频文案提取API价格, FreeVideo Pro',
    noindex: false,
  },
  apiDocs: {
    path: '/account/api/docs',
    title: '视频文案提取开放API接入文档 - 支持口播原文、SRT字幕与媒体地址提取 - FreeVideo',
    description: 'FreeVideo视频文案提取开放API（Open API v1）官方接入文档：支持通过REST接口异步提取抖音、B站、YouTube视频口播原文、带时间戳文本、SRT字幕及临时媒体地址，提供Python与Node.js示例。',
    keywords: '视频文案提取API, 视频转文字API, 抖音文案提取API, B站字幕提取API, SRT字幕接口, 小程序视频文案提取接口, FreeVideo Open API',
    noindex: false,
  },
  apiKeys: {
    path: '/account/api',
    title: 'API 密钥 - FreeVideo',
    description: '管理FreeVideo视频文案提取开放API密钥。',
    keywords: DEFAULT_KEYWORDS,
    noindex: true,
  },
  login: {
    path: '/login',
    title: '登录 - FreeVideo',
    description: '登录FreeVideo账号，使用在线视频文案提取、语音转文字、批量提取与AI视频总结功能。',
    keywords: DEFAULT_KEYWORDS,
    noindex: true,
  },
  register: {
    path: '/register',
    title: '注册账号 - FreeVideo',
    description: '注册FreeVideo账号，免费获取每月语音识别额度与AI视频总结次数。',
    keywords: DEFAULT_KEYWORDS,
    noindex: true,
  },
  verifyEmail: {
    path: '/verify-email',
    title: '验证邮箱 - FreeVideo',
    description: '验证FreeVideo注册邮箱。',
    keywords: DEFAULT_KEYWORDS,
    noindex: true,
  },
  forgotPassword: {
    path: '/forgot-password',
    title: '找回密码 - FreeVideo',
    description: '通过注册邮箱找回FreeVideo账号密码。',
    keywords: DEFAULT_KEYWORDS,
    noindex: true,
  },
  resetPassword: {
    path: '/reset-password',
    title: '设置新密码 - FreeVideo',
    description: '设置FreeVideo账号新密码。',
    keywords: DEFAULT_KEYWORDS,
    noindex: true,
  },
  account: {
    path: '/account',
    title: '个人中心 - FreeVideo',
    description: '管理FreeVideo账号资料、会员与语音识别额度。',
    keywords: DEFAULT_KEYWORDS,
    noindex: true,
  },
  history: {
    path: '/history',
    title: '任务记录 - FreeVideo',
    description: '查看和导出FreeVideo视频字幕提取与语音转文字历史记录。',
    keywords: DEFAULT_KEYWORDS,
    noindex: true,
  },
  payResult: {
    path: '/pay/result',
    title: '支付结果 - FreeVideo',
    description: '查看FreeVideo会员订单支付结果。',
    keywords: DEFAULT_KEYWORDS,
    noindex: true,
  },
  notFound: {
    path: null,
    title: '页面不存在 - FreeVideo',
    description: '访问的页面不存在，请返回FreeVideo首页继续使用视频下载与文案提取。',
    keywords: DEFAULT_KEYWORDS,
    noindex: true,
  },
  adminLogin: { path: '/admin/login', title: '后台登录 - FreeVideo', description: 'FreeVideo管理后台登录。', keywords: DEFAULT_KEYWORDS, noindex: true },
  adminUsers: { path: '/admin/users', title: '注册用户管理 - FreeVideo 后台', description: 'FreeVideo管理后台。', keywords: DEFAULT_KEYWORDS, noindex: true },
  adminStaff: { path: '/admin/staff', title: '后台账号管理 - FreeVideo 后台', description: 'FreeVideo管理后台。', keywords: DEFAULT_KEYWORDS, noindex: true },
  adminPricing: { path: '/admin/pricing', title: '会员价格管理 - FreeVideo 后台', description: 'FreeVideo管理后台。', keywords: DEFAULT_KEYWORDS, noindex: true },
  adminLimits: { path: '/admin/limits', title: '套餐额度管理 - FreeVideo 后台', description: 'FreeVideo管理后台。', keywords: DEFAULT_KEYWORDS, noindex: true },
  adminHistory: { path: '/admin/history', title: '提取记录 - FreeVideo 后台', description: 'FreeVideo管理后台。', keywords: DEFAULT_KEYWORDS, noindex: true },
  adminNotFound: { path: null, title: '后台页面不存在 - FreeVideo', description: 'FreeVideo管理后台。', keywords: DEFAULT_KEYWORDS, noindex: true },
}

export const titles = Object.fromEntries(Object.entries(ROUTE_SEO).map(([key, value]) => [key, value.title]))

function setMeta(attrName, attrValue, content) {
  if (typeof document === 'undefined' || !content) return
  let el = document.head.querySelector(`meta[${attrName}="${attrValue}"]`)
  if (!el) {
    el = document.createElement('meta')
    el.setAttribute(attrName, attrValue)
    document.head.appendChild(el)
  }
  el.setAttribute('content', content)
}

function setLink(rel, href, extra = {}) {
  if (typeof document === 'undefined' || !href) return
  let el = document.head.querySelector(`link[rel="${rel}"]`)
  if (!el) {
    el = document.createElement('link')
    el.setAttribute('rel', rel)
    document.head.appendChild(el)
  }
  el.setAttribute('href', href)
  for (const [k, v] of Object.entries(extra)) el.setAttribute(k, v)
}

export function applyRouteSeo(to) {
  const meta = ROUTE_SEO[to?.name] || ROUTE_SEO.home
  if (typeof document === 'undefined') return
  document.title = meta.title
  const origin = typeof window !== 'undefined' && window.location?.origin ? window.location.origin : ''
  const canonicalPath = meta.path ?? (to?.path || '/')
  const canonicalUrl = origin ? `${origin}${canonicalPath}` : canonicalPath
  const imageUrl = origin ? `${origin}/og-cover.svg` : '/og-cover.svg'
  const robots = meta.noindex ? NOINDEX_ROBOTS : INDEX_ROBOTS

  setMeta('name', 'description', meta.description)
  setMeta('name', 'keywords', meta.keywords)
  setMeta('name', 'robots', robots)
  setMeta('name', 'googlebot', meta.noindex ? NOINDEX_ROBOTS : 'index, follow')
  setLink('canonical', canonicalUrl)

  setMeta('property', 'og:title', meta.title)
  setMeta('property', 'og:description', meta.description)
  setMeta('property', 'og:type', 'website')
  setMeta('property', 'og:url', canonicalUrl)
  setMeta('property', 'og:image', imageUrl)
  setMeta('property', 'og:site_name', 'FreeVideo')
  setMeta('property', 'og:locale', 'zh_CN')

  setMeta('name', 'twitter:card', 'summary_large_image')
  setMeta('name', 'twitter:title', meta.title)
  setMeta('name', 'twitter:description', meta.description)
  setMeta('name', 'twitter:image', imageUrl)
}
