#!/usr/bin/env python3
"""Validate GitHub Actions secrets and external service connectivity."""

from __future__ import annotations

import imaplib
import os
import smtplib
import ssl

from supabase_rest import SupabaseRestClient


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def check_supabase() -> None:
    client = SupabaseRestClient(required_env("SUPABASE_URL"), required_env("SUPABASE_SERVICE_KEY"))
    client.health_check()
    print("OK Supabase REST service_role access")


def check_smtp() -> None:
    host = os.environ.get("SMTP_HOST", "smtp.qiye.163.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = required_env("SMTP_USER")
    password = required_env("SMTP_PASS")
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as server:
        server.login(user, password)
    print("OK SMTP login")


def check_imap() -> None:
    host = os.environ.get("IMAP_HOST", "imap.qiye.163.com")
    port = int(os.environ.get("IMAP_PORT", "993"))
    user = required_env("IMAP_USER")
    password = required_env("IMAP_PASS")
    with imaplib.IMAP4_SSL(host, port) as client:
        client.login(user, password)
        client.select("INBOX", readonly=True)
        client.logout()
    print("OK IMAP login")


def main() -> None:
    check_supabase()
    check_smtp()
    check_imap()


if __name__ == "__main__":
    main()
