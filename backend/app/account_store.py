"""MySQL persistence for users and login sessions (PyMySQL, raw SQL, one short connection per call)."""
import logging
from contextlib import contextmanager
from datetime import datetime, timezone

import pymysql
from pymysql.cursors import DictCursor

from . import config
from .errors import AccountError

log = logging.getLogger("freevideo.accounts")
SCHEMA_FILE = config.BASE_DIR / "sql" / "schema.sql"
UNAVAILABLE = "账号服务暂不可用，请稍后再试"
USER_FIELDS = "u.id, u.username, u.nickname, u.created_at"
# (plan, AI videos per cycle, links per batch, longest single recognition in minutes, chat questions per day)
DEFAULT_LIMITS = [("free", 10, 3, 8, 1), ("monthly", 300, 10, 30, 10), ("yearly", 500, 15, 60, 20)]


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@contextmanager
def _cursor():
    try:
        conn = pymysql.connect(host=config.MYSQL_HOST, port=config.MYSQL_PORT, user=config.MYSQL_USER,
                               password=config.MYSQL_PASSWORD, database=config.MYSQL_DATABASE, charset="utf8mb4",
                               cursorclass=DictCursor, connect_timeout=5, read_timeout=10, write_timeout=10)
    except pymysql.MySQLError as e:
        log.warning("MySQL connection failed: %s", e)
        raise AccountError("DB_UNAVAILABLE", UNAVAILABLE, 503) from e
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except pymysql.err.IntegrityError as e:
        conn.rollback()
        if e.args and e.args[0] == 1062:
            raise AccountError("USERNAME_TAKEN", "该用户名已被注册", 409) from e
        log.exception("MySQL integrity error")
        raise AccountError("DB_ERROR", UNAVAILABLE, 503) from e
    except pymysql.MySQLError as e:
        conn.rollback()
        log.exception("MySQL error")
        raise AccountError("DB_ERROR", UNAVAILABLE, 503) from e
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema():
    """Create tables and widen legacy calendar-month quota keys for anniversary periods."""
    statements = [s.strip() for s in SCHEMA_FILE.read_text(encoding="utf-8").split(";")]
    with _cursor() as cur:
        for sql in statements:
            body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--")).strip()
            if body.upper().startswith("CREATE TABLE"):
                cur.execute(body)
        for column, definition in [('active_requests', 'INT UNSIGNED NOT NULL DEFAULT 0'), ('succeeded', 'TINYINT UNSIGNED NOT NULL DEFAULT 1')]:
            cur.execute(f"SHOW COLUMNS FROM ai_usage_videos LIKE '{column}'")
            if not cur.fetchone():
                cur.execute(f'ALTER TABLE ai_usage_videos ADD COLUMN {column} {definition}')
        # Widen only; old quota rows and pending reservations remain available for settlement.
        for table in ('user_quota_periods', 'quota_reservations'):
            cur.execute(f"SHOW COLUMNS FROM {table} LIKE 'period'")
            column = cur.fetchone()
            if column and column['Type'].lower() == 'char(7)':
                cur.execute(f"ALTER TABLE {table} MODIFY COLUMN period VARCHAR(40) "
                            "CHARACTER SET ascii COLLATE ascii_bin NOT NULL")
        # Plan usage limits arrived later: add the columns once and backfill the documented defaults for that run only.
        cur.execute("SHOW COLUMNS FROM membership_plans LIKE 'ai_monthly_limit'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE membership_plans "
                        "ADD COLUMN ai_monthly_limit INT UNSIGNED NOT NULL DEFAULT 0, "
                        "ADD COLUMN batch_max_links INT UNSIGNED NOT NULL DEFAULT 1, "
                        "ADD COLUMN asr_max_minutes INT UNSIGNED NOT NULL DEFAULT 1, "
                        "ADD COLUMN chat_daily_limit INT UNSIGNED NOT NULL DEFAULT 0")
            for code, ai, batch, minutes, chat in DEFAULT_LIMITS:
                cur.execute("UPDATE membership_plans SET ai_monthly_limit=%s, batch_max_links=%s, asr_max_minutes=%s, "
                            "chat_daily_limit=%s WHERE code=%s", (ai, batch, minutes, chat, code))


def _insert_session(cur, user_id: int, session: dict):
    cur.execute("INSERT INTO sessions (id, token_hash, user_id, created_at, last_seen_at, expires_at, user_agent, ip)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (session["id"], session["token_hash"], user_id, session["created_at"], session["created_at"],
                 session["expires_at"], session["user_agent"], session["ip"]))


def create_user(username: str, username_key: str, nickname: str, password_hash: str, session: dict) -> dict:
    """Create a user and its first login session in one transaction."""
    now = utcnow()
    with _cursor() as cur:
        cur.execute("INSERT INTO users (username, username_key, nickname, password_hash, created_at, updated_at,"
                    " password_changed_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (username, username_key, nickname, password_hash, now, now, now))
        user_id = cur.lastrowid
        _insert_session(cur, user_id, session)
    return {"id": user_id, "username": username, "nickname": nickname, "created_at": now}


def get_credentials(username_key: str) -> dict | None:
    with _cursor() as cur:
        cur.execute(f"SELECT {USER_FIELDS}, u.password_hash FROM users u WHERE u.username_key = %s", (username_key,))
        return cur.fetchone()


def get_password_hash(user_id: int) -> str | None:
    with _cursor() as cur:
        cur.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
    return row["password_hash"] if row else None


def create_session(user_id: int, session: dict):
    with _cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE expires_at <= %s", (utcnow(),))
        _insert_session(cur, user_id, session)


def session_user(token_hash: str) -> dict | None:
    with _cursor() as cur:
        cur.execute(f"SELECT {USER_FIELDS}, s.id AS session_id, s.last_seen_at FROM sessions s"
                    " JOIN users u ON u.id = s.user_id WHERE s.token_hash = %s AND s.expires_at > %s",
                    (token_hash, utcnow()))
        return cur.fetchone()


def touch_session(session_id: str):
    with _cursor() as cur:
        cur.execute("UPDATE sessions SET last_seen_at = %s WHERE id = %s", (utcnow(), session_id))


def delete_session_by_token(token_hash: str):
    with _cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE token_hash = %s", (token_hash,))


def delete_session(user_id: int, session_id: str) -> bool:
    with _cursor() as cur:
        return cur.execute("DELETE FROM sessions WHERE id = %s AND user_id = %s", (session_id, user_id)) > 0


def delete_other_sessions(user_id: int, keep_session_id: str) -> int:
    with _cursor() as cur:
        return cur.execute("DELETE FROM sessions WHERE user_id = %s AND id <> %s", (user_id, keep_session_id))


def list_sessions(user_id: int) -> list[dict]:
    with _cursor() as cur:
        cur.execute("SELECT id, created_at, last_seen_at, expires_at, user_agent, ip FROM sessions"
                    " WHERE user_id = %s AND expires_at > %s ORDER BY last_seen_at DESC", (user_id, utcnow()))
        return list(cur.fetchall())


def update_nickname(user_id: int, nickname: str):
    with _cursor() as cur:
        cur.execute("UPDATE users SET nickname = %s, updated_at = %s WHERE id = %s", (nickname, utcnow(), user_id))


def update_password(user_id: int, password_hash: str):
    """Change the password and revoke every session of the user."""
    now = utcnow()
    with _cursor() as cur:
        cur.execute("UPDATE users SET password_hash = %s, password_changed_at = %s, updated_at = %s WHERE id = %s",
                    (password_hash, now, now, user_id))
        cur.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))


def delete_user(user_id: int):
    with _cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
