"""Launch the pinned Linux receiver in its portable QEMU guest."""
from pathlib import Path, PurePosixPath
import json
import ctypes
import functools
import hashlib
import gzip
import os
import posixpath
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile

COMMIT = '3132713b88a1b5b2ee8291bff8076574749349de'
LABEL = 'GNSS-SDR · Linux · ' + COMMIT[:7]
BUILD_LOCK = Path(__file__).resolve().parent/'portable_linux/receiver-lock.json'


@functools.lru_cache(maxsize=24)
def checked_digest(path, size, mtime_ns):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def verify_guest(base):
    lock=json.loads(BUILD_LOCK.read_text(encoding='utf8'))
    for name in ('initramfs.gz','vmlinuz','monitor-relay'):
        file=base/'linux'/name
        info=file.stat()
        if checked_digest(file,info.st_size,info.st_mtime_ns)!=lock['release_files'][name]:
            raise ValueError('便携接收机文件与发布记录不符：'+name)
    if (base/'linux/receiver.sha256').read_text(encoding='ascii').split()[0]!=lock['receiver_sha256']:
        raise ValueError('接收机摘要与发布记录不符')


def accelerator_args():
    try:
        present, used = ctypes.c_int(), ctypes.c_uint()
        result = ctypes.WinDLL('WinHvPlatform').WHvGetCapability(0, ctypes.byref(present),
                                                                  ctypes.sizeof(present), ctypes.byref(used))
    except (AttributeError,OSError):
        present, result = None, 1
    preferred = ['-accel','whpx'] if result == 0 and present.value else []
    return preferred + ['-accel','tcg,thread=multi']


def runtime(root):
    base = Path(root) / 'receiver'
    marker = base / 'linux/upstream-commit.txt'
    if marker.is_file():
        if marker.read_text(encoding='ascii').strip() != COMMIT:
            raise ValueError('随包接收机版本与工作台构建记录不同')
        for name in ('linux/initramfs.gz', 'linux/vmlinuz', 'qemu/qemu-system-x86_64.exe'):
            if not (base / name).is_file():
                raise ValueError('便携包缺少 ' + name)
        verify_guest(base)
        return base
    return None


def raw_inputs(config, config_dir, supplied, first):
    # Only existing files specifically named by the job are exported.
    import signal_input
    inputs = []
    for key, value in config.items():
        if not re.fullmatch(r'SignalSource\d*\.filename\d*', key):
            continue
        index = len(inputs)
        override = supplied[index].get('path', '') if index < len(supplied) else ''
        if index == 0 and first:
            override = first
        local = Path(override) if override else config_dir / value
        if local.is_file():
            inputs.append(dict(path=str(local.resolve()), guest_name=value, filename_key=key, index=index))
        elif override:
            raise ValueError('找不到所选信号文件：' + str(local))
        else:
            inputs.append(dict(path='', guest_name=value, filename_key=key, index=index))
        role = key.split('.')[0]
        fmt = config.get(role+'.item_type','')
        entry = inputs[-1]
        entry.update(role=role,format=fmt,label=fmt,fs=0)
        if config.get(role+'.implementation') in ('File_Signal_Source','Multichannel_File_Signal_Source') and fmt in signal_input.FORMATS:
            try:
                layout = signal_input.layout({'SignalSource.item_type':fmt})
                rate = float(config.get(role+'.sampling_frequency',0))
                skip = float(config.get(role+'.seconds_to_skip',0)) if config.get(role+'.repeat','false').lower()!='true' else 0
                start = int(max(0,skip)*rate)*layout['sample_bytes'] + int(config.get(role+'.header_size',0))*layout['sample_bytes']//layout['source_items']
                entry.update(label=layout['label'],fs=rate,byte_offset=start)
            except (ValueError,OverflowError):
                pass
    return inputs


GUEST_CWD = PurePosixPath('/work/experiment')


def initrd_entry(name, data, mode):
    label = name.encode() + b'\0'
    fields = [1, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(label), 0]
    header = b'070701' + ''.join(f'{v:08x}' for v in fields).encode() + label
    return header + bytes(-len(header) % 4) + data + bytes(-len(data) % 4)


def job_initrd(base, destination, script, relay=None):
    init = (Path(__file__).resolve().parent/'portable_linux/init').read_bytes().replace(b'\r\n', b'\n')
    job = initrd_entry('init', init, 0o100755) + initrd_entry('workbench-job', script.encode(), 0o100600)
    if relay:
        job += initrd_entry('usr/bin/monitor-relay', relay.read_bytes(), 0o100755)
    job += initrd_entry('TRAILER!!!', b'', 0)
    with base.open('rb') as original, destination.open('wb') as out:
        shutil.copyfileobj(original, out)
        out.write(bytes(-out.tell() % 4))
        out.write(gzip.compress(job, mtime=0))


def guest_path(name):
    return PurePosixPath(posixpath.normpath(str(GUEST_CWD / name)))


def monitor_endpoint(options, name, default_port, original):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(.3)
    role = name+'Monitor.'
    addresses = options.get(role+'client_addresses','127.0.0.1').split('_')
    ports = options.get(role+'udp_port',str(default_port)).split('_')
    enabled = original and options.get(role+'enable_monitor','false').lower()=='true'
    port = next((int(p) for p in ports if p.isdecimal() and 0<int(p)<65536),0) if enabled else 0
    host_port = port if '10.0.2.2' in addresses else 0
    try:
        sock.bind(('127.0.0.1',host_port))
    except OSError:
        if not host_port:
            sock.close()
            raise
        sock.bind(('127.0.0.1',0))
    relay = None
    if port and '127.0.0.1' in addresses and '10.0.2.2' not in addresses:
        relay = (port,sock.getsockname()[1])
    return sock,relay


def guest_script(share, inputs, raw, relays=()):
    lines = [
        'set -e', 'mkdir -p /mnt/host /dev/pts', 'mount -t devpts devpts /dev/pts',
        'export SSHPASS=' + shlex.quote(share.password),
        f"echo '[10.0.2.2]:{share.port} {share.key.get_name()} {share.key.get_base64()}' > /tmp/guest_host_key",
        f'sshpass -e sshfs -f -p {share.port} -o StrictHostKeyChecking=yes,UserKnownHostsFile=/tmp/guest_host_key,PreferredAuthentications=password,dir_cache=no workbench@10.0.2.2:/ /mnt/host &',
        'share_pid=$!', 'unset SSHPASS', 'attempt=0',
        'until [ -r /mnt/host/out/receiver.conf ]; do kill -0 "$share_pid" || exit 1; attempt=$((attempt+1)); [ "$attempt" -lt 60 ] || exit 1; sleep 1; done',
        'mkdir -p /work/experiment', 'mount --bind /mnt/host/out /work/experiment', 'cd /work/experiment',
    ]
    if raw:
        for i, item in enumerate(inputs):
            target = guest_path(item['guest_name'])
            if not target.is_relative_to(GUEST_CWD) and target != PurePosixPath('/mnt/host/input', str(i)):
                lines += [f'mkdir -p {shlex.quote(str(target.parent))}',
                          f'ln -s /mnt/host/input/{i} {shlex.quote(str(target))}']
    lines.extend(f'/usr/bin/monitor-relay {int(src)} {int(dst)} &' for src,dst in relays)
    lines.extend(['set +e', "sh -c 'echo WORKBENCH_RECEIVER_PID=$$; exec /usr/bin/gnss-sdr --config_file=/mnt/host/out/receiver.conf --log_dir=/mnt/host/out --keyboard=true'",
                  'result=$?'])
    lines += ['cd /', '/bin/busybox sync', 'exit "$result"']
    return '\n'.join(lines) + '\n'


def launch(base, output):
    from guest_files import GuestShare
    base, output = Path(base).resolve(), Path(output).resolve()
    verify_guest(base)
    spec = json.loads((output / 'guest-job.json').read_text(encoding='utf8'))
    inputs = [item for item in spec['inputs'] if item.get('path')]
    aliases = {}
    if spec['original']:
        for item in inputs:
            target = guest_path(item['guest_name'])
            if target.is_relative_to(GUEST_CWD):
                aliases[str(target.relative_to(GUEST_CWD))] = item['path']
    with tempfile.TemporaryDirectory(prefix='gnss-guest-') as temp, GuestShare(output, [i['path'] for i in inputs], aliases) as share:
        initrd = Path(temp)/'job.cpio.gz'
        relays = spec.get('relays',[])
        job_initrd(base/'linux/initramfs.gz', initrd, guest_script(share, inputs, spec['original'], relays),
                   base/'linux/monitor-relay' if relays else None)
        # QEMU's firmware loader on Windows still uses narrow paths. Relative
        # ASCII names work inside a Unicode working directory on any volume.
        shutil.copyfile(base/'linux/vmlinuz', Path(temp)/'vmlinuz')
        for name in ('bios-256k.bin', 'kvmvapic.bin', 'linuxboot_dma.bin'):
            shutil.copyfile(base/'qemu/share'/name, Path(temp)/name)
        qemu = base / 'qemu/qemu-system-x86_64.exe'
        args = [str(qemu), '-L', '.', '-machine', 'pc', *accelerator_args(),
                '-cpu', 'max', '-smp', '4', '-m', '2048', '-nodefaults', '-no-reboot',
                '-display', 'none', '-monitor', 'none', '-serial', 'stdio',
                '-netdev', 'user,id=net0', '-device', 'virtio-net-pci,netdev=net0,romfile=',
                '-kernel', 'vmlinuz', '-initrd', initrd.name, '-append', 'console=ttyS0 quiet panic=1']
        result = None
        env = dict(os.environ)
        env['PATH'] = str(qemu.parent) + os.pathsep + str(Path(os.environ['SystemRoot'])/'System32')
        with subprocess.Popen(args, cwd=temp, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as vm:
            print(f'WORKBENCH_QEMU_PID={vm.pid}',flush=True)
            try:
                for line in vm.stdout:
                    marker = re.fullmatch(rb'WORKBENCH_GUEST_EXIT=(\d+)\s*', line)
                    if marker:
                        result = int(marker[1])
                    else:
                        sys.stdout.buffer.write(line)
                        sys.stdout.buffer.flush()
            finally:
                if vm.poll() is None and result is not None:
                    try:
                        vm.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        vm.terminate()
        return result if result is not None else (vm.returncode or 1)
