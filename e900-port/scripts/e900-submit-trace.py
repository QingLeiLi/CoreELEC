#!/usr/bin/env python3
"""Explicitly capture bounded software RDMA tables; no playback or MMIO access."""
import argparse
import difflib
import fcntl
import hashlib
import json
from pathlib import Path

FIELDS = 'index generation stamp batch handle kind reg value item'.split()
ROOT = Path('/sys/module/rdma_mgr/parameters')


def selected(reg):
    return (0x1a50 <= reg <= 0x1a6f or reg in (0x1aa7, 0x1a06, 0x1a07) or
            0x1d00 <= reg <= 0x1dff or 0x3800 <= reg <= 0x38ff or
            0x3d60 <= reg <= 0x3d6f)


def state(text):
    result = {k: int(v) for k, v in (w.split('=', 1) for w in text.split())}
    if set(result) != {'generation', 'status', 'count', 'capacity', 'overflow'}:
        raise ValueError('Unknown submit state schema')
    if result['status'] not in (0, 1, 2) or result['capacity'] != 4096 or not 0 <= result['count'] <= 4096:
        raise ValueError('Invalid submit state')
    return result


def decode(pages, expected):
    rows, batches = [], {}
    for page in pages:
        for line in page.splitlines():
            values = line.split()
            if not values:  # sysfs appends a newline after module-param getters.
                continue
            if len(values) != len(FIELDS):
                raise ValueError('Unexpected submit record width')
            r = {k: int(v, 10 if i < 2 else 16) for i, (k, v) in enumerate(zip(FIELDS, values))}
            if any(v < 0 or v > (0xffffffffffffffff if k == 'stamp' else 0xffffffff) for k, v in r.items()):
                raise ValueError('Out-of-range submit field')
            if r['index'] != len(rows) or r['generation'] != expected['generation']:
                raise ValueError('Missing/replaced/duplicate submit row')
            if not 0 < r['handle'] < 8 or not r['batch'] or r['kind'] not in (0, 1, 2, 3):
                raise ValueError('Invalid submit record')
            batch = batches.get(r['batch'])
            if r['kind'] == 0:
                if batch or r['reg'] or not 0 < r['value'] <= 256 or r['item'] <= 0:
                    raise ValueError('Invalid prepared-table header')
                batches[r['batch']] = dict(handle=r['handle'], trigger=r['value'], total=r['item'],
                                           words=[], terminal='pending', first_stamp=r['stamp'])
            else:
                if not batch or batch['handle'] != r['handle'] or batch['terminal'] != 'pending':
                    raise ValueError('Record has no pending prepared table')
                if r['kind'] == 1:
                    if not selected(r['reg']) or r['item'] >= batch['total'] or (batch['words'] and r['item'] <= batch['words'][-1][0]):
                        raise ValueError('Invalid table word or order')
                    batch['words'].append([r['item'], r['reg'], r['value']])
                else:
                    if r['reg'] or r['item'] or not batch['words']:
                        raise ValueError('Invalid table terminal')
                    batch['terminal'] = 'irq_observed' if r['kind'] == 2 else 'canceled'
                    batch['terminal_value'] = r['value']
            rows.append(r)
    if len(rows) != expected['count'] or any(not b['words'] for b in batches.values()):
        raise ValueError('Incomplete submit export')
    return rows, batches


def read(name):
    return (ROOT / ('gxlx2_submit_' + name)).read_text()


def write(name, value):
    (ROOT / ('gxlx2_submit_' + name)).write_text(str(value) + '\n')


def export(io_read=read, io_write=write):
    before = state(io_read('scan'))
    if before['status'] != 2:
        raise ValueError('Freeze trace before exporting')
    pages = []
    for page in range((before['count'] + 7) // 8):
        io_write('page', page)
        pages.append(io_read('data'))
    after = state(io_read('scan'))
    if before != after:
        raise ValueError('Trace changed during export')
    rows, batches = decode(pages, before)
    return dict(schema=1, state=before, pages=pages, records=rows, batches=batches,
                status='overflow_partial' if before['overflow'] else ('collected_software_tables' if before['count'] else 'empty_no_evidence'),
                hardware_word_execution='not_verified', physical_screen_observed=False,
                notes='IRQ association uses software pending-table state, not hardware per-table cookies. '
                      'Only fixed MIF/route/VPP/CSC/HDR registers in normal-trigger manager submissions are covered; '
                      'direct/auto-start/debug writes and unselected registers are not complete traces.')


def compare(left, right):
    for doc in (left, right):
        if doc.get('schema') != 1 or doc['state']['overflow'] or not doc['state']['count']:
            raise ValueError('Cannot compare an overflowed/unknown trace as complete')
        decode(doc['pages'], doc['state'])
    def normalize(doc):
        result = []
        # Rebuild from raw pages, rather than trusting cached derived fields.
        _, batches = decode(doc['pages'], doc['state'])
        for b in batches.values():
            result.append((b['handle'], b['trigger'], tuple((r, v) for _, r, v in b['words'])))
        return result
    a, b = normalize(left), normalize(right)
    changes = []
    for tag, i, j, k, l in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag != 'equal':
            changes.append(dict(operation=tag, left_range=[i, j], right_range=[k, l], left=a[i:j], right=b[k:l]))
    return dict(schema=1, same_ordered_selected_batches=a == b, left_batches=len(a), right_batches=len(b),
                left_sha256=hashlib.sha256(repr(a).encode()).hexdigest(),
                right_sha256=hashlib.sha256(repr(b).encode()).hexdigest(), differences=changes,
                conclusion='Ordered selected software submissions only; timing, unselected writes, hardware execution and pixels remain separate evidence.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    subs.add_parser('start')
    stop = subs.add_parser('stop'); stop.add_argument('--generation', required=True, type=int); stop.add_argument('--out', required=True, type=Path)
    dump = subs.add_parser('dump'); dump.add_argument('--out', required=True, type=Path)
    diff = subs.add_parser('compare'); diff.add_argument('left', type=Path); diff.add_argument('right', type=Path)
    a = parser.parse_args()
    if a.command == 'compare':
        print(json.dumps(compare(json.loads(a.left.read_text()), json.loads(a.right.read_text())), indent=2)); return
    with open('/run/e900-submit.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if a.command == 'start':
            if state(read('scan'))['status'] == 1:
                raise RuntimeError('Another trace is active')
            write('scan', 1)
            print(json.dumps(state(read('scan')))); return
        if a.command == 'stop':
            if state(read('scan'))['generation'] != a.generation:
                raise RuntimeError('Refusing to stop a different generation')
            write('scan', 0)
        result = export()
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(dict(status=result['status'], state=result['state'])))


if __name__ == '__main__':
    main()
