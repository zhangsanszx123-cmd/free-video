-- FreeVideo accounts schema (MySQL 8.x). Run once as an admin user:
--   mysql -u root -p < backend/sql/schema.sql
-- The app also runs the CREATE TABLE statements below on startup (IF NOT EXISTS).

CREATE DATABASE IF NOT EXISTS freevideo DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS freevideo_test DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE freevideo;

CREATE TABLE IF NOT EXISTS users (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  username VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  username_key VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  email VARCHAR(254) CHARACTER SET ascii COLLATE ascii_bin NULL,
  email_verified TINYINT NOT NULL DEFAULT 1,
  status VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'active',
  disabled_at DATETIME(6) NULL,
  disabled_reason VARCHAR(500) NOT NULL DEFAULT '',
  nickname VARCHAR(30) NOT NULL,
  password_hash VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  created_at DATETIME(6) NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  password_changed_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_username_key (username_key),
  UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Separate administrative identities. Site users and cookies never grant admin access.
CREATE TABLE IF NOT EXISTS admin_users (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  username_key VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  nickname VARCHAR(30) NOT NULL,
  password_hash VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  role VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  status VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'active',
  created_at DATETIME(6) NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  password_changed_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_admin_users_username_key (username_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS admin_sessions (
  id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
  token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
  admin_id BIGINT UNSIGNED NOT NULL,
  created_at DATETIME(6) NOT NULL,
  last_seen_at DATETIME(6) NOT NULL,
  expires_at DATETIME(6) NOT NULL,
  user_agent VARCHAR(255) NOT NULL DEFAULT '',
  ip VARCHAR(45) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT '',
  KEY idx_admin_sessions_user (admin_id),
  KEY idx_admin_sessions_expiry (expires_at),
  CONSTRAINT fk_admin_session_user FOREIGN KEY (admin_id) REFERENCES admin_users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Every administrative mutation takes this row first, including bootstrap/recovery CLI.
CREATE TABLE IF NOT EXISTS admin_account_guard (
  id TINYINT UNSIGNED NOT NULL PRIMARY KEY
) ENGINE=InnoDB;

-- Actor/target snapshots survive account removal. No credentials are stored here.
CREATE TABLE IF NOT EXISTS admin_audit_logs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  actor_id BIGINT UNSIGNED NULL,
  actor_username VARCHAR(32) NOT NULL,
  action VARCHAR(48) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  target_type VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  target_id BIGINT UNSIGNED NOT NULL,
  target_label VARCHAR(254) NOT NULL,
  detail JSON NOT NULL,
  ip VARCHAR(45) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT '',
  created_at DATETIME(6) NOT NULL,
  KEY idx_admin_audit_target (target_type, target_id, created_at),
  KEY idx_admin_audit_actor (actor_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS email_verifications (
  user_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
  created_at DATETIME(6) NOT NULL,
  expires_at DATETIME(6) NOT NULL,
  CONSTRAINT fk_email_verification_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS password_resets (
  user_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
  credential_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  created_at DATETIME(6) NOT NULL,
  expires_at DATETIME(6) NOT NULL,
  CONSTRAINT fk_password_reset_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS membership_plans (
  code VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
  name VARCHAR(32) NOT NULL,
  price_cents INT UNSIGNED NOT NULL,
  monthly_seconds INT UNSIGNED NOT NULL,
  months INT UNSIGNED NOT NULL,
  revision INT UNSIGNED NOT NULL DEFAULT 1,
  ai_monthly_limit INT UNSIGNED NOT NULL DEFAULT 0,
  batch_max_links INT UNSIGNED NOT NULL DEFAULT 1,
  asr_max_minutes INT UNSIGNED NOT NULL DEFAULT 1,
  chat_daily_limit INT UNSIGNED NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_memberships (
  user_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  plan_code VARCHAR(16) NOT NULL,
  plan_name VARCHAR(32) NOT NULL,
  price_cents INT UNSIGNED NOT NULL,
  monthly_seconds INT UNSIGNED NOT NULL,
  revision INT UNSIGNED NOT NULL,
  starts_at DATETIME(6) NOT NULL,
  expires_at DATETIME(6) NOT NULL,
  CONSTRAINT fk_membership_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_quota_periods (
  user_id BIGINT UNSIGNED NOT NULL,
  period VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  plan_code VARCHAR(16) NOT NULL,
  limit_seconds INT UNSIGNED NOT NULL,
  used_seconds INT UNSIGNED NOT NULL DEFAULT 0,
  reserved_seconds INT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY(user_id, period),
  CONSTRAINT fk_quota_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- AI usage: one row per distinct video per personal cycle (period key as in user_quota_periods).
CREATE TABLE IF NOT EXISTS ai_usage_videos (
  user_id BIGINT UNSIGNED NOT NULL,
  period VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  video_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  active_requests INT UNSIGNED NOT NULL DEFAULT 0,
  succeeded TINYINT UNSIGNED NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL,
  PRIMARY KEY (user_id, period, video_key),
  CONSTRAINT fk_ai_usage_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- AI chat questions per Beijing calendar day.
CREATE TABLE IF NOT EXISTS ai_chat_daily (
  user_id BIGINT UNSIGNED NOT NULL,
  day DATE NOT NULL,
  used INT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, day),
  CONSTRAINT fk_ai_chat_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Guest allowance: the links a not-logged-in visitor parsed. One row per subject ('c:<cookie id>' or 'i:<ip>').
CREATE TABLE IF NOT EXISTS guest_links (
  subject VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  link_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  raw_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  duration_seconds INT UNSIGNED NOT NULL DEFAULT 0,
  created_at DATETIME(6) NOT NULL,
  claimed_by BIGINT UNSIGNED NULL,
  claimed_seconds INT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (subject, link_key),
  KEY idx_guest_raw (subject, raw_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS transcription_records (
  id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  fingerprint CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  url TEXT NOT NULL,
  title VARCHAR(255) NOT NULL DEFAULT '视频文稿',
  platform VARCHAR(64) NOT NULL DEFAULT '',
  thumbnail TEXT,
  duration_seconds INT UNSIGNED NOT NULL DEFAULT 0,
  payload JSON NOT NULL,
  status VARCHAR(16) NOT NULL,
  hidden BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DATETIME(6) NOT NULL,
  expires_at DATETIME(6) NOT NULL,
  KEY idx_record_user(user_id, created_at),
  KEY idx_record_key(user_id, fingerprint),
  KEY idx_record_expiry(expires_at),
  CONSTRAINT fk_record_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS quota_reservations (
  job_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  period VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  seconds INT UNSIGNED NOT NULL,
  state VARCHAR(16) NOT NULL,
  fingerprint CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  KEY idx_reservation_user(user_id),
  KEY idx_reservation_fingerprint(user_id, fingerprint, state),
  CONSTRAINT fk_reservation_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS quota_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  job_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  action VARCHAR(16) NOT NULL,
  seconds INT UNSIGNED NOT NULL,
  created_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_quota_event(job_id, action),
  CONSTRAINT fk_event_reservation FOREIGN KEY (job_id) REFERENCES quota_reservations(job_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ZPAY orders keep a price/plan snapshot. Financial rows survive account deletion (user_id set to NULL).
CREATE TABLE IF NOT EXISTS payment_orders (
  out_trade_no CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
  user_id BIGINT UNSIGNED NULL,
  plan_code VARCHAR(16) NOT NULL,
  plan_name VARCHAR(32) NOT NULL,
  price_cents INT UNSIGNED NOT NULL,
  monthly_seconds INT UNSIGNED NOT NULL,
  months INT UNSIGNED NOT NULL,
  revision INT UNSIGNED NOT NULL,
  subject VARCHAR(100) NOT NULL,
  pay_type VARCHAR(16) NOT NULL,
  status VARCHAR(16) NOT NULL,
  trade_no VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  fulfilment VARCHAR(16) NULL,
  membership_expires_at DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL,
  paid_at DATETIME(6) NULL,
  last_checked_at DATETIME(6) NULL,
  UNIQUE KEY uq_payment_trade_no (trade_no),
  KEY idx_payment_user (user_id, created_at),
  KEY idx_payment_status (status, created_at),
  CONSTRAINT fk_payment_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS payment_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  out_trade_no VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  action VARCHAR(16) NOT NULL,
  detail JSON NULL,
  created_at DATETIME(6) NOT NULL,
  KEY idx_payment_event_order (out_trade_no, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sessions (
  id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  created_at DATETIME(6) NOT NULL,
  last_seen_at DATETIME(6) NOT NULL,
  expires_at DATETIME(6) NOT NULL,
  user_agent VARCHAR(255) NOT NULL DEFAULT '',
  ip VARCHAR(45) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT '',
  PRIMARY KEY (id),
  UNIQUE KEY uq_sessions_token_hash (token_hash),
  KEY idx_sessions_user (user_id),
  KEY idx_sessions_expires (expires_at),
  CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
