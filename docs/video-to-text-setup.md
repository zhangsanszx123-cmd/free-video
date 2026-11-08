# 视频转文字：只需一个 API Key

2026-11-08：默认已切换 `fun-asr-flash-2026-06-15`，超过 5 分钟自动分段并发识别。只需现有百炼北京地域 Key，无需 OSS 或 AccessKey。

## 配置与启动

在 [backend/.env](../backend/.env) 填入 `DASHSCOPE_API_KEY`。本机已填写并保留，无需重填。不要把凭证发到聊天或提交 Git；DeepSeek Key 不能代替百炼 Key。

```dotenv
ASR_PROVIDER=fun-asr-flash
ASR_MODEL=fun-asr-flash-2026-06-15
ASR_PRICE_PER_SECOND=0.00022
ASR_TIMEOUT=180
ASR_SEGMENT_WORKERS=2
```

其余参数见 [.env.example](../backend/.env.example)。旧配置若显式指定 Paraformer，需同时更新模型、单价和超时，并重启后端。

```powershell
backend/.venv/Scripts/python -m pip install -r backend/requirements.txt
npm --prefix frontend run build
backend/.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --no-proxy-headers
```

打开 `http://127.0.0.1:8000/`。FFmpeg/ffprobe 需在 PATH 或配置完整路径；本机已配置。健康接口的 `asr_enabled` / `asr_ready` 表示配置及账本准备完成，模型权限需真实调用验证。

## 使用与长视频

1. 粘贴链接并解析。有平台字幕时直接提取，不调用 ASR。
2. 无可用字幕时点击“音频转文字”，后端获取视频真实音轨，通过 HTTPS/Base64 发给百炼。
3. 不超过 5 分钟使用单次 MP3 请求；超过 5 分钟先解码为单声道 16kHz PCM，按连续 280 秒采样范围切为 WAV，默认每条视频并发两段。
4. 按原顺序合并结果，将词时间戳加上分段在原视频的采样偏移，生成原文及 TXT/SRT。界面显示已完成段数。
5. 同一会话复制、导出和重复点击复用结果，不重新收费。

分段无音频采样缺口、无重叠，不自动翻译或润色。固定切分边界附近的词可能影响准确性，需人工验收。整条音轨仍最多 60 分钟，压缩 MP3 上限 100MB。单次样本速度不代表所有视频的处理时间。

## 费用与资源

- 北京预算估算单价 0.00022 元/音频秒，约 0.792 元/小时，以实际账单为准，不抵扣免费额度。
- 日预算默认 10 元，任务并发/等待为 2/20；每条视频分段并发默认 2，可配置 1–4。默认最多 4 个云请求同时进行。
- 收费请求前准备所有分段，按各段向上取整秒数总和预占。每段累计 `usage.duration` 取最大值，逐段向上取整后结算；缺失用量则按本地段时长保守结算。
- `ASR_TIMEOUT=180` 是每个请求的超时，不是整条长视频总超时。
- 结果从任务结束起保留 30 分钟；源文件、MP3、PCM、分段 WAV 在任务终态清理。最长一小时 PCM 与 WAV 各约 115.2MB，另需压缩源磁盘空间。

## 失败与重启

明确拒绝的段释放额度，已完成段按用量结算。部分失败不返回完整成功，也不允许重复提交整条视频导致已完成段再次收费。

提交后断线、结果不完整或重启时保留未决预占，不自动重发音轨；HTTP 请求标识不能用文件任务接口查询。管理员需依据云控制台核对，不能通过删除账本重置预算。关闭页面只停止前端查询，后端继续；重启不恢复页面任务正文。

账本损坏时暂停新的收费请求；未决预占跨日保留。账本不存正文、Key 或音频 Base64。

## 部署与扩展

仅支持单进程、单 worker；`ASR_DIR` 放在下载和静态目录外并持久化。生产需 HTTPS、稳定的至少 32 字符会话密钥、Secure Cookie、精确来源白名单和可信代理配置。匿名会话保护转写文件，不替代账号计费系统。

[asr.py](../backend/app/asr.py) 注册三种适配器：默认 [asr_flash.py](../backend/app/asr_flash.py) 直接 HTTP、可选 [asr_realtime.py](../backend/app/asr_realtime.py) 实时 WebSocket、旧 Paraformer 文件提交/查询。只有旧文件适配器需要私有 OSS，不自动回退慢速接口。

验收覆盖已有字幕、普通话、中英混合、静音、背景音乐、长视频边界及时间轴。测试和耗时见[快速验证](./video-to-text-fast-validation.md)与[测试记录](./video-to-text-verification.md)。
