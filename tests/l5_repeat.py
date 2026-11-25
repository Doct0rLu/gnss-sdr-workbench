"""Repeat one archived file configuration through the portable workbench and native CLI."""
import argparse
import hashlib
import json
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from contextlib import ExitStack
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_receiver
import server
import signals


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def api(endpoint, route, payload=None):
    req = urllib.request.Request(endpoint+route, json.dumps(payload).encode() if payload is not None else None,
                                 {'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=30) as response:
        return json.load(response)


def gui(endpoint, cfg, exe, folder):
    meta = api(endpoint, '/api/start', dict(config_mode='original', original_config=str(cfg), executable=str(exe)))
    work = Path(meta['output'])
    deadline = time.monotonic()+300
    while not (work/'snapshot.json').is_file():
        if time.monotonic()>deadline:
            api(endpoint,'/api/stop',{})
            raise TimeoutError(str(work))
        time.sleep(.15)
    final = json.loads((work/'snapshot.json').read_text(encoding='utf8'))['meta']
    assert final['status']=='completed' and final['exe_sha256']==digest(exe)
    shutil.copytree(work,folder)


def record(sock, done, out, acq):
    seen = set()
    while True:
        try:
            packet,_ = sock.recvfrom(65535)
        except socket.timeout:
            if done.is_set():
                return
            continue
        for row in server.decode(packet):
            # Keep every acquisition event and the first valid monitor symbol per PRN.
            if acq or (row['valid'] and row['prn'] not in seen):
                out.write(json.dumps(row)+'\n')
                seen.add(row['prn'])


def cli(exe, cfg, folder):
    folder.mkdir()
    shutil.copyfile(cfg,folder/'receiver.conf')
    options=signals.parse(cfg.read_text(encoding='utf-8-sig'))
    done=threading.Event()
    threads=[]
    with ExitStack() as stack:
        try:
            for role,port,name in [('Acquisition',1235,'acquisitions'),('Tracking',1236,'telemetry')]:
                sock=stack.enter_context(native_receiver.monitor_socket(options,role,port,True))
                assert native_receiver.reported_port(sock,options,role,port,True)
                sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,4*1024*1024)
                out=stack.enter_context((folder/(name+'.jsonl')).open('w',encoding='utf8'))
                thread=threading.Thread(target=record,args=(sock,done,out,role=='Acquisition'))
                thread.start()
                threads.append(thread)
            with (folder/'receiver.log').open('wb') as log:
                with subprocess.Popen(native_receiver.command(exe,folder),cwd=folder,env=native_receiver.environment(exe),
                                      stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,
                                      creationflags=subprocess.CREATE_NO_WINDOW) as proc:
                    try:
                        code=proc.wait(timeout=300)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        raise
                    if code:
                        raise RuntimeError(f'CLI exited {code} in {folder}')
        finally:
            done.set()
            for thread in threads:
                thread.join()


def navigation_pages(sock, done, out):
    """Record the receiver's decoded CNAV pages, including their transmitted PRN and TOW."""
    while True:
        try:
            packet,_=sock.recvfrom(65535)
        except socket.timeout:
            if done.is_set():
                return
            continue
        fields=dict(server.fields(packet))
        bits=fields[5].decode('ascii')
        if fields.get(2)!=b'L5' or len(bits)!=300:
            continue
        row=dict(prn=fields[3],page_prn=int(bits[8:14],2),mt=int(bits[14:20],2),
                 tow=int(bits[20:37],2)*6,raw=bits)
        out.write(json.dumps(row)+'\n')


def run_one(mode, endpoint, exe, cfg, folder, options):
    with ExitStack() as stack:
        done=threading.Event()
        reader=None
        if options.get('NavDataMonitor.enable_monitor','false').strip().lower()=='true':
            sock=stack.enter_context(socket.socket(socket.AF_INET,socket.SOCK_DGRAM))
            sock.bind(('127.0.0.1',int(options.get('NavDataMonitor.port',1237))))
            sock.settimeout(.3)
            stream=stack.enter_context(folder.with_suffix('.pages.jsonl').open('w',encoding='utf8'))
            reader=threading.Thread(target=navigation_pages,args=(sock,done,stream))
            reader.start()
        try:
            if mode=='gui':
                gui(endpoint,cfg,exe,folder)
            else:
                cli(exe,cfg,folder)
        finally:
            done.set()
            if reader:
                reader.join()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--portable',required=True,type=Path)
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--pairs',type=int,default=5)
    args=parser.parse_args()
    base=args.portable.resolve()
    exe=base/'receiver/bin/gnss-sdr.exe'
    cfg=args.config.resolve()
    root=args.output.resolve()
    root.mkdir(parents=True,exist_ok=False)
    options=signals.parse(cfg.read_text(encoding='utf-8-sig'))
    hashes=dict(iq=digest(Path(options['SignalSource.filename'])),config=digest(cfg),receiver=digest(exe))
    (root/'digests.json').write_text(json.dumps(hashes,indent=2))
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0))
        port=probe.getsockname()[1]
    endpoint=f'http://127.0.0.1:{port}'
    with (root/'server.log').open('wb') as log:
        proc=subprocess.Popen([base/'GNSS-SDR-Workbench.exe','--port',str(port)],cwd=base,
                              env=native_receiver.environment(exe),creationflags=subprocess.CREATE_NO_WINDOW,
                              stdout=log,stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                try:
                    defaults=api(endpoint,'/api/defaults')
                    assert Path(defaults['executable']).samefile(exe)
                    break
                except OSError:
                    time.sleep(.1)
            for i in range(1,args.pairs+1):
                for mode in (('gui','cli') if i%2 else ('cli','gui')):
                    out=root/f'{i:02}-{mode}'
                    print(out.name,flush=True)
                    run_one(mode,endpoint,exe,cfg,out,options)
                    assert digest(out/'receiver.conf')==hashes['config']
        finally:
            proc.terminate()
            proc.wait(timeout=10)


if __name__=='__main__':
    main()
