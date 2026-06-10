#!/usr/bin/env python3
"""Weekly auto-discovery — uses Supabase REST API."""

import os, ssl, smtplib, json
from datetime import datetime
from email.mime.text import MIMEText
import urllib.request, urllib.error, urllib.parse
try:
    import requests
    from bs4 import BeautifulSoup
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://gnqddnujljyqjsfjrrri.supabase.co')
SUPABASE_KEY = os.environ['SUPABASE_SERVICE_KEY']
SMTP_HOST    = os.environ.get('SMTP_HOST', 'smtp.qiye.163.com')
SMTP_PORT    = int(os.environ.get('SMTP_PORT', '465'))
SMTP_USER    = os.environ.get('SMTP_USER', '')
SMTP_PASS    = os.environ.get('SMTP_PASS', '')
NOTIFY_EMAIL = os.environ.get('NOTIFY_EMAIL', '')

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}


def sb_request(method, path, data=None, params=None):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    if params:
        url += '?' + '&'.join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
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
    except Exception as e:
        print(f"API error: {e}")
        return []


def get_setting(key, default=None):
    rows = sb_request('GET', 'settings', params={'key': f'eq.{key}', 'select': 'value'})
    return rows[0]['value'] if rows else default


def search_google(query, max_results=5):
    if not HAS_REQUESTS:
        return []
    url = f"https://www.google.com/search?q={urllib.parse.quote(query)}&num=15"
    results = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        skip = ['linkedin.com','facebook.com','yelp.com','yellowpages.com',
                'bbb.org','indeed.com','google.com','amazon.com','ppai.org']
        for div in soup.select('div.g')[:max_results+5]:
            title_el = div.select_one('h3')
            link_el = div.select_one('a')
            snip_el = div.select_one('.VwiC3b')
            if not title_el or not link_el:
                continue
            href = link_el.get('href', '')
            if not href.startswith('http') or any(d in href for d in skip):
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
    enabled = get_setting('auto_discovery_enabled', True)
    if not enabled:
        print("Auto discovery disabled."); return

    keywords = get_setting('discovery_keywords', ['promotional products distributor'])
    states   = get_setting('discovery_states', ['TX','FL','CA','IL','CO'])

    # Get existing websites to avoid duplicates
    existing_leads = sb_request('GET', 'leads', params={'select': 'website'})
    existing = {r.get('website','').lower() for r in existing_leads if r.get('website')}

    existing_disc = sb_request('GET', 'discovery_queue', params={'select': 'website'})
    existing |= {r.get('website','').lower() for r in existing_disc if r.get('website')}

    new_candidates = []
    for keyword in (keywords or [])[:2]:
        for state in (states or [])[:5]:
            query = f"{keyword} {state}"
            print(f"Searching: {query}")
            results = search_google(query, max_results=5)
            for r in results:
                site = r.get('website','').lower()
                if site and site not in existing:
                    sb_request('POST', 'discovery_queue', data={
                        'company_name': r['company_name'],
                        'website': r['website'],
                        'location': state,
                        'research_brief': {'snippet': r.get('snippet',''), 'query': query},
                        'status': 'pending_review',
                        'source': 'auto_weekly',
                    })
                    existing.add(site)
                    new_candidates.append(r)

    print(f"Found {len(new_candidates)} new candidates")

    if new_candidates and SMTP_USER and NOTIFY_EMAIL:
        lines = [
            f"🔍 EETOON CRM — 本周自动搜索报告",
            f"发现 {len(new_candidates)} 家新候选，请前往「客户搜索」→「待审核候选」审核", "",
        ]
        for r in new_candidates[:10]:
            lines += [f"• {r['company_name']}", f"  {r['website']}", ""]
        lines += ["---", "前往审核：https://eetoon-crm.streamlit.app"]

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
