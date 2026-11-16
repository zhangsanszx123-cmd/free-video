# AGENTS.md

Read `docs/requirements.md` (scope, decisions, backlog) and `docs/design.md` (architecture, API, extension guide) before extending features; keep them updated when behavior changes.

## Layout
- `backend/app/` FastAPI app. `downloader.py` is the entry point + thin yt-dlp wrapper (do not fork yt-dlp); it routes Douyin URLs to `douyin.py` (thin wrapper over Johnserf-Seed/f2 with an auto-generated guest cookie). `errors.py` VideoError, `jobs.py` in-memory job queue, `tasks.py` job bodies, `ai.py` DeepSeek via openai SDK, `subtitles.py` SRT utils. Accounts (MySQL via PyMySQL): `account_store.py` SQL, `account_auth.py` hashing/sessions/`require_user`, `account_api.py` routes; schema in `backend/sql/schema.sql`. Login-only APIs: `/api/batch*`, `/api/ai/*`, `/api/learn/*`, `/api/subtitles`, `/api/transcript`, `/api/transcriptions`; guests may only `/api/parse` + `/api/download` for 2 distinct links (`guest.py`, cookie + IP, duration charged to the quota at first login). Per-plan limits (AI videos/cycle, chat/day, batch links, ASR minutes) live in `membership_plans`, counted by `usage.py`. Payments (ZPAY, Alipay page-jump): `zpay.py` protocol/signing, `payments.py` orders + idempotent `fulfil()` + reconciler + CLI, `payment_api.py` routes incl. `/api/pay/notify`, `zpay_mock.py` dev cashier (`ZPAY_MOCK=true`); guide `docs/zpay-setup.md`.
- Frontend accounts: `src/account.js` (store, rules, safeRedirect, cross-tab sync, `openAuth()` for the login/register dialog `components/AuthModal.vue`), shared `LoginForm/RegisterForm.vue`, backup pages `Login/Register.vue`, `Account.vue`, router `meta.requiresAuth` (guests get the dialog instead of a redirect).
- Admin: independent `/admin/*` UI in `frontend/src/admin/`, backend `admin_store.py/admin_auth.py/admin_api.py` at `/api/admin/*`, cookie `freevideo_admin` (Path `/api/admin`), roles `superadmin/admin`. Bootstrap/recovery use `python -m app.admin_auth` with hidden password input, never seed a default password. Registered-user suspension revokes site sessions and unused email tokens; accepted tasks/payments still settle. Guide `docs/admin-setup.md`. Admin tests use isolated MySQL databases; `admin_test_server.py` :8015 uses `freevideo_admin_ui_test`, never the business DB or a shared pytest DB.
- Current auth: email + password; registration alone requires arithmetic PNG CAPTCHA (`captcha.py`, click image to refresh). Auth modal tabs are login/register/forgot password (`ForgotPasswordForm.vue`). `email_verification.py` handles SMTP and one-use verification links; `password_reset.py` handles recovery and revokes all sessions. Tables `email_verifications/password_resets` store token digests. See `docs/email-auth-plan.md`, `docs/email-verification-setup.md`, `docs/password-recovery-verification.md`. SMTP credentials stay only in ignored `backend/.env`.
- `frontend/` Vue 3 + Vite + Tailwind v4. Design tokens in `src/style.css` (hero-bg, text-grad, btn-primary, btn-gold, glass-card, input-shell), copy/data in `src/data.js`.

## Commands (Windows, run from repo root)
- Backend tests: `cd backend && .venv/Scripts/python -m pytest` (network smoke: `-m network`). Account tests need local MySQL 8.4 (service `MySQL84`) and `MYSQL_TEST_DATABASE=freevideo_test` in `backend/.env`; otherwise they skip.
- UI checks (system `python -P`, Playwright): mocked `frontend/tests/ui_regression.py` / `batch_subtitles_ui.py` need Vite on 127.0.0.1:5178; `frontend/tests/account_ui.py` needs the real backend on :8010 with `MYSQL_DATABASE=freevideo_test`, empty AI/ASR keys and relaxed `AUTH_*_RATE_LIMIT` (see script header).
- Email UI: mock checks `email_auth_ui.py`, `email_verification_ui.py`, `password_recovery_ui.py` use Vite :5178. For real email/recovery flows, start `backend/.venv/Scripts/python -P frontend/tests/email_link_test_server.py` then run `python -P frontend/tests/email_link_real_ui.py` (:8014, test DB, SMTP replaced). Do not run while pytest clears that DB. Legacy account/payment/membership UI backends should set `AUTH_EMAIL_VERIFICATION_REQUIRED=false` to avoid real mail.
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
