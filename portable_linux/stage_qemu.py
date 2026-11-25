"""Stage the headless MSYS2 x86_64 emulator and its actual PE dependencies."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import re

import pefile


def package_notices(dest, copied, prefixes, cache, msys):
    required = {('ucrt64/bin/'+name).lower() for name in copied}
    required.update('ucrt64/share/qemu/'+n for n in ('bios-256k.bin','kvmvapic.bin','linuxboot_dma.bin'))
    packages = {}
    def record(name,version,url,files):
        matches = sorted(required.intersection(f.lower() for f in files))
        if not matches:return
        required.difference_update(matches)
        packages[name] = dict(version=version,project=url,files=matches,
                              package='https://packages.msys2.org/package/'+name)
        for f in files:
            if f.startswith('ucrt64/share/licenses/') and not f.endswith('/'):
                rel=Path(f).relative_to('ucrt64')
                src=next((prefix/rel for prefix in prefixes if (prefix/rel).is_file()),None)
                if src:
                    target=dest/'licenses'/name/rel.relative_to('share/licenses')
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(src,target)
    if cache:
        tar = str(msys/'usr/bin/bsdtar.exe')
        for archive in sorted(cache.glob('*.pkg.tar.zst')):
            listing=subprocess.check_output([tar,'-tf',str(archive)],encoding='utf8').splitlines()
            info=subprocess.check_output([tar,'-xOf',str(archive),'.PKGINFO'],encoding='utf8')
            attrs=dict(re.findall(r'^([^#\s=]+) = (.*)$',info,re.M))
            record(attrs['pkgname'],attrs['pkgver'],attrs.get('url',''),listing)
    for index in (msys/'var/lib/pacman/local').glob('mingw-w64-ucrt-x86_64-*/files'):
        fields=dict(re.findall(r'%([A-Z]+)%\n([^\n]+)',index.with_name('desc').read_text(encoding='utf8')))
        record(fields['NAME'],fields['VERSION'],fields.get('URL',''),index.read_text(encoding='utf8').splitlines())
    if required:
        raise ValueError('Missing package provenance: '+', '.join(sorted(required)))
    (dest/'packages.json').write_text(json.dumps(packages,indent=2),encoding='utf8')


def stage(destination, prefixes, cache=None, msys=Path('C:/msys64')):
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    bins = [Path(p) / 'bin' for p in prefixes]
    # SDL's Windows loader opens SDL3 dynamically even for a headless invocation.
    todo = ['qemu-system-x86_64.exe', 'SDL3.dll']
    copied = {}
    while todo:
        name = todo.pop()
        if name.lower() in copied:
            continue
        source = next((base / name for base in bins if (base / name).is_file()), None)
        if source is None:
            if name.lower().startswith(('api-ms-', 'ext-ms-')) or (Path(os.environ['SystemRoot'])/'System32'/name).is_file():
                continue
            raise FileNotFoundError(name)
        target = dest / name
        if not target.exists() or hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(source.read_bytes()).digest():
            shutil.copy2(source, target)
        copied[name.lower()] = hashlib.sha256(target.read_bytes()).hexdigest()
        with pefile.PE(str(source), fast_load=True) as pe:
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
            todo.extend(item.dll.decode('ascii') for item in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', []))
    data = next(p/'share/qemu' for p in map(Path, prefixes) if (p/'share/qemu/bios-256k.bin').is_file())
    (dest/'share').mkdir(exist_ok=True)
    for name in ('bios-256k.bin', 'kvmvapic.bin', 'linuxboot_dma.bin'):
        shutil.copy2(data/name, dest/'share'/name)
    package_notices(dest,copied,prefixes,cache,msys)
    env = dict(os.environ, PATH=str(dest.resolve())+os.pathsep+str(Path(os.environ['SystemRoot'])/'System32'))
    version = subprocess.check_output([str((dest/'qemu-system-x86_64.exe').resolve()), '--version'], env=env, text=True, timeout=15)
    (dest/'distribution.json').write_text(json.dumps(dict(version=version.splitlines()[0],sha256=copied,
        packages='https://packages.msys2.org/package/mingw-w64-ucrt-x86_64-qemu',
        sources='https://github.com/msys2/MINGW-packages'), indent=2), encoding='utf8')
    return len(copied)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    parser.add_argument('prefixes', type=Path, nargs='+')
    parser.add_argument('--package-cache', type=Path)
    parser.add_argument('--msys', type=Path, default=Path('C:/msys64'))
    args = parser.parse_args()
    print(stage(args.destination, args.prefixes, args.package_cache, args.msys))
