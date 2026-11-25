"""Build an isolated Windows portable distribution. No personal settings/data."""
import argparse,hashlib,importlib.metadata,json,shutil,subprocess,sys,urllib.request,zipfile
from pathlib import Path
import native_receiver
ROOT=Path(__file__).resolve().parent
VERSION='0.6.5'
def main():
    p=argparse.ArgumentParser();p.add_argument('--receiver',type=Path,required=True)
    p.add_argument('--release-dir',type=Path,default=ROOT/'release')
    a=p.parse_args()
    dist=ROOT/f'dist/final-v{VERSION}'
    frozen=dist/'GNSS-SDR-Workbench'
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--name','GNSS-SDR-Workbench','--distpath',str(dist),'--workpath',str(ROOT/f'build/work-v{VERSION}'),'--specpath',str(ROOT/f'build/v{VERSION}'),
                    '--add-data',str(ROOT/'web')+';web','--add-data',str(ROOT/'templates')+';templates',str(ROOT/'server.py')],check=True)
    from PyInstaller.archive.readers import CArchiveReader
    archive=CArchiveReader(str(frozen/'GNSS-SDR-Workbench.exe')).open_embedded_archive('PYZ.pyz')
    for module in ('picker','ctypes.wintypes','signal_input','signals','native_receiver'):
        if module not in archive.toc:raise SystemExit('Missing frozen module: '+module)
    # Build a new staging directory, excluding runtime test outputs and local.json.
    stage=a.release_dir.resolve()/f'GNSS-SDR-Workbench-v{VERSION}-win-x64'
    if stage.exists():raise SystemExit('Release staging already exists; keep it for review or choose a new release version')
    stage.mkdir(parents=True)
    shutil.copy2(frozen/'GNSS-SDR-Workbench.exe',stage)
    shutil.copytree(frozen/'_internal',stage/'_internal')
    receiver=a.receiver.resolve()
    expected_dirs={'bin','licenses','conf','windows_native'}
    expected_files={'gnss-sdr-upstream.tar.gz','LICENSE','THIRD-PARTY.json','WINDOWS-BUILD.json'}
    if {p.name for p in receiver.iterdir() if p.is_dir()}!=expected_dirs or {p.name for p in receiver.iterdir() if p.is_file()}!=expected_files:
        raise ValueError('Unexpected receiver layout')
    record=json.loads((receiver/'WINDOWS-BUILD.json').read_text())
    if record.get('upstream_commit')!=native_receiver.COMMIT or hashlib.sha256((receiver/'bin/gnss-sdr.exe').read_bytes()).hexdigest()!=record['exe_sha256']:
        raise ValueError('Native executable identity mismatch')
    for patch,key in [('windows-compatibility.patch','platform_patch_sha256'),('file-eof.patch','file_eof_patch_sha256')]:
        if hashlib.sha256((receiver/'windows_native'/patch).read_bytes()).hexdigest()!=record.get(key):
            raise ValueError('Receiver source patch digest mismatch: '+patch)
    if hashlib.sha256((receiver/'bin/gnss-sdr-b1c.exe').read_bytes()).hexdigest()!=record['b1c_exe_sha256'] or hashlib.sha256((ROOT/'windows_native/b1c-prelock.patch').read_bytes()).hexdigest()!=record['b1c_prelock_patch_sha256']:
        raise ValueError('B1C receiver identity mismatch')
    if {p.name for p in (receiver/'bin').iterdir()}!=set(record['runtime_dlls'])|{'gnss-sdr.exe','gnss-sdr-b1c.exe','gnss-sdr-snapshots.exe','gnss-sdr-pvt-replay.exe'}:
        raise ValueError('Unexpected native binary inventory')
    for filename,key in [('gnss-sdr-snapshots.exe','snapshot_exe_sha256'),('gnss-sdr-pvt-replay.exe','pvt_replay_sha256')]:
        if hashlib.sha256((receiver/'bin'/filename).read_bytes()).hexdigest()!=record[key]:
            raise ValueError('Native executable digest mismatch: '+filename)
    if hashlib.sha256((ROOT/'windows_native/acquisition-dump-mutex.patch').read_bytes()).hexdigest()!=record['snapshot_patch_sha256']:
        raise ValueError('Acquisition dump patch identity mismatch')
    for filename,digest in record['runtime_dlls'].items():
        if hashlib.sha256((receiver/'bin'/filename).read_bytes()).hexdigest()!=digest:
            raise ValueError('Native DLL digest mismatch: '+filename)
    if hashlib.sha256((receiver/'gnss-sdr-upstream.tar.gz').read_bytes()).hexdigest()!=record['upstream_archive_sha256']:
        raise ValueError('Receiver source archive digest mismatch')
    shutil.copytree(receiver,stage/'receiver')
    shutil.copytree(ROOT/'windows_native',stage/'receiver/windows_native',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('LICENSE','NATIVE-REGRESSION.md','L5-REPEAT.md','PORTABLE.md','THIRD-PARTY.md','SIGNALS.md','M1-REGRESSION.md'):shutil.copy2(ROOT/name,stage/name)
    (stage/'regression').mkdir()
    for record_name in ('native-0.6.0.json','l5-repeat-0.6.1.json'):
        shutil.copy2(ROOT/'regression'/record_name,stage/'regression')
    (stage/'Start-Workbench.cmd').write_text('@echo off\r\ncd /d "%~dp0"\r\nGNSS-SDR-Workbench.exe --open\r\nif errorlevel 1 pause\r\n',encoding='ascii',newline='')
    licenses=stage/'licenses';licenses.mkdir()
    for package in ('numpy','h5py','pyinstaller'):
        distribution=importlib.metadata.distribution(package)
        for f in distribution.files or []:
            if any(x in f.name.upper() for x in ('LICENSE','COPYING','NOTICE')) and distribution.locate_file(f).is_file():
                target=licenses/package/str(f).replace('..','_');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(distribution.locate_file(f),target)
    for name,url in {'python-LICENSE.txt':'https://raw.githubusercontent.com/python/cpython/v3.12.7/LICENSE','hdf5-LICENSE.txt':'https://raw.githubusercontent.com/HDFGroup/hdf5/hdf5_1_14_2/COPYING'}.items():
        (licenses/name).write_bytes(urllib.request.urlopen(url,timeout=30).read())
    manifest={'version':VERSION,'python':sys.version,'components':{n:importlib.metadata.version(n) for n in ('numpy','h5py','pyinstaller')},'files':{str(f.relative_to(stage)).replace('\\','/'):hashlib.sha256(f.read_bytes()).hexdigest() for f in stage.rglob('*') if f.is_file()}}
    (stage/'MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    output=stage.parent/(stage.name+'.zip')
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for f in stage.rglob('*'):
            if f.is_file():z.write(f,Path(stage.name)/f.relative_to(stage))
    source=stage.parent/f'GNSS-SDR-Workbench-v{VERSION}-source.zip'
    paths=subprocess.check_output(['git','ls-files','-z','--cached'],cwd=ROOT).decode('utf8').split('\0')
    paths=sorted(set(paths)|{'sky_geometry.py','web/acquisition-surface.js','windows_native/build_b1c.py','windows_native/b1c-prelock.patch','windows_native/pvt_replay.cc','windows_native/build_pvt.py','windows_native/acquisition-dump-mutex.patch','tests/test_recording_replay.py'})
    with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED) as z:
        for name in paths:
            if name and (ROOT/name).is_file():z.write(ROOT/name,name)
    upstream=stage.parent/'gnss-sdr-upstream-3132713.tar.gz'
    if not upstream.exists() or hashlib.sha256(upstream.read_bytes()).hexdigest()!=record['upstream_archive_sha256']:
        shutil.copy2(stage/'receiver/gnss-sdr-upstream.tar.gz',upstream)
    checks=[]
    for item in (output,source,upstream):
        with item.open('rb') as stream:
            checks.append(hashlib.file_digest(stream,'sha256').hexdigest()+'  '+item.name)
    (stage.parent/f'SHA256SUMS-v{VERSION}.txt').write_text('\n'.join(checks)+'\n',encoding='ascii')
    print(output)
if __name__=='__main__':main()
