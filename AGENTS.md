# AGENTS.md

Read `docs/requirements.md` (scope, decisions, backlog) and `docs/design.md` (architecture, API, extension guide) before extending features; keep them updated when behavior changes.

## Layout
- `backend/app/` FastAPI app. `downloader.py` is the entry point + thin yt-dlp wrapper (do not fork yt-dlp); it routes Douyin URLs to `douyin.py` (thin wrapper over Johnserf-Seed/f2 with an auto-generated guest cookie). `errors.py` VideoError, `jobs.py` in-memory job queue, `tasks.py` job bodies, `ai.py` DeepSeek via openai SDK, `subtitles.py` SRT utils.
- `frontend/` Vue 3 + Vite + Tailwind v4. Design tokens in `src/style.css` (hero-bg, text-grad, btn-primary, btn-gold, glass-card, input-shell, pro-badge), copy/data in `src/data.js`.

## Commands (Windows, run from repo root)
- Backend tests: `cd backend && .venv/Scripts/python -m pytest` (network smoke: `-m network`)
- Frontend build: `cd frontend && npm run build`
- Run: `cd backend && .venv/Scripts/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000` (serves `frontend/dist` too)
- Dev: `npm run dev` in frontend (proxies `/api` to :8000)

## Notes
- Set `PYTHONIOENCODING=utf-8` when printing Chinese titles in the console.
- `C:\Users\yangx\AppData\Local\Temp\struct.py` shadows stdlib for scripts run from Temp; use `python -P`.
- ffmpeg is required (installed via winget).
- Pin new npm/pip deps to versions published >= 7 days ago.
- f2 is installed from a pinned GitHub commit zip via codeload (git clone to github.com fails on this network); PyPI f2 0.0.1.7 is outdated (403 from Douyin).
- `pip install` must not run with cwd = `%TEMP%` (the stray `struct.py` breaks build subprocesses).
