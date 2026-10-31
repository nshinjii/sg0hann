"""Refresh public feeds; preserve last good data independently for every source."""
import json, re, html, sys, time, math, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone
ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('.')
PATH = ROOT / 'content.json'
CHANNEL = 'UCR9uxbyH0S_sAfOoZLkm0FA'
BROWSER = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'

def fetch(url, tries=3, browser=False):
    """GET with retries: YouTube's RSS feed and pages fail intermittently."""
    headers = {'User-Agent': BROWSER if browser else 'sg0hann-website/1.0 (public content refresh)',
               'Accept-Language': 'en-US,en;q=0.9', 'Cookie': 'CONSENT=YES+1; SOCS=CAI'}
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                return r.read().decode('utf-8')
        except Exception:
            if attempt == tries - 1: raise
            time.sleep(5 * (attempt + 1))

def compact(n):
    """YouTube-style short counts: 263, 1.2K, 38K, 1.4M (rounded down like YouTube)."""
    n = int(n)
    if n < 1000: return str(n)
    if n < 10_000: return (f'{math.floor(n / 100) / 10:.1f}'.rstrip('0').rstrip('.')) + 'K'
    if n < 1_000_000: return f'{n // 1000}K'
    return (f'{math.floor(n / 100_000) / 10:.1f}'.rstrip('0').rstrip('.')) + 'M'

def short(text):
    """'2.1k' / '12k' / '263' from YouTube's page -> '2.1K' / '12K' / '263'."""
    text = text.strip().replace(',', '')
    if re.fullmatch(r'\d+', text): return compact(int(text))
    return text.upper()

def clean(s):
    return html.unescape(re.sub('<[^>]+>', '', s)).strip()

def match(pattern, page):
    m = re.search(pattern, page, re.S)
    if not m: raise ValueError('Source layout changed: ' + pattern[:50])
    return clean(m.group(1))

def metric(page, label, cls):
    return match(r"class='" + cls + r"'[^>]*>([\d.,KM]+)\s*<a[^>]*>[^<]*</a></div>(?:<div[^>]*>)?" + re.escape(label), page)

def run():
    data = json.loads(PATH.read_text())
    now = datetime.now(timezone.utc).isoformat()
    successes = 0
    try:
        root = ET.fromstring(fetch('https://www.youtube.com/feeds/videos.xml?channel_id=' + CHANNEL))
        ns = {'a':'http://www.w3.org/2005/Atom','yt':'http://www.youtube.com/xml/schemas/2015','m':'http://search.yahoo.com/mrss/'}
        entries = root.findall('a:entry', ns)
        if not entries: raise ValueError('Empty video feed')
        by_id = {v['id']:v for v in data['videos']}
        for entry in entries:
            vid = entry.findtext('yt:videoId', namespaces=ns)
            title = entry.findtext('a:title', namespaces=ns)
            date = entry.findtext('a:published', namespaces=ns)
            if not vid or not title or not date: raise ValueError('Incomplete video entry')
            old = by_id.get(vid, {})
            stats = entry.find('m:group/m:community/m:statistics', ns)
            by_id[vid] = {**old, 'id':vid, 'title':title, 'date':date,
                'category':'Tutorials' if re.search('how',title,re.I) else 'Gameplay' if re.search('keyboard|asmr|gameplay',title,re.I) else 'Videos',
                'views':compact(stats.get('views')) if stats is not None and stats.get('views') else old.get('views',''),
                'duration':old.get('duration',''), 'project':old.get('project','SG0HANN'),
                'image':'https://i.ytimg.com/vi/' + vid + '/hqdefault.jpg'}
        data['videos'] = sorted(by_id.values(), key=lambda v:v.get('date',''), reverse=True)
        data['youtubeUpdatedAt'] = now
        successes += 1
        print('YouTube updated:', len(data['videos']), 'videos')
    except Exception as e: print('YouTube retained last good data:',e)
    # Channel totals (subscribers, uploads, total views) from the public About page.
    try:
        page = fetch('https://www.youtube.com/channel/' + CHANNEL + '/about', browser=True)
        subs = re.search(r'"subscriberCountText":"([\d.,]+[KkMm]?) subscribers?"', page)
        views = re.search(r'"viewCountText":"([\d,]+) views?"', page)
        uploads = re.search(r'"videoCountText":"([\d,]+) videos?"', page) or re.search(r'"([\d,]+) videos"', page)
        if not (subs and views and uploads): raise ValueError('About page layout changed')
        total = int(views.group(1).replace(',', ''))
        data['channel'] = {'subscribers': short(subs.group(1)), 'uploads': uploads.group(1).replace(',', ''),
            'views': (f'{total // 1000:,}K+' if total < 1_000_000 else compact(total) + '+'), 'viewsExact': total, 'updatedAt': now}
        successes += 1
        print('Channel updated:', data['channel'])
    except Exception as e: print('Channel totals retained last good data:', e)
    # View counts for the latest 30 uploads from the public Videos tab (RSS only covers 15).
    try:
        page = fetch('https://www.youtube.com/channel/' + CHANNEL + '/videos', browser=True)
        seen = 0
        by_id = {v['id']: v for v in data['videos']}
        for chunk in page.split('"lockupViewModel":{')[1:]:
            vid = re.search(r'"contentId":"([\w-]{11})"', chunk)
            vw = re.search(r'"text":\{"content":"([^"]+)"\},"accessibilityLabel":"[^"]*views?"', chunk)
            if vid and vw and vid.group(1) in by_id:
                by_id[vid.group(1)]['views'] = short(vw.group(1)); seen += 1
        if not seen: raise ValueError('No view counts found on the Videos tab')
        successes += 1
        print('View counts updated for', seen, 'uploads')
    except Exception as e: print('Video view counts retained last good data:', e)
    # Keep every stored view count in the same short format.
    for v in data['videos']:
        raw = str(v.get('views', '')).replace(',', '')
        if re.fullmatch(r'\d{4,}', raw): v['views'] = compact(int(raw))
    for island in data['maps']:
        try:
            page = fetch('https://fortnite.gg/island/' + island['code'])
            fresh = {'title': match(r'<h1>(.*?)</h1>',page),
                'minutes':metric(page,'Minutes Played','stats-overview-number'),
                'favorites':int(metric(page,'Favorites','stats-overview-number').replace(',','')),
                'players':int(match(r"class='chart-stats-div js-players-now' data-n='(\d+)'",page)),
                'peak':int(match(r"class='chart-stats-div js-alltime-peak' data-n='(\d+)'",page)),
                'image':html.unescape(match(r"property='og:image' content='([^']+)'",page)),
                'description':html.unescape(re.sub('<[^>]+>','',match(r"class='island-desc'>(.*?)</div>",page).replace('<br>','\n'))),
                'statsUpdatedAt':now}
            # Preserve description line breaks before stripping markup.
            raw = re.search(r"class='island-desc'>(.*?)</div>",page,re.S).group(1)
            fresh['description'] = clean(raw.replace('<br>','\n'))
            island.update(fresh)
            successes += 1
            print('Map updated:',island['code'])
        except Exception as e: print('Map retained last good data:',island['code'],e)
    try:
        page = fetch('https://fortnite.gg/creator/twitchsg0hann')
        data['creator'] = { 'minutes':metric(page,'Minutes Played','chart-stats-title'),
            'favorites':metric(page,'Favorites','chart-stats-title'),
            'followers':metric(page,'Followers','chart-stats-title'), 'updatedAt':now }
        successes += 1
        print('Creator updated')
    except Exception as e: print('Creator retained last good data:',e)
    if not successes:
        print('::warning::All public sources failed; deploying the last good content without replacing it')
        return
    temporary = PATH.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    temporary.replace(PATH)

if __name__ == '__main__': run()
