#!/usr/bin/env python3
"""Limit Mali PP resources to the two cores in the board's Android reference DT."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile

PORT = Path(__file__).resolve().parents[1]

def make(source, reference, output, dtc):
    assert not output.exists()
    spec = importlib.util.spec_from_file_location('mp2_board', PORT/'scripts/validate-board.py')
    board = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(board)
    before = board.read_fdt(source.read_bytes())
    ref = board.read_fdt(reference.read_bytes())
    path = '/mali@d00c0000'
    keys = ['num_of_pp','sc_mpp','pmu_domain_config','interrupts','interrupt-names']
    assert board.cells(before[path]['num_of_pp']) == [3]
    assert board.cells(ref[path]['num_of_pp']) == [2]
    assert len(board.cells(ref[path]['interrupts'])) == 24
    assert b'IRQPP2' not in ref[path]['interrupt-names']
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='e900-mp2-') as tmp:
        src = Path(tmp)/'board.dts'
        subprocess.run([str(dtc),'-q','-I','dtb','-O','dts','-o',str(src),str(source)],check=True)
        text = src.read_text()
        start = text.index('\n\tmali@d00c0000 {')
        end = text.index('\n\t};',start)
        section = text[start:end]
        for key in keys:
            value = ref[path][key]
            if key == 'interrupt-names': literal = ', '.join(json.dumps(v.decode()) for v in value.rstrip(b'\0').split(b'\0'))
            else: literal = '<'+' '.join(hex(n) for n in board.cells(value))+'>'
            section,count = re.subn(r'(?m)^(\s*'+re.escape(key)+r' = )[^;]+;',lambda m:m[1]+literal+';',section)
            assert count == 1,key
        text = text[:start]+section+text[end:]
        src.write_text(text)
        target = output/'e900-full.dtb'
        subprocess.run([str(dtc),'-q','-I','dts','-O','dtb','-o',str(target),str(src)],check=True)
    after = board.read_fdt(target.read_bytes())
    changes = []
    assert before.keys() == after.keys()
    for node,props in before.items():
        assert props.keys() == after[node].keys()
        for key,value in props.items():
            if value != after[node][key]:
                assert node == path and key in keys,(node,key)
                changes.append(key)
    assert set(changes) == set(keys)
    for key in keys: assert after[path][key] == ref[path][key]
    (output/'mp2-provenance.json').write_text(json.dumps({'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'reference_sha256':hashlib.sha256(reference.read_bytes()).hexdigest(),'changed_gpu_properties':changes,'failure_address':'0xd00c6004','hardware_tested':False},indent=2)+'\n')
    print('PASS only five GPU properties changed; all match Android MP2 reference')

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('reference',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--dtc',type=Path,required=True)
    a = p.parse_args();make(a.source,a.reference,a.output,a.dtc)
