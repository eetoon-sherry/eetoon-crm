#!/usr/bin/env python3
"""GitHub Actions email queue processor — runs every 10 minutes."""

import os, ssl, smtplib, json, psycopg2, psycopg2.extras
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Load from environment variables (set in GitHub Secrets)
DB_HOST     = os.environ['DB_HOST']
DB_PASSWORD = os.environ['DB_PASSWORD']
SMTP_HOST   = os.environ.get('SMTP_HOST', 'smtp.qiye.163.com')
SMTP_PORT   = int(os.environ.get('SMTP_PORT', '465'))
SMTP_USER   = os.environ['SMTP_USER']
SMTP_PASS   = os.environ['SMTP_PASS']
SENDER_NAME = os.environ.get('SENDER_NAME', 'Sherry | EETOON GROUP')
BCC_EMAIL   = os.environ.get('BCC_EMAIL', '')


def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=5432, dbname='postgres',
        user='postgres', password=DB_PASSWORD, connect_timeout=10
    )


def get_setting(cur, key, default=None):
    cur.execute("SELECT value FROM settings WHERE key = %s", (key,))
    row = cur.fetchone()
    return row[0] if row else default


def get_signature(cur):
    sig = get_setting(cur, 'sender_signature', '')
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
    for i in range(0, 7):
        c = d + timedelta(days=i)
        if c.weekday() in allowed_weekdays:
            return c
    return d


def main():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    signature = get_signature(cur)
    send_days = get_setting(cur, 'send_days', ['Tuesday', 'Wednesday', 'Thursday'])
    intervals = get_setting(cur, 'followup_intervals', [7, 14, 21])
    day_map = {'Monday':0,'Tuesday':1,'Wednesday':2,'Thursday':3,
               'Friday':4,'Saturday':5,'Sunday':6}
    allowed = [day_map[d] for d in send_days if d in day_map]

    now_utc = datetime.now(timezone.utc)

    # Get pending emails due for sending
    cur.execute("""
        SELECT * FROM email_queue
        WHERE status = 'pending' AND scheduled_utc <= %s
        ORDER BY scheduled_utc ASC
    """, (now_utc,))
    jobs = cur.fetchall()

    sent_count = failed_count = 0

    for job in jobs:
        try:
            send_email(job['to_email'], job['to_name'],
                      job['subject'], job['body'], signature)

            # Mark sent
            cur2 = conn.cursor()
            cur2.execute("UPDATE email_queue SET status='sent', sent_at=%s WHERE id=%s",
                        (now_utc, job['id']))

            # Update lead
            if job.get('lead_id'):
                cur2.execute("SELECT * FROM leads WHERE id=%s", (job['lead_id'],))
                lead = cur2.fetchone()
                if lead:
                    # Need RealDictCursor for lead
                    cur3 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                    cur3.execute("SELECT touch_count FROM leads WHERE id=%s", (job['lead_id'],))
                    lead_row = cur3.fetchone()
                    count = (lead_row['touch_count'] or 0) + 1
                    send_date = now_utc.date()
                    d7  = next_allowed_day(send_date + timedelta(days=intervals[0] if len(intervals)>0 else 7), allowed)
                    d14 = next_allowed_day(send_date + timedelta(days=intervals[1] if len(intervals)>1 else 14), allowed)
                    d21 = next_allowed_day(send_date + timedelta(days=intervals[2] if len(intervals)>2 else 21), allowed)
                    cur3.execute("""
                        UPDATE leads SET
                            touch_count=%s, send_date=%s, day7_date=%s,
                            day14_date=%s, day21_date=%s, last_subject=%s,
                            status=%s, updated_at=NOW()
                        WHERE id=%s
                    """, (count, send_date, d7, d14, d21,
                          job['subject'], f'已发送第{count}封', job['lead_id']))
                    cur3.close()

            # Record in history
            cur2.execute("""
                INSERT INTO email_history
                    (lead_id, company_name, to_email, to_name, subject, body,
                     status, scheduled_local, recipient_tz, sent_at, queue_id)
                VALUES (%s,%s,%s,%s,%s,%s,'sent',%s,%s,%s,%s)
            """, (job.get('lead_id'), job['company_name'], job['to_email'],
                  job['to_name'], job['subject'], job['body'],
                  job.get('scheduled_local'), job.get('recipient_tz'),
                  now_utc, job['queue_id']))
            cur2.close()
            conn.commit()

            print(f"✅ Sent: {job['company_name']} → {job['to_email']}")
            sent_count += 1

        except Exception as e:
            conn.rollback()
            cur_err = conn.cursor()
            cur_err.execute("""
                UPDATE email_queue SET status='failed',
                    error_message=%s, retry_count=retry_count+1
                WHERE id=%s
            """, (str(e)[:500], job['id']))
            conn.commit()
            cur_err.close()
            print(f"❌ Failed: {job['company_name']} | {e}")
            failed_count += 1

    cur.close()
    conn.close()
    print(f"\nDone: {sent_count} sent, {failed_count} failed, {len(jobs)-sent_count-failed_count} skipped")


if __name__ == '__main__':
    main()
