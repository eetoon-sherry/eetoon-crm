"""Email sending via NetEase Enterprise SMTP."""

import ssl, smtplib, logging, uuid, json
import os
import streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from utils.database import add_to_queue, add_email_history, update_lead, get_lead_by_email, get_setting

TZ_MAP = {
    'TX':'America/Chicago','FL':'America/New_York','NY':'America/New_York',
    'CA':'America/Los_Angeles','CO':'America/Denver','IL':'America/Chicago',
    'TN':'America/Chicago','OH':'America/New_York','WA':'America/Los_Angeles',
    'MO':'America/Chicago','NJ':'America/New_York','SC':'America/New_York',
    'KY':'America/New_York','UT':'America/Denver','OK':'America/Chicago',
    'WI':'America/Chicago','GA':'America/New_York','NC':'America/New_York',
    'AZ':'America/Phoenix','PA':'America/New_York','MI':'America/New_York',
    'MN':'America/Chicago','MA':'America/New_York','VA':'America/New_York',
    'OR':'America/Los_Angeles','NV':'America/Los_Angeles',
}

FORBIDDEN_PHRASES = ["competitive price","best quality","hope to cooperate","one-stop solution"]


def get_smtp_config():
    try:
        s = st.secrets.get("smtp", {})
    except Exception:
        s = {}

    host = s.get("host") or os.getenv("SMTP_HOST")
    port = int(s.get("port") or os.getenv("SMTP_PORT") or 465)
    user = s.get("user") or os.getenv("SMTP_USER")
    password = s.get("password") or os.getenv("SMTP_PASS")
    sender_name = s.get("sender_name") or os.getenv("SENDER_NAME") or "Sherry | EETOON GROUP"
    bcc = ""  # BCC disabled: do not copy Sherry/Gmail on CRM sends.

    if not host or not user or not password:
        raise RuntimeError("SMTP is not configured. Add [smtp] settings in Streamlit Secrets.")

    return host, port, user, password, sender_name, bcc


def get_signature():
    sig = get_setting("sender_signature", "")
    if isinstance(sig, str):
        return sig
    return ""


def validate_content(subject: str, body: str) -> list:
    errors = []
    if len(subject) > 50:
        errors.append(f"主题行 {len(subject)} 字符，超过50上限")
    words = len(body.split())
    if words > 120:
        errors.append(f"正文 {words} 词，超过120上限")
    combined = (subject + ' ' + body).lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase in combined:
            errors.append(f"包含禁止词组：'{phrase}'")
    return errors


def next_send_window(state_abbr: str):
    tz_name = TZ_MAP.get(state_abbr.upper(), 'America/New_York')
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)
    send_days = get_setting("send_days", ["Tuesday","Wednesday","Thursday"])
    day_map = {"Monday":0,"Tuesday":1,"Wednesday":2,"Thursday":3,"Friday":4,"Saturday":5,"Sunday":6}
    allowed = [day_map[d] for d in send_days if d in day_map]
    for delta in range(1, 8):
        candidate = now_local + timedelta(days=delta)
        if candidate.weekday() in allowed:
            target_local = candidate.replace(
                hour=get_setting("send_hour", 9), minute=0, second=0, microsecond=0
            )
            return target_local.astimezone(timezone.utc), tz_name, target_local
    return now_local.astimezone(timezone.utc), tz_name, now_local


def send_now(to_email: str, to_name: str, subject: str, body: str) -> tuple[bool, str]:
    host, port, user, password, sender_name, bcc = get_smtp_config()
    signature = get_signature()
    full_body = f"{body}\n\n{signature}" if signature else body
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f"{sender_name} <{user}>"
    msg['To'] = f"{to_name} <{to_email}>" if to_name else to_email
    msg.attach(MIMEText(full_body, 'plain', 'utf-8'))
    recipients = [to_email]
    if bcc:
        recipients.append(bcc)
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=ctx) as server:
            server.login(user, password)
            server.sendmail(user, recipients, msg.as_string())
        return True, ""
    except Exception as e:
        return False, str(e)


def queue_email(lead_id: int, company: str, to_email: str, to_name: str,
                subject: str, body: str, state_abbr: str, campaign_id=None,
                template_id=None, touch_number: int = 1, requires_approval: bool = True) -> dict:
    scheduled_utc, tz_name, local_time = next_send_window(state_abbr)
    job = {
        'queue_id': str(uuid.uuid4())[:8],
        'lead_id': lead_id,
        'campaign_id': campaign_id,
        'company_name': company,
        'to_email': to_email,
        'to_name': to_name,
        'subject': subject,
        'body': body,
        'recipient_tz': tz_name,
        'scheduled_utc': scheduled_utc,
        'scheduled_local': local_time.strftime('%Y-%m-%d %H:%M %Z'),
        'status': 'pending',
        'requires_approval': requires_approval,
        'approved_at': datetime.now(timezone.utc) if not requires_approval else None,
        'template_id': template_id,
        'touch_number': touch_number,
    }
    add_to_queue(job)
    return job


def process_due_emails():
    """Process all pending emails whose scheduled time has passed."""
    from utils.database import (
        get_campaign,
        get_pending_queue,
        get_sent_count_today,
        update_queue_status,
        update_lead,
    )
    from datetime import date, timedelta

    now_utc = datetime.now(timezone.utc)
    pending = get_pending_queue()
    sent_count, failed_count = 0, 0
    campaign_sent_cache = {}
    campaign_limit_cache = {}

    for job in pending:
        if job.get('requires_approval') and not job.get('approved_at'):
            continue
        campaign_id = job.get('campaign_id')
        if campaign_id:
            if campaign_id not in campaign_sent_cache:
                campaign_sent_cache[campaign_id] = get_sent_count_today(campaign_id)
            if campaign_id not in campaign_limit_cache:
                campaign = get_campaign(campaign_id) or {}
                campaign_limit_cache[campaign_id] = int(campaign.get('daily_send_limit') or 10)
            if campaign_sent_cache[campaign_id] >= campaign_limit_cache[campaign_id]:
                continue
        scheduled = job['scheduled_utc']
        if hasattr(scheduled, 'tzinfo') and scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        elif isinstance(scheduled, str):
            scheduled = datetime.fromisoformat(scheduled.replace('Z', '+00:00'))

        if now_utc >= scheduled:
            ok, err = send_now(job['to_email'], job['to_name'], job['subject'], job['body'])
            if ok:
                update_queue_status(job['queue_id'], 'sent')
                # Update lead
                if job.get('lead_id'):
                    lead = get_lead_by_email(job['to_email'])
                    if lead:
                        count = (lead.get('touch_count') or 0) + 1
                        send_date = now_utc.date()
                        intervals = get_setting("followup_intervals", [7, 14, 21])
                        send_days_setting = get_setting("send_days", ["Tuesday","Wednesday","Thursday"])
                        day_map2 = {"Monday":0,"Tuesday":1,"Wednesday":2,"Thursday":3,
                                    "Friday":4,"Saturday":5,"Sunday":6}
                        allowed2 = [day_map2[d] for d in send_days_setting if d in day_map2]

                        def next_good_day(d):
                            for i in range(0, 7):
                                c = d + timedelta(days=i)
                                if c.weekday() in allowed2:
                                    return c
                            return d

                        update_lead(job['lead_id'],
                            touch_count=count,
                            send_date=send_date,
                            day7_date=next_good_day(send_date + timedelta(days=intervals[0])) if len(intervals)>0 else None,
                            day14_date=next_good_day(send_date + timedelta(days=intervals[1])) if len(intervals)>1 else None,
                            day21_date=next_good_day(send_date + timedelta(days=intervals[2])) if len(intervals)>2 else None,
                            last_subject=job['subject'],
                            status=f'已发送第{count}封'
                        )
                add_email_history({
                    'lead_id': job.get('lead_id'),
                    'campaign_id': job.get('campaign_id'),
                    'company_name': job['company_name'],
                    'to_email': job['to_email'],
                    'to_name': job['to_name'],
                    'subject': job['subject'],
                    'body': job['body'],
                    'status': 'sent',
                    'scheduled_local': job.get('scheduled_local'),
                    'recipient_tz': job.get('recipient_tz'),
                    'sent_at': now_utc,
                    'queue_id': job['queue_id'],
                    'template_id': job.get('template_id'),
                    'touch_number': job.get('touch_number'),
                })
                sent_count += 1
                if campaign_id:
                    campaign_sent_cache[campaign_id] = campaign_sent_cache.get(campaign_id, 0) + 1
            else:
                update_queue_status(job['queue_id'], 'failed', err)
                failed_count += 1

    return sent_count, failed_count
