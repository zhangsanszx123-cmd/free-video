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
  nickname VARCHAR(30) NOT NULL,
  password_hash VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  created_at DATETIME(6) NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  password_changed_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_username_key (username_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS membership_plans (
  code VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
  name VARCHAR(32) NOT NULL,
  price_cents INT UNSIGNED NOT NULL,
  monthly_seconds INT UNSIGNED NOT NULL,
  months INT UNSIGNED NOT NULL,
  revision INT UNSIGNED NOT NULL DEFAULT 1
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
  period CHAR(7) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  plan_code VARCHAR(16) NOT NULL,
  limit_seconds INT UNSIGNED NOT NULL,
  used_seconds INT UNSIGNED NOT NULL DEFAULT 0,
  reserved_seconds INT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY(user_id, period),
  CONSTRAINT fk_quota_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
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
  period CHAR(7) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
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
