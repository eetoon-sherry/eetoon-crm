"""IMAP inbox monitor — detect client replies and update lead status."""

import imaplib, email, re
import streamlit as st
from utils.database import get_lead_by_email, update_lead_status, add_note


def get_imap_config():
    try:
        s = st.secrets["imap"]
        return s["host"], int(s["port"]), s["user"], s["password"]
    except Exception:
        return "imap.qiye.163.com", 993, "sherry.xie@eetoon.com", "ANbDzSKtN9k@Bg#%"


def check_inbox_for_replies(days_back: int = 3) -> list:
    """
    Scan inbox for replies from known leads.
    Returns list of dicts: {email, subject, date, lead_id}
    """
    host, port, user, password = get_imap_config()
    found = []
    try:
        mail = imaplib.IMAP4_SSL(host, port)
        mail.login(user, password)
        mail.select('INBOX')

        from datetime import date, timedelta
        since_date = (date.today() - timedelta(days=days_back)).strftime('%d-%b-%Y')
        _, data = mail.search(None, f'(SINCE {since_date})')

        for num in data[0].split():
            _, msg_data = mail.fetch(num, '(RFC822)')
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            from_addr = email.utils.parseaddr(msg.get('From', ''))[1].lower()
            subject = msg.get('Subject', '')
            date_str = msg.get('Date', '')

            lead = get_lead_by_email(from_addr)
            if lead:
                found.append({
                    'email': from_addr,
                    'company': lead['company_name'],
                    'lead_id': lead['id'],
                    'subject': subject,
                    'date': date_str,
                    'current_status': lead['status']
                })

        mail.logout()
    except Exception as e:
        print(f"IMAP error: {e}")
    return found


def auto_mark_replies(days_back: int = 3) -> int:
    """Auto-mark leads as '有回复' if inbox reply found."""
    replies = check_inbox_for_replies(days_back)
    marked = 0
    for r in replies:
        if r['current_status'] != '有回复':
            update_lead_status(r['lead_id'], '有回复')
            add_note(r['lead_id'], 'email_reply',
                     f"系统自动检测到回复 | 主题: {r['subject']} | 日期: {r['date']}")
            marked += 1
    return marked
