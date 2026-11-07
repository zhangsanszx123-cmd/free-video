export const platforms = [
  { name: 'B站', color: '#fb7299' },
  { name: 'YouTube', color: '#ff0033' },
  { name: 'TikTok', color: '#111827' },
  { name: 'Twitter/X', color: '#0f172a' },
  { name: '微博', color: '#e6162d' },
  { name: '小红书', color: '#ff2442' },
  { name: 'Vimeo', color: '#1ab7ea' },
  { name: 'Instagram', color: '#d62976' },
  { name: 'Twitch', color: '#9146ff' },
  { name: 'Facebook', color: '#1877f2' },
  { name: 'SoundCloud', color: '#ff5500' },
  { name: 'Dailymotion', color: '#0066dc' },
]

export const platformTable = [
  { name: 'B站', video: '最高 1080P', audio: true, sub: true, note: '支持 b23.tv 短链' },
  { name: 'YouTube', video: '最高 8K', audio: true, sub: true, note: '服务器需可访问海外网络' },
  { name: 'TikTok', video: '原画', audio: true, sub: false, note: '' },
  { name: 'Twitter/X', video: '原画', audio: true, sub: false, note: '仅公开推文' },
  { name: '微博', video: '最高 1080P', audio: true, sub: false, note: '' },
  { name: 'Vimeo', video: '最高 4K', audio: true, sub: true, note: '' },
  { name: '小红书 / 抖音 等', video: '部分支持', audio: true, sub: false, note: '需登录的内容暂不支持' },
]

export const features = [
  { icon: 'globe', title: '1800+ 平台通吃', desc: '基于 GitHub 15 万 Star 的 yt-dlp，国内外主流视频站、社交平台、播客一个网址全搞定。', pro: false },
  { icon: 'crown', title: '4K / 8K 原画质', desc: '自动挑选最高码率的音视频流并无损合并为 MP4，画质比平台自带下载更高。', pro: true },
  { icon: 'music', title: '一键提取 MP3', desc: '视频秒变 192kbps 高品质 MP3，课程、播客、BGM 随身听。', pro: false },
  { icon: 'layers', title: '批量下载打包', desc: '一次粘贴 20 条链接，自动去重、后台逐条下载、打包成 ZIP 一次带走。', pro: true },
  { icon: 'sparkles', title: 'AI 视频总结', desc: '1 小时的视频 30 秒读完：核心要点、时间轴大纲、金句摘录自动生成。', pro: true },
  { icon: 'translate', title: 'AI 双语字幕', desc: '外语字幕一键翻译为中英双语 SRT，学英语、看海外课程利器。', pro: true },
]

export const steps = [
  { title: '复制分享链接', desc: '在 App 或网页中点击「分享 → 复制链接」，带文字的分享口令也可以直接粘贴。' },
  { title: '粘贴并解析', desc: '粘贴到上方输入框，点击「立即解析」，3~10 秒获取封面、标题与全部清晰度。' },
  { title: '选择清晰度下载', desc: '选择 MP4 清晰度、MP3 或字幕，服务器高速处理后保存到手机或电脑。' },
]

export const scenarios = [
  { who: '学生党', text: '把网课、公开课下载到本地离线复习，再用 AI 总结快速整理笔记。' },
  { who: '自媒体创作者', text: '收集优质素材做二次创作参考，MP3 提取 BGM，字幕直接做文案拆解。' },
  { who: '外语学习者', text: 'YouTube 视频 + 中英双语字幕，配合播放器逐句精听。' },
  { who: '研究人员', text: '批量下载公开视频建立语料库，字幕文本便于检索与分析。' },
]

export const faqs = [
  { q: '支持哪些平台？手机可以用吗？', a: '底层使用开源项目 yt-dlp，支持 B站、YouTube、TikTok、X、微博、Vimeo 等 1800+ 站点。网站针对手机做了适配，手机浏览器打开即可使用，无需安装 App。' },
  { q: '为什么有些链接解析失败？', a: '常见原因：内容需要登录或付费（本站不使用任何账号 Cookie，只支持公开内容）、链接已失效、平台有地区限制，或平台接口变动。可稍后重试或换一个链接。' },
  { q: '下载的视频有水印吗？画质会压缩吗？', a: '我们直接获取平台的原始音视频流并无损合并，不做二次压缩；是否带水印取决于平台源文件本身。' },
  { q: '下载的文件会保存在服务器吗？', a: '不会长期保存。文件仅用于中转，30 分钟后自动删除，我们也不记录你的下载历史。' },
  { q: 'AI 总结是怎么实现的？', a: '读取视频字幕（平台字幕或自动字幕）后交给大模型（DeepSeek）生成要点与大纲。没有字幕的视频暂不支持 AI 总结。' },
  { q: '可以商用吗？有版权问题吗？', a: '本站仅供个人学习研究使用。请尊重原作者版权，未经授权不得用于商业用途或二次传播。频繁下载可能触发平台风控，请合理使用。' },
]
