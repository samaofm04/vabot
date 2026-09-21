"""Local bot health and systemd watchdog; no credentials or remote requests."""
import argparse
import asyncio
import json
import logging
import math
import os
from pathlib import Path
import socket
import tempfile
import time

log = logging.getLogger('vabot.health')


def snapshot(bots, tasks, states):
    details = {}
    watchdog_ok = True
    for label, bot in bots.items():
        state = states.get(label, 'starting')
        alive = not tasks[label].done()
        # Invalid credentials/permissions need intervention, not a restart loop.
        if not alive and state != 'blocked':
            watchdog_ok = False
        latency = float(getattr(bot, 'latency', float('inf')))
        ready = bool(bot.is_ready()) and alive
        failures = len(getattr(bot, 'echecs_cogs', []))
        synced = str(getattr(bot, 'etat_sync', '')).endswith('synchronisee(s)')
        details[label] = {
            'state': state, 'task_alive': alive, 'ready': ready,
            'heartbeat_latency_seconds': round(latency, 3) if math.isfinite(latency) else None,
            'cog_failures': failures, 'commands_synced': synced,
            'healthy': ready and math.isfinite(latency) and latency < 60 and failures == 0 and synced,
        }
    return {
        'pid': os.getpid(), 'updated_at': time.time(),
        'healthy': bool(details) and all(b['healthy'] for b in details.values()),
        'watchdog_ok': bool(details) and watchdog_ok, 'bots': details,
    }


def notify(message):
    address = os.environ.get('NOTIFY_SOCKET')
    if not address:
        return
    if address.startswith('@'):
        address = '\0' + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.settimeout(1)
            sock.sendto(message.encode(), address)
    except OSError:
        log.exception('Notification systemd impossible')


def write_snapshot(path, data):
    path = Path(path)
    # The runtime directory is provided by systemd, never made public here.
    fd, tmp = tempfile.mkstemp(prefix='.health-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(data, out)
            out.write('\n')
        os.chmod(tmp, 0o640)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


async def watch_health(bots, tasks, states):
    previous = None
    while True:
        data = snapshot(bots, tasks, states)
        summary = ', '.join(
            f"{label}={'ready' if b['healthy'] else b['state'] + '/not-ready'}"
            for label, b in data['bots'].items()
        )
        if summary != previous:
            log.info('Sante Discord : %s', summary)
            previous = summary
        if data['watchdog_ok']:
            # Running reconnect attempts during a Discord outage remain alive.
            # A dead bot task or a blocked event loop stops these notifications.
            notify('WATCHDOG=1\nSTATUS=' + summary)
        else:
            notify('STATUS=Bot task stopped; waiting for watchdog recovery: ' + summary)
        path = os.environ.get('VA_HEALTH_FILE')
        if path:
            try:
                write_snapshot(path, data)
            except OSError:
                log.exception('Ecriture du diagnostic de sante impossible')
        await asyncio.sleep(10)


def check_file(path, expected_pid=None, max_age=30):
    try:
        data = json.loads(Path(path).read_text())
        age = time.time() - float(data['updated_at'])
        valid = (0 <= age <= max_age and data.get('healthy') is True
                 and (expected_pid is None or data.get('pid') == expected_pid))
        return valid, data
    except (OSError, ValueError, KeyError, TypeError):
        return False, {'healthy': False, 'error': 'health_missing_or_invalid'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', default='/run/va-bot/health.json')
    parser.add_argument('--pid', type=int)
    parser.add_argument('--wait', type=float, default=0)
    args = parser.parse_args()
    deadline = time.monotonic() + args.wait
    while True:
        valid, data = check_file(args.file, args.pid)
        if valid or time.monotonic() >= deadline:
            print(json.dumps(data, ensure_ascii=False))
            return 0 if valid else 1
        time.sleep(min(2, max(0, deadline - time.monotonic())))


if __name__ == '__main__':
    raise SystemExit(main())
