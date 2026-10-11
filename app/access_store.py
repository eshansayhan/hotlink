import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator


DEFAULT_SESSION_HOURS = 24


class AccessRateLimitError(Exception):
    pass


def _db_path() -> Path:
    return Path(os.getenv("HFSTREAM_ACCESS_DB", "/data/hfstream-access.sqlite3"))


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 15000")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _pepper() -> bytes:
    configured = os.getenv("HFSTREAM_AUTH_SECRET")
    if configured:
        return configured.encode("utf-8")

    key_path = _db_path().with_suffix(".key")
    key_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return key_path.read_bytes()

    key = secrets.token_bytes(48)
    with os.fdopen(descriptor, "wb") as key_file:
        key_file.write(key)
    return key


def digest(value: str) -> str:
    return hmac.new(_pepper(), value.encode("utf-8"), hashlib.sha256).hexdigest()


def initialize() -> None:
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS access_codes (
                code_hash TEXT PRIMARY KEY,
                discord_user_id TEXT NOT NULL,
                issued_at INTEGER NOT NULL,
                redeemed_at INTEGER,
                expires_at INTEGER,
                device_hash TEXT,
                revoked_at INTEGER,
                raw_code TEXT
            );
            CREATE INDEX IF NOT EXISTS access_codes_user_idx
                ON access_codes(discord_user_id, issued_at);
            CREATE TABLE IF NOT EXISTS access_sessions (
                token_hash TEXT PRIMARY KEY,
                code_hash TEXT NOT NULL,
                discord_user_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS access_sessions_expiry_idx
                ON access_sessions(expires_at);
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token_hash TEXT PRIMARY KEY,
                discord_user_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS oauth_states (
                state_hash TEXT PRIMARY KEY,
                nonce_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS access_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS access_attempts (
                ip_hash TEXT PRIMARY KEY,
                window_start INTEGER NOT NULL,
                attempts INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS video_views (
                video_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                views INTEGER DEFAULT 0,
                last_viewed_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS banned_clients (
                identifier TEXT PRIMARY KEY,
                client_type TEXT NOT NULL DEFAULT 'ip',
                reason TEXT,
                banned_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS issue_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL,
                video_title TEXT NOT NULL,
                issue_type TEXT NOT NULL,
                message TEXT,
                created_at INTEGER NOT NULL,
                resolved_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS access_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                discord_user_id TEXT NOT NULL,
                code TEXT,
                ip_address TEXT,
                device_id TEXT,
                details TEXT,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS access_logs_created_idx ON access_logs(created_at DESC);
            CREATE TABLE IF NOT EXISTS google_users (
                google_id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                given_name TEXT,
                family_name TEXT,
                picture TEXT,
                created_at INTEGER NOT NULL,
                last_login_at INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_banned INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS google_sessions (
                token_hash TEXT PRIMARY KEY,
                google_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS google_sessions_expiry_idx ON google_sessions(expires_at);
            CREATE TABLE IF NOT EXISTS user_video_progress (
                google_id TEXT NOT NULL,
                video_id TEXT NOT NULL,
                position_sec REAL NOT NULL,
                duration_sec REAL NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (google_id, video_id)
            );
            CREATE TABLE IF NOT EXISTS user_favorites (
                google_id TEXT NOT NULL,
                video_id TEXT NOT NULL,
                video_title TEXT NOT NULL,
                cover_url TEXT,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (google_id, video_id)
            );
            CREATE TABLE IF NOT EXISTS user_watch_history (
                google_id TEXT NOT NULL,
                video_id TEXT NOT NULL,
                video_title TEXT NOT NULL,
                cover_url TEXT,
                watched_at INTEGER NOT NULL,
                PRIMARY KEY (google_id, video_id)
            );
            CREATE TABLE IF NOT EXISTS video_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL,
                google_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                user_picture TEXT,
                comment TEXT NOT NULL,
                rating INTEGER DEFAULT 10,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_video_comments_vid ON video_comments(video_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS comment_likes (
                comment_id INTEGER NOT NULL,
                google_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (comment_id, google_id)
            );
            CREATE INDEX IF NOT EXISTS idx_comment_likes_cid ON comment_likes(comment_id);
            CREATE TABLE IF NOT EXISTS user_follows (
                follower_id TEXT NOT NULL,
                following_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (follower_id, following_id)
            );
            CREATE TABLE IF NOT EXISTS user_friends (
                user_id TEXT NOT NULL,
                friend_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (user_id, friend_id)
            );
            CREATE TABLE IF NOT EXISTS user_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id TEXT NOT NULL,
                receiver_id TEXT NOT NULL,
                message TEXT NOT NULL,
                is_read INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_user_messages_pair ON user_messages(sender_id, receiver_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_user_messages_recv ON user_messages(receiver_id, is_read);
            """
        )
        try:
            connection.execute("ALTER TABLE video_comments ADD COLUMN video_title TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            connection.execute("ALTER TABLE google_users ADD COLUMN is_banned INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        for col_def in [
            "username TEXT",
            "birth_date TEXT",
            "age INTEGER",
            "gender TEXT",
            "bio TEXT",
            "phone TEXT",
            "phone_verified INTEGER DEFAULT 0",
        ]:
            try:
                connection.execute(f"ALTER TABLE google_users ADD COLUMN {col_def}")
            except sqlite3.OperationalError:
                pass
        try:
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_google_users_username ON google_users(username)")
        except sqlite3.OperationalError:
            pass
        connection.execute(
            "INSERT OR IGNORE INTO access_settings(setting_key, setting_value) VALUES (?, ?)",
            ("public_video_ids", "[]"),
        )
        connection.execute(
            "INSERT OR IGNORE INTO access_settings(setting_key, setting_value) VALUES (?, ?)",
            ("session_hours", str(DEFAULT_SESSION_HOURS)),
        )
        try:
            connection.execute("ALTER TABLE access_codes ADD COLUMN raw_code TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            connection.execute("ALTER TABLE access_codes ADD COLUMN custom_hours INTEGER")
        except sqlite3.OperationalError:
            pass
        try:
            connection.execute("ALTER TABLE access_codes ADD COLUMN note TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            connection.execute("ALTER TABLE access_codes ADD COLUMN active_stream_id TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            connection.execute("ALTER TABLE access_codes ADD COLUMN active_stream_at INTEGER")
        except sqlite3.OperationalError:
            pass


def _new_code() -> str:
    return str(secrets.randbelow(90_000_000_000_000) + 10_000_000_000_000)


def issue_code(discord_user_id: str, custom_hours: int | None = None, note: str | None = None, ip_address: str = "") -> str:
    now = int(time.time())
    with _connect() as connection:
        if discord_user_id != "admin-panel" and custom_hours is None:
            # 24 saat kurali: ayni kullanici aktif suresi icinde tekrar isterse ayni kodu ver
            hours_str = connection.execute(
                "SELECT setting_value FROM access_settings WHERE setting_key = 'session_hours'"
            ).fetchone()
            try:
                hours = int(hours_str["setting_value"]) if hours_str else DEFAULT_SESSION_HOURS
            except (ValueError, TypeError):
                hours = DEFAULT_SESSION_HOURS
            window_seconds = hours * 3600

            row = connection.execute(
                """
                SELECT raw_code, issued_at, expires_at, custom_hours
                FROM access_codes
                WHERE discord_user_id = ? AND revoked_at IS NULL
                ORDER BY issued_at DESC LIMIT 1
                """,
                (str(discord_user_id),),
            ).fetchone()

            if row and row["raw_code"]:
                if row["expires_at"] and row["expires_at"] <= now:
                    pass  # Oturum suresi dolmus, yeni kod uret
                else:
                    win = (row["custom_hours"] * 3600) if row["custom_hours"] else window_seconds
                    if now - row["issued_at"] < win:
                        existing = str(row["raw_code"])
                        log_access_event("issued_existing", str(discord_user_id), code=existing, ip_address=ip_address, details="Mevcut aktif kod tekrar sorgulandı", conn=connection)
                        return existing

        connection.execute(
            """
            UPDATE access_codes SET revoked_at = ?
            WHERE discord_user_id = ? AND redeemed_at IS NULL AND revoked_at IS NULL
            """,
            (now, str(discord_user_id)),
        )
        for _ in range(5):
            code = _new_code()
            try:
                connection.execute(
                    """
                    INSERT INTO access_codes(code_hash, discord_user_id, issued_at, raw_code, custom_hours, note)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (digest(code), str(discord_user_id), now, code, custom_hours, note),
                )
                log_access_event("issued", str(discord_user_id), code=code, ip_address=ip_address, details=note or "Yeni kod üretildi", conn=connection)
                return code
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError("A unique access code could not be generated.")


def _check_attempt_limit(connection: sqlite3.Connection, ip_address: str, now: int) -> None:
    ip_hash = digest(ip_address or "unknown")
    row = connection.execute(
        "SELECT window_start, attempts FROM access_attempts WHERE ip_hash = ?",
        (ip_hash,),
    ).fetchone()
    if row and now - row["window_start"] < 60 and row["attempts"] >= 12:
        raise AccessRateLimitError
    if row and now - row["window_start"] < 60:
        connection.execute(
            "UPDATE access_attempts SET attempts = attempts + 1 WHERE ip_hash = ?",
            (ip_hash,),
        )
    else:
        connection.execute(
            """
            INSERT INTO access_attempts(ip_hash, window_start, attempts)
            VALUES (?, ?, 1)
            ON CONFLICT(ip_hash) DO UPDATE SET window_start = excluded.window_start, attempts = 1
            """,
            (ip_hash, now),
        )


def check_admin_login_attempt(ip_address: str) -> None:
    now = int(time.time())
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        _check_attempt_limit(connection, ip_address, now)


def redeem_code(code: str, device_id: str, ip_address: str, default_hours: int = DEFAULT_SESSION_HOURS) -> dict[str, Any] | None:
    if is_banned(ip_address, device_id):
        return None
    now = int(time.time())
    code_hash = digest(code.strip())
    device_hash = digest(device_id)
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        _check_attempt_limit(connection, ip_address, now)
        row = connection.execute(
            "SELECT * FROM access_codes WHERE code_hash = ?",
            (code_hash,),
        ).fetchone()
        if not row or row["revoked_at"] is not None:
            return None
        if row["redeemed_at"] is not None:
            if (
                row["expires_at"] is None
                or row["expires_at"] <= now
            ):
                return None
            actual_code = row["raw_code"] if "raw_code" in row.keys() and row["raw_code"] else code
            connection.execute(
                "UPDATE access_codes SET device_hash = ? WHERE code_hash = ?",
                (device_hash, code_hash),
            )
            log_access_event("redeemed_relogin", str(row["discord_user_id"]), code=actual_code, ip_address=ip_address, device_id=device_id, details="Oturum yenilendi", conn=connection)
            return {
                "code_hash": code_hash,
                "discord_user_id": row["discord_user_id"],
                "expires_at": row["expires_at"],
                "raw_code": actual_code,
            }

        if row["custom_hours"]:
            session_hours = row["custom_hours"]
        else:
            hours_row = connection.execute(
                "SELECT setting_value FROM access_settings WHERE setting_key = 'session_hours'"
            ).fetchone()
            try:
                session_hours = int(hours_row["setting_value"]) if hours_row else default_hours
            except (TypeError, ValueError):
                session_hours = default_hours
        session_hours = max(1, min(session_hours, 24 * 365))
        expires_at = now + session_hours * 60 * 60
        connection.execute(
            """
            UPDATE access_codes
            SET redeemed_at = ?, expires_at = ?, device_hash = ?
            WHERE code_hash = ? AND redeemed_at IS NULL AND revoked_at IS NULL
            """,
            (now, expires_at, device_hash, code_hash),
        )
        actual_code = row["raw_code"] if "raw_code" in row.keys() and row["raw_code"] else code
        log_access_event("redeemed", str(row["discord_user_id"]), code=actual_code, ip_address=ip_address, device_id=device_id, details="Kod ilk kez cihazla eşleştirildi", conn=connection)
        return {
            "code_hash": code_hash,
            "discord_user_id": row["discord_user_id"],
            "expires_at": expires_at,
            "raw_code": actual_code,
        }


def create_access_session(code_hash: str, discord_user_id: str, expires_at: int) -> str:
    token = secrets.token_urlsafe(40)
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO access_sessions(token_hash, code_hash, discord_user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (digest(token), code_hash, str(discord_user_id), int(time.time()), expires_at),
        )
    return token


def get_access_session(token: str | None, device_id: str | None = None) -> dict[str, Any] | None:
    if not token:
        return None
    now = int(time.time())
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT s.discord_user_id, s.expires_at, s.code_hash, c.device_hash, c.raw_code
            FROM access_sessions AS s
            JOIN access_codes AS c ON c.code_hash = s.code_hash
            WHERE s.token_hash = ? AND s.expires_at > ? AND c.revoked_at IS NULL
              AND c.expires_at > ?
            """,
            (digest(token), now, now),
        ).fetchone()
    if not row:
        return None
    return dict(row)


def revoke_access_session(token: str | None) -> None:
    if not token:
        return
    with _connect() as connection:
        connection.execute("DELETE FROM access_sessions WHERE token_hash = ?", (digest(token),))


def save_oauth_state(state: str, nonce: str) -> None:
    now = int(time.time())
    with _connect() as connection:
        connection.execute("DELETE FROM oauth_states WHERE created_at < ?", (now - 600,))
        connection.execute(
            "INSERT INTO oauth_states(state_hash, nonce_hash, created_at) VALUES (?, ?, ?)",
            (digest(state), digest(nonce), now),
        )


def consume_oauth_state(state: str, nonce: str) -> bool:
    now = int(time.time())
    with _connect() as connection:
        row = connection.execute(
            "SELECT nonce_hash FROM oauth_states WHERE state_hash = ? AND created_at >= ?",
            (digest(state), now - 600),
        ).fetchone()
        if not row or not hmac.compare_digest(row["nonce_hash"], digest(nonce)):
            return False
        connection.execute("DELETE FROM oauth_states WHERE state_hash = ?", (digest(state),))
        return True


def create_admin_session(discord_user_id: str, hours: int = 12) -> tuple[str, int]:
    token = secrets.token_urlsafe(40)
    now = int(time.time())
    expires_at = now + hours * 60 * 60
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO admin_sessions(token_hash, discord_user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (digest(token), str(discord_user_id), now, expires_at),
        )
    return token, expires_at


def get_admin_session(token: str | None, admin_user_id: str | None = None) -> dict[str, Any] | None:
    if not token:
        return None
    now = int(time.time())
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT discord_user_id, expires_at FROM admin_sessions
            WHERE token_hash = ? AND expires_at > ?
            """,
            (digest(token), now),
        ).fetchone()
    if not row:
        return None
    if admin_user_id and not hmac.compare_digest(row["discord_user_id"], str(admin_user_id)):
        return None
    return dict(row)


def revoke_admin_session(token: str | None) -> None:
    if not token:
        return
    with _connect() as connection:
        connection.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (digest(token),))


def get_settings() -> dict[str, Any]:
    with _connect() as connection:
        values = {
            row["setting_key"]: row["setting_value"]
            for row in connection.execute("SELECT setting_key, setting_value FROM access_settings")
        }
    try:
        public_ids = json.loads(values.get("public_video_ids", "[]"))
    except json.JSONDecodeError:
        public_ids = []
    try:
        session_hours = int(values.get("session_hours", DEFAULT_SESSION_HOURS))
    except (TypeError, ValueError):
        session_hours = DEFAULT_SESSION_HOURS
    return {
        "public_video_ids": public_ids if isinstance(public_ids, list) else [],
        "session_hours": max(1, min(session_hours, 24 * 30)),
        "admin_log_webhook": values.get("admin_log_webhook", ""),
    }


def update_settings(public_video_ids: list[str], session_hours: int, admin_log_webhook: str | None = None) -> dict[str, Any]:
    normalized_ids = sorted({str(video_id).strip() for video_id in public_video_ids if str(video_id).strip()})
    session_hours = max(1, min(int(session_hours), 24 * 30))
    with _connect() as connection:
        items = [
            ("public_video_ids", json.dumps(normalized_ids, ensure_ascii=False)),
            ("session_hours", str(session_hours)),
        ]
        if admin_log_webhook is not None:
            items.append(("admin_log_webhook", admin_log_webhook.strip()))
        connection.executemany(
            """
            INSERT INTO access_settings(setting_key, setting_value) VALUES (?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value
            """,
            items,
        )
    res = {"public_video_ids": normalized_ids, "session_hours": session_hours}
    if admin_log_webhook is not None:
        res["admin_log_webhook"] = admin_log_webhook.strip()
    return res


def list_codes(limit: int = 200) -> list[dict[str, Any]]:
    now = int(time.time())
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT code_hash, discord_user_id, issued_at, redeemed_at, expires_at, revoked_at, raw_code, custom_hours, note
            FROM access_codes ORDER BY issued_at DESC LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        ).fetchall()
    results = []
    for row in rows:
        if row["revoked_at"] is not None:
            status = "revoked"
        elif row["redeemed_at"] is None:
            status = "available"
        elif row["expires_at"] is not None and row["expires_at"] > now:
            status = "active"
        else:
            status = "expired"
        results.append({**dict(row), "status": status})
    return results


def revoke_code(code_hash: str) -> bool:
    now = int(time.time())
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE access_codes SET revoked_at = ?
            WHERE code_hash = ? AND revoked_at IS NULL
            """,
            (now, code_hash),
        )
    return cursor.rowcount > 0



def record_video_view(video_id: str, title: str = "") -> None:
    if not video_id:
        return
    now = int(time.time())
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO video_views(video_id, title, views, last_viewed_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                views = views + 1,
                last_viewed_at = excluded.last_viewed_at,
                title = CASE WHEN excluded.title != '' THEN excluded.title ELSE video_views.title END
            """,
            (video_id, title or video_id, now),
        )


def get_user_active_code(discord_user_id: str) -> dict | None:
    now = int(time.time())
    with _connect() as connection:
        hours_str = connection.execute(
            "SELECT setting_value FROM access_settings WHERE setting_key = 'session_hours'"
        ).fetchone()
        try:
            hours = int(hours_str["setting_value"]) if hours_str else DEFAULT_SESSION_HOURS
        except (ValueError, TypeError):
            hours = DEFAULT_SESSION_HOURS
        window_seconds = hours * 3600

        row = connection.execute(
            """
            SELECT raw_code, issued_at, expires_at, redeemed_at, custom_hours
            FROM access_codes
            WHERE discord_user_id = ? AND revoked_at IS NULL
            ORDER BY issued_at DESC LIMIT 1
            """,
            (str(discord_user_id),),
        ).fetchone()

        if not row or not row["raw_code"]:
            return None

        if row["expires_at"]:
            remaining = row["expires_at"] - now
        else:
            win = (row["custom_hours"] * 3600) if row["custom_hours"] else window_seconds
            remaining = (row["issued_at"] + win) - now

        if remaining <= 0:
            return None

        return {
            "code": row["raw_code"],
            "remaining_seconds": remaining,
            "redeemed": bool(row["redeemed_at"]),
        }


def get_analytics_summary() -> dict:
    now = int(time.time())
    today_start = now - 86400  # son 24 saat
    with _connect() as connection:
        codes_today = connection.execute(
            "SELECT COUNT(*) AS c FROM access_codes WHERE issued_at >= ?",
            (today_start,),
        ).fetchone()["c"]

        total_codes = connection.execute(
            "SELECT COUNT(*) AS c FROM access_codes"
        ).fetchone()["c"]

        active_sessions = connection.execute(
            "SELECT COUNT(DISTINCT token_hash) AS c FROM access_sessions WHERE expires_at > ?",
            (now,),
        ).fetchone()["c"]

        top_rows = connection.execute(
            """
            SELECT video_id, title, views, last_viewed_at
            FROM video_views
            ORDER BY views DESC LIMIT 10
            """
        ).fetchall()

        top_videos = [
            {
                "video_id": row["video_id"],
                "title": row["title"],
                "views": row["views"],
                "last_viewed_at": row["last_viewed_at"],
            }
            for row in top_rows
        ]

        return {
            "codes_today": codes_today,
            "total_codes": total_codes,
            "active_sessions": active_sessions,
            "top_videos": top_videos,
        }


def is_banned(ip: str | None, device_id: str | None = None) -> bool:
    identifiers = []
    if ip and ip.strip():
        identifiers.append(ip.strip())
        identifiers.append(digest(ip.strip()))
    if device_id and device_id.strip():
        identifiers.append(device_id.strip())
        identifiers.append(digest(device_id.strip()))
    if not identifiers:
        return False
    with _connect() as connection:
        placeholders = ",".join("?" for _ in identifiers)
        row = connection.execute(
            f"SELECT identifier FROM banned_clients WHERE identifier IN ({placeholders}) LIMIT 1",
            identifiers,
        ).fetchone()
        return row is not None


def ban_client(identifier: str, client_type: str = "ip", reason: str = "") -> None:
    ident = identifier.strip()
    if not ident:
        return
    now = int(time.time())
    with _connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO banned_clients(identifier, client_type, reason, banned_at)
            VALUES (?, ?, ?, ?)
            """,
            (ident, client_type, reason.strip(), now),
        )


def unban_client(identifier: str) -> bool:
    with _connect() as connection:
        cur = connection.execute("DELETE FROM banned_clients WHERE identifier = ?", (identifier.strip(),))
        return cur.rowcount > 0


def list_banned_clients() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT identifier, client_type, reason, banned_at FROM banned_clients ORDER BY banned_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def cleanup_expired_codes() -> int:
    now = int(time.time())
    with _connect() as connection:
        cur = connection.execute(
            """
            DELETE FROM access_codes
            WHERE revoked_at IS NOT NULL OR (expires_at IS NOT NULL AND expires_at < ?)
            """,
            (now,),
        )
        deleted = cur.rowcount
        connection.execute("DELETE FROM access_sessions WHERE expires_at < ?", (now,))
        return deleted


def create_issue_report(video_id: str, video_title: str, issue_type: str, message: str = "") -> int:
    now = int(time.time())
    with _connect() as connection:
        cur = connection.execute(
            """
            INSERT INTO issue_reports(video_id, video_title, issue_type, message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (video_id.strip(), video_title.strip() or video_id.strip(), issue_type.strip(), message.strip(), now),
        )
        return cur.lastrowid


def list_issue_reports(unresolved_only: bool = True) -> list[dict[str, Any]]:
    with _connect() as connection:
        if unresolved_only:
            query = "SELECT * FROM issue_reports WHERE resolved_at IS NULL ORDER BY created_at DESC LIMIT 100"
        else:
            query = "SELECT * FROM issue_reports ORDER BY created_at DESC LIMIT 100"
        rows = connection.execute(query).fetchall()
        return [dict(r) for r in rows]


def resolve_issue_report(report_id: int) -> bool:
    now = int(time.time())
    with _connect() as connection:
        cur = connection.execute(
            "UPDATE issue_reports SET resolved_at = ? WHERE id = ? AND resolved_at IS NULL",
            (now, int(report_id)),
        )
        return cur.rowcount > 0


def delete_issue_report(report_id: int) -> bool:
    with _connect() as connection:
        cur = connection.execute("DELETE FROM issue_reports WHERE id = ?", (int(report_id),))
        return cur.rowcount > 0


def log_access_event(
    event_type: str,
    discord_user_id: str,
    code: str = "",
    ip_address: str = "",
    device_id: str = "",
    details: str = "",
    conn: sqlite3.Connection | None = None,
) -> None:
    now = int(time.time())
    sql = """
        INSERT INTO access_logs(event_type, discord_user_id, code, ip_address, device_id, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    params = (
        str(event_type),
        str(discord_user_id),
        str(code),
        str(ip_address or "bilinmiyor"),
        str(device_id or ""),
        str(details),
        now,
    )
    if conn is not None:
        conn.execute(sql, params)
    else:
        with _connect() as connection:
            connection.execute(sql, params)


def list_access_logs(limit: int = 150) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, event_type, discord_user_id, code, ip_address, device_id, details, created_at
            FROM access_logs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        ).fetchall()
        return [dict(r) for r in rows]


def clear_access_logs() -> int:
    with _connect() as connection:
        cur = connection.execute("DELETE FROM access_logs")
        return cur.rowcount


def update_stream_heartbeat(code_hash: str, stream_id: str, is_new: bool = False) -> tuple[bool, str]:
    now = int(time.time())
    with _connect() as connection:
        row = connection.execute(
            "SELECT active_stream_id, active_stream_at FROM access_codes WHERE code_hash = ?",
            (code_hash,),
        ).fetchone()
        if not row:
            return False, "Geçersiz oturum veya erişim kodu."

        current_stream = row["active_stream_id"]
        # Yeni akış başlatıldıysa veya mevcut akış ile eşleşiyorsa izin ver
        if is_new or not current_stream or current_stream == stream_id:
            connection.execute(
                "UPDATE access_codes SET active_stream_id = ?, active_stream_at = ? WHERE code_hash = ?",
                (stream_id, now, code_hash),
            )
            return True, "ok"

        # Başka bir sekme/cihaz akışı devralmışsa kontrol et
        last_ping = row["active_stream_at"] or 0
        if now - last_ping < 30:
            return False, "Bu erişim kodu başka bir sekmede veya cihazda izlenmektedir."

        # Önceki akıştan 30 saniyedir sinyal gelmemiş, yeni oturuma devret
        connection.execute(
            "UPDATE access_codes SET active_stream_id = ?, active_stream_at = ? WHERE code_hash = ?",
            (stream_id, now, code_hash),
        )
        return True, "ok"


def _clean_base_username(email: str, name: str) -> str:
    raw = email.split("@")[0] if "@" in email else name
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", raw).strip("_").lower()
    if not cleaned or len(cleaned) < 3:
        cleaned = f"user_{secrets.randbelow(9000) + 1000}"
    return cleaned[:24]


def _generate_unique_username(connection: sqlite3.Connection, base: str, current_google_id: str) -> str:
    candidate = base
    attempt = 1
    while True:
        row = connection.execute(
            "SELECT google_id FROM google_users WHERE username = ? AND google_id != ?",
            (candidate, str(current_google_id)),
        ).fetchone()
        if not row:
            return candidate
        candidate = f"{base}_{secrets.randbelow(9000) + 1000}"
        attempt += 1
        if attempt > 10:
            return f"user_{secrets.token_hex(4)}"


def _calculate_age(birth_date_str: str) -> int | None:
    if not birth_date_str:
        return None
    try:
        bd = datetime.strptime(birth_date_str.strip(), "%Y-%m-%d").date()
        today = date.today()
        age = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
        return max(0, age)
    except Exception:
        return None


def upsert_google_user(
    google_id: str,
    email: str,
    name: str,
    picture: str = "",
    given_name: str = "",
    family_name: str = "",
    role: str = "user",
) -> dict[str, Any]:
    now = int(time.time())
    with _connect() as connection:
        existing = connection.execute(
            "SELECT * FROM google_users WHERE google_id = ?",
            (str(google_id),),
        ).fetchone()
        if existing:
            current_dict = dict(existing)
            # Eğer eski kayıtta username boşsa otomatik oluştur
            existing_username = current_dict.get("username")
            custom_name = (current_dict.get("name") or "").strip()
            display_name = custom_name if custom_name else str(name)
            if not existing_username:
                base_uname = _clean_base_username(email, name)
                new_uname = _generate_unique_username(connection, base_uname, str(google_id))
                connection.execute(
                    """
                    UPDATE google_users
                    SET email = ?, name = ?, given_name = ?, family_name = ?, picture = ?, last_login_at = ?, username = ?
                    WHERE google_id = ?
                    """,
                    (str(email), display_name, str(given_name), str(family_name), str(picture), now, new_uname, str(google_id)),
                )
            else:
                connection.execute(
                    """
                    UPDATE google_users
                    SET email = ?, name = ?, given_name = ?, family_name = ?, picture = ?, last_login_at = ?
                    WHERE google_id = ?
                    """,
                    (str(email), display_name, str(given_name), str(family_name), str(picture), now, str(google_id)),
                )
        else:
            base_uname = _clean_base_username(email, name)
            new_uname = _generate_unique_username(connection, base_uname, str(google_id))
            connection.execute(
                """
                INSERT INTO google_users (google_id, email, name, given_name, family_name, picture, username, created_at, last_login_at, role)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (str(google_id), str(email), str(name), str(given_name), str(family_name), str(picture), new_uname, now, now, str(role)),
            )
        row = connection.execute("SELECT * FROM google_users WHERE google_id = ?", (str(google_id),)).fetchone()
        return dict(row) if row else {}


def create_google_session(google_id: str, session_hours: int = 24 * 30) -> tuple[str, int]:
    raw_token = secrets.token_urlsafe(32)
    token_hash = digest(raw_token)
    now = int(time.time())
    expires_at = now + (session_hours * 3600)
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO google_sessions (token_hash, google_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (token_hash, str(google_id), now, expires_at),
        )
    return raw_token, expires_at


def get_google_session(raw_token: str | None) -> dict[str, Any] | None:
    if not raw_token:
        return None
    token_hash = digest(raw_token)
    now = int(time.time())
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT s.expires_at, u.google_id, u.email, u.name, u.given_name, u.family_name, u.picture, u.role,
                   u.username, u.birth_date, u.age, u.gender, u.bio, u.phone,
                   u.created_at, COALESCE(u.is_banned, 0) as is_banned
            FROM google_sessions s
            JOIN google_users u ON s.google_id = u.google_id
            WHERE s.token_hash = ? AND s.expires_at > ?
            """,
            (token_hash, now),
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        if data.get("is_banned"):
            return None
        return data


def update_user_profile(
    google_id: str,
    name: str | None = None,
    username: str | None = None,
    birth_date: str | None = None,
    gender: str | None = None,
    bio: str | None = None,
    phone: str | None = None,
    phone_verified: bool | int | None = None,
) -> dict[str, Any]:
    with _connect() as connection:
        user_row = connection.execute("SELECT * FROM google_users WHERE google_id = ?", (str(google_id),)).fetchone()
        if not user_row:
            raise ValueError("Kullanıcı bulunamadı.")

        updates: list[str] = []
        params: list[Any] = []

        if name is not None:
            clean_name = str(name).strip()
            if not clean_name:
                raise ValueError("Takma ad boş bırakılamaz.")
            updates.append("name = ?")
            params.append(clean_name[:60])

        if username is not None:
            clean_uname = str(username).strip().lstrip("@").lower()
            if not re.match(r"^[a-z0-9_]{3,30}$", clean_uname):
                raise ValueError("Kullanıcı adı 3-30 karakter arasında olmalı ve yalnızca küçük harf, rakam ve alt çizgi içermelidir.")
            current_uname = str(user_row["username"] or "").strip().lower()
            if current_uname and clean_uname != current_uname:
                raise ValueError("Kullanıcı adı kalıcıdır ve değiştirilemez.")
            existing = connection.execute(
                "SELECT google_id FROM google_users WHERE username = ? AND google_id != ?",
                (clean_uname, str(google_id)),
            ).fetchone()
            if existing:
                raise ValueError("Bu kullanıcı adı başka bir kullanıcı tarafından alınmış.")
            updates.append("username = ?")
            params.append(clean_uname)

        if birth_date is not None:
            clean_bd = str(birth_date).strip()
            if clean_bd:
                calculated_age = _calculate_age(clean_bd)
                if calculated_age is None or calculated_age > 125:
                    raise ValueError("Geçerli bir doğum tarihi giriniz (YYYY-AA-GG).")
                updates.append("birth_date = ?")
                params.append(clean_bd)
                updates.append("age = ?")
                params.append(calculated_age)
            else:
                updates.append("birth_date = ?")
                params.append(None)
                updates.append("age = ?")
                params.append(None)

        if gender is not None:
            clean_gender = str(gender).strip().lower()
            if clean_gender in ("male", "female", "other", "unspecified", "erkek", "kadın", "kadin", "belirtilmemiş", "belirtilmemis", ""):
                updates.append("gender = ?")
                params.append(clean_gender[:20])

        if bio is not None:
            updates.append("bio = ?")
            params.append(str(bio).strip()[:300])

        if phone is not None:
            updates.append("phone = ?")
            params.append(str(phone).strip()[:30])

        if phone_verified is not None:
            updates.append("phone_verified = ?")
            params.append(1 if phone_verified else 0)

        if updates:
            params.append(str(google_id))
            connection.execute(
                f"UPDATE google_users SET {', '.join(updates)} WHERE google_id = ?",
                params,
            )

        updated = connection.execute("SELECT * FROM google_users WHERE google_id = ?", (str(google_id),)).fetchone()
        return dict(updated) if updated else {}


def get_user_profile_details(google_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        user_row = connection.execute("SELECT * FROM google_users WHERE google_id = ?", (str(google_id),)).fetchone()
        if not user_row:
            return None
        profile = dict(user_row)
        fav_count = connection.execute("SELECT COUNT(*) FROM user_favorites WHERE google_id = ?", (str(google_id),)).fetchone()[0]
        history_count = connection.execute("SELECT COUNT(*) FROM user_watch_history WHERE google_id = ?", (str(google_id),)).fetchone()[0]
        comment_count = connection.execute("SELECT COUNT(*) FROM video_comments WHERE google_id = ?", (str(google_id),)).fetchone()[0]
        profile["favorites_count"] = fav_count
        profile["history_count"] = history_count
        profile["comments_count"] = comment_count
        return profile


def delete_google_session(raw_token: str | None) -> None:
    if not raw_token:
        return
    token_hash = digest(raw_token)
    with _connect() as connection:
        connection.execute("DELETE FROM google_sessions WHERE token_hash = ?", (token_hash,))


def list_google_users(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT google_id, email, name, picture, role, created_at, last_login_at, COALESCE(is_banned, 0) as is_banned
            FROM google_users
            ORDER BY last_login_at DESC
            LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        ).fetchall()
        return [dict(r) for r in rows]


def set_google_user_ban(google_id: str, is_banned: bool = True) -> bool:
    val = 1 if is_banned else 0
    with _connect() as connection:
        connection.execute("UPDATE google_users SET is_banned = ? WHERE google_id = ?", (val, str(google_id)))
        if is_banned:
            connection.execute("DELETE FROM google_sessions WHERE google_id = ?", (str(google_id),))
    return True


def save_video_progress(google_id: str, video_id: str, position_sec: float, duration_sec: float) -> None:
    now = int(time.time())
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO user_video_progress (google_id, video_id, position_sec, duration_sec, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(google_id, video_id) DO UPDATE SET
                position_sec = excluded.position_sec,
                duration_sec = excluded.duration_sec,
                updated_at = excluded.updated_at
            """,
            (str(google_id), str(video_id), float(position_sec), float(duration_sec), now),
        )


def get_video_progress(google_id: str, video_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT position_sec, duration_sec, updated_at FROM user_video_progress WHERE google_id = ? AND video_id = ?",
            (str(google_id), str(video_id)),
        ).fetchone()
        return dict(row) if row else None


def list_all_video_progress(google_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT video_id, position_sec, duration_sec, updated_at
            FROM user_video_progress
            WHERE google_id = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (str(google_id), limit),
        ).fetchall()
        return [dict(r) for r in rows]


def toggle_favorite(google_id: str, video_id: str, video_title: str = "", cover_url: str = "") -> bool:
    now = int(time.time())
    with _connect() as connection:
        existing = connection.execute(
            "SELECT 1 FROM user_favorites WHERE google_id = ? AND video_id = ?",
            (str(google_id), str(video_id)),
        ).fetchone()
        if existing:
            connection.execute("DELETE FROM user_favorites WHERE google_id = ? AND video_id = ?", (str(google_id), str(video_id)))
            return False
        else:
            connection.execute(
                """
                INSERT INTO user_favorites (google_id, video_id, video_title, cover_url, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(google_id), str(video_id), str(video_title), str(cover_url), now),
            )
            return True


def list_favorites(google_id: str) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT video_id, video_title, cover_url, created_at FROM user_favorites WHERE google_id = ? ORDER BY created_at DESC",
            (str(google_id),),
        ).fetchall()
        return [dict(r) for r in rows]


def is_favorite(google_id: str, video_id: str) -> bool:
    with _connect() as connection:
        row = connection.execute(
            "SELECT 1 FROM user_favorites WHERE google_id = ? AND video_id = ?",
            (str(google_id), str(video_id)),
        ).fetchone()
        return row is not None


def add_watch_history(google_id: str, video_id: str, video_title: str = "", cover_url: str = "") -> None:
    now = int(time.time())
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO user_watch_history (google_id, video_id, video_title, cover_url, watched_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(google_id, video_id) DO UPDATE SET
                watched_at = excluded.watched_at,
                video_title = excluded.video_title,
                cover_url = excluded.cover_url
            """,
            (str(google_id), str(video_id), str(video_title), str(cover_url), now),
        )


def list_watch_history(google_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT video_id, video_title, cover_url, watched_at
            FROM user_watch_history
            WHERE google_id = ?
            ORDER BY watched_at DESC
            LIMIT ?
            """,
            (str(google_id), limit),
        ).fetchall()
        return [dict(r) for r in rows]


def add_video_comment(
    video_id: str,
    google_id: str,
    user_name: str,
    user_picture: str,
    comment: str,
    rating: int = 10,
    video_title: str = "",
) -> dict[str, Any]:
    now = int(time.time())
    with _connect() as connection:
        v_title = str(video_title).strip()
        if not v_title:
            vh_row = connection.execute(
                "SELECT video_title FROM user_watch_history WHERE video_id = ? LIMIT 1",
                (str(video_id),),
            ).fetchone()
            if vh_row and vh_row["video_title"]:
                v_title = vh_row["video_title"]
            else:
                fav_row = connection.execute(
                    "SELECT video_title FROM user_favorites WHERE video_id = ? LIMIT 1",
                    (str(video_id),),
                ).fetchone()
                if fav_row and fav_row["video_title"]:
                    v_title = fav_row["video_title"]
        cur = connection.execute(
            """
            INSERT INTO video_comments (video_id, video_title, google_id, user_name, user_picture, comment, rating, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (str(video_id), v_title or str(video_id), str(google_id), str(user_name), str(user_picture), str(comment).strip(), max(1, min(10, rating)), now),
        )
        comm_id = cur.lastrowid
        row = connection.execute(
            """
            SELECT c.id, c.video_id, COALESCE(c.video_title, c.video_id) AS video_title, c.google_id, 
                   COALESCE(u.name, c.user_name) AS user_name,
                   COALESCE(u.picture, c.user_picture) AS user_picture,
                   COALESCE(u.username, '') AS username,
                   c.comment, c.rating, c.created_at,
                   0 AS likes_count, 0 AS is_liked, 1 AS is_own
            FROM video_comments c
            LEFT JOIN google_users u ON c.google_id = u.google_id
            WHERE c.id = ?
            """,
            (comm_id,),
        ).fetchone()
        return dict(row) if row else {}


def list_video_comments(video_id: str, current_google_id: str | None = None, sort_by: str = "popular", limit: int = 50) -> list[dict[str, Any]]:
    with _connect() as connection:
        order_clause = "likes_count DESC, c.created_at DESC" if sort_by == "popular" else "c.created_at DESC"
        rows = connection.execute(
            f"""
            SELECT 
                c.id, 
                c.video_id, 
                c.google_id, 
                COALESCE(u.name, c.user_name) AS user_name, 
                COALESCE(u.picture, c.user_picture) AS user_picture,
                COALESCE(u.username, '') AS username,
                c.comment, 
                c.rating, 
                c.created_at,
                (SELECT COUNT(*) FROM comment_likes cl WHERE cl.comment_id = c.id) AS likes_count,
                CASE WHEN ? IS NOT NULL AND EXISTS(
                    SELECT 1 FROM comment_likes cl2 WHERE cl2.comment_id = c.id AND cl2.google_id = ?
                ) THEN 1 ELSE 0 END AS is_liked,
                CASE WHEN ? IS NOT NULL AND c.google_id = ? THEN 1 ELSE 0 END AS is_own
            FROM video_comments c
            LEFT JOIN google_users u ON c.google_id = u.google_id
            WHERE c.video_id = ?
            ORDER BY {order_clause}
            LIMIT ?
            """,
            (current_google_id, current_google_id, current_google_id, current_google_id, str(video_id), limit),
        ).fetchall()
        return [dict(r) for r in rows]


def toggle_comment_like(comment_id: int, google_id: str) -> dict[str, Any]:
    now = int(time.time())
    with _connect() as connection:
        c_row = connection.execute("SELECT id FROM video_comments WHERE id = ?", (int(comment_id),)).fetchone()
        if not c_row:
            raise ValueError("Yorum bulunamadı.")
        existing = connection.execute(
            "SELECT 1 FROM comment_likes WHERE comment_id = ? AND google_id = ?",
            (int(comment_id), str(google_id)),
        ).fetchone()
        if existing:
            connection.execute(
                "DELETE FROM comment_likes WHERE comment_id = ? AND google_id = ?",
                (int(comment_id), str(google_id)),
            )
            liked = False
        else:
            connection.execute(
                "INSERT INTO comment_likes (comment_id, google_id, created_at) VALUES (?, ?, ?)",
                (int(comment_id), str(google_id), now),
            )
            liked = True
        count_row = connection.execute(
            "SELECT COUNT(*) FROM comment_likes WHERE comment_id = ?",
            (int(comment_id),),
        ).fetchone()
        likes_count = count_row[0] if count_row else 0
        return {"liked": liked, "likes_count": likes_count}


def delete_video_comment(comment_id: int, google_id: str, is_admin: bool = False) -> bool:
    with _connect() as connection:
        row = connection.execute("SELECT google_id FROM video_comments WHERE id = ?", (int(comment_id),)).fetchone()
        if not row:
            return False
        if not is_admin and str(row["google_id"]) != str(google_id):
            raise PermissionError("Bu yorumu silme yetkiniz yok.")
        connection.execute("DELETE FROM comment_likes WHERE comment_id = ?", (int(comment_id),))
        connection.execute("DELETE FROM video_comments WHERE id = ?", (int(comment_id),))
        return True


def resolve_user_id(connection: sqlite3.Connection, identifier: str) -> str | None:
    ident = str(identifier).strip().lstrip("@")
    row = connection.execute(
        "SELECT google_id FROM google_users WHERE username = ? COLLATE NOCASE OR google_id = ?",
        (ident, ident),
    ).fetchone()
    return str(row["google_id"]) if row else None


def get_public_profile(identifier: str, viewer_google_id: str | None = None) -> dict[str, Any] | None:
    with _connect() as connection:
        target_id = resolve_user_id(connection, identifier)
        if not target_id:
            return None
        user_row = connection.execute("SELECT * FROM google_users WHERE google_id = ?", (target_id,)).fetchone()
        if not user_row:
            return None
        profile = dict(user_row)
        profile.pop("email", None)
        profile.pop("phone", None)
        
        followers_count = connection.execute(
            "SELECT COUNT(*) FROM user_follows WHERE following_id = ?", (target_id,)
        ).fetchone()[0]
        following_count = connection.execute(
            "SELECT COUNT(*) FROM user_follows WHERE follower_id = ?", (target_id,)
        ).fetchone()[0]
        friends_count = connection.execute(
            "SELECT COUNT(*) FROM user_friends WHERE user_id = ?", (target_id,)
        ).fetchone()[0]
        comments_count = connection.execute(
            "SELECT COUNT(*) FROM video_comments WHERE google_id = ?", (target_id,)
        ).fetchone()[0]
        favorites_count = connection.execute(
            "SELECT COUNT(*) FROM user_favorites WHERE google_id = ?", (target_id,)
        ).fetchone()[0]
        hearts_count = connection.execute(
            """
            SELECT COUNT(*) FROM comment_likes cl
            JOIN video_comments vc ON cl.comment_id = vc.id
            WHERE vc.google_id = ?
            """,
            (target_id,),
        ).fetchone()[0]
        
        profile["followers_count"] = followers_count
        profile["following_count"] = following_count
        profile["friends_count"] = friends_count
        profile["comments_count"] = comments_count
        profile["favorites_count"] = favorites_count
        profile["hearts_received"] = hearts_count
        
        is_following = False
        follows_you = False
        is_mutual = False
        is_friend = False
        is_self = False
        if viewer_google_id:
            if str(viewer_google_id) == target_id:
                is_self = True
            else:
                f_row = connection.execute(
                    "SELECT 1 FROM user_follows WHERE follower_id = ? AND following_id = ?",
                    (str(viewer_google_id), target_id),
                ).fetchone()
                is_following = bool(f_row)
                fy_row = connection.execute(
                    "SELECT 1 FROM user_follows WHERE follower_id = ? AND following_id = ?",
                    (target_id, str(viewer_google_id)),
                ).fetchone()
                follows_you = bool(fy_row)
                is_mutual = is_following and follows_you
                fr_row = connection.execute(
                    "SELECT 1 FROM user_friends WHERE user_id = ? AND friend_id = ?",
                    (str(viewer_google_id), target_id),
                ).fetchone()
                is_friend = bool(fr_row)
        
        profile["is_following"] = is_following
        profile["follows_you"] = follows_you
        profile["is_mutual"] = is_mutual
        profile["is_friend"] = is_friend
        profile["is_self"] = is_self
        
        c_rows = connection.execute(
            """
            SELECT c.id, c.video_id, 
                   COALESCE(NULLIF(c.video_title, ''), (
                       SELECT video_title FROM user_watch_history wh WHERE wh.video_id = c.video_id LIMIT 1
                   ), (
                       SELECT video_title FROM user_favorites f WHERE f.video_id = c.video_id LIMIT 1
                   ), c.video_id) AS video_title,
                   c.comment, c.rating, c.created_at,
                   (SELECT COUNT(*) FROM comment_likes cl WHERE cl.comment_id = c.id) AS likes_count
            FROM video_comments c
            WHERE c.google_id = ?
            ORDER BY c.created_at DESC
            LIMIT 10
            """,
            (target_id,),
        ).fetchall()
        profile["recent_comments"] = [dict(r) for r in c_rows]
        return profile


def toggle_follow(follower_id: str, target_identifier: str) -> dict[str, Any]:
    with _connect() as connection:
        target_id = resolve_user_id(connection, target_identifier)
        if not target_id:
            raise ValueError("Kullanıcı bulunamadı.")
        if target_id == str(follower_id):
            raise ValueError("Kendinizi takip edemezsiniz.")
        
        existing = connection.execute(
            "SELECT 1 FROM user_follows WHERE follower_id = ? AND following_id = ?",
            (str(follower_id), target_id),
        ).fetchone()
        if existing:
            connection.execute(
                "DELETE FROM user_follows WHERE follower_id = ? AND following_id = ?",
                (str(follower_id), target_id),
            )
            following = False
        else:
            now = int(time.time())
            connection.execute(
                "INSERT INTO user_follows (follower_id, following_id, created_at) VALUES (?, ?, ?)",
                (str(follower_id), target_id, now),
            )
            following = True
        
        cnt = connection.execute(
            "SELECT COUNT(*) FROM user_follows WHERE following_id = ?", (target_id,)
        ).fetchone()[0]
        fy_row = connection.execute(
            "SELECT 1 FROM user_follows WHERE follower_id = ? AND following_id = ?",
            (target_id, str(follower_id)),
        ).fetchone()
        follows_you = bool(fy_row)
        is_mutual = following and follows_you
        return {
            "following": following,
            "followers_count": cnt,
            "follows_you": follows_you,
            "is_mutual": is_mutual,
        }


def toggle_friend(user_id: str, target_identifier: str) -> dict[str, Any]:
    with _connect() as connection:
        target_id = resolve_user_id(connection, target_identifier)
        if not target_id:
            raise ValueError("Kullanıcı bulunamadı.")
        if target_id == str(user_id):
            raise ValueError("Kendinizi arkadaş olarak ekleyemezsiniz.")
        
        existing = connection.execute(
            "SELECT 1 FROM user_friends WHERE user_id = ? AND friend_id = ?",
            (str(user_id), target_id),
        ).fetchone()
        if existing:
            connection.execute(
                "DELETE FROM user_friends WHERE (user_id = ? AND friend_id = ?) OR (user_id = ? AND friend_id = ?)",
                (str(user_id), target_id, target_id, str(user_id)),
            )
            is_friend = False
        else:
            now = int(time.time())
            connection.execute(
                "INSERT OR IGNORE INTO user_friends (user_id, friend_id, created_at) VALUES (?, ?, ?)",
                (str(user_id), target_id, now),
            )
            connection.execute(
                "INSERT OR IGNORE INTO user_friends (user_id, friend_id, created_at) VALUES (?, ?, ?)",
                (target_id, str(user_id), now),
            )
            is_friend = True
        
        cnt = connection.execute(
            "SELECT COUNT(*) FROM user_friends WHERE user_id = ?", (target_id,)
        ).fetchone()[0]
        return {"is_friend": is_friend, "friends_count": cnt}


def send_direct_message(sender_id: str, target_identifier: str, text: str) -> dict[str, Any]:
    clean_text = str(text).strip()
    if not clean_text:
        raise ValueError("Mesaj metni boş olamaz.")
    with _connect() as connection:
        target_id = resolve_user_id(connection, target_identifier)
        if not target_id:
            raise ValueError("Kullanıcı bulunamadı.")
        if target_id == str(sender_id):
            raise ValueError("Kendinize mesaj gönderemezsiniz.")
        now = int(time.time())
        cur = connection.execute(
            """
            INSERT INTO user_messages (sender_id, receiver_id, message, is_read, created_at)
            VALUES (?, ?, ?, 0, ?)
            """,
            (str(sender_id), target_id, clean_text[:2000], now),
        )
        msg_id = cur.lastrowid
        row = connection.execute("SELECT * FROM user_messages WHERE id = ?", (msg_id,)).fetchone()
        return dict(row) if row else {}


def get_conversation_messages(user1_id: str, target_identifier: str, limit: int = 50) -> dict[str, Any]:
    with _connect() as connection:
        target_id = resolve_user_id(connection, target_identifier)
        if not target_id:
            raise ValueError("Kullanıcı bulunamadı.")
        connection.execute(
            "UPDATE user_messages SET is_read = 1 WHERE receiver_id = ? AND sender_id = ?",
            (str(user1_id), target_id),
        )
        rows = connection.execute(
            """
            SELECT id, sender_id, receiver_id, message, is_read, created_at
            FROM user_messages
            WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (str(user1_id), target_id, target_id, str(user1_id), max(1, min(limit, 200))),
        ).fetchall()
        target_user = connection.execute(
            "SELECT google_id, username, name, picture FROM google_users WHERE google_id = ?",
            (target_id,),
        ).fetchone()
        return {
            "partner": dict(target_user) if target_user else {},
            "messages": [dict(r) for r in rows],
        }


def list_user_conversations(user_id: str) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT 
                CASE WHEN sender_id = ? THEN receiver_id ELSE sender_id END AS partner_id
            FROM user_messages
            WHERE sender_id = ? OR receiver_id = ?
            """,
            (str(user_id), str(user_id), str(user_id)),
        ).fetchall()
        conversations = []
        for r in rows:
            partner_id = r["partner_id"]
            p_user = connection.execute(
                "SELECT google_id, username, name, picture FROM google_users WHERE google_id = ?",
                (partner_id,),
            ).fetchone()
            if not p_user:
                continue
            last_msg = connection.execute(
                """
                SELECT id, sender_id, receiver_id, message, is_read, created_at
                FROM user_messages
                WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (str(user_id), partner_id, partner_id, str(user_id)),
            ).fetchone()
            unread_count = connection.execute(
                "SELECT COUNT(*) FROM user_messages WHERE receiver_id = ? AND sender_id = ? AND is_read = 0",
                (str(user_id), partner_id),
            ).fetchone()[0]
            conversations.append({
                "partner": dict(p_user),
                "last_message": dict(last_msg) if last_msg else None,
                "unread_count": unread_count,
            })
        conversations.sort(
            key=lambda x: (x["last_message"]["created_at"] if x["last_message"] else 0),
            reverse=True,
        )
        return conversations


EXPORTABLE_TABLES = [
    "google_users",
    "video_comments",
    "comment_likes",
    "user_follows",
    "user_friends",
    "user_messages",
    "user_favorites",
    "user_watch_history",
    "user_video_progress",
    "access_settings",
]


def export_full_database(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    def _do_export(connection: sqlite3.Connection) -> dict[str, Any]:
        data: dict[str, Any] = {
            "version": 1,
            "exported_at": int(time.time()),
            "platform": "eshanio-mesh",
            "tables": {},
        }
        for table in EXPORTABLE_TABLES:
            try:
                rows = connection.execute(f"SELECT * FROM {table}").fetchall()
                data["tables"][table] = [dict(r) for r in rows]
            except Exception:
                data["tables"][table] = []
        return data

    if conn is not None:
        return _do_export(conn)
    with _connect() as connection:
        return _do_export(connection)


def import_full_database(payload: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    tables = payload.get("tables", {})
    if not isinstance(tables, dict):
        raise ValueError("Geçersiz yedekleme dosyası formatı ('tables' anahtarı bulunamadı)")

    def _do_import(connection: sqlite3.Connection) -> dict[str, Any]:
        total_imported = 0
        with connection:
            for table_name, rows in tables.items():
                if table_name not in EXPORTABLE_TABLES or not isinstance(rows, list):
                    continue
                for row in rows:
                    if not isinstance(row, dict) or not row:
                        continue
                    cols = list(row.keys())
                    placeholders = ", ".join(["?"] * len(cols))
                    col_names = ", ".join(cols)
                    values = [row[c] for c in cols]
                    sql = f"INSERT OR REPLACE INTO {table_name} ({col_names}) VALUES ({placeholders})"
                    try:
                        connection.execute(sql, values)
                        total_imported += 1
                    except Exception:
                        pass
        return {
            "status": "success",
            "imported_rows": total_imported,
            "tables_processed": len(tables),
            "timestamp": int(time.time()),
        }

    if conn is not None:
        return _do_import(conn)
    with _connect() as connection:
        return _do_import(connection)
