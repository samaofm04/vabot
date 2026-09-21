"""Display-only chatter names from the exact email/name pairs in team pages."""
from concurrent.futures import ThreadPoolExecutor
from html import unescape
import json
from pathlib import Path
import re
import threading
import time

_CACHE_FILE = Path(__file__).resolve().parent / 'data/mypuls_chatter_names.json'
_REFRESH_LOCK = threading.Lock()
_LAST_ATTEMPT = 0.0


def parse_team_names(source):
    names = {}
    tables = re.findall(r'''<table\b[^>]*class=["'][^"']*\btable-team\b[^"']*["'][^>]*>(.*?)</table>''', source, re.S | re.I)
    for table in tables:
        for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', table, re.S | re.I):
            name = re.search(r'<h6\b[^>]*>(.*?)</h6>', row, re.S | re.I)
            email = re.search(r'<small\b[^>]*>([^<]*@[^<]*)</small>', row, re.S | re.I)
            if name and email:
                label = unescape(re.sub(r'<[^>]*>', '', name[1])).strip()
                key = unescape(email[1]).strip().lower()
                if label and '@' not in label:
                    names[key] = label
    return names


def _read_cache():
    try:
        data = json.loads(_CACHE_FILE.read_text())
        return data if isinstance(data.get('names'), dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def refresh_chatter_names(creators):
    """Read team pages only. Never change membership, payments or crypto."""
    global _LAST_ATTEMPT
    if not _REFRESH_LOCK.acquire(blocking=False):
        return _read_cache().get('names', {})
    try:
        _LAST_ATTEMPT = time.time()
        import mypuls
        ids = sorted({int(cid) for cid in creators.values() if str(cid).isdigit()})
        def fetch(cid):
            try:
                session = mypuls._make_session()
                if session is None:
                    return {}
                with session:
                    response = session.get(f'{mypuls.BASE_URL}/creator/{cid}/params', timeout=15)
                return parse_team_names(response.text) if response.status_code == 200 else {}
            except Exception:
                return {}
        cache = _read_cache()
        names = dict(cache.get('names', {}))
        found = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            for result in pool.map(fetch, ids):
                found.update(result)
        if found:
            names.update(found)
            _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            temporary = _CACHE_FILE.with_suffix('.tmp')
            temporary.write_text(json.dumps({'updated_at':time.time(),'names':names}, ensure_ascii=False))
            temporary.chmod(0o600)
            temporary.replace(_CACHE_FILE)
        return names
    finally:
        _REFRESH_LOCK.release()


def chatter_display_names(creators):
    cache = _read_cache()
    if time.time() - max(cache.get('updated_at', 0), _LAST_ATTEMPT) > 3600:
        threading.Thread(target=refresh_chatter_names, args=(dict(creators),), daemon=True).start()
    return cache.get('names', {})
