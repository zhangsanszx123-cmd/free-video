# AGENTS.md

Read `docs/requirements.md` (scope, decisions, backlog) and `docs/design.md` (architecture, API, extension guide) before extending features; keep them updated when behavior changes.

## Layout
- `backend/app/` FastAPI app. `downloader.py` is a thin yt-dlp wrapper (do not fork yt-dlp), `jobs.py` in-memory job queue, `tasks.py` job bodies, `ai.py` DeepSeek via openai SDK, `subtitles.py` SRT utils.
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
