# AI 视频精读与助学系统总结文档（v1.3）

> 状态：已完成竞品调研、方案设计、全栈开发、UI 布局迭代与测试验收  
> 关联文档：[需求文档](./requirements.md) ｜ [架构设计](./design.md)

---

## 1. 背景与竞品调研总结

针对用户“提升长视频学习效率、快速掌握视频大纲与核心知识要点”的核心诉求，对标行业标杆 **BibiGPT（bibigpt.co）** 与 **NoteGPT（notegpt.io/cn/bilibili-summarizer）** 进行了深度调研，提炼出四大核心能力差距并完成补齐：

| 维度 | 扩展前现状（`ai.py` / `AiTools.vue`） | 竞品核心体验（BibiGPT / NoteGPT） | 本期落地能力（v1.3） |
|---|---|---|---|
| **入口与布局** | 隐藏在二级页 `/ai` 或埋在结果卡片第 5 层底部（需滚 3～4 屏） | 首屏高对比双模态入口 + 左右同屏视频对照工作台 | **首页输入框左上角高对比渐变双选项卡 + 双提交按钮 + 结果卡片双视图分流 + `/learn` 独立分栏工作台** |
| **结构化总结与时间戳** | 仅输出纯文本摘要，无时间戳，无法跳播 | 多学习视角切换 + 带 `[MM:SS]` 章节时间轴点击空降视频 | **三视角切换（通用精读 / 课堂笔记 / 深度拆解）+ `[MM:SS]` 交互胶囊同屏联动左侧播放器跳播** |
| **长视频支持** | `text[:15000]` 硬截断，超过约 25 分钟后半段内容完全丢失 | 支持 1～3 小时公开课/长访谈全片覆盖 | **20s 紧凑时间轴压缩 + 6 万字单次直通 + 6～18 万字 Map-Reduce 分段提炼汇总** |
| **可视化与深度消化** | 无思维导图、无上下文追问、无笔记导出 | 交互式思维导图（缩放/折叠/导出图片）+ AI 追问 + Markdown 笔记导出 | **纯 Vue 3 + SVG 零依赖交互式思维导图（支持 2x PNG / SVG / MD 导出）+ 推荐问题气泡与多轮流式追问** |
| **无字幕视频衔接** | 报错中断（`NoSubtitles`），与已实现的 F8 语音转写割裂 | 自动检测字幕，无字幕时衔接语音转文字并总结 | **三级文稿复用 + 无字幕 `need_asr` 显式确认后调用百炼 `fun-asr-flash` 转写（零隐式扣费，单视频转写一次全功能共享）** |

---

## 2. 交互布局演进与最终设计

围绕首页「AI 视频总结入口与结果展示如何更显眼、比例更协调」进行了多轮原型对比与迭代，最终确立以下黄金布局（位于 [Home.vue](../frontend/src/pages/Home.vue) 与 [ResultCard.vue](../frontend/src/components/ResultCard.vue)）：

1. **上窄聚拢（`896px` / `max-w-4xl`）+ 下宽舒展（`1152px` / `max-w-6xl`）漏斗比例**：
   - 首屏输入框保持 `896px` 居中聚拢，与上方副标题和下方平台标签视觉重心自然对齐；
   - 解析出结果后，下方结果卡片展开至 `1152px`，为双栏视频联动与精读内容提供充足呼吸感。
2. **URL 输入框左上角高对比度品牌渐变双选项卡 + 右侧双动作按钮**：
   - 输入框左上角集成 **`[📥 素材与文案下载]`** 与 **`[✨ AI 视频总结 PRO]`** 两个选项卡（选中态采用蓝紫/紫罗兰实心渐变 + 发光弥散阴影，对比鲜明）；
   - 输入框右侧并列 **`⚡ 立即解析`**（进入下载视图）与 **`✨ AI 总结`**（一键直达 AI 视频总结视图并自动触发流式总结）。
3. **提取结果卡片双视图无损分流（`v-show` 保活）**：
   - 顶栏标题旁实时显示 `当前：素材与文案下载` / `当前：AI 视频总结` 状态徽标，并提供 `↗ 全屏工作台` 快捷入口；
   - **视图 1（素材与文案下载）**：完整保留标题与简介、视频下载、音频提取、视频文案（后台自动加载字幕并实时共享给 AI 视图）、图片批量下载；
   - **视图 2（AI 视频总结）**：桌面端采用 **左侧「🎬 同屏联动预览」吸顶小窗（含跳播状态徽标、`⬇ 顺手下载视频`、`更多素材` 按钮）+ 右侧全功能 `AiLearningPanel`** 双栏布局，点击右侧任意 `[MM:SS]` 时间戳胶囊即可让左侧视频小窗立即跳播。

---

## 3. 新增与调整模块清单

### 3.1 后端模块（`backend/`）
- **[NEW] [backend/app/learning_text.py](../backend/app/learning_text.py)**：
  - `parse_ts` / `fmt_ts`：兼容 `MM:SS` 与 `H:MM:SS` 解析与格式化；
  - `compact_from_cues` / `compact_from_timed_text`：按 20 秒窗口合并细碎字幕行，零文本丢失降低约 75% 时间戳字符开销；
  - `split_chunks` / `sample_evenly` / `relevant_excerpt`：长文稿按行切块、均匀采样与追问关键词召回。
- **[NEW] [backend/app/ai_learning.py](../backend/app/ai_learning.py)**：
  - 默认使用 `AI_LEARNING_MODEL=deepseek-flash`，并通过 `extra_body={"thinking": {"type": "disabled"}}` 默认关闭推理思考模式以保障流式首字响应速度；
  - `summarize_events` / `summarize_stream`：支持 `general`（通用精读）、`study`（课堂笔记）、`deep`（深度拆解）三模式，`<=60,000` 字直通、`60,000～180,000` 字 Map-Reduce 分段提炼汇总；
  - `generate_mindmap`：输出 Markdown 树（`# / ## / ### / -`），优先基于已生成总结极速提炼；
  - `chat_stream`：严格基于原片文稿片段进行多轮流式回答并标注 `[MM:SS]`。
- **[NEW] [backend/app/ai_learning_api.py](../backend/app/ai_learning_api.py)**：
  - 基于 FastAPI 0.162 原生 `fastapi.sse`（`EventSourceResponse` + `ServerSentEvent`）提供 `POST /api/learn/summary`、`POST /api/learn/mindmap`、`POST /api/learn/chat`；
  - 集成同 IP 滑动窗口限流、签名匿名会话（`transcription_auth`）归属校验，以及无字幕 `need_asr` 零隐式扣费守卫。
- **[NEW] [backend/tests/test_learning.py](../backend/tests/test_learning.py)**：新增 8 组多断言单元测试，全量测试达 **125 passed**。
- **[MODIFY] [backend/app/main.py](../backend/app/main.py)**：在 `FRONTEND_DIST` 静态兜底路由之前挂载 `learning_router`。

### 3.2 前端模块（`frontend/`）
- **[NEW] [frontend/src/learning/learnApi.js](../frontend/src/learning/learnApi.js)**：支持 `AbortSignal` 的 POST SSE 流式解析器、平台带时间参数链接生成、推荐追问解析。
- **[NEW] [frontend/src/learning/markdown.js](../frontend/src/learning/markdown.js)**：独立 `new Marked({ gfm: true, breaks: true })` 实例 + `DOMPurify.sanitize` 消毒 + `DOMParser` 安全文本节点 `[MM:SS]` 胶囊转换。
- **[NEW] [frontend/src/learning/MindMapView.vue](../frontend/src/learning/MindMapView.vue)**：纯 Vue 3 + SVG 自研交互式思维导图，支持平移、缩放、折叠展开、时间戳跳播、导出 2x PNG / SVG / MD。
- **[NEW] [frontend/src/learning/AiLearningPanel.vue](../frontend/src/learning/AiLearningPanel.vue)**：三合一 AI 视频精读面板（智能总结 / 思维导图 / AI 追问 + 无字幕确认转写卡片 + `autoRunTrigger` 自动触发支持）。
- **[NEW] [frontend/src/learning/LearnTranscript.vue](../frontend/src/learning/LearnTranscript.vue)** & **[frontend/src/learning/pages/LearnWorkbench.vue](../frontend/src/learning/pages/LearnWorkbench.vue)**：`/learn` 独立左右分栏沉浸式学习工作台。
- **[MODIFY] [frontend/src/pages/Home.vue](../frontend/src/pages/Home.vue)** & **[frontend/src/components/ResultCard.vue](../frontend/src/components/ResultCard.vue)**：实现左上角高对比渐变双选项卡、右侧「立即解析 / AI 总结」双按钮及提取结果双视图分流。
- **[MODIFY] [frontend/src/router.js](../frontend/src/router.js)** & **[frontend/src/components/NavBar.vue](../frontend/src/components/NavBar.vue)**：注册 `/learn` 路由与导航栏入口。

---

## 4. 关键技术经验沉淀

1. **DeepSeek 模型演进与流式延迟优化**：
   - DeepSeek 官方 API 中旧模型名 `deepseek-chat` 已下线，现使用 `deepseek-flash`（兼顾高吞吐与低成本）；
   - `deepseek-flash` 默认开启思维链（`reasoning_content`），会导致 SSE 首字等待数秒。通过传入 `extra_body={"thinking": {"type": "disabled"}}` 关闭思考模式后，流式首字响应降至毫秒级。
2. **FastAPI 0.162 原生 `fastapi.sse` 用法约束**：
   - `response_class=EventSourceResponse` 要求路由函数本身直接是 `async def ... yield ServerSentEvent(...)` 异步生成器，不可在普通 `async def` 中 `return EventSourceResponse(gen())`；
   - 需要在开启流之前返回 `503`（未配置 API Key）或 `429`（触发限流）HTTP 状态码时，应通过 `Depends(...)` 依赖项在进入生成器前抛出 `HTTPException`。
3. **Windows 本地开发端口阴影排查**：
   - 在 Windows 上若存在旧进程绑定 `127.0.0.1:8000`，新进程绑定 `0.0.0.0:8000` 不会报错，但浏览器访问 `localhost:8000` 会优先命中旧进程内存中的路由表（导致新接口报 `405 Method Not Allowed`）。重启服务前需确保清理同端口残留进程。
