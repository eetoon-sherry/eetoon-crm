#!/usr/bin/env python3
"""Daily follow-up reminder — sends digest email to Sherry's Gmail."""

import os, ssl, smtplib, psycopg2, psycopg2.extras
from datetime import date, timedelta
from email.mime.text import MIMEText

DB_HOST     = os.environ['DB_HOST']
DB_PASSWORD = os.environ['DB_PASSWORD']
SMTP_HOST   = os.environ.get('SMTP_HOST', 'smtp.qiye.163.com')
SMTP_PORT   = int(os.environ.get('SMTP_PORT', '465'))
SMTP_USER   = os.environ['SMTP_USER']
SMTP_PASS   = os.environ['SMTP_PASS']
NOTIFY_EMAIL = os.environ.get('NOTIFY_EMAIL', 'sherry995995@gmail.com')


def get_conn():
    return psycopg2.connect(
        host=os.environ.get('DB_HOST', 'aws-0-ap-southeast-1.pooler.supabase.com'),
        port=int(os.environ.get('DB_PORT', '6543')),
        dbname='postgres',
        user=os.environ.get('DB_USER', 'postgres.gnqddnujljyqjsfjrrri'),
        password=DB_PASSWORD,
        connect_timeout=15,
        sslmode='require'
    )


def main():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    today = date.today()

    # Due follow-ups
    cur.execute("""
        SELECT company_name, contact_name, email, touch_count,
               day7_date, day14_date, day21_date, last_subject,
               hook_direction, recommended_cta, score_grade, score
        FROM leads
        WHERE status NOT IN ('有回复','无意向','退信','冷静期-90天后重新激活')
        AND touch_count < 3
        AND (
            (day7_date <= %s AND touch_count = 1) OR
            (day14_date <= %s AND touch_count = 2) OR
            (day21_date <= %s AND touch_count = 3)
        )
        ORDER BY score DESC
    """, (today, today, today))
    due = cur.fetchall()

    # Cold period due
    cur.execute("""
        SELECT company_name, contact_name, reactivation_date, score_grade
        FROM leads
        WHERE status = '冷静期-90天后重新激活'
        AND reactivation_date <= %s
    """, (today,))
    reactivation = cur.fetchall()

    # Seasonal triggers
    cur.execute("SELECT value FROM settings WHERE key='seasonal_triggers'")
    seasonal_row = cur.fetchone()
    seasonal = seasonal_row['value'] if seasonal_row else []
    seasonal_alerts = []
    for trigger in (seasonal or []):
        if trigger.get('month') == today.month and trigger.get('day') == today.day:
            seasonal_alerts.append(trigger)

    cur.close()
    conn.close()

    if not due and not reactivation and not seasonal_alerts:
        print("No reminders to send today.")
        return

    # Build email
    lines = [f"📋 EETOON CRM 每日提醒 — {today}", "=" * 50, ""]

    if due:
        lines.append(f"⏰ 今日到期跟进（{len(due)}家）：")
        lines.append("")
        for lead in due:
            touch = lead['touch_count']
            next_n = touch + 1
            lines.append(f"  【第{next_n}封】{lead['company_name']}")
            lines.append(f"    联系人: {lead.get('contact_name','')}")
            lines.append(f"    邮件: {lead.get('email','')}")
            lines.append(f"    评分: {lead.get('score_grade','C')}({lead.get('score',0)}分)")
            lines.append(f"    上封主题: {lead.get('last_subject','—')}")
            if lead.get('hook_direction'):
                lines.append(f"    建议角度: {lead.get('hook_direction','')[:80]}")
            if lead.get('recommended_cta'):
                lines.append(f"    推荐CTA: {lead.get('recommended_cta','')}")
            lines.append("")

    if reactivation:
        lines.append(f"❄️ 冷静期到期，建议重新激活（{len(reactivation)}家）：")
        for lead in reactivation:
            lines.append(f"  • {lead['company_name']} ({lead.get('contact_name','')}) | 激活日：{lead.get('reactivation_date','')}")
        lines.append("")

    if seasonal_alerts:
        lines.append("🌟 季节性提醒：")
        for alert in seasonal_alerts:
            lines.append(f"  ⚡ {alert.get('name','')}: {alert.get('message','')}")
        lines.append("")

    lines.append("---")
    lines.append("前往系统处理：https://eetoon-crm.streamlit.app")

    body = "\n".join(lines)

    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = f"[EETOON CRM] {today} 每日提醒 — {len(due)}个跟进待处理"
    msg['From'] = f"EETOON CRM <{SMTP_USER}>"
    msg['To'] = NOTIFY_EMAIL

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [NOTIFY_EMAIL], msg.as_string())

    print(f"✅ Reminder sent to {NOTIFY_EMAIL}: {len(due)} followups, {len(reactivation)} reactivations")


if __name__ == '__main__':
    main()
