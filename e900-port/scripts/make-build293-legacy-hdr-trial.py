#!/usr/bin/env python3
"""Pinned 293H experiment: validated five SDR selectors plus two HDR helpers."""
import argparse,importlib.util,json
from pathlib import Path
spec=importlib.util.spec_from_file_location('legacy_sdr',Path(__file__).with_name('make-build293-legacy-csc-trial.py'))
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)

def prepare(source,out):
    original_changes=base.CHANGES
    base.CHANGES=original_changes+(
        (0x9c9ad4,0x5400102c,None,'hdr_process.isra.0: legacy HDR10->SDR helper'),
        (0x9c958c,0x54000f8c,None,'hlg_process.constprop.0: legacy HLG->SDR helper'))
    try:
        base.prepare(source,out)
    finally:
        base.CHANGES=original_changes
    (out/'e900-Image293L').rename(out/'e900-Image293H')
    p=out/'provenance.json';m=json.loads(p.read_text())
    m['scope']='GXLX2-only binary experiment: five SDR selectors plus HDR10/HLG helper entry; no claim all HDR paths are legacy or valid'
    m['supersedes']='293L for temporary HDR10/HLG tests; original source-built 293 retained'
    p.write_text(json.dumps(m,indent=2)+'\n')
    print('Prepared total seven selector slots; added HDR helper slots are NOPs preserving original legacy fall-through')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();prepare(a.source,a.output)
