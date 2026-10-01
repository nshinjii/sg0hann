"""Refresh public feeds; preserve last good data independently for every source."""
import json, re, html, sys, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone
ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('.')
PATH = ROOT / 'content.json'
CHANNEL = 'UCR9uxbyH0S_sAfOoZLkm0FA'

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'sg0hann-website/1.0 (public content refresh)'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8')

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
                'views':str(stats.get('views')) if stats is not None else old.get('views',''),
                'duration':old.get('duration',''), 'project':old.get('project','SG0HANN'),
                'image':'https://i.ytimg.com/vi/' + vid + '/hqdefault.jpg'}
        data['videos'] = sorted(by_id.values(), key=lambda v:v.get('date',''), reverse=True)
        data['youtubeUpdatedAt'] = now
        successes += 1
        print('YouTube updated:', len(data['videos']), 'videos')
    except Exception as e: print('YouTube retained last good data:',e)
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
    if not successes: raise RuntimeError('All sources failed; no data replaced')
    PATH.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

if __name__ == '__main__': run()
