#!/usr/bin/env python3
"""YT failure triage — read-only агрегатор для T1 baseline / GATE decision.

Usage:
  python yt_failure_triage.py --since '2026-04-28T08:18:35+00' --limit 10

Output: markdown-ready табличный вывод (per-account ratio, reason histogram,
B6 hit/miss, last-step distribution).

Filters:
  - platform = 'YouTube'
  - account IN ('makiavelli-o2u', 'Инакент-т2щ')
  - created_at > since
  - status != 'awaiting_url'  (pending — пропускаем)
"""
from __future__ import annotations
import argparse
from collections import Counter

import psycopg2
import psycopg2.extras

ACCOUNTS = ('makiavelli-o2u', 'Инакент-т2щ')
DB = dict(host='localhost', port=5432, dbname='openclaw',
          user='openclaw', password='openclaw123')


def fetch(since: str, limit: int):
    sql = """
    SELECT id, account, status, error_code, events, created_at, updated_at
    FROM publish_tasks
    WHERE platform='YouTube'
      AND account = ANY(%s)
      AND created_at > %s
      AND status != 'awaiting_url'
    ORDER BY id ASC
    LIMIT %s
    """
    conn = psycopg2.connect(**DB)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, (list(ACCOUNTS), since, limit))
            return cur.fetchall()
    finally:
        conn.close()


def reason_of(events):
    """Return first error event's meta.reason | meta.category | msg snippet."""
    if not events:
        return 'no_events'
    for ev in events:
        if ev.get('type') == 'error':
            meta = ev.get('meta') or {}
            return (meta.get('reason')
                    or meta.get('category')
                    or (ev.get('msg') or '')[:60]
                    or 'unlabeled_error')
    return 'no_error_event'


def last_step_of(events):
    if not events:
        return None
    for ev in reversed(events):
        if ev.get('type') in ('start', 'info'):
            msg = ev.get('msg') or ''
            return msg[:50]
    return None


def b6_hits_of(events):
    """Count foreground-guard related events."""
    if not events:
        return 0
    return sum(
        1 for ev in events
        if (ev.get('meta') or {}).get('category', '').startswith('yt_app_not_foregrounded')
        or (ev.get('meta') or {}).get('category', '').startswith('yt_foreground')
    )


def render(rows):
    if not rows:
        print('# T1 baseline\n\nNo tasks found in window.')
        return

    total = len(rows)
    by_status = Counter(r['status'] for r in rows)
    by_account = Counter(r['account'] for r in rows)
    done_by_account = Counter(r['account'] for r in rows if r['status'] == 'done')
    reasons = Counter(reason_of(r['events']) for r in rows if r['status'] != 'done')
    b6_total = sum(b6_hits_of(r['events']) for r in rows)
    last_steps = Counter(last_step_of(r['events']) for r in rows if r['status'] != 'done')

    print(f"# T1 baseline ({total} tasks)\n")
    print(f"**Window first→last:** {rows[0]['created_at']} → {rows[-1]['created_at']}\n")

    print("## Status counts\n")
    for st, n in by_status.most_common():
        print(f"- `{st}`: {n}")
    print()

    print("## Per-account ratio\n")
    print("| Account | done | total | rate |")
    print("|---|---|---|---|")
    for acc in ACCOUNTS:
        d, t = done_by_account[acc], by_account[acc]
        rate = f"{(100 * d / t):.0f}%" if t else 'n/a'
        print(f"| {acc} | {d} | {t} | {rate} |")
    print()

    print("## Failure reason histogram\n")
    if not reasons:
        print("(нет фейлов)\n")
    else:
        print("| Reason | Count |")
        print("|---|---|")
        for r, n in reasons.most_common(15):
            print(f"| `{r}` | {n} |")
        print()

    print(f"## B6 v3 foreground-guard hits\n\nTotal events: {b6_total}\n")

    print("## Last-step distribution (failed/preflight only)\n")
    if not last_steps:
        print("(нет фейлов)\n")
    else:
        print("| Last step | Count |")
        print("|---|---|")
        for s, n in last_steps.most_common(10):
            label = (s or '(none)').replace('|', '\\|')
            print(f"| {label} | {n} |")
        print()

    print("## Raw rows\n")
    print("| id | account | status | error_code |")
    print("|---|---|---|---|")
    for r in rows:
        ec = r['error_code'] or ''
        print(f"| {r['id']} | {r['account']} | {r['status']} | `{ec}` |")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', required=True, help='ISO8601 lower bound (created_at)')
    ap.add_argument('--limit', type=int, default=10)
    args = ap.parse_args()
    rows = fetch(args.since, args.limit)
    render(rows)


if __name__ == '__main__':
    main()
