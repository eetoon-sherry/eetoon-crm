#!/usr/bin/env python3
"""Daily follow-up reminder — uses Supabase REST API."""

import os, ssl, smtplib, json
from datetime import date
from email.mime.text import MIMEText
import urllib.request, urllib.error

def required_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


SUPABASE_URL = required_env('SUPABASE_URL').rstrip('/')
SUPABASE_KEY = required_env('SUPABASE_SERVICE_KEY')
SMTP_HOST    = os.environ.get('SMTP_HOST', 'smtp.qiye.163.com')
SMTP_PORT    = int(os.environ.get('SMTP_PORT', '465'))
SMTP_USER    = os.environ.get('SMTP_USER', '')
SMTP_PASS    = os.environ.get('SMTP_PASS', '')
NOTIFY_EMAIL = os.environ.get('NOTIFY_EMAIL', '')


def sb_get(path, params=None):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    if params:
        url += '?' + '&'.join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, headers={
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"Error: {e}")
        return []


def get_setting(key, default=None):
    rows = sb_get('settings', {'key': f'eq.{key}', 'select': 'value'})
    return rows[0]['value'] if rows else default


def main():
    if not SMTP_USER or not SMTP_PASS or not NOTIFY_EMAIL:
        print("Reminder email skipped: SMTP_USER, SMTP_PASS, or NOTIFY_EMAIL is not configured.")
        return

    today = date.today()
    today_iso = str(today)

    cold_statuses = '有回复,无意向,退信,冷静期-90天后重新激活'

    # Get due followups
    all_leads = sb_get('leads', {
        'status': f'not.in.({cold_statuses})',
        'touch_count': 'lt.3',
        'select': 'company_name,contact_name,email,touch_count,day7_date,day14_date,day21_date,last_subject,hook_direction,recommended_cta,score_grade,score',
        'order': 'score.desc',
    })

    due = []
    for lead in all_leads:
        tc = lead.get('touch_count', 0)
        d7, d14, d21 = lead.get('day7_date',''), lead.get('day14_date',''), lead.get('day21_date','')
        if (tc == 1 and d7 and d7 <= today_iso) or \
           (tc == 2 and d14 and d14 <= today_iso) or \
           (tc == 3 and d21 and d21 <= today_iso):
            due.append(lead)

    # Reactivation due
    reactivation = sb_get('leads', {
        'status': 'eq.冷静期-90天后重新激活',
        'reactivation_date': f'lte.{today_iso}',
        'select': 'company_name,contact_name,reactivation_date,score_grade',
    })

    # Seasonal triggers
    seasonal = get_setting('seasonal_triggers', [])
    seasonal_alerts = [t for t in (seasonal or [])
                      if t.get('month') == today.month and t.get('day') == today.day]

    if not due and not reactivation and not seasonal_alerts:
        print("No reminders to send today.")
        return

    lines = [f"📋 EETOON CRM 每日提醒 — {today}", "=" * 50, ""]

    if due:
        lines.append(f"⏰ 今日到期跟进（{len(due)}家）：")
        lines.append("")
        for lead in due:
            next_n = (lead.get('touch_count', 0) or 0) + 1
            lines += [
                f"  【第{next_n}封】{lead['company_name']}",
                f"    联系人: {lead.get('contact_name','')}",
                f"    邮件: {lead.get('email','')}",
                f"    评分: {lead.get('score_grade','C')}({lead.get('score',0)}分)",
                f"    上封主题: {lead.get('last_subject','—')}",
                f"    建议角度: {(lead.get('hook_direction','') or '')[:80]}",
                f"    推荐CTA: {lead.get('recommended_cta','')}",
                "",
            ]

    if reactivation:
        lines.append(f"❄️ 冷静期到期，建议重新激活（{len(reactivation)}家）：")
        for l in reactivation:
            lines.append(f"  • {l['company_name']} ({l.get('contact_name','')}) | 激活日：{l.get('reactivation_date','')}")
        lines.append("")

    if seasonal_alerts:
        lines.append("🌟 季节性提醒：")
        for a in seasonal_alerts:
            lines.append(f"  ⚡ {a.get('name','')}: {a.get('message','')}")
        lines.append("")

    lines += ["---", "前往系统处理：https://eetoon-crm.streamlit.app"]

    msg = MIMEText("\n".join(lines), 'plain', 'utf-8')
    msg['Subject'] = f"[EETOON CRM] {today} 每日提醒 — {len(due)}个跟进待处理"
    msg['From'] = f"EETOON CRM <{SMTP_USER}>"
    msg['To'] = NOTIFY_EMAIL

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [NOTIFY_EMAIL], msg.as_string())

    print(f"✅ Reminder sent: {len(due)} followups, {len(reactivation)} reactivations")


if __name__ == '__main__':
    main()
