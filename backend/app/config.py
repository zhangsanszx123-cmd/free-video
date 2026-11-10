import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR") or BASE_DIR / "downloads")
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"

YTDLP_PROXY = os.getenv("YTDLP_PROXY") or None
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "3"))
FILE_TTL_SECONDS = int(os.getenv("FILE_TTL_MINUTES", "30")) * 60
MAX_FILESIZE_MB = int(os.getenv("MAX_FILESIZE_MB", "1024"))
MAX_BATCH = int(os.getenv("MAX_BATCH", "20"))

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY") or None
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
_raw_deepseek_model = (os.getenv("DEEPSEEK_MODEL") or "deepseek-flash").strip()
DEEPSEEK_MODEL = "deepseek-flash" if _raw_deepseek_model == "deepseek-chat" else _raw_deepseek_model

# Cloud ASR is independent of DeepSeek; keep results/ledger outside DOWNLOAD_DIR.
ASR_DIR = Path(os.getenv("ASR_DIR") or BASE_DIR / "transcriptions")
ASR_PROVIDER = os.getenv("ASR_PROVIDER", "fun-asr-flash")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY") or None
DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/api/v1").rstrip("/")
ASR_MODEL = os.getenv("ASR_MODEL", {"fun-asr-flash": "fun-asr-flash-2026-06-15",
                                  "paraformer-realtime": "paraformer-realtime-v2"}.get(ASR_PROVIDER, "paraformer-v2"))
DASHSCOPE_WS_URL = os.getenv("DASHSCOPE_WS_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/inference")
OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "https://oss-cn-beijing.aliyuncs.com")
OSS_REGION = os.getenv("OSS_REGION", "cn-beijing")
OSS_BUCKET = os.getenv("OSS_BUCKET") or None
OSS_ACCESS_KEY_ID = os.getenv("OSS_ACCESS_KEY_ID") or None
OSS_ACCESS_KEY_SECRET = os.getenv("OSS_ACCESS_KEY_SECRET") or None
OSS_SECURITY_TOKEN = os.getenv("OSS_SECURITY_TOKEN") or None
OSS_PREFIX = "freevideo-asr/"
ASR_WORKERS = int(os.getenv("ASR_WORKERS", "2"))
ASR_MAX_QUEUE = int(os.getenv("ASR_MAX_QUEUE", "20"))
ASR_MAX_DURATION = int(os.getenv("ASR_MAX_DURATION", "3600"))
ASR_MAX_FILESIZE_MB = int(os.getenv("ASR_MAX_FILESIZE_MB", "100"))
ASR_DAILY_BUDGET = os.getenv("ASR_DAILY_BUDGET", "10")
ASR_PRICE_PER_SECOND = os.getenv("ASR_PRICE_PER_SECOND", {"fun-asr-flash": "0.00022",
                                                        "paraformer-realtime": "0.00024"}.get(ASR_PROVIDER, "0.00008"))
ASR_TIMEOUT = int(os.getenv("ASR_TIMEOUT", "180" if ASR_PROVIDER == "fun-asr-flash" else
                            "3900" if ASR_PROVIDER == "paraformer-realtime" else "3600"))
ASR_SEGMENT_WORKERS = int(os.getenv("ASR_SEGMENT_WORKERS", "2"))
ASR_POLL_SECONDS = float(os.getenv("ASR_POLL_SECONDS", "3"))
OSS_URL_TTL = int(os.getenv("OSS_URL_TTL", "7200"))
ASR_RATE_LIMIT = int(os.getenv("ASR_RATE_LIMIT", "10"))
SESSION_SECRET = os.getenv("SESSION_SECRET") or None
SESSION_SECURE = os.getenv("SESSION_SECURE", "false").lower() == "true"
ALLOWED_ORIGINS = [s.strip().rstrip("/") for s in os.getenv("ALLOWED_ORIGINS", "").split(",") if s.strip()]
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "freevideo")
MYSQL_TEST_DATABASE = os.getenv("MYSQL_TEST_DATABASE") or None
AUTH_SESSION_DAYS = int(os.getenv("AUTH_SESSION_DAYS", "7"))
AUTH_REGISTER_RATE_LIMIT = int(os.getenv("AUTH_REGISTER_RATE_LIMIT", "5"))  # per IP per 10 minutes
AUTH_LOGIN_RATE_LIMIT = int(os.getenv("AUTH_LOGIN_RATE_LIMIT", "10"))  # per IP per minute
FFMPEG_BINARY = os.getenv("FFMPEG_BINARY", "ffmpeg")
FFPROBE_BINARY = os.getenv("FFPROBE_BINARY", "ffprobe")
