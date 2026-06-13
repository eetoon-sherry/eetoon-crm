"""Operational health checks for the CRM."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from utils import database as db
from utils.email_monitor import get_imap_config
from utils.email_sender import get_smtp_config, send_now


REQUIRED_TABLES = [
    "settings",
    "leads",
    "email_queue",
    "email_history",
    "followup_notes",
    "templates",
    "discovery_queue",
    "campaigns",
    "review_queue",
    "campaign_reviews",
]


def _row(name: str, status: str, details: str = "", action: str = "") -> dict[str, str]:
    return {"检查项": name, "状态": status, "说明": details, "需要动作": action}


def run_health_checks() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    db_connected = False

    if db.has_db_config():
        rows.append(_row("Streamlit Supabase Secrets", "已配置", "[supabase] 连接字段存在"))
    else:
        rows.append(_row(
            "Streamlit Supabase Secrets",
            "缺失",
            "应用没有可用数据库连接信息",
            "Streamlit Cloud -> app -> Settings/Secrets 填 [supabase].db_host 和 [supabase].db_password",
        ))

    try:
        with db.db_cursor() as (_, cur):
            cur.execute("SELECT 1")
            cur.fetchone()
        rows.append(_row("Supabase 连接", "正常", "Postgres SELECT 1 成功"))
        db_connected = True
    except Exception as exc:
        rows.append(_row("Supabase 连接", "失败", str(exc)[:180], "检查 Supabase 数据库密码、host、网络白名单/连接池设置"))

    if db_connected:
        schema_ok = db.ensure_schema()
        rows.append(_row("Campaign schema", "正常" if schema_ok else "失败", "campaign/review 表和兼容字段已检查"))

        for table in REQUIRED_TABLES:
            exists = db._table_exists(table)
            rows.append(_row(f"数据表: {table}", "存在" if exists else "缺失", "", "需要运行 schema 初始化或检查旧数据库" if not exists else ""))

        try:
            with db.db_cursor() as (conn, cur):
                key = f"health_check_{int(datetime.now(timezone.utc).timestamp())}"
                cur.execute(
                    "INSERT INTO settings (key, value) VALUES (%s, %s::jsonb) ON CONFLICT (key) DO NOTHING",
                    (key, '{"ok": true}'),
                )
                cur.execute("SELECT value FROM settings WHERE key=%s", (key,))
                ok = cur.fetchone() is not None
                cur.execute("DELETE FROM settings WHERE key=%s", (key,))
                conn.commit()
            rows.append(_row("数据库读写", "正常" if ok else "失败", "settings 临时写入/读取/删除测试"))
        except Exception as exc:
            rows.append(_row("数据库读写", "失败", str(exc)[:180], "检查数据库权限和 settings 表"))
    else:
        rows.append(_row("Campaign schema", "未检查", "Supabase 未连接，无法检查或创建表", "先修复 Streamlit Supabase Secrets"))
        for table in REQUIRED_TABLES:
            rows.append(_row(f"数据表: {table}", "未检查", "Supabase 未连接", "先修复数据库连接"))
        rows.append(_row("数据库读写", "未检查", "Supabase 未连接", "先修复数据库连接"))

    try:
        get_smtp_config()
        rows.append(_row("SMTP 配置", "已配置", "[smtp] 或 SMTP_* 环境变量存在"))
    except Exception as exc:
        rows.append(_row("SMTP 配置", "缺失/失败", str(exc), "Streamlit Secrets 填 [smtp].host/port/user/password/sender_name/bcc"))

    try:
        get_imap_config()
        rows.append(_row("IMAP 配置", "已配置", "[imap] 或 IMAP_* 环境变量存在"))
    except Exception as exc:
        rows.append(_row("IMAP 配置", "缺失/失败", str(exc), "Streamlit Secrets 填 [imap].host/port/user/password"))

    return rows


def send_test_email(to_email: str) -> tuple[bool, str]:
    if not to_email:
        return False, "需要填写测试收件邮箱"
    subject = "[EETOON CRM] SMTP test"
    body = "This is a controlled SMTP test from EETOON CRM."
    return send_now(to_email, "Test", subject, body)
