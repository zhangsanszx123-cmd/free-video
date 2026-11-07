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
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
