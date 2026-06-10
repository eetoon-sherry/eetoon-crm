"""Supabase database operations for EETOON CRM."""

import psycopg2
import psycopg2.extras
import json
import streamlit as st
from datetime import date, datetime
from typing import Optional


def get_conn():
    try:
        db = st.secrets["supabase"]
        return psycopg2.connect(
            host=db["db_host"], port=5432,
            dbname="postgres", user="postgres",
            password=db["db_password"], connect_timeout=10
        )
    except Exception:
        import os
        return psycopg2.connect(
            host="db.gnqddnujljyqjsfjrrri.supabase.co",
            port=5432, dbname="postgres", user="postgres",
            password="Eetoon@995995", connect_timeout=10
        )


def get_setting(key: str, default=None):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = %s", (key,))
        row = cur.fetchone()
        cur.close(); conn.close()
        return row[0] if row else default
    except Exception:
        return default


def set_setting(key: str, value):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO settings (key, value) VALUES (%s, %s::jsonb) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
        (key, json.dumps(value))
    )
    conn.commit(); cur.close(); conn.close()


def get_all_leads(status_filter=None):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if status_filter:
        cur.execute("SELECT * FROM leads WHERE status = %s ORDER BY score DESC, created_at DESC", (status_filter,))
    else:
        cur.execute("SELECT * FROM leads ORDER BY score DESC, created_at DESC")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def get_lead(lead_id: int):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM leads WHERE id = %s", (lead_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def get_lead_by_email(email: str):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM leads WHERE email = %s", (email,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def update_lead(lead_id: int, **kwargs):
    if not kwargs:
        return
    kwargs['updated_at'] = datetime.now()
    set_clause = ", ".join(f"{k} = %s" for k in kwargs)
    values = list(kwargs.values()) + [lead_id]
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE leads SET {set_clause} WHERE id = %s", values)
    conn.commit(); cur.close(); conn.close()


def update_lead_status(lead_id: int, status: str, note: str = ""):
    update_lead(lead_id, status=status)
    if note:
        add_note(lead_id, "status_change", note)


def add_lead(data: dict) -> Optional[int]:
    conn = get_conn()
    cur = conn.cursor()
    cols = ", ".join(data.keys())
    vals = ", ".join(["%s"] * len(data))
    try:
        cur.execute(
            f"INSERT INTO leads ({cols}) VALUES ({vals}) RETURNING id",
            list(data.values())
        )
        lead_id = cur.fetchone()[0]
        conn.commit()
        cur.close(); conn.close()
        return lead_id
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        cur.close(); conn.close()
        return None


def get_email_history(lead_id: int):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM email_history WHERE lead_id = %s ORDER BY sent_at DESC", (lead_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def add_email_history(data: dict):
    conn = get_conn()
    cur = conn.cursor()
    cols = ", ".join(data.keys())
    vals = ", ".join(["%s"] * len(data))
    cur.execute(f"INSERT INTO email_history ({cols}) VALUES ({vals})", list(data.values()))
    conn.commit(); cur.close(); conn.close()


def get_pending_queue():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM email_queue WHERE status = 'pending' ORDER BY scheduled_utc ASC")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def get_all_queue():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM email_queue ORDER BY queued_at DESC LIMIT 100")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def add_to_queue(data: dict):
    conn = get_conn()
    cur = conn.cursor()
    cols = ", ".join(data.keys())
    vals = ", ".join(["%s"] * len(data))
    cur.execute(
        f"INSERT INTO email_queue ({cols}) VALUES ({vals}) ON CONFLICT (queue_id) DO NOTHING",
        list(data.values())
    )
    conn.commit(); cur.close(); conn.close()


def update_queue_status(queue_id: str, status: str, error: str = None):
    conn = get_conn()
    cur = conn.cursor()
    if status == 'sent':
        cur.execute("UPDATE email_queue SET status='sent', sent_at=NOW() WHERE queue_id=%s", (queue_id,))
    elif status == 'failed':
        cur.execute(
            "UPDATE email_queue SET status='failed', error_message=%s, retry_count=retry_count+1 WHERE queue_id=%s",
            (error, queue_id)
        )
    conn.commit(); cur.close(); conn.close()


def get_due_followups(check_date=None):
    check_date = check_date or date.today()
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT * FROM leads
        WHERE status NOT IN ('有回复','无意向','退信','冷静期-90天后重新激活')
        AND touch_count < 3
        AND (
            (day7_date <= %s AND touch_count = 1) OR
            (day14_date <= %s AND touch_count = 2) OR
            (day21_date <= %s AND touch_count = 3)
        )
        ORDER BY score DESC
    """, (check_date, check_date, check_date))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def get_reactivation_due(check_date=None):
    check_date = check_date or date.today()
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT * FROM leads
        WHERE status = '冷静期-90天后重新激活'
        AND reactivation_date <= %s
        ORDER BY score DESC
    """, (check_date,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def add_note(lead_id: int, note_type: str, content: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO followup_notes (lead_id, note_type, content) VALUES (%s, %s, %s)",
        (lead_id, note_type, content)
    )
    conn.commit(); cur.close(); conn.close()


def get_notes(lead_id: int):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM followup_notes WHERE lead_id = %s ORDER BY created_at DESC", (lead_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def get_templates(category=None, touch_number=None):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    query = "SELECT * FROM templates WHERE 1=1"
    params = []
    if category:
        query += " AND category = %s"; params.append(category)
    if touch_number:
        query += " AND touch_number = %s"; params.append(touch_number)
    query += " ORDER BY reply_rate DESC, use_count DESC"
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def add_template(data: dict):
    conn = get_conn()
    cur = conn.cursor()
    cols = ", ".join(data.keys())
    vals = ", ".join(["%s"] * len(data))
    cur.execute(f"INSERT INTO templates ({cols}) VALUES ({vals})", list(data.values()))
    conn.commit(); cur.close(); conn.close()


def get_stats():
    conn = get_conn()
    cur = conn.cursor()
    stats = {}
    cur.execute("SELECT COUNT(*) FROM leads")
    stats['total'] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM leads WHERE status LIKE '已发送%'")
    stats['active'] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM leads WHERE status = '有回复'")
    stats['replied'] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM leads WHERE status = '冷静期-90天后重新激活'")
    stats['cold'] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM leads WHERE status = '无意向'")
    stats['no_interest'] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM leads WHERE status = '退信'")
    stats['bounced'] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM email_queue WHERE status = 'pending'")
    stats['pending_emails'] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM email_history")
    stats['total_sent'] = cur.fetchone()[0]
    cur.close(); conn.close()
    return stats


def get_discovery_queue(status='pending_review'):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM discovery_queue WHERE status = %s ORDER BY found_at DESC", (status,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def add_discovery_candidate(data: dict):
    conn = get_conn()
    cur = conn.cursor()
    cols = ", ".join(data.keys())
    vals = ", ".join(["%s"] * len(data))
    cur.execute(f"INSERT INTO discovery_queue ({cols}) VALUES ({vals})", list(data.values()))
    conn.commit(); cur.close(); conn.close()
