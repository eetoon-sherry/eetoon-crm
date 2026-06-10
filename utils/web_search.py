"""Client discovery via web search."""

import requests, re
from bs4 import BeautifulSoup
from urllib.parse import quote


HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
}

def search_companies(keyword: str, location: str = "", max_results: int = 10) -> list:
    """
    Search for promotional products distributors.
    Returns list of candidate dicts.
    """
    query = f"{keyword} {location}".strip()
    candidates = []
    try:
        url = f"https://www.google.com/search?q={quote(query)}&num=20"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')

        for result in soup.select('div.g')[:max_results]:
            title_el = result.select_one('h3')
            link_el = result.select_one('a')
            snippet_el = result.select_one('.VwiC3b')

            if not title_el or not link_el:
                continue

            title = title_el.get_text(strip=True)
            link = link_el.get('href', '')
            if not link.startswith('http'):
                continue
            snippet = snippet_el.get_text(strip=True) if snippet_el else ''

            # Filter out irrelevant results
            skip_domains = ['linkedin.com', 'facebook.com', 'yelp.com',
                           'yellowpages.com', 'bbb.org', 'indeed.com']
            if any(d in link for d in skip_domains):
                continue

            candidates.append({
                'company_name': title,
                'website': link,
                'location': location,
                'snippet': snippet,
                'source': 'google_search',
                'status': 'pending_review'
            })
    except Exception as e:
        print(f"Search error: {e}")

    return candidates


def extract_company_info(website_url: str) -> dict:
    """Try to extract basic company info from a website."""
    info = {'website': website_url, 'description': '', 'email': '', 'phone': ''}
    try:
        resp = requests.get(website_url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Description from meta
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc:
            info['description'] = meta_desc.get('content', '')[:300]

        # Email
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', resp.text)
        skip_emails = ['example.com', 'yourdomain', 'gmail.com', 'sentry']
        valid_emails = [e for e in emails if not any(s in e for s in skip_emails)]
        if valid_emails:
            info['email'] = valid_emails[0]

        # Phone
        phones = re.findall(r'[\+\(]?[1-9][0-9 .\-\(\)]{8,}[0-9]', resp.text)
        if phones:
            info['phone'] = phones[0]

        # Title as company name
        title = soup.find('title')
        if title:
            info['company_name'] = title.get_text(strip=True)[:80]

    except Exception as e:
        info['error'] = str(e)

    return info


def guess_email_formats(contact_name: str, domain: str) -> list:
    """Generate possible email formats for a contact."""
    if not contact_name or not domain:
        return []
    parts = contact_name.lower().split()
    if len(parts) < 2:
        first = parts[0] if parts else ''
        last = ''
    else:
        first, last = parts[0], parts[-1]

    formats = []
    if first and last:
        formats.extend([
            f"{first}@{domain}",
            f"{first}.{last}@{domain}",
            f"{first[0]}{last}@{domain}",
            f"{first}{last[0]}@{domain}",
            f"{last}@{domain}",
        ])
    elif first:
        formats.extend([f"{first}@{domain}", f"info@{domain}", f"contact@{domain}"])

    formats.extend([f"info@{domain}", f"sales@{domain}"])
    return list(dict.fromkeys(formats))  # dedupe while preserving order
