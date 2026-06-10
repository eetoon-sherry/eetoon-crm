#!/usr/bin/env python3
"""GitHub Actions email queue processor — uses Supabase REST API."""

import os, ssl, smtplib, json
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import urllib.request, urllib.error

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://gnqddnujljyqjsfjrrri.supabase.co')
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']
SMTP_HOST    = os.environ.get('SMTP_HOST', 'smtp.qiye.163.com')
SMTP_PORT    = int(os.environ.get('SMTP_PORT', '465'))
SMTP_USER    = os.environ['SMTP_USER']
SMTP_PASS    = os.environ['SMTP_PASS']
SENDER_NAME  = os.environ.get('SENDER_NAME', 'Sherry | EETOON GROUP')
BCC_EMAIL    = os.environ.get('BCC_EMAIL', '')


def sb_request(method, path, data=None, params=None):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    if params:
        url += '?' + '&'.join(f"{k}={v}" for k, v in params.items())
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation',
    }
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()}")
        return []


def get_setting(key, default=None):
    rows = sb_request('GET', 'settings', params={'key': f'eq.{key}', 'select': 'value'})
    return rows[0]['value'] if rows else default


def get_signature():
    sig = get_setting('sender_signature', '')
    return sig if isinstance(sig, str) else ''


def send_email(to_email, to_name, subject, body, signature):
    full_body = f"{body}\n\n{signature}" if signature else body
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f"{SENDER_NAME} <{SMTP_USER}>"
    msg['To'] = f"{to_name} <{to_email}>" if to_name else to_email
    msg.attach(MIMEText(full_body, 'plain', 'utf-8'))
    recipients = [to_email]
    if BCC_EMAIL:
        recipients.append(BCC_EMAIL)
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, recipients, msg.as_string())


def next_allowed_day(d, allowed_weekdays):
    for i in range(7):
        c = d + timedelta(days=i)
        if c.weekday() in allowed_weekdays:
            return c
    return d


def main():
    signature = get_signature()
    send_days  = get_setting('send_days', ['Tuesday', 'Wednesday', 'Thursday'])
    intervals  = get_setting('followup_intervals', [7, 14, 21])
    day_map = {'Monday':0,'Tuesday':1,'Wednesday':2,'Thursday':3,
               'Friday':4,'Saturday':5,'Sunday':6}
    allowed = [day_map[d] for d in send_days if d in day_map]

    now_utc   = datetime.now(timezone.utc)
    now_iso   = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Get pending emails due now
    jobs = sb_request('GET', 'email_queue', params={
        'status': 'eq.pending',
        'scheduled_utc': f'lte.{now_iso}',
        'order': 'scheduled_utc.asc',
    })

    if not jobs:
        print(f"No pending emails due. Checked at {now_iso}")
        return

    sent_count = failed_count = 0

    for job in jobs:
        try:
            send_email(job['to_email'], job['to_name'] or '',
                      job['subject'], job['body'], signature)

            # Mark sent
            sb_request('PATCH', f"email_queue?id=eq.{job['id']}",
                      data={'status': 'sent', 'sent_at': now_iso})

            # Update lead
            lead_id = job.get('lead_id')
            if lead_id:
                leads = sb_request('GET', 'leads', params={'id': f'eq.{lead_id}', 'select': 'touch_count'})
                if leads:
                    count = (leads[0].get('touch_count') or 0) + 1
                    send_date = now_utc.date()
                    d7  = next_allowed_day(send_date + timedelta(days=intervals[0]), allowed)
                    d14 = next_allowed_day(send_date + timedelta(days=intervals[1]), allowed)
                    d21 = next_allowed_day(send_date + timedelta(days=intervals[2]), allowed)
                    sb_request('PATCH', f"leads?id=eq.{lead_id}", data={
                        'touch_count': count,
                        'send_date': str(send_date),
                        'day7_date': str(d7),
                        'day14_date': str(d14),
                        'day21_date': str(d21),
                        'last_subject': job['subject'],
                        'status': f'已发送第{count}封',
                        'updated_at': now_iso,
                    })

            # Record history
            sb_request('POST', 'email_history', data={
                'lead_id': lead_id,
                'company_name': job['company_name'],
                'to_email': job['to_email'],
                'to_name': job['to_name'],
                'subject': job['subject'],
                'body': job['body'],
                'status': 'sent',
                'scheduled_local': job.get('scheduled_local'),
                'recipient_tz': job.get('recipient_tz'),
                'sent_at': now_iso,
                'queue_id': job['queue_id'],
            })

            print(f"✅ Sent: {job['company_name']} → {job['to_email']}")
            sent_count += 1

        except Exception as e:
            sb_request('PATCH', f"email_queue?id=eq.{job['id']}", data={
                'status': 'failed',
                'error_message': str(e)[:500],
                'retry_count': (job.get('retry_count') or 0) + 1,
            })
            print(f"❌ Failed: {job['company_name']} | {e}")
            failed_count += 1

    print(f"\nDone: {sent_count} sent, {failed_count} failed out of {len(jobs)} jobs")


if __name__ == '__main__':
    main()
