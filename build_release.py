"""Build an isolated Windows portable distribution. No personal settings/data."""
import argparse,hashlib,importlib.metadata,json,shutil,subprocess,sys,urllib.request,zipfile
from pathlib import Path
import native_receiver
ROOT=Path(__file__).resolve().parent
def main():
    p=argparse.ArgumentParser();p.add_argument('--receiver',type=Path,required=True);a=p.parse_args()
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--name','GNSS-SDR-Workbench','--distpath',str(ROOT/'dist/final-v0.6.0'),'--workpath',str(ROOT/'build/work-v0.6.0'),'--specpath',str(ROOT/'build/v0.6.0'),
                    '--add-data',str(ROOT/'web')+';web','--add-data',str(ROOT/'templates')+';templates',str(ROOT/'server.py')],check=True)
    from PyInstaller.archive.readers import CArchiveReader
    archive=CArchiveReader(str(ROOT/'dist/final-v0.6.0/GNSS-SDR-Workbench/GNSS-SDR-Workbench.exe')).open_embedded_archive('PYZ.pyz')
    for module in ('picker','ctypes.wintypes','signal_input','signals','native_receiver'):
        if module not in archive.toc:raise SystemExit('Missing frozen module: '+module)
    # Build a new staging directory, excluding runtime test outputs and local.json.
    stage=ROOT/'release/GNSS-SDR-Workbench-v0.6.0-win-x64'
    if stage.exists():raise SystemExit('Release staging already exists; keep it for review or choose a new release version')
    stage.mkdir(parents=True)
    frozen=ROOT/'dist/final-v0.6.0/GNSS-SDR-Workbench'
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
    if {p.name for p in (receiver/'bin').iterdir()}!=set(record['runtime_dlls'])|{'gnss-sdr.exe'}:
        raise ValueError('Unexpected native binary inventory')
    for filename,digest in record['runtime_dlls'].items():
        if hashlib.sha256((receiver/'bin'/filename).read_bytes()).hexdigest()!=digest:
            raise ValueError('Native DLL digest mismatch: '+filename)
    if hashlib.sha256((receiver/'gnss-sdr-upstream.tar.gz').read_bytes()).hexdigest()!=record['upstream_archive_sha256']:
        raise ValueError('Receiver source archive digest mismatch')
    shutil.copytree(receiver,stage/'receiver')
    for name in ('LICENSE','NATIVE-REGRESSION.md','PORTABLE.md','THIRD-PARTY.md','SIGNALS.md','M1-REGRESSION.md'):shutil.copy2(ROOT/name,stage/name)
    (stage/'regression').mkdir()
    shutil.copy2(ROOT/'regression/native-0.6.0.json',stage/'regression')
    (stage/'Start-Workbench.cmd').write_text('@echo off\r\ncd /d "%~dp0"\r\nGNSS-SDR-Workbench.exe --open\r\nif errorlevel 1 pause\r\n',encoding='ascii',newline='')
    licenses=stage/'licenses';licenses.mkdir()
    for package in ('numpy','h5py','pyinstaller'):
        distribution=importlib.metadata.distribution(package)
        for f in distribution.files or []:
            if any(x in f.name.upper() for x in ('LICENSE','COPYING','NOTICE')) and distribution.locate_file(f).is_file():
                target=licenses/package/str(f).replace('..','_');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(distribution.locate_file(f),target)
    for name,url in {'python-LICENSE.txt':'https://raw.githubusercontent.com/python/cpython/v3.12.7/LICENSE','hdf5-LICENSE.txt':'https://raw.githubusercontent.com/HDFGroup/hdf5/hdf5_1_14_2/COPYING'}.items():
        (licenses/name).write_bytes(urllib.request.urlopen(url,timeout=30).read())
    manifest={'version':'0.6.0','python':sys.version,'components':{n:importlib.metadata.version(n) for n in ('numpy','h5py','pyinstaller')},'files':{str(f.relative_to(stage)).replace('\\','/'):hashlib.sha256(f.read_bytes()).hexdigest() for f in stage.rglob('*') if f.is_file()}}
    (stage/'MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    output=stage.parent/(stage.name+'.zip')
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for f in stage.rglob('*'):
            if f.is_file():z.write(f,Path(stage.name)/f.relative_to(stage))
    source=stage.parent/'GNSS-SDR-Workbench-v0.6.0-source.zip'
    subprocess.run(['git','archive','--format=zip','--output='+str(source),'HEAD'],cwd=ROOT,check=True)
    upstream=stage.parent/'gnss-sdr-upstream-3132713.tar.gz'
    shutil.copy2(stage/'receiver/gnss-sdr-upstream.tar.gz',upstream)
    checks=[]
    for item in (output,source,upstream):
        with item.open('rb') as stream:
            checks.append(hashlib.file_digest(stream,'sha256').hexdigest()+'  '+item.name)
    (ROOT/'release/SHA256SUMS.txt').write_text('\n'.join(checks)+'\n',encoding='ascii')
    print(output)
if __name__=='__main__':main()
