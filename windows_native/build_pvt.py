"""Build the observables-only entry point against the Windows GNSS-SDR libraries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from windows_utf8 import embed_manifest


def build(work, target, prefix):
    build_dir = work/'build'
    tools = prefix/'bin'
    env = dict(os.environ, PATH=str(tools)+os.pathsep+os.environ['PATH'])
    def run(*args):
        return subprocess.check_output(args, cwd=build_dir, env=env, text=True)

    entries = json.loads((build_dir/'compile_commands.json').read_text())
    adapter = next(row for row in entries if Path(row['file']).name=='rtklib_pvt.cc')
    upstream = Path(adapter['file']).parents[3]
    commands = json.loads(run(tools/'ninja.exe','-t','compdb','-x'))
    link = next(row['command'] for row in commands if row['output'].replace('\\','/').endswith('/main/gnss-sdr.exe'))
    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        rsp = work_dir/'arguments.rsp'
        obj = work_dir/'pvt_replay.obj'
        source = Path(__file__).with_name('pvt_replay.cc').resolve()
        flags = adapter['command'].split('g++.exe ',1)[1].split(' -o ',1)[0]
        rsp.write_text(flags,encoding='utf8')
        run(tools/'g++.exe','@'+str(rsp),'-I'+str(upstream/'core/receiver'),
            '-I'+str(upstream/'algorithms/PVT/adapters'),'-c',source,'-o',obj)
        flags = link.split('g++.exe ',1)[1].split(' -o ',1)[0]
        flags = flags.replace('src/main/CMakeFiles/gnss-sdr.dir/main.cc.obj','"'+obj.as_posix()+'"')
        exe = work_dir/'linked.exe'
        rsp.write_text(flags,encoding='utf8')
        run(tools/'g++.exe','@'+str(rsp),'-o',exe)
        staged = work_dir/'staged.exe'
        shutil.copyfile(exe,staged)
        embed_manifest(staged,exe)
        run(tools/'strip.exe','--strip-debug',staged)
        shutil.copyfile(staged,target)
        manifest=target.parent.parent/'WINDOWS-BUILD.json'
        meta=json.loads(manifest.read_text(encoding='utf8'))
        meta['pvt_replay_sha256']=hashlib.sha256(target.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(meta,indent=2)+'\n',encoding='utf8')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--prefix',type=Path,default=Path('C:/msys64/ucrt64'))
    args=parser.parse_args()
    build(args.work.resolve(),args.output.resolve(),args.prefix.resolve())
