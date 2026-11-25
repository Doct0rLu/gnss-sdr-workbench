"""Build and stage the native x64 file receiver from a pinned upstream source archive."""
import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import tarfile
from pathlib import Path

from pe_dlls import stage
from windows_utf8 import embed_manifest

HERE = Path(__file__).resolve().parent
COMMIT = '3132713b88a1b5b2ee8291bff8076574749349de'
ARCHIVE_SHA = 'b697acdefa7920286152cb254f27c6e8ff1cce767f602d7230ebebcb9ed66fe2'


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def text_section(path):
    with path.open('rb') as f:
        f.seek(60)
        pe = int.from_bytes(f.read(4), 'little')
        f.seek(pe+6)
        count = int.from_bytes(f.read(2), 'little')
        f.seek(pe+20)
        size = int.from_bytes(f.read(2), 'little')
        f.seek(pe+24+size)
        for _ in range(count):
            section = f.read(40)
            if section[:8].rstrip(b'\0') == b'.text':
                size, offset = struct.unpack_from('<II', section, 16)
                f.seek(offset)
                return hashlib.sha256(f.read(size)).hexdigest()
    raise ValueError('Missing PE .text section')


def dependency_notices(prefix, runtime):
    bin_dir = runtime/'bin'
    installed = json.loads((bin_dir/'runtime-dependencies.json').read_text())
    needed = {prefix.name+'/bin/'+Path(p).name for p in installed.values() if Path(p).is_relative_to(prefix)}
    packages = []
    for db in (prefix.parent/'var/lib/pacman/local').glob('*/files'):
        files = db.read_text(encoding='utf8').splitlines()
        matches = needed.intersection(files)
        if not matches:
            continue
        meta = {}
        for group in (db.parent/'desc').read_text(encoding='utf8').split('\n\n'):
            key,*vals = group.strip().splitlines() or ['']
            meta[key] = vals
        name = meta['%NAME%'][0]
        for rel in files:
            path = prefix.parent/rel
            if rel.startswith(prefix.name+'/share/licenses/') and path.is_file():
                dst = runtime/'licenses'/name/path.relative_to(prefix/'share/licenses')
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path,dst)
        packages.append(dict(name=name,version=meta['%VERSION%'][0],license=meta.get('%LICENSE%',[]),
                             upstream=meta.get('%URL%',[]),dlls=sorted(matches)))
        needed.difference_update(matches)
    if needed:
        raise ValueError('Missing package records: '+str(sorted(needed)))
    (runtime/'THIRD-PARTY.json').write_text(json.dumps(packages, indent=2),encoding='utf8')
    (bin_dir/'runtime-dependencies.json').unlink()


def package(args, source, volk):
    runtime = args.output.resolve() if args.output else args.work/'receiver'
    bin_dir = runtime/'bin'
    bin_dir.mkdir(parents=True,exist_ok=True)
    built = args.work/'build/src/main/gnss-sdr.exe'
    exe = bin_dir/built.name
    shutil.copy2(built,exe)
    embed_manifest(exe,built)
    subprocess.run([args.prefix/'bin/strip.exe','--strip-debug',exe],check=True)
    if text_section(exe)!=text_section(built):
        raise ValueError('PE instructions changed while staging resources')
    stage(exe,bin_dir,[volk/'bin',args.prefix/'bin'])
    dependency_notices(args.prefix,runtime)
    shutil.copytree(source/'conf',runtime/'conf',dirs_exist_ok=True)
    shutil.copyfile(source/'COPYING',runtime/'LICENSE')
    notice = runtime/'licenses/volk_gnsssdr'
    notice.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source/'src/algorithms/libs/volk_gnsssdr_module/volk_gnsssdr/COPYING',notice/'COPYING')
    shutil.copyfile(args.archive,runtime/'gnss-sdr-upstream.tar.gz')
    shutil.copytree(HERE,runtime/'windows_native',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
    # Verify every compiled source against an independently extracted and patched tree.
    import tempfile
    with tempfile.TemporaryDirectory(dir=args.work) as temporary:
        ref = extract(args.archive,Path(temporary))
        expected = {p.relative_to(ref):sha(p) for p in ref.rglob('*') if p.is_file()}
        actual = {p.relative_to(source):sha(p) for p in source.rglob('*') if p.is_file()}
        # CMake writes the staged executable under the source tree as a post-build action.
        extras = actual.keys()-expected.keys()
        if any(p.as_posix() not in ('install/exe/gnss-sdr.exe',) for p in extras) or any(actual.get(p)!=h for p,h in expected.items()):
            raise ValueError('Unverified source files: '+str(sorted(extras)))
    meta = dict(upstream_commit=COMMIT,upstream_archive_sha256=ARCHIVE_SHA,
                platform_patch_sha256=sha(HERE/'windows-compatibility.patch'),build_type='Release',
                text_sha256=text_section(exe),exe_sha256=sha(exe),
                runtime_dlls={p.name:sha(p) for p in sorted(bin_dir.glob('*.dll'))})
    (runtime/'WINDOWS-BUILD.json').write_text(json.dumps(meta, indent=2)+'\n',encoding='utf8')
    return runtime


def extract(archive, destination):
    with tarfile.open(archive) as f:
        f.extractall(destination,filter='data')
    source=destination/('gnss-sdr-'+COMMIT)
    subprocess.run(['git','apply','--whitespace=nowarn',str(HERE/'windows-compatibility.patch')],cwd=source,check=True)
    return source


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--archive',required=True,type=Path)
    p.add_argument('--work',required=True,type=Path)
    p.add_argument('--prefix',type=Path,default=Path('C:/msys64/ucrt64'))
    p.add_argument('--volk-prefix',type=Path,help='existing installation of this commit’s VOLK_GNSSSDR')
    p.add_argument('--output',type=Path,help='native receiver distribution directory')
    p.add_argument('--stage-only',action='store_true')
    p.add_argument('--jobs',type=int,default=6)
    a=p.parse_args()
    a.work=a.work.resolve()
    a.prefix=a.prefix.resolve()
    if sha(a.archive)!=ARCHIVE_SHA:
        p.error('Upstream archive SHA-256 mismatch')
    a.work.mkdir(parents=True,exist_ok=True)
    volk=a.volk_prefix.resolve() if a.volk_prefix else a.work/'volk'
    src=a.work/('gnss-sdr-'+COMMIT)
    if not a.stage_only:
        if src.exists():
            p.error('Choose a new build directory')
        src=extract(a.archive,a.work)
        tools=a.prefix/'bin'
        system=Path(os.environ['SystemRoot'])
        env=dict(os.environ,PATH=os.pathsep.join(map(str,[volk/'bin',tools,a.prefix.parent/'usr/bin',system/'System32',system])),
                 MSYSTEM='UCRT64',PKG_CONFIG_PATH=str(a.prefix/'lib/pkgconfig'),CMAKE_PREFIX_PATH=str(a.prefix),
                 XDG_DATA_DIRS=str(a.prefix/'share'),VOLK_GNSSSDR_DIR=str(volk))
        cmake=tools/'cmake.exe'
        def run(*cmd):
            subprocess.run([cmake,*cmd],env=env,check=True)
        flags=['-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_C_COMPILER='+str(tools/'gcc.exe'),
               '-DCMAKE_CXX_COMPILER='+str(tools/'g++.exe'),'-DPYTHON_EXECUTABLE='+str(tools/'python.exe')]
        if not a.volk_prefix:
            run('-S',src/'src/algorithms/libs/volk_gnsssdr_module/volk_gnsssdr','-B',a.work/'volk-build',*flags,
                '-DCMAKE_INSTALL_PREFIX='+str(volk),'-DVOLK_CPU_FEATURES=OFF','-DENABLE_TESTING=OFF','-DENABLE_ORC=OFF')
            run('--build',a.work/'volk-build','--parallel',str(a.jobs))
            run('--install',a.work/'volk-build')
        shutil.copyfile(HERE/'native-imports.cmake',a.work/'native-imports.cmake')
        run('-S',src,'-B',a.work/'build',*flags,'-DCMAKE_EXPORT_COMPILE_COMMANDS=ON','-DCMAKE_CXX_SCAN_FOR_MODULES=OFF',
            '-DBLA_VENDOR=OpenBLAS','-DBLA_PKGCONFIG_BLAS=openblas','-DBLA_PKGCONFIG_LAPACK=openblas',
            '-DCMAKE_PROJECT_INCLUDE='+str(a.work/'native-imports.cmake'),'-DCMAKE_PREFIX_PATH='+str(a.prefix),
            '-DPython3_EXECUTABLE='+str(tools/'python.exe'),'-DENABLE_UHD=OFF','-DENABLE_ZMQ=OFF',
            '-DENABLE_CPUFEATURES=OFF','-DENABLE_UNIT_TESTING=OFF','-DENABLE_SYSTEM_TESTING=OFF','-DENABLE_GNSS_SIM_INSTALL=OFF')
        run('--build',a.work/'build','--target','gnss-sdr','--parallel',str(a.jobs))
    print(package(a,src,volk))


if __name__=='__main__':
    main()
