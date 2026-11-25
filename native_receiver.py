"""Run the native Windows receiver and prepare file paths for an isolated run."""
import hashlib
import json
import os
import re
import socket
import sys
from contextlib import contextmanager
from pathlib import Path

import signal_input

COMMIT = '3132713b88a1b5b2ee8291bff8076574749349de'


def raw_inputs(config, config_dir, supplied, first):
    inputs = []
    for key, raw in config.items():
        if not re.fullmatch(r'SignalSource\d*\.filename\d*', key):
            continue
        value = raw.strip()
        index = len(inputs)
        override = supplied[index].get('path', '') if index < len(supplied) else ''
        if index == 0 and first:
            override = first
        local = Path(override) if override else config_dir / value
        role = key.split('.')[0]
        fmt = config.get(role + '.item_type', '').strip()
        entry = dict(path=str(local.resolve()), configured_name=value, filename_key=key,
                     index=index, role=role, format=fmt, label=fmt, fs=0)
        if not local.is_file():
            raise ValueError(f'找不到录制文件 {value}，请在录制文件映射中选择本机文件')
        if fmt in signal_input.FORMATS and config.get(role+'.implementation','').strip() in ('File_Signal_Source','Multichannel_File_Signal_Source'):
            layout = signal_input.layout({'SignalSource.item_type': fmt})
            rate = float(config.get(role + '.sampling_frequency', 0))
            repeat = config.get(role + '.repeat', 'false').strip().lower() == 'true'
            skip = 0 if repeat else float(config.get(role + '.seconds_to_skip', 0))
            header = int(config.get(role + '.header_size', 0))
            entry.update(label=layout['label'], fs=rate, byte_offset=(
                int(max(0,skip) * rate) * layout['sample_bytes']
                + header * layout['sample_bytes'] // layout['source_items']))
        inputs.append(entry)
    return inputs


def prepare_config(contents, inputs, run):
    """Preserve all bytes except explicitly resolved input filename values."""
    (run / 'original.conf').write_bytes(contents)
    effective = contents
    for entry in inputs:
        actual = Path(entry['path'])
        configured = run / entry['configured_name']
        if configured.is_file() and configured.samefile(actual):
            continue
        key = re.escape(entry['filename_key'].encode('ascii'))
        pattern = rb'(?m)^((?:\xef\xbb\xbf)?[ \t]*' + key + rb'[ \t]*=[ \t]*)[^\r\n;#]*?([ \t]*(?=[;#\r\n]|$))'
        effective, count = re.subn(pattern, lambda m: m[1] + actual.as_posix().encode('utf8') + m[2], effective)
        if not count:
            raise ValueError('无法解析录制路径字段 ' + entry['filename_key'])
    (run / 'receiver.conf').write_bytes(effective)


def monitor_socket(options, name, default, original):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    role = name + 'Monitor.'
    local = {'127.0.0.1', 'localhost'} & set(options.get(role+'client_addresses', '127.0.0.1').strip().split('_'))
    enabled = options.get(role+'enable_monitor', 'false').strip().lower() == 'true'
    candidates = []
    if original and local and enabled:
        for entry in str(options.get(role+'udp_port', default)).split('_'):
            if entry.strip().isdecimal() and 0 < int(entry) <= 65535:
                candidates.append(int(entry))
    # GNSS-SDR can fan out to multiple ports. Listen on one available copy.
    # A separate monitor may already own every configured port.
    try:
        for port in candidates:
            try:
                sock.bind(('127.0.0.1',port))
                break
            except OSError:
                continue
        else:
            sock.bind(('127.0.0.1',0))
        sock.settimeout(.3)
    except OSError:
        sock.close()
        raise
    return sock


def reported_port(sock, options, name, default, original):
    port = sock.getsockname()[1]
    if not original:
        return port
    ports = str(options.get(name+'Monitor.udp_port',default)).split('_')
    return port if str(port) in ports and options.get(name+'Monitor.enable_monitor','false').strip().lower()=='true' else None


def command(exe, run):
    return [str(exe), '--config_file='+str(run/'receiver.conf'), '--log_dir='+str(run), '--keyboard=true']


@contextmanager
def native_dll_search():
    if not getattr(sys, 'frozen', False):
        yield
        return
    import ctypes
    ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:
        yield
    finally:
        ctypes.windll.kernel32.SetDllDirectoryW(str(sys._MEIPASS))


def environment(exe, dll_dirs=()):
    env = dict(os.environ)
    system = Path(env.get('SystemRoot', 'C:/Windows'))
    env['PATH'] = os.pathsep.join(map(str, [exe.parent, *dll_dirs, system/'System32', system]))
    return env


def identity(exe, root):
    with exe.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    result = dict(exe_sha256=digest, backend='native-windows')
    manifest = root / 'receiver/WINDOWS-BUILD.json'
    bundled = root / 'receiver/bin/gnss-sdr.exe'
    alternate = bundled.with_name('gnss-sdr-b1c.exe')
    if exe.resolve()==alternate.resolve():
        build=json.loads(manifest.read_text(encoding='utf8'))
        if build['upstream_commit']!=COMMIT or build.get('b1c_exe_sha256')!=digest:
            raise ValueError('B1C 接收机与构建记录不一致')
        result.update(upstream_commit=COMMIT,b1c_prelock=True,full_int16_eof=bool(build.get('file_eof_patch_sha256')))
    elif exe.resolve()==bundled.with_name('gnss-sdr-snapshots.exe').resolve():
        build=json.loads(manifest.read_text(encoding='utf8'))
        if build['upstream_commit']!=COMMIT or build.get('snapshot_exe_sha256')!=digest:
            raise ValueError('多通道快照接收机与构建记录不一致')
        result.update(upstream_commit=COMMIT,full_int16_eof=bool(build.get('file_eof_patch_sha256')))
    if bundled.is_file() and exe.samefile(bundled):
        if not manifest.is_file():
            raise ValueError('缺少随包接收机构建记录，请重新解压便携包')
        build = json.loads(manifest.read_text(encoding='utf8'))
        if build.get('upstream_commit') != COMMIT or build.get('exe_sha256') != digest:
            raise ValueError('随包接收机与构建记录不一致，请重新解压便携包')
        result['upstream_commit'] = COMMIT
        result['full_int16_eof'] = bool(build.get('file_eof_patch_sha256'))
    return result
