"""Verify the release build and stage the upstream examples and provenance."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile


def stage(source, destination):
    src, dst = Path(source), Path(destination)
    lock_path = Path(__file__).with_name('receiver-lock.json')
    lock = json.loads(lock_path.read_text(encoding='utf8'))
    linux = dst/'linux'
    linux.mkdir(parents=True)
    for name, expected in lock['release_files'].items():
        with (src/'linux'/name).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise ValueError('Linux release digest mismatch: '+name)
        shutil.copy2(src/'linux'/name, linux/name)
    if (src/'linux/upstream-commit.txt').read_text().strip() != lock['commit']:
        raise ValueError('Upstream revision mismatch')
    for name in ('upstream-commit.txt','CMakeCache.txt','version.txt','build-packages.tsv','SHA256SUMS'):
        shutil.copy2(src/'linux'/name,linux/name)
    shutil.copy2(lock_path,linux/'receiver-lock.json')
    (linux/'receiver.sha256').write_text(lock['receiver_sha256']+'  /usr/bin/gnss-sdr\n',encoding='ascii')
    with tarfile.open(linux/'gnss-sdr-upstream.tar.gz') as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if member.isfile() and path.parts[0]=='conf' and '..' not in path.parts and path.suffix=='.conf':
                target = linux.joinpath(*path.parts)
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
    qemu = dst/'qemu'
    qemu.mkdir()
    manifest = json.loads((src/'qemu/distribution.json').read_text(encoding='utf8'))
    if lock['qemu'] not in manifest['version']:
        raise ValueError('Emulator version mismatch')
    for name, expected in manifest['sha256'].items():
        binary = src/'qemu'/name
        if hashlib.sha256(binary.read_bytes()).hexdigest()!=expected:
            raise ValueError('Emulator file digest mismatch: '+name)
        shutil.copy2(binary,qemu/name)
    (qemu/'share').mkdir()
    for name in ('bios-256k.bin','kvmvapic.bin','linuxboot_dma.bin'):
        shutil.copy2(src/'qemu/share'/name,qemu/'share'/name)
    for name in ('distribution.json', 'packages.json'):
        shutil.copy2(src/'qemu'/name,qemu/name)
    shutil.copytree(src/'qemu/licenses',qemu/'licenses')
