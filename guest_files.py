"""Expose selected recordings read-only and one run directory to the Linux guest."""
import errno
import functools
import hmac
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import secrets
import socket
import stat
import threading

import paramiko


def sftp_errors(fn):
    @functools.wraps(fn)
    def wrapped(*args):
        try:
            return fn(*args)
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno or errno.EIO)
    return wrapped


def directory(name):
    entry = paramiko.SFTPAttributes()
    entry.filename = name
    entry.st_mode = stat.S_IFDIR | 0o755
    entry.st_size = 0
    entry.st_uid = entry.st_gid = entry.st_atime = entry.st_mtime = 0
    return entry


class RunFiles(paramiko.SFTPServerInterface):
    def __init__(self, server, output, inputs, aliases=None):
        super().__init__(server)
        self.output = Path(output).resolve()
        self.inputs = {str(i): Path(src).resolve() for i, src in enumerate(inputs)}
        self.aliases = {PurePosixPath('/out', name): Path(src).resolve() for name, src in (aliases or {}).items()}
        self.virtual = {p for name in self.aliases for p in name.parents}

    def resolve(self, path, write=False):
        parts = PurePosixPath(path).parts
        if not parts or parts[0] != '/' or '..' in parts:
            raise PermissionError(errno.EACCES, path)
        alias = self.aliases.get(PurePosixPath(path))
        if alias is not None:
            if write:
                raise PermissionError(errno.EACCES, path)
            return alias
        if len(parts) == 3 and parts[1] == 'input' and parts[2] in self.inputs and not write:
            return self.inputs[parts[2]]
        if len(parts) < 2 or parts[1] != 'out':
            raise FileNotFoundError(errno.ENOENT, path)
        for name in parts[2:]:
            if '\\' in name or ':' in name or PureWindowsPath(name).is_reserved() or name.rstrip(' .') != name:
                raise PermissionError(errno.EACCES, path)
        p = self.output.joinpath(*parts[2:]).resolve()
        if not p.is_relative_to(self.output):
            raise PermissionError(errno.EACCES, path)
        if write and (p == self.output or p.name.casefold() in ('manifest.json', 'snapshot.json', 'receiver.conf', 'receiver.log') or p.suffix.casefold() == '.jsonl'):
            raise PermissionError(errno.EACCES, path)
        return p

    @sftp_errors
    def stat(self, path):
        if path in ('/', '/input') or PurePosixPath(path) in self.virtual:
            return directory(path)
        return paramiko.SFTPAttributes.from_stat(self.resolve(path).stat())

    lstat = stat

    @sftp_errors
    def list_folder(self, path):
        if path == '/':
            return [directory('input'), directory('out')]
        if path == '/input':
            return [paramiko.SFTPAttributes.from_stat(p.stat(), name) for name, p in self.inputs.items()]
        folder = PurePosixPath(path)
        if folder in self.virtual and folder != PurePosixPath('/out'):
            entries = {}
        else:
            entries = {p.name:paramiko.SFTPAttributes.from_stat(p.stat(), p.name) for p in self.resolve(path).iterdir()}
        for p in self.virtual | self.aliases.keys():
            if p.parent == folder and p != folder:
                entries[p.name] = self.stat(str(p))
                entries[p.name].filename = p.name
        return list(entries.values())

    @sftp_errors
    def open(self, path, flags, attr):
        writing = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        p = self.resolve(path, writing)
        fd = os.open(p, flags | getattr(os, 'O_BINARY', 0), 0o644)
        mode = 'r+b' if flags & os.O_RDWR else 'wb' if flags & os.O_WRONLY else 'rb'
        f = os.fdopen(fd, mode, buffering=0)
        handle = paramiko.SFTPHandle(flags)
        handle.readfile = handle.writefile = f
        handle.stat = lambda: paramiko.SFTPAttributes.from_stat(os.fstat(f.fileno()))
        @sftp_errors
        def change_attributes(attrs):
            if not writing:
                raise PermissionError(errno.EACCES, path)
            if attrs.st_size is not None:
                f.truncate(attrs.st_size)
            if attrs.st_atime is not None and attrs.st_mtime is not None:
                os.utime(p,(attrs.st_atime,attrs.st_mtime))
            return paramiko.SFTP_OK
        handle.chattr = change_attributes
        return handle

    @sftp_errors
    def chattr(self, path, attrs):
        p = self.resolve(path,True)
        if attrs.st_size is not None:
            with p.open('r+b') as f:
                f.truncate(attrs.st_size)
        if attrs.st_atime is not None and attrs.st_mtime is not None:
            os.utime(p,(attrs.st_atime,attrs.st_mtime))
        return paramiko.SFTP_OK

    @sftp_errors
    def remove(self, path):
        self.resolve(path, True).unlink()
        return paramiko.SFTP_OK

    @sftp_errors
    def rename(self, old, new):
        self.resolve(old, True).rename(self.resolve(new, True))
        return paramiko.SFTP_OK

    @sftp_errors
    def mkdir(self, path, attr):
        self.resolve(path, True).mkdir()
        return paramiko.SFTP_OK

    @sftp_errors
    def rmdir(self, path):
        self.resolve(path, True).rmdir()
        return paramiko.SFTP_OK


class Login(paramiko.ServerInterface):
    def __init__(self, password):
        self.password = password

    def check_auth_password(self, username, password):
        if username == 'workbench' and hmac.compare_digest(password, self.password):
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return 'password'

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == 'session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED


class GuestShare:
    def __init__(self, output, inputs, aliases=None):
        self.output, self.inputs = output, inputs
        self.aliases = aliases
        self.password = secrets.token_hex(24)
        self.key = paramiko.ECDSAKey.generate()
        self.sock = socket.socket()
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        self.transports = []

    def accept(self):
        while True:
            try:
                client, _ = self.sock.accept()
            except OSError:
                return
            transport = paramiko.Transport(client)
            self.transports.append(transport)
            transport.add_server_key(self.key)
            transport.set_subsystem_handler('sftp', paramiko.SFTPServer, RunFiles, self.output, self.inputs, self.aliases)
            transport.start_server(event=threading.Event(), server=Login(self.password))

    def __enter__(self):
        threading.Thread(target=self.accept, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.sock.close()
        for transport in self.transports:
            transport.close()
