"""Link the optional B1C receiver from an existing build.py Release build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from windows_utf8 import embed_manifest


PATCHES={
    'acquisition-dump-mutex.patch': ('acquisition','pcps_acquisition.cc'),
    'b1c-prelock.patch': ('telemetry_decoder','beidou_b1c_telemetry_decoder_gs.cc'),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(target):
    path=target.parent.parent/'WINDOWS-BUILD.json'
    meta=json.loads(path.read_text(encoding='utf8'))
    if digest(target.with_name('gnss-sdr.exe'))!=meta['exe_sha256']:
        raise ValueError('Reference executable digest mismatch')
    meta.update(b1c_exe_sha256=digest(target),snapshot_exe_sha256=digest(target.with_name('gnss-sdr-snapshots.exe')),
        b1c_prelock_patch_sha256=digest(Path(__file__).with_name('b1c-prelock.patch')),
        snapshot_patch_sha256=digest(Path(__file__).with_name('acquisition-dump-mutex.patch')))
    path.write_text(json.dumps(meta,indent=2)+'\n',encoding='utf8')


def build(work, target, prefix):
    build_dir = work/'build'
    tools = prefix/'bin'
    env = dict(os.environ, PATH=str(tools)+os.pathsep+os.environ['PATH'])
    def run(*args, cwd=build_dir):
        return subprocess.check_output(args,cwd=cwd,env=env,text=True)

    entries = json.loads((build_dir/'compile_commands.json').read_text())
    link = json.loads(run(tools/'ninja.exe','-t','compdb','-x'))
    command = next(row['command'] for row in link if row['output'].replace('\\','/').endswith('/main/gnss-sdr.exe'))
    flags=command.split('g++.exe ',1)[1].split(' -o ',1)[0]
    with tempfile.TemporaryDirectory() as tmp:
        folder=Path(tmp)
        rsp=folder/'args.rsp'
        for patch,(module,name) in PATCHES.items():
            entry=next(row for row in entries if Path(row['file']).name==name)
            source=Path(entry['file'])
            rel=Path('src/algorithms')/module/'gnuradio_blocks'
            edited=folder/rel/name
            edited.parent.mkdir(parents=True)
            shutil.copyfile(source,edited)
            run('git','apply',str(Path(__file__).with_name(patch).resolve()),cwd=folder)
            obj=folder/(name+'.obj')
            rsp.write_text(entry['command'].split('g++.exe ',1)[1].split(' -o ',1)[0],encoding='utf8')
            run(tools/'g++.exe','@'+str(rsp),'-iquote',source.parent,'-c',edited,'-o',obj)
            archive=(rel/f'lib{module}_gr_blocks.a').as_posix()
            if archive not in flags:
                raise ValueError('Native block archive missing from link')
            lib=folder/Path(archive).name
            shutil.copyfile(build_dir/archive,lib)
            run(tools/'ar.exe','rs',lib,obj)
            flags=flags.replace(archive,'"'+lib.as_posix()+'"')
            exe=folder/'linked.exe'
            rsp.write_text(flags,encoding='utf8')
            run(tools/'g++.exe','@'+str(rsp),'-o',exe)
            staged=folder/'staged.exe'
            shutil.copyfile(exe,staged)
            embed_manifest(staged,exe)
            run(tools/'strip.exe','--strip-debug',staged)
            shutil.copyfile(staged,target if module=='telemetry_decoder' else target.with_name('gnss-sdr-snapshots.exe'))
        record(target)


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prefix', type=Path, default=Path('C:/msys64/ucrt64'))
    args = parser.parse_args()
    build(args.work.resolve(), args.output.resolve(), args.prefix.resolve())
