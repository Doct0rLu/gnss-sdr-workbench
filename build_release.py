"""Build an isolated Windows portable distribution. No personal settings/data."""
import argparse,hashlib,importlib.metadata,json,shutil,subprocess,sys,urllib.request,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def main():
    p=argparse.ArgumentParser();p.add_argument('--receiver',type=Path,required=True);p.add_argument('--receiver-source',type=Path,required=True);a=p.parse_args()
    if not (a.receiver/'bin/gnss-sdr.exe').is_file() or not a.receiver_source.is_file():raise SystemExit('Receiver runtime and matching source ZIP are required')
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--name','GNSS-SDR-Workbench','--distpath',str(ROOT/'dist'),'--workpath',str(ROOT/'build/work'),'--specpath',str(ROOT/'build'),
                    '--add-data',str(ROOT/'web')+';web','--add-data',str(ROOT/'templates')+';templates',str(ROOT/'server.py')],check=True)
    from PyInstaller.archive.readers import CArchiveReader
    archive=CArchiveReader(str(ROOT/'dist/GNSS-SDR-Workbench/GNSS-SDR-Workbench.exe')).open_embedded_archive('PYZ.pyz')
    for module in ('picker','ctypes.wintypes','signal_input','signals'):
        if module not in archive.toc:raise SystemExit('Missing frozen module: '+module)
    # Build a new staging directory, excluding runtime test outputs and local.json.
    stage=ROOT/'release/GNSS-SDR-Workbench-v0.4.3-win-x64'
    if stage.exists():raise SystemExit('Release staging already exists; keep it for review or choose a new release version')
    stage.mkdir(parents=True)
    frozen=ROOT/'dist/GNSS-SDR-Workbench'
    shutil.copy2(frozen/'GNSS-SDR-Workbench.exe',stage)
    shutil.copytree(frozen/'_internal',stage/'_internal')
    rec=stage/'receiver';rec.mkdir()
    for name in ('bin','licenses'):shutil.copytree(a.receiver/name,rec/name)
    for name in ('LICENSE','NOTICE.txt','THIRD-PARTY.json','WINDOWS-BUILD.json'):shutil.copy2(a.receiver/name,rec/name)
    shutil.copy2(a.receiver_source,rec/'receiver-corresponding-source.zip')
    for name in ('LICENSE','PORTABLE.md','THIRD-PARTY.md','SIGNALS.md','M1-REGRESSION.md'):shutil.copy2(ROOT/name,stage/name)
    (stage/'Start-Workbench.cmd').write_text('@echo off\r\ncd /d "%~dp0"\r\nGNSS-SDR-Workbench.exe --open\r\nif errorlevel 1 pause\r\n',encoding='ascii')
    licenses=stage/'licenses';licenses.mkdir()
    for package in ('numpy','h5py','pyinstaller'):
        distribution=importlib.metadata.distribution(package)
        for f in distribution.files or []:
            if any(x in f.name.upper() for x in ('LICENSE','COPYING','NOTICE')) and distribution.locate_file(f).is_file():
                target=licenses/package/str(f).replace('..','_');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(distribution.locate_file(f),target)
    for name,url in {'python-LICENSE.txt':'https://raw.githubusercontent.com/python/cpython/v3.12.7/LICENSE','hdf5-LICENSE.txt':'https://raw.githubusercontent.com/HDFGroup/hdf5/hdf5_1_14_2/COPYING'}.items():
        (licenses/name).write_bytes(urllib.request.urlopen(url,timeout=30).read())
    manifest={'version':'0.4.3','python':sys.version,'components':{n:importlib.metadata.version(n) for n in ('numpy','h5py','pyinstaller')},'files':{str(f.relative_to(stage)).replace('\\','/'):hashlib.sha256(f.read_bytes()).hexdigest() for f in stage.rglob('*') if f.is_file()}}
    (stage/'MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    output=stage.parent/(stage.name+'.zip')
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for f in stage.rglob('*'):
            if f.is_file():z.write(f,Path(stage.name)/f.relative_to(stage))
    (ROOT/'release/SHA256SUMS.txt').write_text(hashlib.sha256(output.read_bytes()).hexdigest()+'  '+output.name+'\n',encoding='ascii')
    print(output)
if __name__=='__main__':main()
