"""Database helpers for EETOON CRM.

The app should stay usable even when Supabase is not configured or is
temporarily unreachable. Read functions return empty/default values in that
case, while write functions return False/None so pages can show a clear message.
"""

from __future__ import annotations

import json
import os
import socket
from urllib.parse import urlparse
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool
import streamlit as st
from utils.timezone import beijing_today


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
SCHEMA_VERSION_KEY = "schema_version"
SCHEMA_VERSION_VALUE = "campaign_growth_v1"
_SCHEMA_READY = False
PROJECT_REF = "gnqddnujljyqjsfjrrri"
DEFAULT_POOLER_HOST = "aws-1-ap-southeast-1.pooler.supabase.com"
DEFAULT_POOLER_PORT = 6543
_POOL = None
_POOL_KEY = None
_BORROWED_CONN_IDS: set[int] = set()
READ_CACHE_TTL = 20


def _secret_section(name: str) -> dict[str, Any]:
    try:
        section = st.secrets.get(name, {})
    except Exception:
        return {}
    return dict(section) if section else {}


def _truthy(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _read_db_config() -> dict[str, Any]:
    """Read Postgres config from Streamlit secrets or environment variables."""
    db = _secret_section("supabase")
    host = db.get("db_host") or db.get("host") or os.getenv("SUPABASE_DB_HOST") or os.getenv("PGHOST")
    project_ref = db.get("project_ref") or os.getenv("SUPABASE_PROJECT_REF") or PROJECT_REF
    raw_prefer_pooler = db.get("prefer_pooler")
    if raw_prefer_pooler is None:
        raw_prefer_pooler = os.getenv("SUPABASE_PREFER_POOLER")
    prefer_pooler = _truthy(raw_prefer_pooler)
    if prefer_pooler is None:
        prefer_pooler = host == f"db.{project_ref}.supabase.co"
    config = {
        "host": host,
        "port": db.get("db_port") or db.get("port") or os.getenv("SUPABASE_DB_PORT") or os.getenv("PGPORT") or 5432,
        "dbname": db.get("db_name") or db.get("dbname") or os.getenv("SUPABASE_DB_NAME") or os.getenv("PGDATABASE") or "postgres",
        "user": db.get("db_user") or db.get("user") or os.getenv("SUPABASE_DB_USER") or os.getenv("PGUSER") or "postgres",
        "password": db.get("db_password") or db.get("password") or os.getenv("SUPABASE_DB_PASSWORD") or os.getenv("PGPASSWORD"),
        "sslmode": db.get("sslmode") or os.getenv("PGSSLMODE") or "require",
        "hostaddr": db.get("hostaddr") or os.getenv("PGHOSTADDR"),
        "project_ref": project_ref,
        "prefer_pooler": prefer_pooler,
        "pooler_host": db.get("pooler_host") or os.getenv("SUPABASE_POOLER_HOST") or DEFAULT_POOLER_HOST,
        "pooler_port": db.get("pooler_port") or os.getenv("SUPABASE_POOLER_PORT") or DEFAULT_POOLER_PORT,
        "pooler_user": db.get("pooler_user") or os.getenv("SUPABASE_POOLER_USER"),
    }
    database_url = db.get("database_url") or os.getenv("DATABASE_URL")
    legacy_url = db.get("url")
    if not database_url and isinstance(legacy_url, str) and legacy_url.startswith(("postgres://", "postgresql://")):
        database_url = legacy_url
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


def _clear_read_cache() -> None:
    try:
        st.cache_data.clear()
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


def _connect_kwargs(config: dict[str, Any], *, use_hostaddr: bool = True) -> dict[str, Any]:
    hostaddr = config.get("hostaddr")
    if use_hostaddr and not hostaddr:
        try:
            ipv4 = socket.getaddrinfo(config["host"], int(config["port"]), socket.AF_INET, socket.SOCK_STREAM)
            if ipv4:
                hostaddr = ipv4[0][4][0]
        except Exception:
            hostaddr = None

    kwargs = dict(
        host=config["host"],
        port=int(config["port"]),
        dbname=config["dbname"],
        user=config["user"],
        password=config["password"],
        sslmode=config["sslmode"],
        connect_timeout=10,
    )
    if use_hostaddr and hostaddr:
        kwargs["hostaddr"] = hostaddr
    return kwargs


def _connect_with_config(config: dict[str, Any], *, use_hostaddr: bool = True):
    return psycopg2.connect(**_connect_kwargs(config, use_hostaddr=use_hostaddr))


def _pooler_config(config: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not config.get("password"):
        return None
    direct_user = str(config.get("user") or "postgres")
    if "." in direct_user:
        pooler_user = direct_user
    else:
        project_ref = config.get("project_ref") or PROJECT_REF
        pooler_user = config.get("pooler_user") or f"{direct_user}.{project_ref}"
    return {
        "host": config.get("pooler_host") or DEFAULT_POOLER_HOST,
        "port": config.get("pooler_port") or DEFAULT_POOLER_PORT,
        "dbname": config.get("dbname") or "postgres",
        "user": pooler_user,
        "password": config.get("password"),
        "sslmode": config.get("sslmode") or "require",
        "hostaddr": None,
    }


def _connection_attempts(config: dict[str, Any]) -> list[tuple[dict[str, Any], bool]]:
    pooler = _pooler_config(config)
    if config.get("prefer_pooler") and pooler:
        return [(pooler, False), (config, True)]
    attempts = [(config, True)]
    if pooler:
        attempts.append((pooler, False))
    return attempts


def _pool_key(connect_kwargs: dict[str, Any]) -> tuple:
    return tuple(sorted((k, v) for k, v in connect_kwargs.items()))


def _close_pool() -> None:
    global _POOL, _POOL_KEY, _BORROWED_CONN_IDS
    if _POOL:
        try:
            _POOL.closeall()
        except Exception:
            pass
    _POOL = None
    _POOL_KEY = None
    _BORROWED_CONN_IDS = set()


def _get_pool():
    global _POOL, _POOL_KEY
    config = _read_db_config()
    if config.get("dsn"):
        key = ("dsn", config["dsn"])
        if _POOL and _POOL_KEY == key:
            return _POOL
        _close_pool()
        _POOL = psycopg2.pool.SimpleConnectionPool(1, 5, config["dsn"], connect_timeout=10)
        _POOL_KEY = key
        return _POOL

    if not (config.get("host") and config.get("password")):
        raise RuntimeError(
            "Database is not configured. Add [supabase] db_host/db_password "
            "or DATABASE_URL in Streamlit Secrets."
        )

    last_exc = None
    for attempt_config, use_hostaddr in _connection_attempts(config):
        try:
            kwargs = _connect_kwargs(attempt_config, use_hostaddr=use_hostaddr)
            key = _pool_key(kwargs)
            if _POOL and _POOL_KEY == key:
                return _POOL
            _close_pool()
            _POOL = psycopg2.pool.SimpleConnectionPool(1, 5, **kwargs)
            _POOL_KEY = key
            return _POOL
        except Exception as exc:
            last_exc = exc
            _close_pool()
    if last_exc:
        raise last_exc
    raise RuntimeError("Database connection failed.")


def get_conn():
    """Create a PostgreSQL connection.

    Raises RuntimeError with a safe message when configuration is missing.
    """
    try:
        pool = _get_pool()
        conn = pool.getconn()
        _BORROWED_CONN_IDS.add(id(conn))
        clear_db_error()
        return conn
    except Exception as exc:
        _set_db_error(exc)
        raise


def release_conn(conn) -> None:
    if conn is None:
        return
    global _POOL
    if _POOL and id(conn) in _BORROWED_CONN_IDS:
        _BORROWED_CONN_IDS.discard(id(conn))
        try:
            _POOL.putconn(conn)
            return
        except Exception:
            _close_pool()
    try:
        conn.close()
    except Exception:
        pass


@contextmanager
def db_cursor(dict_rows: bool = False):
    conn = get_conn()
    cursor_factory = psycopg2.extras.RealDictCursor if dict_rows else None
    cur = conn.cursor(cursor_factory=cursor_factory)
    try:
        yield conn, cur
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        cur.close()
        release_conn(conn)


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
        _clear_read_cache()
        return True
    except Exception as exc:
        _set_db_error(exc)
        return False


def _adapt_value(value):
    if isinstance(value, (dict, list)):
        return psycopg2.extras.Json(value)
    return value


def _insert(table: str, data: dict[str, Any], returning: Optional[str] = None) -> Any:
    if not data:
        return None
    cols = list(data.keys())
    col_sql = ", ".join(cols)
    val_sql = ", ".join(["%s"] * len(cols))
    returning_sql = f" RETURNING {returning}" if returning else ""
    query = f"INSERT INTO {table} ({col_sql}) VALUES ({val_sql}){returning_sql}"
    try:
        with db_cursor() as (conn, cur):
            cur.execute(query, tuple(_adapt_value(data[col]) for col in cols))
            value = cur.fetchone()[0] if returning else True
            conn.commit()
            _clear_read_cache()
            return value
    except psycopg2.errors.UniqueViolation as exc:
        _set_db_error(exc)
        return None
    except Exception as exc:
        _set_db_error(exc)
        return None if returning else False


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_setting(key: str, default=None):
    row = _fetch_one("SELECT value FROM settings WHERE key = %s", (key,))
    return row["value"] if row else default


def set_setting(key: str, value) -> bool:
    return _execute(
        "INSERT INTO settings (key, value) VALUES (%s, %s::jsonb) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
        (key, json.dumps(value)),
    )


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_all_leads(status_filter=None):
    if status_filter:
        return _fetch_all(
            "SELECT * FROM leads WHERE status = %s ORDER BY score DESC, created_at DESC",
            (status_filter,),
        )
    return _fetch_all("SELECT * FROM leads ORDER BY score DESC, created_at DESC")


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
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
        "campaign_id", "lead_source", "qualification_status", "positive_reply",
        "opportunity_status", "customer_type", "email_quality", "last_reply_at",
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


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_email_history(lead_id: int):
    return _fetch_all(
        "SELECT * FROM email_history WHERE lead_id = %s ORDER BY sent_at DESC",
        (lead_id,),
    )


def add_email_history(data: dict) -> bool:
    return bool(_insert("email_history", data))


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_pending_queue():
    ensure_schema()
    return _fetch_all(
        """
        SELECT * FROM email_queue
        WHERE status = 'pending'
        AND (COALESCE(requires_approval, FALSE) = FALSE OR approved_at IS NOT NULL)
        ORDER BY scheduled_utc ASC
        """
    )


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_all_queue():
    ensure_schema()
    return _fetch_all("SELECT * FROM email_queue ORDER BY queued_at DESC LIMIT 100")


def add_to_queue(data: dict) -> bool:
    if not data:
        return False
    ensure_schema()
    cols = list(data.keys())
    col_sql = ", ".join(cols)
    val_sql = ", ".join(["%s"] * len(cols))
    query = (
        f"INSERT INTO email_queue ({col_sql}) VALUES ({val_sql}) "
        "ON CONFLICT (queue_id) DO NOTHING"
    )
    return _execute(query, tuple(_adapt_value(data[col]) for col in cols))


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


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_due_followups(check_date=None):
    check_date = check_date or beijing_today()
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


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_reactivation_due(check_date=None):
    check_date = check_date or beijing_today()
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


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_notes(lead_id: int):
    return _fetch_all(
        "SELECT * FROM followup_notes WHERE lead_id = %s ORDER BY created_at DESC",
        (lead_id,),
    )


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_templates(category=None, touch_number=None):
    ensure_schema()
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


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_templates_for_campaign(campaign_id: Optional[int] = None, category=None, touch_number=None):
    ensure_schema()
    query = "SELECT * FROM templates WHERE 1=1"
    params: list[Any] = []
    if campaign_id:
        query += " AND (campaign_id = %s OR campaign_id IS NULL)"
        params.append(campaign_id)
    if category:
        query += " AND category = %s"
        params.append(category)
    if touch_number:
        query += " AND touch_number = %s"
        params.append(touch_number)
    query += " ORDER BY enabled DESC, reply_rate DESC, use_count DESC"
    return _fetch_all(query, tuple(params))


def add_template(data: dict) -> bool:
    ensure_schema()
    return bool(_insert("templates", data))


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_stats():
    try:
        with db_cursor(dict_rows=True) as (_, cur):
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM leads) AS total,
                    (SELECT COUNT(*) FROM leads WHERE status LIKE '已发送%%') AS active,
                    (SELECT COUNT(*) FROM leads WHERE status = '有回复') AS replied,
                    (SELECT COUNT(*) FROM leads WHERE status = '冷静期-90天后重新激活') AS cold,
                    (SELECT COUNT(*) FROM leads WHERE status = '无意向') AS no_interest,
                    (SELECT COUNT(*) FROM leads WHERE status = '退信') AS bounced,
                    (SELECT COUNT(*) FROM email_queue WHERE status = 'pending') AS pending_emails,
                    (SELECT COUNT(*) FROM email_history) AS total_sent
                """
            )
            return dict(cur.fetchone())
    except Exception as exc:
        _set_db_error(exc)
        return DEFAULT_STATS.copy()


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_discovery_queue(status="pending_review"):
    return _fetch_all(
        "SELECT * FROM discovery_queue WHERE status = %s ORDER BY found_at DESC",
        (status,),
    )


def add_discovery_candidate(data: dict) -> bool:
    allowed = {
        "company_name", "website", "location", "email", "owner_name",
        "contact_name", "company_size", "research_brief",
        "source", "status", "campaign_id", "score",
        "score_grade", "score_reason", "review_decision", "reviewed_at",
    }
    payload = {key: value for key, value in data.items() if key in allowed}
    return bool(_insert("discovery_queue", payload))


def update_discovery_status(candidate_id: int, status: str) -> bool:
    return _execute(
        "UPDATE discovery_queue SET status=%s WHERE id=%s",
        (status, candidate_id),
    )


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
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


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_sent_count_today(campaign_id: Optional[int] = None) -> int:
    ensure_schema()
    today = beijing_today()
    try:
        with db_cursor() as (_, cur):
            if campaign_id:
                cur.execute(
                    "SELECT COUNT(*) FROM email_history WHERE DATE(sent_at)=%s AND campaign_id=%s",
                    (today, campaign_id),
                )
            else:
                cur.execute("SELECT COUNT(*) FROM email_history WHERE DATE(sent_at)=%s", (today,))
            return cur.fetchone()[0]
    except Exception as exc:
        _set_db_error(exc)
        return 0


DEFAULT_CAMPAIGN = {
    "campaign_name": "US Promo Distributors - Bag Demand Test",
    "target_segment": "US promotional products distributors with possible bag demand",
    "country_region": "United States",
    "icp_description": (
        "US promotional products distributors, branded merchandise agencies, "
        "corporate gifting suppliers, and trade-show merchandise providers. "
        "Best fit: companies that mention bags, tote bags, cooler bags, backpacks, "
        "trade show giveaways, corporate gifts, or sustainable merchandise."
    ),
    "search_keywords": [
        "promotional products distributor tote bags",
        "branded merchandise distributor cooler bags",
        "corporate gifting company custom bags",
        "trade show giveaways tote bags distributor",
        "custom swag company backpacks",
    ],
    "exclude_customer_types": [
        "retail consumer bag stores",
        "pure apparel decorators with no promotional products",
        "Amazon marketplace sellers",
        "non-US companies",
        "manufacturers competing directly on bags",
    ],
    "contact_titles": [
        "Owner",
        "Founder",
        "President",
        "VP Sales",
        "Sourcing Manager",
        "Purchasing Manager",
        "Account Manager",
    ],
    "scoring_rules": {
        "us_company": 20,
        "promo_distributor_signal": 25,
        "bag_signal": 25,
        "clear_contact": 10,
        "usable_email": 10,
        "active_website": 5,
        "campaign_fit": 5,
    },
    "value_angles": [
        "custom tote/cooler/backpack sourcing for promo distributors",
        "RPET and GRS-certified bag options for ESG-aware corporate gifts",
        "BSCI factory-backed bag production with controlled delivery timeline",
        "bag style guide for seasonal gifting and trade-show programs",
    ],
    "default_template_group": "us_promo_bag_demand",
    "followup_days": [7, 14, 21],
    "daily_send_limit": 10,
    "status": "active",
}


def _json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _table_exists(table_name: str) -> bool:
    try:
        with db_cursor() as (_, cur):
            cur.execute("SELECT to_regclass(%s)", (table_name,))
            return cur.fetchone()[0] is not None
    except Exception as exc:
        _set_db_error(exc)
        return False


def _add_column_if_missing(table: str, column_sql: str) -> bool:
    if not _table_exists(table):
        return False
    return _execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column_sql}")


def _schema_marker_is_current(cur) -> bool:
    cur.execute("SELECT to_regclass('settings')")
    if cur.fetchone()[0] is None:
        return False
    cur.execute("SELECT value FROM settings WHERE key=%s", (SCHEMA_VERSION_KEY,))
    row = cur.fetchone()
    if not row:
        return False
    value = row[0]
    if isinstance(value, dict):
        return value.get("version") == SCHEMA_VERSION_VALUE
    return value == SCHEMA_VERSION_VALUE


def ensure_schema() -> bool:
    """Create the campaign/review foundation and non-destructive legacy columns."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return True
    try:
        with db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT
                    to_regclass('settings') IS NOT NULL
                    AND to_regclass('campaigns') IS NOT NULL
                    AND to_regclass('review_queue') IS NOT NULL
                    AND to_regclass('campaign_reviews') IS NOT NULL
                """
            )
            if cur.fetchone()[0] and _schema_marker_is_current(cur):
                _SCHEMA_READY = True
                clear_db_error()
                return True

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value JSONB,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    id SERIAL PRIMARY KEY,
                    company_name TEXT,
                    contact_name TEXT,
                    email TEXT,
                    website TEXT,
                    location TEXT,
                    company_size TEXT,
                    status TEXT DEFAULT '新建',
                    bag_signal_strength TEXT,
                    bag_signal TEXT,
                    company_direction TEXT,
                    ppai_member BOOLEAN DEFAULT FALSE,
                    owner_topics TEXT,
                    hook_direction TEXT,
                    recommended_cta TEXT,
                    owner_linkedin TEXT,
                    company_linkedin TEXT,
                    linkedin_active TEXT,
                    instagram TEXT,
                    touch_count INTEGER DEFAULT 0,
                    send_date DATE,
                    day7_date DATE,
                    day14_date DATE,
                    day21_date DATE,
                    reactivation_date DATE,
                    last_subject TEXT,
                    notes TEXT,
                    score INTEGER DEFAULT 0,
                    score_grade TEXT DEFAULT 'C',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS email_queue (
                    id SERIAL PRIMARY KEY,
                    queue_id TEXT UNIQUE,
                    lead_id INTEGER,
                    company_name TEXT,
                    to_email TEXT,
                    to_name TEXT,
                    subject TEXT,
                    body TEXT,
                    recipient_tz TEXT,
                    scheduled_utc TIMESTAMPTZ,
                    scheduled_local TEXT,
                    status TEXT DEFAULT 'pending',
                    sent_at TIMESTAMPTZ,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    queued_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS email_history (
                    id SERIAL PRIMARY KEY,
                    lead_id INTEGER,
                    company_name TEXT,
                    to_email TEXT,
                    to_name TEXT,
                    subject TEXT,
                    body TEXT,
                    status TEXT,
                    scheduled_local TEXT,
                    recipient_tz TEXT,
                    sent_at TIMESTAMPTZ DEFAULT NOW(),
                    queue_id TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS followup_notes (
                    id SERIAL PRIMARY KEY,
                    lead_id INTEGER,
                    note_type TEXT,
                    content TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS templates (
                    id SERIAL PRIMARY KEY,
                    name TEXT,
                    category TEXT,
                    touch_number INTEGER DEFAULT 1,
                    customer_type TEXT,
                    subject TEXT,
                    body TEXT,
                    hook TEXT,
                    use_count INTEGER DEFAULT 0,
                    reply_count INTEGER DEFAULT 0,
                    reply_rate NUMERIC DEFAULT 0,
                    is_high_performer BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS discovery_queue (
                    id SERIAL PRIMARY KEY,
                    company_name TEXT,
                    website TEXT,
                    location TEXT,
                    email TEXT,
                    owner_name TEXT,
                    contact_name TEXT,
                    company_size TEXT,
                    research_brief JSONB DEFAULT '{}'::jsonb,
                    snippet TEXT,
                    description TEXT,
                    source TEXT,
                    status TEXT DEFAULT 'pending_review',
                    found_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS campaigns (
                    id SERIAL PRIMARY KEY,
                    campaign_name TEXT NOT NULL UNIQUE,
                    target_segment TEXT,
                    country_region TEXT,
                    icp_description TEXT,
                    search_keywords JSONB DEFAULT '[]'::jsonb,
                    exclude_customer_types JSONB DEFAULT '[]'::jsonb,
                    contact_titles JSONB DEFAULT '[]'::jsonb,
                    scoring_rules JSONB DEFAULT '{}'::jsonb,
                    value_angles JSONB DEFAULT '[]'::jsonb,
                    default_template_group TEXT,
                    followup_days JSONB DEFAULT '[7,14,21]'::jsonb,
                    daily_send_limit INTEGER DEFAULT 10,
                    status TEXT DEFAULT 'draft',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS review_queue (
                    id SERIAL PRIMARY KEY,
                    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
                    item_type TEXT NOT NULL,
                    item_id INTEGER,
                    title TEXT NOT NULL,
                    summary TEXT,
                    payload JSONB DEFAULT '{}'::jsonb,
                    recommendation TEXT,
                    status TEXT DEFAULT 'pending',
                    priority INTEGER DEFAULT 2,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    reviewed_at TIMESTAMPTZ
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS campaign_reviews (
                    id SERIAL PRIMARY KEY,
                    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
                    review_type TEXT NOT NULL,
                    period_start DATE,
                    period_end DATE,
                    metrics JSONB DEFAULT '{}'::jsonb,
                    ai_judgement JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            legacy_columns = {
                "leads": [
                    "campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL",
                    "lead_source TEXT",
                    "qualification_status TEXT DEFAULT 'unreviewed'",
                    "positive_reply BOOLEAN DEFAULT FALSE",
                    "opportunity_status TEXT",
                    "customer_type TEXT",
                    "email_quality TEXT",
                    "last_reply_at TIMESTAMPTZ",
                ],
                "discovery_queue": [
                    "campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL",
                    "score INTEGER DEFAULT 0",
                    "score_grade TEXT DEFAULT 'C'",
                    "score_reason JSONB DEFAULT '{}'::jsonb",
                    "review_decision TEXT",
                    "reviewed_at TIMESTAMPTZ",
                ],
                "email_queue": [
                    "campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL",
                    "requires_approval BOOLEAN DEFAULT TRUE",
                    "approved_at TIMESTAMPTZ",
                    "template_id INTEGER",
                    "touch_number INTEGER DEFAULT 1",
                ],
                "templates": [
                    "campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL",
                    "template_group TEXT",
                    "version INTEGER DEFAULT 1",
                    "enabled BOOLEAN DEFAULT TRUE",
                    "positive_reply_count INTEGER DEFAULT 0",
                    "customer_type TEXT",
                    "hook TEXT",
                    "reply_count INTEGER DEFAULT 0",
                    "reply_rate NUMERIC DEFAULT 0",
                    "use_count INTEGER DEFAULT 0",
                    "is_high_performer BOOLEAN DEFAULT FALSE",
                ],
                "email_history": [
                    "campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL",
                    "template_id INTEGER",
                    "touch_number INTEGER",
                ],
            }
            for table, columns in legacy_columns.items():
                cur.execute("SELECT to_regclass(%s)", (table,))
                if cur.fetchone()[0] is None:
                    continue
                for column_sql in columns:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column_sql}")
            cur.execute(
                """
                INSERT INTO settings (key, value)
                VALUES (%s, %s::jsonb)
                ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()
                """,
                (SCHEMA_VERSION_KEY, json.dumps({"version": SCHEMA_VERSION_VALUE})),
            )
            conn.commit()

        get_or_create_default_campaign()
        _SCHEMA_READY = True
        return True
    except Exception as exc:
        _set_db_error(exc)
        return False


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_campaigns(status: Optional[str] = None):
    ensure_schema()
    if status:
        return _fetch_all("SELECT * FROM campaigns WHERE status=%s ORDER BY created_at DESC", (status,))
    return _fetch_all("SELECT * FROM campaigns ORDER BY created_at DESC")


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_campaign(campaign_id: int):
    ensure_schema()
    return _fetch_one("SELECT * FROM campaigns WHERE id=%s", (campaign_id,))


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_campaign_by_name(campaign_name: str):
    ensure_schema()
    return _fetch_one("SELECT * FROM campaigns WHERE campaign_name=%s", (campaign_name,))


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_or_create_default_campaign():
    ensure_schema_without_default = getattr(get_or_create_default_campaign, "_in_progress", False)
    if ensure_schema_without_default:
        return None
    get_or_create_default_campaign._in_progress = True
    try:
        row = _fetch_one(
            "SELECT * FROM campaigns WHERE campaign_name=%s",
            (DEFAULT_CAMPAIGN["campaign_name"],),
        )
        if row:
            return row
        with db_cursor(dict_rows=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO campaigns (
                    campaign_name, target_segment, country_region, icp_description,
                    search_keywords, exclude_customer_types, contact_titles,
                    scoring_rules, value_angles, default_template_group,
                    followup_days, daily_send_limit, status
                )
                VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s,%s)
                RETURNING *
                """,
                (
                    DEFAULT_CAMPAIGN["campaign_name"],
                    DEFAULT_CAMPAIGN["target_segment"],
                    DEFAULT_CAMPAIGN["country_region"],
                    DEFAULT_CAMPAIGN["icp_description"],
                    _json_dumps(DEFAULT_CAMPAIGN["search_keywords"]),
                    _json_dumps(DEFAULT_CAMPAIGN["exclude_customer_types"]),
                    _json_dumps(DEFAULT_CAMPAIGN["contact_titles"]),
                    _json_dumps(DEFAULT_CAMPAIGN["scoring_rules"]),
                    _json_dumps(DEFAULT_CAMPAIGN["value_angles"]),
                    DEFAULT_CAMPAIGN["default_template_group"],
                    _json_dumps(DEFAULT_CAMPAIGN["followup_days"]),
                    DEFAULT_CAMPAIGN["daily_send_limit"],
                    DEFAULT_CAMPAIGN["status"],
                ),
            )
            row = dict(cur.fetchone())
            conn.commit()
            return row
    except Exception as exc:
        _set_db_error(exc)
        return None
    finally:
        get_or_create_default_campaign._in_progress = False


def add_campaign(data: dict) -> Optional[int]:
    ensure_schema()
    payload = {**DEFAULT_CAMPAIGN, **data}
    try:
        with db_cursor() as (conn, cur):
            cur.execute(
                """
                INSERT INTO campaigns (
                    campaign_name, target_segment, country_region, icp_description,
                    search_keywords, exclude_customer_types, contact_titles,
                    scoring_rules, value_angles, default_template_group,
                    followup_days, daily_send_limit, status
                )
                VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s,%s)
                RETURNING id
                """,
                (
                    payload.get("campaign_name"),
                    payload.get("target_segment"),
                    payload.get("country_region"),
                    payload.get("icp_description"),
                    _json_dumps(payload.get("search_keywords", [])),
                    _json_dumps(payload.get("exclude_customer_types", [])),
                    _json_dumps(payload.get("contact_titles", [])),
                    _json_dumps(payload.get("scoring_rules", {})),
                    _json_dumps(payload.get("value_angles", [])),
                    payload.get("default_template_group"),
                    _json_dumps(payload.get("followup_days", [7, 14, 21])),
                    int(payload.get("daily_send_limit", 10)),
                    payload.get("status", "draft"),
                ),
            )
            campaign_id = cur.fetchone()[0]
            conn.commit()
            return campaign_id
    except Exception as exc:
        _set_db_error(exc)
        return None


def update_campaign(campaign_id: int, **kwargs) -> bool:
    ensure_schema()
    allowed_json = {"search_keywords", "exclude_customer_types", "contact_titles", "scoring_rules", "value_angles", "followup_days"}
    allowed_scalar = {
        "campaign_name", "target_segment", "country_region", "icp_description",
        "default_template_group", "daily_send_limit", "status",
    }
    updates = {}
    for key, value in kwargs.items():
        if key in allowed_json:
            updates[key] = json.dumps(value if value is not None else [], ensure_ascii=False)
        elif key in allowed_scalar:
            updates[key] = value
    if not updates:
        return False
    parts = []
    values = []
    for key, value in updates.items():
        if key in allowed_json:
            parts.append(f"{key}=%s::jsonb")
        else:
            parts.append(f"{key}=%s")
        values.append(value)
    parts.append("updated_at=NOW()")
    values.append(campaign_id)
    return _execute(f"UPDATE campaigns SET {', '.join(parts)} WHERE id=%s", tuple(values))


def _as_text_blob(candidate: dict) -> str:
    parts = [
        candidate.get("company_name", ""),
        candidate.get("website", ""),
        candidate.get("location", ""),
        candidate.get("email", ""),
        candidate.get("research_brief", ""),
        candidate.get("snippet", ""),
        candidate.get("description", ""),
    ]
    return " ".join(str(p) for p in parts if p).lower()


def _normalize_website(url: str) -> str:
    if not url:
        return ""
    raw = str(url).strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    host = (parsed.netloc or parsed.path).lower()
    if host.startswith("www."):
        host = host[4:]
    return host.rstrip("/")


def candidate_exists(company_name: str = "", website: str = "") -> bool:
    normalized_site = _normalize_website(website)
    normalized_name = str(company_name or "").strip().lower()
    if not normalized_site and not normalized_name:
        return False
    try:
        with db_cursor() as (_, cur):
            if normalized_site:
                pattern = f"%{normalized_site}%"
                cur.execute(
                    """
                    SELECT
                        EXISTS (SELECT 1 FROM discovery_queue WHERE LOWER(COALESCE(website,'')) LIKE %s)
                        OR EXISTS (SELECT 1 FROM leads WHERE LOWER(COALESCE(website,'')) LIKE %s)
                    """,
                    (pattern, pattern),
                )
                if cur.fetchone()[0]:
                    return True
            if normalized_name:
                cur.execute(
                    """
                    SELECT
                        EXISTS (SELECT 1 FROM discovery_queue WHERE LOWER(TRIM(COALESCE(company_name,''))) = %s)
                        OR EXISTS (SELECT 1 FROM leads WHERE LOWER(TRIM(COALESCE(company_name,''))) = %s)
                    """,
                    (normalized_name, normalized_name),
                )
                return bool(cur.fetchone()[0])
    except Exception as exc:
        _set_db_error(exc)
        return False
    return False


def score_candidate(candidate: dict, campaign: Optional[dict] = None) -> dict:
    campaign = campaign or DEFAULT_CAMPAIGN
    text = _as_text_blob(candidate)
    website = str(candidate.get("website", "")).lower()
    email = str(candidate.get("email", "")).lower()

    score = 0
    reasons = []

    if "united states" in text or " usa" in text or any(f" {s.lower()} " in f" {text} " for s in ["tx", "ca", "fl", "ny", "il", "co", "ga", "nc", "oh", "pa", "mi", "wa"]):
        score += 20
        reasons.append("US signal")

    promo_terms = ["promotional products", "branded merchandise", "advertising specialty", "corporate gifts", "swag", "trade show"]
    if any(term in text for term in promo_terms):
        score += 25
        reasons.append("promo distributor signal")

    bag_terms = ["bag", "bags", "tote", "tote bags", "cooler bags", "backpacks", "drawstring", "duffel"]
    if any(term in text for term in bag_terms):
        score += 25
        reasons.append("bag demand signal")

    if candidate.get("owner_name") or candidate.get("contact_name"):
        score += 10
        reasons.append("clear contact")

    if "@" in email and "." in email:
        score += 10
        reasons.append("usable email")

    if website.startswith("http"):
        score += 5
        reasons.append("active website")

    keywords = campaign.get("search_keywords") or []
    if isinstance(keywords, str):
        try:
            keywords = json.loads(keywords)
        except Exception:
            keywords = []
    if any(str(term).lower().split()[0] in text for term in keywords if str(term).strip()):
        score += 5
        reasons.append("campaign keyword fit")

    grade = "A" if score >= 70 else ("B" if score >= 45 else "C")
    return {"score": score, "score_grade": grade, "score_reason": {"reasons": reasons}}


def add_discovery_candidate_for_campaign(data: dict, campaign_id: Optional[int] = None) -> bool:
    ensure_schema()
    if candidate_exists(data.get("company_name", ""), data.get("website", "")):
        return False
    campaign = get_campaign(campaign_id) if campaign_id else get_or_create_default_campaign()
    score = score_candidate(data, campaign)
    payload = {
        **data,
        "campaign_id": campaign.get("id") if campaign else campaign_id,
        "score": score["score"],
        "score_grade": score["score_grade"],
        "score_reason": score["score_reason"],
        "status": data.get("status", "pending_review"),
    }
    ok = add_discovery_candidate(payload)
    if ok:
        create_review_item(
            campaign_id=payload.get("campaign_id"),
            item_type="candidate_company",
            item_id=None,
            title=payload.get("company_name", "Unnamed candidate"),
            summary=f"{payload.get('score_grade')}级 / {payload.get('score')}分 / {payload.get('website','')}",
            payload=payload,
            recommendation="A级直接优先审核；B级补充联系人/邮箱后再决定；C级默认放弃或稍后看。",
            priority=1 if payload.get("score_grade") == "A" else 2,
        )
    return ok


def create_review_item(campaign_id: Optional[int], item_type: str, item_id: Optional[int],
                       title: str, summary: str = "", payload: Optional[dict] = None,
                       recommendation: str = "", priority: int = 2) -> Optional[int]:
    ensure_schema()
    try:
        with db_cursor() as (conn, cur):
            cur.execute(
                """
                INSERT INTO review_queue (
                    campaign_id, item_type, item_id, title, summary, payload,
                    recommendation, status, priority
                )
                VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,'pending',%s)
                RETURNING id
                """,
                (campaign_id, item_type, item_id, title, summary, _json_dumps(payload or {}), recommendation, priority),
            )
            review_id = cur.fetchone()[0]
            conn.commit()
            return review_id
    except Exception as exc:
        _set_db_error(exc)
        return None


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_review_queue(status: str = "pending", item_type: Optional[str] = None, campaign_id: Optional[int] = None):
    ensure_schema()
    query = "SELECT rq.*, c.campaign_name FROM review_queue rq LEFT JOIN campaigns c ON c.id=rq.campaign_id WHERE rq.status=%s"
    params: list[Any] = [status]
    if item_type:
        query += " AND rq.item_type=%s"
        params.append(item_type)
    if campaign_id:
        query += " AND rq.campaign_id=%s"
        params.append(campaign_id)
    query += " ORDER BY rq.priority ASC, rq.created_at ASC"
    return _fetch_all(query, tuple(params))


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_review_counts(status: str = "pending", campaign_id: Optional[int] = None) -> dict[str, int]:
    ensure_schema()
    query = "SELECT item_type, COUNT(*) AS count FROM review_queue WHERE status=%s"
    params: list[Any] = [status]
    if campaign_id:
        query += " AND campaign_id=%s"
        params.append(campaign_id)
    query += " GROUP BY item_type"
    rows = _fetch_all(query, tuple(params))
    return {row["item_type"]: int(row["count"]) for row in rows}


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_candidate_email_counts(campaign_id: Optional[int] = None) -> dict[str, int]:
    ensure_schema()
    query = """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE COALESCE(email, '') <> '') AS with_email,
            COUNT(*) FILTER (WHERE COALESCE(email, '') = '') AS missing_email
        FROM discovery_queue
        WHERE status='pending_review'
    """
    params: tuple[Any, ...] = ()
    if campaign_id:
        query += " AND campaign_id=%s"
        params = (campaign_id,)
    row = _fetch_one(query, params) or {}
    return {
        "total": int(row.get("total") or 0),
        "with_email": int(row.get("with_email") or 0),
        "missing_email": int(row.get("missing_email") or 0),
    }


def update_review_item(review_id: int, status: str, payload_update: Optional[dict] = None) -> bool:
    ensure_schema()
    if payload_update:
        item = _fetch_one("SELECT payload FROM review_queue WHERE id=%s", (review_id,))
        payload = item.get("payload") if item else {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        payload.update(payload_update)
        return _execute(
            "UPDATE review_queue SET status=%s, payload=%s::jsonb, reviewed_at=NOW(), updated_at=NOW() WHERE id=%s",
            (status, _json_dumps(payload), review_id),
        )
    return _execute(
        "UPDATE review_queue SET status=%s, reviewed_at=NOW(), updated_at=NOW() WHERE id=%s",
        (status, review_id),
    )


def approve_candidate_review(review_id: int, contact_name: str = "", email: str = "", company_size: str = "") -> Optional[int]:
    ensure_schema()
    item = _fetch_one("SELECT * FROM review_queue WHERE id=%s", (review_id,))
    if not item:
        return None
    payload = item.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    if email:
        payload["email"] = email
    if contact_name:
        payload["contact_name"] = contact_name
    if company_size:
        payload["company_size"] = company_size
    lead_data = {
        "campaign_id": item.get("campaign_id"),
        "company_name": payload.get("company_name", ""),
        "contact_name": payload.get("contact_name") or payload.get("owner_name") or contact_name,
        "email": payload.get("email", ""),
        "website": payload.get("website", ""),
        "location": payload.get("location", ""),
        "company_size": payload.get("company_size", company_size),
        "status": "新建",
        "bag_signal_strength": "强" if payload.get("score_grade") == "A" else "中",
        "score": payload.get("score", 0),
        "score_grade": payload.get("score_grade", "C"),
        "lead_source": "review_queue",
        "qualification_status": "approved",
        "customer_type": payload.get("customer_type", ""),
    }
    lead_id = add_lead(lead_data)
    if lead_id:
        update_review_item(review_id, "approved", {"lead_id": lead_id})
        create_review_item(
            campaign_id=item.get("campaign_id"),
            item_type="first_email",
            item_id=lead_id,
            title=f"首封开发信待审核 - {lead_data['company_name']}",
            summary="客户已确认进入开发流程。下一步需要生成或审核首封邮件。",
            payload={"lead_id": lead_id, "company_name": lead_data["company_name"], "email": lead_data["email"]},
            recommendation="先用当前 campaign 的 value angle 写一封不超过120词的首封信，批准后再入发送队列。",
            priority=1,
        )
    return lead_id


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_campaign_metrics(campaign_id: Optional[int] = None) -> dict:
    ensure_schema()
    campaign_filter = "WHERE campaign_id=%s" if campaign_id else ""
    params = (campaign_id,) if campaign_id else ()
    metrics = {
        "candidates": 0,
        "qualified": 0,
        "grade_a": 0,
        "grade_b": 0,
        "grade_c": 0,
        "sent": 0,
        "bounced": 0,
        "replied": 0,
        "positive_replied": 0,
        "opportunities": 0,
        "pending_reviews": 0,
    }
    try:
        with db_cursor() as (_, cur):
            if _table_exists("discovery_queue"):
                cur.execute(f"SELECT COUNT(*) FROM discovery_queue {campaign_filter}", params)
                metrics["candidates"] = cur.fetchone()[0]
                for grade in ["A", "B", "C"]:
                    cur.execute(f"SELECT COUNT(*) FROM discovery_queue {campaign_filter + (' AND ' if campaign_filter else 'WHERE ')} score_grade=%s", params + (grade,))
                    metrics[f"grade_{grade.lower()}"] = cur.fetchone()[0]
            if _table_exists("leads"):
                cur.execute(f"SELECT COUNT(*) FROM leads {campaign_filter}", params)
                metrics["qualified"] = cur.fetchone()[0]
                cur.execute(f"SELECT COUNT(*) FROM leads {campaign_filter + (' AND ' if campaign_filter else 'WHERE ')} status='退信'", params)
                metrics["bounced"] = cur.fetchone()[0]
                cur.execute(f"SELECT COUNT(*) FROM leads {campaign_filter + (' AND ' if campaign_filter else 'WHERE ')} status='有回复'", params)
                metrics["replied"] = cur.fetchone()[0]
                cur.execute(f"SELECT COUNT(*) FROM leads {campaign_filter + (' AND ' if campaign_filter else 'WHERE ')} positive_reply=TRUE", params)
                metrics["positive_replied"] = cur.fetchone()[0]
                cur.execute(f"SELECT COUNT(*) FROM leads {campaign_filter + (' AND ' if campaign_filter else 'WHERE ')} opportunity_status IS NOT NULL", params)
                metrics["opportunities"] = cur.fetchone()[0]
            if _table_exists("email_history"):
                cur.execute(f"SELECT COUNT(*) FROM email_history {campaign_filter}", params)
                metrics["sent"] = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM review_queue WHERE status='pending' AND (%s IS NULL OR campaign_id=%s)",
                (campaign_id, campaign_id),
            )
            metrics["pending_reviews"] = cur.fetchone()[0]
    except Exception as exc:
        _set_db_error(exc)
    sent = metrics["sent"] or 0
    metrics["reply_rate"] = round(metrics["replied"] / sent * 100, 2) if sent else 0
    metrics["positive_reply_rate"] = round(metrics["positive_replied"] / sent * 100, 2) if sent else 0
    metrics["bounce_rate"] = round(metrics["bounced"] / sent * 100, 2) if sent else 0
    return metrics


def judge_campaign_health(metrics: dict) -> dict:
    sent = metrics.get("sent", 0)
    candidates = metrics.get("candidates", 0)
    reply_rate = metrics.get("reply_rate", 0)
    positive_rate = metrics.get("positive_reply_rate", 0)
    bounce_rate = metrics.get("bounce_rate", 0)
    qualified = metrics.get("qualified", 0)

    evidence = [
        f"候选客户 {candidates} 个",
        f"合格进入开发 {qualified} 个",
        f"已发送 {sent} 封",
        f"退信率 {bounce_rate}%",
        f"回复率 {reply_rate}%",
        f"正向回复率 {positive_rate}%",
    ]

    if sent < 30:
        decision = "继续测试"
        bottleneck = "发送量不足，样本不够判断"
        confidence = "低"
        next_action = "先完成30封以上经人工审核的首封邮件，再判断是否加码。"
    elif bounce_rate > 12:
        decision = "暂停放量"
        bottleneck = "邮箱质量或客户数据质量"
        confidence = "中"
        next_action = "暂停增加发送量，优先修正邮箱来源和联系人确认流程。"
    elif reply_rate >= 5 and positive_rate >= 1.5:
        decision = "加码"
        bottleneck = "需要扩大A/B级客户供给"
        confidence = "中"
        next_action = "扩大候选搜索，保留表现好的hook，提升每日上限前先监控退信率。"
    elif reply_rate >= 2:
        decision = "保持低频开发"
        bottleneck = "话术或客户细分还需优化"
        confidence = "中"
        next_action = "维持每日10-20封，测试2-3个更具体的bag demand hook。"
    else:
        decision = "调整后再测"
        bottleneck = "客户质量或邮件hook可能不匹配"
        confidence = "中"
        next_action = "先复盘A/B级客户和邮件hook，不建议直接放量。"

    return {
        "decision": decision,
        "bottleneck": bottleneck,
        "confidence": confidence,
        "evidence": evidence,
        "risk": "当前判断只基于系统内真实记录；如果发送/回复记录不完整，结论会偏弱。",
        "next_action": next_action,
    }


@st.cache_data(ttl=READ_CACHE_TTL, show_spinner=False)
def get_mission_control() -> dict:
    ensure_schema()
    campaign = get_or_create_default_campaign()
    campaign_id = campaign.get("id") if campaign else None
    metrics = get_campaign_metrics(campaign_id)
    due = get_due_followups()
    counts = get_review_counts("pending", campaign_id=campaign_id)
    candidate_email_counts = get_candidate_email_counts(campaign_id)
    reviews = get_review_queue("pending", campaign_id=campaign_id)
    preview_reviews = reviews[:20]
    queue = get_all_queue()
    pending_email_reviews = [r for r in preview_reviews if r.get("item_type") in {"first_email", "followup_email"}]
    candidate_reviews = [r for r in preview_reviews if r.get("item_type") == "candidate_company"]
    reply_reviews = [r for r in preview_reviews if r.get("item_type") == "reply"]
    return {
        "campaign": campaign,
        "metrics": metrics,
        "judgement": judge_campaign_health(metrics),
        "review_counts": counts,
        "candidate_email_counts": candidate_email_counts,
        "due_followups": due,
        "pending_queue": [q for q in queue if q.get("status") == "pending"],
        "candidate_reviews": candidate_reviews,
        "email_reviews": pending_email_reviews,
        "reply_reviews": reply_reviews,
        "reviews": reviews,
    }
