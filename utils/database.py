"""Database helpers for EETOON CRM.

The app should stay usable even when Supabase is not configured or is
temporarily unreachable. Read functions return empty/default values in that
case, while write functions return False/None so pages can show a clear message.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Optional

import psycopg2
import psycopg2.extras
import streamlit as st


DEFAULT_STATS = {
    "total": 0,
    "active": 0,
    "replied": 0,
    "cold": 0,
    "no_interest": 0,
    "bounced": 0,
    "pending_emails": 0,
    "total_sent": 0,
}

LAST_DB_ERROR_KEY = "_db_last_error"


def _secret_section(name: str) -> dict[str, Any]:
    try:
        section = st.secrets.get(name, {})
    except Exception:
        return {}
    return dict(section) if section else {}


def _read_db_config() -> dict[str, Any]:
    """Read Postgres config from Streamlit secrets or environment variables."""
    db = _secret_section("supabase")
    config = {
        "host": db.get("db_host") or db.get("host") or os.getenv("SUPABASE_DB_HOST") or os.getenv("PGHOST"),
        "port": db.get("db_port") or db.get("port") or os.getenv("SUPABASE_DB_PORT") or os.getenv("PGPORT") or 5432,
        "dbname": db.get("db_name") or db.get("dbname") or os.getenv("SUPABASE_DB_NAME") or os.getenv("PGDATABASE") or "postgres",
        "user": db.get("db_user") or db.get("user") or os.getenv("SUPABASE_DB_USER") or os.getenv("PGUSER") or "postgres",
        "password": db.get("db_password") or db.get("password") or os.getenv("SUPABASE_DB_PASSWORD") or os.getenv("PGPASSWORD"),
    }
    database_url = db.get("database_url") or db.get("url") or os.getenv("DATABASE_URL")
    if database_url:
        config["dsn"] = database_url
    return config


def _sanitize_error(exc: Exception) -> str:
    msg = str(exc).strip() or exc.__class__.__name__
    config = _read_db_config()
    for value in config.values():
        if isinstance(value, str) and value:
            msg = msg.replace(value, "***")
    return msg


def _set_db_error(exc: Exception) -> None:
    try:
        st.session_state[LAST_DB_ERROR_KEY] = _sanitize_error(exc)
    except Exception:
        pass


def clear_db_error() -> None:
    try:
        st.session_state.pop(LAST_DB_ERROR_KEY, None)
    except Exception:
        pass


def get_last_db_error() -> str:
    try:
        return st.session_state.get(LAST_DB_ERROR_KEY, "")
    except Exception:
        return ""


def has_db_config() -> bool:
    config = _read_db_config()
    return bool(config.get("dsn") or (config.get("host") and config.get("password")))


def get_conn():
    """Create a PostgreSQL connection.

    Raises RuntimeError with a safe message when configuration is missing.
    """
    config = _read_db_config()
    try:
        if config.get("dsn"):
            conn = psycopg2.connect(config["dsn"], connect_timeout=10)
        elif config.get("host") and config.get("password"):
            conn = psycopg2.connect(
                host=config["host"],
                port=int(config["port"]),
                dbname=config["dbname"],
                user=config["user"],
                password=config["password"],
                connect_timeout=10,
            )
        else:
            raise RuntimeError(
                "Database is not configured. Add [supabase] db_host/db_password "
                "or DATABASE_URL in Streamlit Secrets."
            )
        clear_db_error()
        return conn
    except Exception as exc:
        _set_db_error(exc)
        raise


@contextmanager
def db_cursor(dict_rows: bool = False):
    conn = get_conn()
    cursor_factory = psycopg2.extras.RealDictCursor if dict_rows else None
    cur = conn.cursor(cursor_factory=cursor_factory)
    try:
        yield conn, cur
    finally:
        cur.close()
        conn.close()


def _fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    try:
        with db_cursor(dict_rows=True) as (_, cur):
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]
    except Exception as exc:
        _set_db_error(exc)
        return []


def _fetch_one(query: str, params: tuple[Any, ...] = ()) -> Optional[dict[str, Any]]:
    try:
        with db_cursor(dict_rows=True) as (_, cur):
            cur.execute(query, params)
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as exc:
        _set_db_error(exc)
        return None


def _execute(query: str, params: tuple[Any, ...] = ()) -> bool:
    try:
        with db_cursor() as (conn, cur):
            cur.execute(query, params)
            conn.commit()
        return True
    except Exception as exc:
        _set_db_error(exc)
        return False


def _insert(table: str, data: dict[str, Any], returning: str | None = None) -> Any:
    if not data:
        return None
    cols = list(data.keys())
    col_sql = ", ".join(cols)
    val_sql = ", ".join(["%s"] * len(cols))
    returning_sql = f" RETURNING {returning}" if returning else ""
    query = f"INSERT INTO {table} ({col_sql}) VALUES ({val_sql}){returning_sql}"
    try:
        with db_cursor() as (conn, cur):
            cur.execute(query, tuple(data[col] for col in cols))
            value = cur.fetchone()[0] if returning else True
            conn.commit()
            return value
    except psycopg2.errors.UniqueViolation as exc:
        _set_db_error(exc)
        return None
    except Exception as exc:
        _set_db_error(exc)
        return None if returning else False


def get_setting(key: str, default=None):
    row = _fetch_one("SELECT value FROM settings WHERE key = %s", (key,))
    return row["value"] if row else default


def set_setting(key: str, value) -> bool:
    return _execute(
        "INSERT INTO settings (key, value) VALUES (%s, %s::jsonb) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
        (key, json.dumps(value)),
    )


def get_all_leads(status_filter=None):
    if status_filter:
        return _fetch_all(
            "SELECT * FROM leads WHERE status = %s ORDER BY score DESC, created_at DESC",
            (status_filter,),
        )
    return _fetch_all("SELECT * FROM leads ORDER BY score DESC, created_at DESC")


def get_lead(lead_id: int):
    return _fetch_one("SELECT * FROM leads WHERE id = %s", (lead_id,))


def get_lead_by_email(email: str):
    return _fetch_one("SELECT * FROM leads WHERE email = %s", (email,))


def update_lead(lead_id: int, **kwargs) -> bool:
    if not kwargs:
        return True
    kwargs["updated_at"] = datetime.now()
    allowed = {
        "company_name", "contact_name", "email", "website", "location",
        "company_size", "status", "bag_signal_strength", "bag_signal",
        "company_direction", "ppai_member", "owner_topics", "hook_direction",
        "recommended_cta", "owner_linkedin", "company_linkedin",
        "linkedin_active", "instagram", "touch_count", "send_date",
        "day7_date", "day14_date", "day21_date", "reactivation_date",
        "last_subject", "notes", "score", "score_grade", "updated_at",
    }
    updates = {key: value for key, value in kwargs.items() if key in allowed}
    if not updates:
        return False
    set_clause = ", ".join(f"{key} = %s" for key in updates)
    values = tuple(updates.values()) + (lead_id,)
    return _execute(f"UPDATE leads SET {set_clause} WHERE id = %s", values)


def update_lead_status(lead_id: int, status: str, note: str = "") -> bool:
    ok = update_lead(lead_id, status=status)
    if ok and note:
        add_note(lead_id, "status_change", note)
    return ok


def add_lead(data: dict) -> Optional[int]:
    return _insert("leads", data, returning="id")


def get_email_history(lead_id: int):
    return _fetch_all(
        "SELECT * FROM email_history WHERE lead_id = %s ORDER BY sent_at DESC",
        (lead_id,),
    )


def add_email_history(data: dict) -> bool:
    return bool(_insert("email_history", data))


def get_pending_queue():
    return _fetch_all(
        "SELECT * FROM email_queue WHERE status = 'pending' ORDER BY scheduled_utc ASC"
    )


def get_all_queue():
    return _fetch_all("SELECT * FROM email_queue ORDER BY queued_at DESC LIMIT 100")


def add_to_queue(data: dict) -> bool:
    if not data:
        return False
    cols = list(data.keys())
    col_sql = ", ".join(cols)
    val_sql = ", ".join(["%s"] * len(cols))
    query = (
        f"INSERT INTO email_queue ({col_sql}) VALUES ({val_sql}) "
        "ON CONFLICT (queue_id) DO NOTHING"
    )
    return _execute(query, tuple(data[col] for col in cols))


def update_queue_status(queue_id: str, status: str, error: str = None) -> bool:
    if status == "sent":
        return _execute(
            "UPDATE email_queue SET status='sent', sent_at=NOW() WHERE queue_id=%s",
            (queue_id,),
        )
    if status == "failed":
        return _execute(
            "UPDATE email_queue SET status='failed', error_message=%s, "
            "retry_count=retry_count+1 WHERE queue_id=%s",
            (error, queue_id),
        )
    return False


def get_due_followups(check_date=None):
    check_date = check_date or date.today()
    return _fetch_all(
        """
        SELECT * FROM leads
        WHERE status NOT IN ('有回复','无意向','退信','冷静期-90天后重新激活')
        AND touch_count < 3
        AND (
            (day7_date <= %s AND touch_count = 1) OR
            (day14_date <= %s AND touch_count = 2) OR
            (day21_date <= %s AND touch_count = 3)
        )
        ORDER BY score DESC
        """,
        (check_date, check_date, check_date),
    )


def get_reactivation_due(check_date=None):
    check_date = check_date or date.today()
    return _fetch_all(
        """
        SELECT * FROM leads
        WHERE status = '冷静期-90天后重新激活'
        AND reactivation_date <= %s
        ORDER BY score DESC
        """,
        (check_date,),
    )


def add_note(lead_id: int, note_type: str, content: str) -> bool:
    return _execute(
        "INSERT INTO followup_notes (lead_id, note_type, content) VALUES (%s, %s, %s)",
        (lead_id, note_type, content),
    )


def get_notes(lead_id: int):
    return _fetch_all(
        "SELECT * FROM followup_notes WHERE lead_id = %s ORDER BY created_at DESC",
        (lead_id,),
    )


def get_templates(category=None, touch_number=None):
    query = "SELECT * FROM templates WHERE 1=1"
    params: list[Any] = []
    if category:
        query += " AND category = %s"
        params.append(category)
    if touch_number:
        query += " AND touch_number = %s"
        params.append(touch_number)
    query += " ORDER BY reply_rate DESC, use_count DESC"
    return _fetch_all(query, tuple(params))


def add_template(data: dict) -> bool:
    return bool(_insert("templates", data))


def get_stats():
    try:
        with db_cursor() as (_, cur):
            stats = {}
            cur.execute("SELECT COUNT(*) FROM leads")
            stats["total"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM leads WHERE status LIKE '已发送%'")
            stats["active"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM leads WHERE status = '有回复'")
            stats["replied"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM leads WHERE status = '冷静期-90天后重新激活'")
            stats["cold"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM leads WHERE status = '无意向'")
            stats["no_interest"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM leads WHERE status = '退信'")
            stats["bounced"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM email_queue WHERE status = 'pending'")
            stats["pending_emails"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM email_history")
            stats["total_sent"] = cur.fetchone()[0]
            return stats
    except Exception as exc:
        _set_db_error(exc)
        return DEFAULT_STATS.copy()


def get_discovery_queue(status="pending_review"):
    return _fetch_all(
        "SELECT * FROM discovery_queue WHERE status = %s ORDER BY found_at DESC",
        (status,),
    )


def add_discovery_candidate(data: dict) -> bool:
    return bool(_insert("discovery_queue", data))


def update_discovery_status(candidate_id: int, status: str) -> bool:
    return _execute(
        "UPDATE discovery_queue SET status=%s WHERE id=%s",
        (status, candidate_id),
    )


def get_email_history_daily(limit: int = 30):
    return _fetch_all(
        """
        SELECT DATE(sent_at) as send_date, COUNT(*) as count
        FROM email_history
        WHERE sent_at IS NOT NULL
        GROUP BY DATE(sent_at)
        ORDER BY send_date DESC
        LIMIT %s
        """,
        (limit,),
    )
