#!/usr/bin/env python3
"""Keep installed tools and completed host stamps independently of huge builds."""
import json,os,pathlib,shutil,sys
GIB=1024**3

def size(path):
    total=0
    for root,dirs,files in os.walk(path,followlinks=False):
        for name in files:
            p=pathlib.Path(root)/name
            if not p.is_symlink():total+=p.stat().st_size
    return total

def copy_file(source,target):
    try:os.link(source,target)
    except OSError:shutil.copy2(source,target)

def expected(work):
    return json.loads((work/'cache-identity.json').read_text())

def prepare(repo,work):
    identity=expected(work);dest=work/'toolchain-snapshot'
    if dest.exists():shutil.rmtree(dest)
    builds=[p for p in repo.glob('build.*') if (p/'toolchain/bin').is_dir()]
    ready=False
    if len(builds)==1:
        build=builds[0]
        # Conservative uncompressed cap: the saved archive is smaller still.
        if size(build/'toolchain')<=3*GIB:
            target=dest/build.name
            shutil.copytree(build/'toolchain',target/'toolchain',symlinks=True,copy_function=copy_file)
            for stamp in (build/'.stamps').glob('*/build_*'):
                if stamp.name not in {'build_host','build_bootstrap'} or not stamp.is_file():continue
                p=target/'.stamps'/stamp.parent.name/stamp.name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(stamp,p)
            (dest/'identity.json').write_text(json.dumps({'schema':1,'compat':identity['compat'],'source_root':str(repo.resolve()),'build':build.name})+'\n')
            ready=True
    # A monolithic state previously uploaded 10.14GiB and then disappeared.
    # Stay below a 4GiB raw budget; preserve this optional richer checkpoint
    # only when small, with the independent <=3GiB toolchain as the fallback.
    full_ready=size(repo)<=4*GIB
    print(f'Toolchain fallback prepared: {ready}; bounded full-state cache: {full_ready}')
    output=os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output,'a') as f:f.write(f'toolchain_ready={str(ready).lower()}\nfull_ready={str(full_ready).lower()}\n')
    return ready,full_ready

def restore(repo,work):
    dest=work/'toolchain-snapshot'
    meta=json.loads((dest/'identity.json').read_text());identity=expected(work)
    if meta.get('schema')!=1 or meta['compat'] not in {identity['compat'],identity.get('previous_compat')} or meta['source_root']!=str(repo.resolve()):
        raise ValueError('Incompatible toolchain snapshot')
    name=meta['build']
    if pathlib.Path(name).name!=name or not name.startswith('build.'):
        raise ValueError('Invalid build directory')
    target=repo/name
    if target.exists():raise ValueError('Refuse to overlay an existing build tree')
    source=dest/name
    # Only known installed tools and host stamps are restored. Target build
    # stamps are intentionally absent: no missing target output is marked built.
    if set(p.name for p in source.iterdir())-{'toolchain','.stamps'}:
        raise ValueError('Unexpected snapshot content')
    for stamp in (source/'.stamps').glob('*/*'):
        if stamp.name not in {'build_host','build_bootstrap'}:
            raise ValueError('Target or install stamp in toolchain fallback')
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(source,target,symlinks=True,copy_function=copy_file)
    print('Restored installed toolchain and completed host/bootstrap stamps; target packages rebuild as needed')

if __name__=='__main__':
    action=sys.argv[1];repo=pathlib.Path(sys.argv[2]).resolve();work=pathlib.Path(os.environ['E900_WORK_ROOT']).resolve()
    if action=='prepare':prepare(repo,work)
    elif action=='restore':restore(repo,work)
    else:raise SystemExit('Unknown action')
