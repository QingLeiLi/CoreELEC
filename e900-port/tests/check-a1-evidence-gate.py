#!/usr/bin/env python3
"""Offline negative controls from real Build291 records; no hardware access."""
import copy
import gzip
import json
from pathlib import Path
import runpy

PORT = Path(__file__).resolve().parents[1]
module = runpy.run_path(str(PORT / 'scripts/check-a1-transition.py'))
data = json.loads(gzip.decompress((PORT / 'boards/evidence/build291-short-transition.json.gz').read_bytes()))
manifest = {'boot_id': data['boot_id']}

def check(value, info=manifest):
    return module['check'](value, info)

result = check(data)
assert result['verdict'] == 'REJECTED'
assert result['checks']['actual_hold_bits_and_full_live'] == 'FAIL'
assert result['checks']['after_images'] == 'FAIL'  # only one post-transition image
assert result['checks']['software_disabled'] == 'PASS'  # first restore row enabled=0 is legitimate
for key in ('raw_register_pages', 'raw_submission_pages', 'submission_time_coverage', 'restored_16_vsync'):
    assert result['checks'][key] == 'PASS', (key, result['details'][key])
assert check(data, None)['checks']['boot'] == 'UNKNOWN'
assert check(data, {'boot_id': 'foreign'})['checks']['boot'] == 'FAIL'

# Claims in summaries cannot override the raw records or fill missing samples.
changed = copy.deepcopy(data)
changed['records'][10]['live'] = 0x100054b0
assert check(changed)['checks']['raw_register_pages'] == 'FAIL'
changed = copy.deepcopy(data)
changed['records'].pop(12)
assert check(changed)['checks']['row_sequence'] == 'FAIL'
changed = copy.deepcopy(data)
changed['submissions']['records'].pop()
assert check(changed)['checks']['raw_submission_pages'] == 'FAIL'
changed = copy.deepcopy(data)
changed['submissions']['state']['overflow'] = 1
assert check(changed)['checks']['submissions'] == 'FAIL'
changed = copy.deepcopy(data)
changed['submissions']['records'][-1]['stamp'] = changed['records'][0]['stamp']
assert check(changed)['checks']['submission_time_coverage'] == 'FAIL'
changed = copy.deepcopy(data)
changed['image_before']['frames'][1]['frame_timestamp'] = changed['image_before']['frames'][0]['frame_timestamp']
assert check(changed)['checks']['before_images'] == 'FAIL'
changed = copy.deepcopy(data)
changed['image_before']['frames'][0].pop('completion_count')
assert check(changed)['checks']['before_images'] == 'FAIL'
changed = copy.deepcopy(data)
changed['state']['off'] = 0
assert check(changed)['checks']['mode_status'] == 'FAIL'

print('PASS: real default-pulse data rejected as A1; legitimate delayed enable accepted; raw-page tampering, missing rows, overflow, short coverage, stale images and wrong boot rejected')
print('No A1 hardware trial has been executed; this tool never grants final VALID status.')
