# AGENTS.md

Read `docs/requirements.md` (scope, decisions, backlog) and `docs/design.md` (architecture, API, extension guide) before extending features; keep them updated when behavior changes.

## Layout
- `backend/app/` FastAPI app. `downloader.py` is the entry point + thin yt-dlp wrapper (do not fork yt-dlp); it routes Douyin URLs to `douyin.py` (thin wrapper over Johnserf-Seed/f2 with an auto-generated guest cookie). `errors.py` VideoError, `jobs.py` in-memory job queue, `tasks.py` job bodies, `ai.py` DeepSeek via openai SDK, `subtitles.py` SRT utils. Accounts (MySQL via PyMySQL): `account_store.py` SQL, `account_auth.py` hashing/sessions/`require_user`, `account_api.py` routes; schema in `backend/sql/schema.sql`. Login-only APIs: `/api/batch*`, `/api/ai/*`, `/api/learn/*`. Payments (ZPAY, Alipay page-jump): `zpay.py` protocol/signing, `payments.py` orders + idempotent `fulfil()` + reconciler + CLI, `payment_api.py` routes incl. `/api/pay/notify`, `zpay_mock.py` dev cashier (`ZPAY_MOCK=true`); guide `docs/zpay-setup.md`.
- Frontend accounts: `src/account.js` (store, rules, safeRedirect, cross-tab sync, `openAuth()` for the login/register dialog `components/AuthModal.vue`), shared `LoginForm/RegisterForm.vue`, backup pages `Login/Register.vue`, `Account.vue`, router `meta.requiresAuth` (guests get the dialog instead of a redirect).
- `frontend/` Vue 3 + Vite + Tailwind v4. Design tokens in `src/style.css` (hero-bg, text-grad, btn-primary, btn-gold, glass-card, input-shell, pro-badge), copy/data in `src/data.js`.

## Commands (Windows, run from repo root)
- Backend tests: `cd backend && .venv/Scripts/python -m pytest` (network smoke: `-m network`). Account tests need local MySQL 8.4 (service `MySQL84`) and `MYSQL_TEST_DATABASE=freevideo_test` in `backend/.env`; otherwise they skip.
- UI checks (system `python -P`, Playwright): mocked `frontend/tests/ui_regression.py` / `batch_subtitles_ui.py` need Vite on 127.0.0.1:5178; `frontend/tests/account_ui.py` needs the real backend on :8010 with `MYSQL_DATABASE=freevideo_test`, empty AI/ASR keys and relaxed `AUTH_*_RATE_LIMIT` (see script header).
- Payment UI: `frontend/tests/payment_ui.py` needs a real backend on :8011 with `MYSQL_DATABASE=freevideo_test`, `ZPAY_MOCK=true`, empty `ZPAY_PID/KEY`, `PUBLIC_BASE_URL=http://127.0.0.1:8011` (see script header). Backend tests never call real ZPAY (conftest clears ZPAY config).
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
