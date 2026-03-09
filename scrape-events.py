#!/usr/bin/env python3
"""
Scrapes Helsinki theatre venue event listings and writes scrape-events.js.
Run: python3 scrape-events.py
Venues: Zodiak, Teater Viirus, Q-Teatteri, Kiasma, Cirko, Mad House,
        Tekstin Talo, Takomo, Espoon Teatteri, Ryhmäteatteri,
        Svenska Teatern, Kansallisteatteri, Universum
"""

import requests, re, json
from bs4 import BeautifulSoup
from datetime import datetime, timezone, date, timedelta

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
OUTPUT  = 'scrape-events.js'
events  = []

def get(url):
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r

# ── ZODIAK ──────────────────────────────────────────────────────────────────
print('Scraping Zodiak...')

try:
    r = get('https://zodiak.fi/fi/ohjelmisto')
    soup = BeautifulSoup(r.text, 'html.parser')

    # Find all show links
    show_links = {}
    for a in soup.find_all('a', href=re.compile(r'^/fi/ohjelmisto/\w')):
        href = a.get('href')
        title = a.get_text(strip=True)
        if href and href not in show_links and title:
            show_links[href] = title

    print(f'  Found {len(show_links)} shows')

    for path, title in show_links.items():
        url = 'https://zodiak.fi' + path
        try:
            sr = get(url)
            ssoup = BeautifulSoup(sr.text, 'html.parser')
            times = ssoup.find_all('time', datetime=True)
            for t in times:
                dt_str = t.get('datetime')
                if not dt_str:
                    continue
                try:
                    dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                    events.append({
                        'venue':      'zodiak',
                        'venue_label':'Zodiak',
                        'title':      title,
                        'start_time': dt.isoformat(),
                        'url':        url,
                    })
                except ValueError:
                    pass
            print(f'  {title}: {len(times)} dates')
        except Exception as e:
            print(f'  SKIP {path}: {e}')

except Exception as e:
    print(f'  Zodiak failed: {e}')

# ── VIIRUS ───────────────────────────────────────────────────────────────────
print('Scraping Teater Viirus...')

try:
    r = get('https://viirus.fi/fi/esitykset')
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                  r.text, re.DOTALL)
    if not m:
        raise ValueError('__NEXT_DATA__ not found')

    data = json.loads(m.group(1))

    # Walk the JSON tree to find 'shows'
    shows_obj = [None]
    def find_shows(obj, depth=0):
        if depth > 10 or shows_obj[0]: return
        if isinstance(obj, dict):
            if 'shows' in obj and isinstance(obj['shows'], dict):
                shows_obj[0] = obj['shows']
            for v in obj.values(): find_shows(v, depth+1)
        elif isinstance(obj, list):
            for i in obj: find_shows(i, depth+1)
    find_shows(data)

    shows = shows_obj[0]
    if not shows:
        raise ValueError('shows key not found in JSON')

    nodes = shows.get('nodes', [])
    print(f'  Found {len(nodes)} shows')

    for show in nodes:
        title   = show.get('title', '')
        uri     = show.get('uri', '')
        url     = 'https://viirus.fi' + uri
        extras  = show.get('showsExtras', {}) or {}
        calendar = extras.get('calendar') or []

        for entry in calendar:
            date_str = entry.get('startDate', '')
            time_str = entry.get('startTime', '00:00:00')
            if not date_str:
                continue
            try:
                # startDate is like "2026-03-27T00:00:00+00:00" — use only the date part
                date_part = date_str[:10]
                time_part = time_str[:5]  # HH:MM
                dt = datetime.fromisoformat(f'{date_part}T{time_part}:00+02:00')
                events.append({
                    'venue':       'viirus',
                    'venue_label': 'Teater Viirus',
                    'title':       title,
                    'start_time':  dt.isoformat(),
                    'url':         url,
                })
            except ValueError as e:
                print(f'  Date parse error: {e}')

        print(f'  {title}: {len(calendar)} dates')

except Exception as e:
    print(f'  Viirus failed: {e}')

# ── Q-TEATTERI ───────────────────────────────────────────────────────────────
print('Scraping Q-Teatteri...')

FI_MONTHS = {
    'TAMMIKUU': 1, 'HELMIKUU': 2, 'MAALISKUU': 3, 'HUHTIKUU': 4,
    'TOUKOKUU': 5, 'KESÄKUU': 6, 'HEINÄKUU': 7, 'ELOKUU': 8,
    'SYYSKUU': 9, 'LOKAKUU': 10, 'MARRASKUU': 11, 'JOULUKUU': 12,
}
_MONTH_RE = re.compile(r'\b(' + '|'.join(FI_MONTHS) + r')\b')
# Matches a day entry like "17", "4*", "27.2.", "16*" — NOT "21.1.2026" or "18:30"
_DAY_RE = re.compile(r'^(\d{1,2})(\*)?(?:\.\d{1,2}\.?)?(?:[^\d.]|$)')

def parse_qteatteri_schedule(text, start_year):
    """Parse Q-Teatteri schedule text → list of (year, month, day, 'HH:MM') tuples."""
    t_upper = text.upper()
    # Extract default and asterisk times from full text
    default_time = '18:00'
    asterisk_time = None
    m = re.search(r'klo\s+(\d{1,2}:\d{2})', text, re.IGNORECASE)
    if m:
        default_time = m.group(1)
    m2 = re.search(r'\*-merkityt.*?klo\s+(\d{1,2}:\d{2})', text, re.IGNORECASE | re.DOTALL)
    if m2:
        asterisk_time = m2.group(1)

    results = []
    parts = _MONTH_RE.split(t_upper)
    # parts = [preamble, MON1, days1, MON2, days2, ...]
    year = start_year
    prev_month_num = 0
    i = 1
    while i + 1 < len(parts):
        month_name = parts[i]
        days_text  = parts[i + 1]
        month_num  = FI_MONTHS[month_name]
        if month_num < prev_month_num:
            year += 1
        prev_month_num = month_num

        # Truncate at start of time/status description
        for stop in ['KLO ', 'TÄLLÄ ', 'LOPPUUNVARATTU', 'OSTAA LIPUT', 'ESITYKSET PUOLI']:
            idx = days_text.find(stop)
            if idx >= 0:
                days_text = days_text[:idx]

        for entry in re.split(r'[|\n]', days_text):
            entry = entry.strip().replace(' ', '')  # "21 * " → "21*"
            dm = _DAY_RE.match(entry)
            if not dm:
                continue
            day = int(dm.group(1))
            if 1 <= day <= 31:
                is_star = dm.group(2) == '*'
                t = asterisk_time if (is_star and asterisk_time) else default_time
                results.append((year, month_num, day, t))
        i += 2
    return results

try:
    r = get('https://q-teatteri.fi/esitykset')
    soup = BeautifulSoup(r.text, 'html.parser')

    show_paths = {}
    for a in soup.find_all('a', href=re.compile(r'^/esitykset/\w')):
        href = a.get('href', '')
        if href and href not in show_paths:
            # Title: the first meaningful link text (not "Lue Lisää")
            title = a.get_text(strip=True)
            if title and title != 'Lue Lisää' and len(title) > 3:
                show_paths[href] = title.split('\n')[0][:80]

    print(f'  Found {len(show_paths)} shows')

    for path, raw_title in show_paths.items():
        url = 'https://q-teatteri.fi' + path
        try:
            sr = get(url)
            ssoup = BeautifulSoup(sr.text, 'html.parser')

            # Get title from h1 / heading if available
            h1 = ssoup.find('h1')
            title = h1.get_text(strip=True) if h1 else raw_title

            # Get start year from esityskausi ("21.1.2026–18.4.2026")
            start_year = datetime.now().year
            kausi = ssoup.find(class_='esityskausi')
            if kausi:
                ym = re.search(r'(\d{4})', kausi.get_text())
                if ym:
                    start_year = int(ym.group(1))

            # Find the richtext div containing Finnish month names
            schedule_text = ''
            for div in ssoup.find_all(class_=re.compile(r'richtext|rich-text|w-richtext', re.I)):
                t = div.get_text(' ', strip=True)
                if _MONTH_RE.search(t.upper()):
                    schedule_text = t
                    break

            if not schedule_text:
                print(f'  {title}: no schedule found')
                continue

            dates = parse_qteatteri_schedule(schedule_text, start_year)
            count = 0
            for (yr, mo, day, t) in dates:
                try:
                    dt = datetime(yr, mo, day,
                                  int(t.split(':')[0]), int(t.split(':')[1]),
                                  tzinfo=timezone.utc)
                    # Q-Teatteri is in Helsinki (EET/EEST), store as +02:00
                    from datetime import timedelta
                    dt_hki = dt.replace(tzinfo=None)
                    dt_iso = f'{yr:04d}-{mo:02d}-{day:02d}T{t}:00+02:00'
                    events.append({
                        'venue':       'qteatteri',
                        'venue_label': 'Q-Teatteri',
                        'title':       title,
                        'start_time':  dt_iso,
                        'url':         url,
                    })
                    count += 1
                except ValueError:
                    pass
            print(f'  {title}: {count} dates')
        except Exception as e:
            print(f'  SKIP {path}: {e}')

except Exception as e:
    print(f'  Q-Teatteri failed: {e}')

# ── HELPERS ───────────────────────────────────────────────────────────────────

FI_MONTH_NAMES = {
    1: 'tammikuu', 2: 'helmikuu', 3: 'maaliskuu', 4: 'huhtikuu',
    5: 'toukokuu', 6: 'kesäkuu', 7: 'heinäkuu', 8: 'elokuu',
    9: 'syyskuu', 10: 'lokakuu', 11: 'marraskuu', 12: 'joulukuu',
}
EN_MONTHS = {
    'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,
    'july':7,'august':8,'september':9,'october':10,'november':11,'december':12,
}

def hki_tz(dt_date, time_str='00:00'):
    """Return ISO offset string for Helsinki time (+02:00 winter, +03:00 summer DST)."""
    # DST starts last Sunday of March, ends last Sunday of October
    year = dt_date.year
    # last Sunday of March
    d = date(year, 3, 31)
    while d.weekday() != 6:
        d -= timedelta(days=1)
    dst_start = d
    # last Sunday of October
    d = date(year, 10, 31)
    while d.weekday() != 6:
        d -= timedelta(days=1)
    dst_end = d
    tz = '+03:00' if dst_start <= dt_date < dst_end else '+02:00'
    return f'{dt_date.isoformat()}T{time_str}:00{tz}'

def guess_year(month, day):
    """Given a D.M. date without year, return the most likely upcoming year."""
    today = date.today()
    for year in [today.year, today.year + 1]:
        try:
            d = date(year, month, day)
            if d >= today - timedelta(days=7):
                return year
        except ValueError:
            pass
    return today.year + 1

def parse_dot_date(text):
    """Parse 'D.M.' or 'D.M.YYYY' → (day, month, year) or None."""
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', text)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.?', text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        return day, month, guess_year(month, day)
    return None

# ── KIASMA ───────────────────────────────────────────────────────────────────
print('Scraping Kiasma...')

try:
    r = get('https://kiasma.fi/kg_event-sitemap2.xml')
    perf_urls = re.findall(r'<loc>(https://kiasma\.fi/esitykset/[^<]+)</loc>', r.text)
    print(f'  Found {len(perf_urls)} performance URLs from sitemap')

    for url in perf_urls:
        try:
            pr = get(url)
            soup = BeautifulSoup(pr.text, 'html.parser')
            title_el = soup.find('title')
            title = title_el.get_text(strip=True).split('|')[0].strip() if title_el else url.split('/')[-2]

            dates_div = soup.find(class_=re.compile('event-dates', re.I))
            count = 0
            if dates_div:
                for li in dates_div.find_all('li', class_=re.compile('single-event-date')):
                    date_div = li.find('div', class_='date-meta')
                    start = date_div.get('data-start', '') if date_div else ''
                    if not start:
                        continue
                    try:
                        dt = datetime.strptime(start, '%B %d, %Y %H:%M')
                        iso = hki_tz(dt.date(), dt.strftime('%H:%M'))
                        events.append({
                            'venue': 'kiasma',
                            'venue_label': 'Kiasma',
                            'title': title,
                            'start_time': iso,
                            'url': url,
                        })
                        count += 1
                    except ValueError:
                        pass
            print(f'  {title}: {count} dates')
        except Exception as e:
            print(f'  SKIP {url}: {e}')

except Exception as e:
    print(f'  Kiasma failed: {e}')

# ── CIRKO ────────────────────────────────────────────────────────────────────
print('Scraping Cirko...')

try:
    r = get('https://cirko.fi/programme/')
    soup = BeautifulSoup(r.text, 'html.parser')
    # Programme page links are /sv/esitys/ — convert to Finnish /esitys/
    sv_links = [a['href'] for a in soup.find_all('a', href=re.compile(r'cirko\.fi/sv/esitys/'))]
    fi_links = list(dict.fromkeys(l.replace('/sv/esitys/', '/esitys/') for l in sv_links))
    print(f'  Found {len(fi_links)} shows')

    for url in fi_links:
        try:
            pr = get(url)
            soup2 = BeautifulSoup(pr.text, 'html.parser')
            title_el = soup2.find('title')
            title = title_el.get_text(strip=True).split('|')[0].strip() if title_el else url.split('/')[-2]

            date_els = soup2.find_all(class_='date')
            time_els = soup2.find_all(class_='time')

            # Deduplicate by pairing consecutive date+time elements
            seen_dt = set()
            count = 0
            for i, d_el in enumerate(date_els):
                d_text = d_el.get_text(strip=True)  # e.g. "la 18.4." or "la 18.4.la 18.4."
                t_text = time_els[i].get_text(strip=True) if i < len(time_els) else '00:00'
                parsed = parse_dot_date(d_text)
                if not parsed:
                    continue
                day, month, year = parsed
                try:
                    d = date(year, month, day)
                except ValueError:
                    continue
                # Normalise time: "19:00" → "19:00", "12.30" → "12:30"
                t_clean = re.sub(r'[.,]', ':', t_text.strip())
                t_clean = re.search(r'\d{1,2}:\d{2}', t_clean)
                t_clean = t_clean.group(0) if t_clean else '00:00'
                key = (d, t_clean)
                if key in seen_dt:
                    continue
                seen_dt.add(key)
                events.append({
                    'venue': 'cirko',
                    'venue_label': 'Cirko',
                    'title': title,
                    'start_time': hki_tz(d, t_clean),
                    'url': url,
                })
                count += 1
            print(f'  {title}: {count} dates')
        except Exception as e:
            print(f'  SKIP {url}: {e}')

except Exception as e:
    print(f'  Cirko failed: {e}')

# ── MAD HOUSE ────────────────────────────────────────────────────────────────
print('Scraping Mad House...')

try:
    r = get('https://www.madhousehelsinki.fi/ohjelmisto?format=json')
    items = r.json().get('items', [])
    print(f'  Found {len(items)} shows')

    for item in items:
        title = BeautifulSoup(item.get('title', ''), 'html.parser').get_text(strip=True)
        url = 'https://www.madhousehelsinki.fi' + item.get('fullUrl', '')
        excerpt_html = item.get('excerpt', '')
        excerpt_text = BeautifulSoup(excerpt_html, 'html.parser').get_text()

        # Find the date string (first line before PAIKKA:)
        date_line = excerpt_text.split('PAIKKA')[0].strip()

        # Expand ranges like "26.-28.3.2026" → individual dates
        def expand_dates(text):
            dates = []
            # "D. & D.M.YYYY" → two specific dates
            m = re.match(r'(\d{1,2})\.\s*&\s*(\d{1,2})\.(\d{1,2})\.(\d{4})', text)
            if m:
                month, year = int(m.group(3)), int(m.group(4))
                for day in [int(m.group(1)), int(m.group(2))]:
                    dates.append((day, month, year))
                return dates
            # "D.-D.M.YYYY" → date range
            m = re.match(r'(\d{1,2})\.-(\d{1,2})\.(\d{1,2})\.(\d{4})', text)
            if m:
                d1, d2, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                for day in range(d1, d2 + 1):
                    dates.append((day, month, year))
                return dates
            # Single: "D.M.YYYY"
            m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', text)
            if m:
                dates.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
            return dates

        raw_dates = expand_dates(date_line)
        count = 0
        for (day, month, year) in raw_dates:
            try:
                d = date(year, month, day)
                events.append({
                    'venue': 'madhouse',
                    'venue_label': 'Mad House',
                    'title': title,
                    'start_time': hki_tz(d, '19:00'),  # default time
                    'url': url,
                })
                count += 1
            except ValueError:
                pass
        print(f'  {title}: {count} dates')

except Exception as e:
    print(f'  Mad House failed: {e}')

# ── TEKSTIN TALO ─────────────────────────────────────────────────────────────
print('Scraping Tekstin Talo...')

try:
    r = get('https://www.tekstintalo.fi/tapahtumat/')
    soup = BeautifulSoup(r.text, 'html.parser')
    items = soup.find_all(class_='event-listing__item')
    print(f'  Found {len(items)} event items')

    seen_tt = set()
    count = 0
    for item in items:
        a = item.find('a', href=True)
        if not a:
            continue
        url = a.get('href', '')
        title = a.get('aria-label', '') or a.get_text(strip=True)
        spans = item.find_all('span')
        if len(spans) < 4:
            continue
        date_str = spans[1].get_text(strip=True)   # DD.MM.YYYY
        time_str = spans[3].get_text(strip=True)   # HH.MM

        parsed = parse_dot_date(date_str)
        if not parsed:
            continue
        day, month, year = parsed
        t_clean = time_str.replace('.', ':').strip()
        t_match = re.search(r'\d{1,2}:\d{2}', t_clean)
        t_clean = t_match.group(0) if t_match else '19:00'

        key = (url, date_str)
        if key in seen_tt:
            continue
        seen_tt.add(key)

        try:
            d = date(year, month, day)
            events.append({
                'venue': 'tekstintalo',
                'venue_label': 'Tekstin Talo',
                'title': title,
                'start_time': hki_tz(d, t_clean),
                'url': url,
            })
            count += 1
        except ValueError:
            pass
    print(f'  {count} events added')

except Exception as e:
    print(f'  Tekstin Talo failed: {e}')

# ── TAKOMO ───────────────────────────────────────────────────────────────────
print('Scraping Takomo...')

try:
    r = get('https://teatteritakomo.fi/ohjelmisto/')
    soup = BeautifulSoup(r.text, 'html.parser')
    base = 'https://teatteritakomo.fi/ohjelmisto/'
    show_urls = []
    for a in soup.find_all('a', href=True):
        h = a['href']
        if '/ohjelmisto/' in h and h != base and h not in show_urls:
            show_urls.append(h)
    print(f'  Found {len(show_urls)} shows on ohjelmisto page')

    for url in show_urls:
        try:
            pr = get(url)
            sp = BeautifulSoup(pr.text, 'html.parser')
            h1 = sp.find('h1')
            title = h1.get_text(strip=True) if h1 else url
            # Build month->year map from full DD.MM.YYYY dates; take max year per month
            month_year = {}
            for full in re.findall(r'\d{1,2}\.(\d{1,2})\.(202\d)', sp.get_text()):
                mo, yr = int(full[0]), int(full[1])
                if yr > month_year.get(mo, 0):
                    month_year[mo] = yr
            count = 0
            for el in sp.find_all('time', class_='show-date'):
                # Format: "la 14.2. klo 19.00"
                txt = el.get_text(strip=True)
                m = re.search(r'(\d{1,2})\.(\d{1,2})\.\s*klo\s*(\d{1,2})\.(\d{2})', txt)
                if not m:
                    continue
                day, month, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                year = month_year.get(month, guess_year(month, day))
                try:
                    d = date(year, month, day)
                except ValueError:
                    continue
                if d < date.today() - timedelta(days=1):
                    continue
                events.append({
                    'venue': 'takomo',
                    'venue_label': 'Teatteri Takomo',
                    'title': title,
                    'start_time': hki_tz(d, f'{hour:02d}:{minute:02d}'),
                    'url': url,
                })
                count += 1
            print(f'  {title}: {count} dates')
        except Exception as e:
            print(f'  SKIP {url}: {e}')

except Exception as e:
    print(f'  Takomo failed: {e}')

# ── ESPOON TEATTERI ──────────────────────────────────────────────────────────
print('Scraping Espoon Teatteri...')

try:
    today = date.today()
    # Scrape next 90 days to get a full season of upcoming events
    seen_et = set()
    count = 0
    for delta in range(90):
        d = today + timedelta(days=delta)
        query_date = d.strftime('%d.%m.%Y')
        r = requests.post(
            'https://espoonteatteri.fi/wp-admin/admin-ajax.php',
            headers={**HEADERS, 'Content-Type': 'application/x-www-form-urlencoded'},
            data=f'action=get_nextup&query_date={query_date}',
            timeout=10,
        )
        soup = BeautifulSoup(r.text, 'html.parser')
        for item in soup.find_all(class_='event-item'):
            url_el = item.find('div', attrs={'data-url': True})
            url = url_el.get('data-url', '') if url_el else ''
            day_el = item.find(class_='day')
            time_el = item.find(class_='time')
            day_text = day_el.get_text(strip=True) if day_el else ''
            time_text = time_el.get_text(strip=True) if time_el else '19:00'

            # Parse time: "18.30" → "18:30"
            t_clean = time_text.replace('.', ':')
            t_match = re.search(r'\d{1,2}:\d{2}', t_clean)
            t_clean = t_match.group(0) if t_match else '19:00'

            # Get title from show page URL slug or visit page
            if not url:
                continue
            key = (url, d.isoformat())
            if key in seen_et:
                continue
            seen_et.add(key)

            # Fetch title from show page
            try:
                pr = get(url)
                psoup = BeautifulSoup(pr.text, 'html.parser')
                h1 = psoup.find('h1')
                title = h1.get_text(strip=True) if h1 else url.rstrip('/').split('/')[-1]
            except Exception:
                title = url.rstrip('/').split('/')[-1]

            events.append({
                'venue': 'espoonteatteri',
                'venue_label': '& Espoon Teatteri',
                'title': title,
                'start_time': hki_tz(d, t_clean),
                'url': url,
            })
            count += 1

    print(f'  {count} events added')

except Exception as e:
    print(f'  Espoon Teatteri failed: {e}')

# ── RYHMÄTEATTERI ────────────────────────────────────────────────────────────
print('Scraping Ryhmäteatteri...')

try:
    r = get('https://www.ryhmateatteri.fi/ohjelmisto-liput/')
    soup = BeautifulSoup(r.text, 'html.parser')
    show_links = list(dict.fromkeys(
        a['href'] for a in soup.find_all('a', href=re.compile(r'ryhmateatteri\.fi/ohjelma/\w'))
    ))
    print(f'  Found {len(show_links)} shows')

    for url in show_links:
        try:
            pr = get(url)
            psoup = BeautifulSoup(pr.text, 'html.parser')
            h1 = psoup.find('h1')
            title = h1.get_text(strip=True) if h1 else url.rstrip('/').split('/')[-1]

            date_els = psoup.find_all(class_='date')
            seen_rh = set()
            count = 0
            for el in date_els:
                text = el.get_text(strip=True)
                parsed = parse_dot_date(text)
                if not parsed:
                    continue
                day, month, year = parsed
                # Extract time from surrounding text
                parent_text = el.parent.get_text(' ', strip=True) if el.parent else ''
                t_match = re.search(r'klo\s+(\d{1,2}[.:]\d{2})', parent_text, re.I)
                if not t_match:
                    t_match = re.search(r'(\d{1,2}[.:]\d{2})', parent_text)
                t_clean = t_match.group(1).replace('.', ':') if t_match else '19:00'

                try:
                    d = date(year, month, day)
                except ValueError:
                    continue
                key = (url, d.isoformat(), t_clean)
                if key in seen_rh:
                    continue
                seen_rh.add(key)
                events.append({
                    'venue': 'ryhmateatteri',
                    'venue_label': 'Ryhmäteatteri',
                    'title': title,
                    'start_time': hki_tz(d, t_clean),
                    'url': url,
                })
                count += 1
            print(f'  {title}: {count} dates')
        except Exception as e:
            print(f'  SKIP {url}: {e}')

except Exception as e:
    print(f'  Ryhmäteatteri failed: {e}')

# ── SVENSKA TEATERN ──────────────────────────────────────────────────────────
print('Scraping Svenska Teatern...')

try:
    r = get('https://www.svenskateatern.fi/fi/ohjelmisto/')
    soup = BeautifulSoup(r.text, 'html.parser')
    show_links = list(dict.fromkeys(
        a['href'] for a in soup.find_all('a', href=re.compile(r'svenskateatern\.fi/fi/ohjelmisto/\w'))
    ))
    print(f'  Found {len(show_links)} shows')

    for url in show_links:
        try:
            pr = get(url)
            psoup = BeautifulSoup(pr.text, 'html.parser')
            h1 = psoup.find('h1')
            title = h1.get_text(strip=True) if h1 else url.rstrip('/').split('/')[-1]

            # Look for DD.MM.YYYY date patterns in body text
            text = psoup.get_text()
            date_matches = re.findall(r'(\d{1,2})\.(\d{1,2})\.(202\d)', text)
            seen_st = set()
            count = 0
            for (d_str, mo_str, yr_str) in date_matches:
                day, month, year = int(d_str), int(mo_str), int(yr_str)
                try:
                    d = date(year, month, day)
                except ValueError:
                    continue
                if d < date.today() - timedelta(days=1):
                    continue
                key = (url, d.isoformat())
                if key in seen_st:
                    continue
                seen_st.add(key)
                events.append({
                    'venue': 'svenska',
                    'venue_label': 'Svenska Teatern',
                    'title': title,
                    'start_time': hki_tz(d, '19:00'),
                    'url': url,
                })
                count += 1
            print(f'  {title}: {count} dates')
        except Exception as e:
            print(f'  SKIP {url}: {e}')

except Exception as e:
    print(f'  Svenska Teatern failed: {e}')

# ── KANSALLISTEATTERI ────────────────────────────────────────────────────────
print('Scraping Kansallisteatteri...')

try:
    r = get('https://www.kansallisteatteri.fi/ohjelmisto/ohjelmistokalenteri')
    soup = BeautifulSoup(r.text, 'html.parser')

    seen_knt = set()
    count = 0
    for block in soup.find_all(class_='paragraph--performance'):
        tablet = block.find(class_='visibility-tablet')
        if not tablet:
            continue
        t_el = tablet.find('time', datetime=True)
        if not t_el:
            continue
        date_str = t_el['datetime'][:10]  # "2026-03-04"

        time_field = block.find(class_='field--name-field-time')
        time_text = time_field.get_text(strip=True) if time_field else 'klo 19:00'
        t_match = re.search(r'(\d{1,2}:\d{2})', time_text)
        t_clean = t_match.group(1) if t_match else '19:00'

        a = block.find('a', href=re.compile(r'/esitys/'))
        title = a.get_text(strip=True) if a else '?'
        url = 'https://www.kansallisteatteri.fi' + a['href'] if a else ''

        key = (date_str, title)
        if key in seen_knt:
            continue
        seen_knt.add(key)

        try:
            d = date.fromisoformat(date_str)
        except ValueError:
            continue
        if d < date.today() - timedelta(days=1):
            continue

        events.append({
            'venue': 'kansallisteatteri',
            'venue_label': 'Kansallisteatteri',
            'title': title,
            'start_time': hki_tz(d, t_clean),
            'url': url,
        })
        count += 1

    print(f'  {count} events added')

except Exception as e:
    print(f'  Kansallisteatteri failed: {e}')

# ── UNIVERSUM ────────────────────────────────────────────────────────────────
print('Scraping Universum...')

try:
    r = get('https://universum.fi/wp-json/wp/v2/events?per_page=100&orderby=date&order=asc')
    items = r.json()
    print(f'  Found {len(items)} events')

    count = 0
    for item in items:
        raw_title = BeautifulSoup(item.get('title', {}).get('rendered', ''), 'html.parser').get_text(strip=True)
        url = item.get('link', '')
        # Date is encoded in the title: e.g. "SHOW NAME 24.3" or "SHOW NAME 24.3.2026"
        # Strip the trailing date to get the clean title
        parsed = parse_dot_date(raw_title)
        if not parsed:
            continue
        day, month, year = parsed
        # Clean title: remove the trailing date
        title = re.sub(r'\s+\d{1,2}\.\d{1,2}\.?(\d{4})?$', '', raw_title).strip()

        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if d < date.today() - timedelta(days=1):
            continue
        events.append({
            'venue': 'universum',
            'venue_label': 'Universum',
            'title': title,
            'start_time': hki_tz(d, '19:00'),
            'url': url,
        })
        count += 1
    print(f'  {count} events added')

except Exception as e:
    print(f'  Universum failed: {e}')

# ── TANSSIN TALO ─────────────────────────────────────────────────────────────
print('Scraping Tanssin Talo...')

try:
    gql_url = 'https://www.tanssintalo.fi/api'
    query = '{ experiencesEntries(limit: 300, orderBy: "startDate asc") { title slug startDate endDate } }'
    resp = requests.post(gql_url,
                         json={'query': query},
                         headers={**HEADERS, 'Content-Type': 'application/json'},
                         timeout=20)
    resp.raise_for_status()
    entries = resp.json().get('data', {}).get('experiencesEntries', [])
    print(f'  Found {len(entries)} entries')

    now_utc = datetime.now(timezone.utc)
    today   = date.today()
    count   = 0

    # Track (title, date) pairs already added to avoid duplicates across multiple slugs
    tt_seen = set()

    for entry in entries:
        title     = entry.get('title', '').strip()
        slug      = entry.get('slug', '')
        start_raw = entry.get('startDate', '')
        end_raw   = entry.get('endDate', '') or start_raw
        if not title or not slug or not start_raw:
            continue

        # Parse startDate — stored as UTC midnight of Finnish date
        # e.g. Finnish April 1 midnight = UTC March 31 21:00 (UTC+3 in summer)
        # Convert to Finnish local date for correct month assignment
        try:
            start_dt = datetime.fromisoformat(start_raw)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue

        # Skip shows whose run ended more than a day ago
        try:
            end_dt = datetime.fromisoformat(end_raw)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            end_dt = start_dt

        if end_dt < now_utc - timedelta(days=1):
            continue

        show_url = f'https://www.tanssintalo.fi/ohjelma/{slug}'

        # Convert UTC startDate to Finnish local date (UTC+3 summer, UTC+2 winter)
        # We use the hki_tz helper logic in reverse: the CMS stores midnight Finnish as UTC
        start_hki_date = (start_dt + timedelta(hours=3)).date()  # approximate: UTC+3 covers summer

        # Determine expected run window for filtering scraped dates
        end_hki_date = (end_dt + timedelta(hours=3)).date()
        run_start = start_hki_date                       # don't pick up other shows listed before this one
        run_end   = end_hki_date   + timedelta(days=7)   # small buffer after stated end date

        # Scrape individual performance dates from page text (DD.MM.YYYY patterns)
        dates_found = []
        try:
            pr = get(show_url)
            psoup = BeautifulSoup(pr.text, 'html.parser')
            text = psoup.get_text()
            for m in re.finditer(r'(\d{1,2})\.(\d{1,2})\.(202\d)', text):
                day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
                try:
                    d = date(year, month, day)
                    # Only accept dates within the show's expected run window
                    if run_start <= d <= run_end and d >= today - timedelta(days=1):
                        dates_found.append(d)
                except ValueError:
                    pass
            dates_found = sorted(set(dates_found))
        except Exception as e:
            print(f'  SKIP page {slug}: {e}')

        # Fallback: use the GraphQL startDate Finnish local date
        if not dates_found:
            if start_hki_date >= today - timedelta(days=1):
                dates_found = [start_hki_date]

        for d in dates_found:
            key = (title, d.isoformat())
            if key in tt_seen:
                continue
            tt_seen.add(key)
            events.append({
                'venue':       'tanssintalo',
                'venue_label': 'Tanssin Talo',
                'title':       title,
                'start_time':  hki_tz(d, '19:00'),
                'url':         show_url,
            })
            count += 1

        print(f'  {title}: {len(dates_found)} dates')

    print(f'  {count} events added')

except Exception as e:
    print(f'  Tanssin Talo failed: {e}')

# ── WRITE OUTPUT ─────────────────────────────────────────────────────────────
events.sort(key=lambda e: e['start_time'])

with open(OUTPUT, 'w', encoding='utf-8') as f:
    f.write('window.SCRAPED_EVENTS = ')
    json.dump(events, f, ensure_ascii=False, indent=2)
    f.write(';\n')

print(f'\nDone — {len(events)} events written to {OUTPUT}')
