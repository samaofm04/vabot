"""Private, persistent Dashboard snapshots; external reads happen off-request."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import wraps
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import threading
import time
from zoneinfo import ZoneInfo

PERIODS = {'today', 'yesterday', 'week', 'month', 'trente'}
GROUPS = {'all', 'mym', 'of_us', 'of_fr'}


def period_bounds(period, today=None):
    today = today or datetime.now(ZoneInfo('Europe/Paris')).date()
    if period == 'today':
        return today, today, "Aujourd'hui"
    if period == 'yesterday':
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday, 'Hier'
    if period == 'month':
        return today.replace(day=1), today, 'Ce mois'
    if period == 'trente':
        # « Mois dernier » : le mois calendaire precedent, en entier
        # (du 1er au dernier jour). La cle reste 'trente' pour ne pas
        # casser les liens deja partages ni les instantanes en cache.
        fin = today.replace(day=1) - timedelta(days=1)
        return fin.replace(day=1), fin, 'Mois dernier'
    # « Cette semaine » : du lundi a aujourd'hui, et non sept jours
    # glissants. Un lundi ne montre donc que le lundi, un mardi le
    # lundi et le mardi — c'est ce que « cette semaine » veut dire.
    return today - timedelta(days=today.weekday()), today, 'Cette semaine'


def selection(args):
    period = args.get('home_period', 'week')
    group = args.get('home_group', 'all')
    return (period if period in PERIODS else 'week', group if group in GROUPS else 'all')


class SnapshotStore:
    def __init__(self, directory, revision, clock=time.time, fresh_seconds=300):
        self.directory = Path(directory)
        self.revision = revision
        self.clock = clock
        self.fresh_seconds = fresh_seconds
        self.lock = threading.RLock()
        self.records = {}
        self.jobs = set()
        self.retry_after = {}
        self.generation = 0
        try:
            self.invalidated_at = float((self.directory / '.invalidated').read_text())
        except (OSError, ValueError):
            self.invalidated_at = 0
        # A single renderer at a time shares MyPuls caches instead of multiplying calls.
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='dashboard-snapshot')

    def _path(self, key):
        return self.directory / (sha256(key.encode()).hexdigest() + '.json')

    def _read(self, key):
        if key in self.records:
            return self.records[key]
        try:
            data = json.loads(self._path(key).read_text())
            if (data.get('key') == key and data.get('revision') == self.revision
                    and isinstance(data.get('html'), str) and isinstance(data.get('updated'), (float, int))):
                self.records[key] = data
                return data
        except (OSError, ValueError, AttributeError):
            pass
        return None

    def _write(self, key, record):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = self._path(key)
        temporary = target.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as handle:
            os.chmod(temporary, 0o600)
            json.dump(record, handle, ensure_ascii=False)
        os.replace(temporary, target)
        # Snapshot retention is bounded; source financial records are never touched.
        files = sorted(self.directory.glob('*.json'), key=lambda p: p.stat().st_mtime)
        for old in files[:-768]:
            old.unlink(missing_ok=True)

    def get(self, key, compute):
        with self.lock:
            hit = self._read(key)
            age = self.clock() - hit['updated'] if hit else None
            ttl = self.fresh_seconds if hit and hit.get('complete') else 45
            stale = not hit or age >= ttl or hit['updated'] < self.invalidated_at
            if stale and key not in self.jobs and self.clock() >= self.retry_after.get(key, 0):
                self.jobs.add(key)
                generation = self.generation
                self.pool.submit(self._refresh, key, compute, generation)
            running = key in self.jobs
            status = 'ready' if hit and not stale else 'refreshing' if hit and running else 'saved' if hit else 'pending' if running else 'error'
            return hit, status

    def _refresh(self, key, compute, generation):
        try:
            html = compute()
            if "class='home-overview'" not in html:
                raise ValueError('No revenue overview returned')
            complete = 'data-home-complete="true"' in html
            with self.lock:
                if generation != self.generation:
                    return
                previous = self._read(key)
                # Keep the complete snapshot through transient API failures.
                if previous and previous.get('complete') and not complete:
                    self.retry_after[key] = self.clock() + 60
                    return
                record = dict(key=key, revision=self.revision, html=html,
                              updated=self.clock(), complete=complete)
                self._write(key, record)
                self.records[key] = record
        except Exception:
            with self.lock:
                self.retry_after[key] = self.clock() + 60
            logging.getLogger(__name__).exception('Dashboard snapshot refresh failed')
        finally:
            with self.lock:
                self.jobs.discard(key)

    def invalidate(self):
        with self.lock:
            self.generation += 1
            self.invalidated_at = self.clock()
            self.retry_after.clear()
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            marker = self.directory / '.invalidated'
            marker.write_text(str(self.invalidated_at))
            marker.chmod(0o600)


def _pending(period, group, failed=False):
    from dashboard_layout import render_pending
    return render_pending(period, group, failed)


_STORE = None


def dashboard_cached(fn):
    global _STORE
    if _STORE is None:
        root = Path(__file__).resolve().parent
        revision = sha256(b''.join((root / name).read_bytes() for name in
                         ('web_upload.py', 'dashboard_platforms.py', 'dashboard_cache.py', 'dashboard_layout.py'))).hexdigest()
        _STORE = SnapshotStore(root / 'data' / 'dashboard_snapshots', revision)

    @wraps(fn)
    def wrapped(*args, **kwargs):
        from flask import copy_current_request_context, request
        period, group = selection(request.args)
        day = datetime.now(ZoneInfo('Europe/Paris')).date()
        start, end, _ = period_bounds(period, day)
        key = f'{day}|{period}|{group}|{start}|{end}'
        @copy_current_request_context
        def compute():
            request.environ['dashboard.day'] = str(day)
            return fn(*args, **kwargs)
        record, status = _STORE.get(key, compute)
        updated = record['updated'] if record else 0
        content = record['html'] if record else _pending(period, group, status == 'error')
        age = max(0, int((time.time() - updated) // 60)) if record else 0
        note = ''
        if status in ('refreshing', 'saved'):
            note = (f'<div class="home-snapshot-note" role="status">Relevé enregistré il y a {age} min'
                    + (' · actualisation en cours…' if status == 'refreshing' else ' · nouvelle tentative dans une minute.') + '</div>')
        return ('''<style>
.home-snapshot-note{padding:9px 13px;margin-bottom:12px;border-radius:8px;background:rgba(59,130,246,.08);color:#93b7ed;font-size:12px}
body.light .home-snapshot-note{color:#3268a1}
</style>'''
                + f'<div class="home-snapshot" data-home-period="{period}" data-home-group="{group}" '
                f'data-home-day="{day}" data-home-start="{start}" data-home-end="{end}" '
                f'data-home-updated="{updated}" data-home-status="{status}">{note}{content}</div>')
    wrapped.invalidate = _STORE.invalidate
    return wrapped
