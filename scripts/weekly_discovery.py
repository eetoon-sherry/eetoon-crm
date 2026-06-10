#!/usr/bin/env python3
"""Weekly auto-discovery — search for new promotional products distributors."""

import os, ssl, smtplib, json, psycopg2, psycopg2.extras, requests
from datetime import datetime
from email.mime.text import MIMEText
from bs4 import BeautifulSoup

DB_HOST      = os.environ['DB_HOST']
DB_PASSWORD  = os.environ['DB_PASSWORD']
SMTP_HOST    = os.environ.get('SMTP_HOST', 'smtp.qiye.163.com')
SMTP_PORT    = int(os.environ.get('SMTP_PORT', '465'))
SMTP_USER    = os.environ.get('SMTP_USER', '')
SMTP_PASS    = os.environ.get('SMTP_PASS', '')
NOTIFY_EMAIL = os.environ.get('NOTIFY_EMAIL', '')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
}


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


def get_existing_websites(cur):
    cur.execute("SELECT LOWER(website) FROM leads WHERE website != ''")
    return {row[0] for row in cur.fetchall()}


def search_google(query, max_results=8):
    from urllib.parse import quote
    url = f"https://www.google.com/search?q={quote(query)}&num=15"
    results = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        skip_domains = ['linkedin.com','facebook.com','yelp.com','yellowpages.com',
                       'bbb.org','indeed.com','google.com','amazon.com','ppai.org']
        for div in soup.select('div.g')[:max_results+5]:
            title_el = div.select_one('h3')
            link_el = div.select_one('a')
            snip_el = div.select_one('.VwiC3b')
            if not title_el or not link_el:
                continue
            href = link_el.get('href','')
            if not href.startswith('http'):
                continue
            if any(d in href for d in skip_domains):
                continue
            results.append({
                'company_name': title_el.get_text(strip=True),
                'website': href,
                'snippet': snip_el.get_text(strip=True) if snip_el else '',
            })
            if len(results) >= max_results:
                break
    except Exception as e:
        print(f"Search error: {e}")
    return results


def main():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get settings
    cur.execute("SELECT value FROM settings WHERE key='auto_discovery_enabled'")
    row = cur.fetchone()
    if not row or not row['value']:
        print("Auto discovery disabled."); conn.close(); return

    cur.execute("SELECT value FROM settings WHERE key='discovery_keywords'")
    kw_row = cur.fetchone()
    keywords = kw_row['value'] if kw_row else ['promotional products distributor']

    cur.execute("SELECT value FROM settings WHERE key='discovery_states'")
    st_row = cur.fetchone()
    states = st_row['value'] if st_row else ['TX','FL','CA','IL','CO']

    existing = get_existing_websites(cur)
    cur2 = conn.cursor()

    new_candidates = []
    for keyword in keywords[:2]:  # Limit to 2 keywords to avoid rate limiting
        for state in states[:5]:  # Limit to 5 states
            query = f"{keyword} {state}"
            print(f"Searching: {query}")
            results = search_google(query, max_results=5)
            for r in results:
                site = r['website'].lower()
                if site not in existing:
                    cur2.execute("""
                        INSERT INTO discovery_queue
                            (company_name, website, location, research_brief, status, source)
                        VALUES (%s, %s, %s, %s::jsonb, 'pending_review', 'auto_weekly')
                        ON CONFLICT DO NOTHING
                    """, (
                        r['company_name'], r['website'], state,
                        json.dumps({'snippet': r.get('snippet',''), 'search_query': query})
                    ))
                    existing.add(site)
                    new_candidates.append(r)

    conn.commit()
    cur2.close()
    cur.close()
    conn.close()

    print(f"Found {len(new_candidates)} new candidates")

    # Send summary email
    if new_candidates and SMTP_USER and NOTIFY_EMAIL:
        lines = [
            f"🔍 EETOON CRM — 本周自动搜索报告",
            f"发现 {len(new_candidates)} 家新候选公司，请前往「客户搜索」→「待审核候选」审核",
            "",
        ]
        for r in new_candidates[:10]:
            lines.append(f"• {r['company_name']}")
            lines.append(f"  {r['website']}")
            if r.get('snippet'):
                lines.append(f"  {r['snippet'][:80]}")
            lines.append("")
        lines.append("---")
        lines.append("前往审核：https://eetoon-crm.streamlit.app")

        msg = MIMEText("\n".join(lines), 'plain', 'utf-8')
        msg['Subject'] = f"[EETOON CRM] 本周新发现 {len(new_candidates)} 家候选客户"
        msg['From'] = f"EETOON CRM <{SMTP_USER}>"
        msg['To'] = NOTIFY_EMAIL
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [NOTIFY_EMAIL], msg.as_string())
        print(f"✅ Summary sent to {NOTIFY_EMAIL}")


if __name__ == '__main__':
    main()
