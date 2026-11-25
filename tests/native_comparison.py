"""Compare the workbench start API with the actual GNSS-SDR executable, sequentially."""
import argparse
import hashlib
import json
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import diagnostics
import native_receiver
import server
import signals


def summarize(folder, elapsed, acquired, tracked):
    stdout = (folder/'receiver.log').read_text(encoding='utf8', errors='replace')
    fix = re.search(r'First position fix at (.+?) UTC.*?Lat = ([\d.+-]+).*?Long = ([\d.+-]+).*?Height = ([\d.+-]+)', stdout)
    epochs = re.findall(r'Position at (.+?) UTC using (\d+) observations.*?Lat = ([\d.+-]+).*?Long = ([\d.+-]+).*?Height = ([\d.+-]+)', stdout)
    ticks = [int(m or 0)*60+int(s) for m,s in re.findall(r'Current receiver time: (?:(\d+) min )?(\d+) s', stdout)]
    eph = {}
    for path in folder.glob('*ephemeris.xml'):
        eph[path.name] = sorted({int(p.text) for p in ET.parse(path).findall('.//item/second/PRN')})
    frames=set()
    for path in folder.glob('gnss-sdr.*.log'):
        with path.open(encoding='utf8',errors='replace') as stream:
            for line in stream:
                if 'successful frame synchronization' in line.lower() or 'crc ok' in line.lower():
                    match=re.search(r'(GPS|Beidou) PRN (\d+)',line,re.I)
                    if match:
                        frames.add(('G' if match[1].upper()=='GPS' else 'C')+match[2].zfill(2))
    return dict(frame_evidence=sorted(frames), folder=folder.name, elapsed_s=round(elapsed,3), last_tick_s=max(ticks,default=0),
                config_sha256=hashlib.sha256((folder/'receiver.conf').read_bytes()).hexdigest(),
                acquired=sorted(acquired), valid_tracking=sorted(tracked), ephemeris=eph,
                first_fix=fix.groups() if fix else None, positions=epochs,
                last_pvt_satellites=diagnostics.pvt_satellites(folder))


def prn(row):
    return row['system']+str(row['prn']).zfill(2)


def collect(sock, stage, stop, seen):
    # Drain queued datagrams after process exit.
    while True:
        try:
            data,_ = sock.recvfrom(65535)
        except socket.timeout:
            if stop.is_set():
                return
            continue
        for row in server.decode(data):
            if stage == 'acq' or row['valid']:
                seen.add(prn(row))


def raw_cli(exe, config, folder):
    folder.mkdir()
    contents=config.read_bytes()
    (folder/'receiver.conf').write_bytes(contents)
    opts=signals.parse(contents.decode('utf-8-sig'))
    stop=threading.Event()
    sets=[set(),set()]
    threads=[]
    sockets=[]
    for stage, name, default, values in zip(('acq','trk'),('Acquisition','Tracking'),(1235,1236),sets):
        sock=native_receiver.monitor_socket(opts,name,default,True)
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,4*1024*1024)
        t=threading.Thread(target=collect,args=(sock,stage,stop,values))
        t.start()
        threads.append(t)
        sockets.append(sock)
    start=time.perf_counter()
    try:
        with (folder/'receiver.log').open('wb') as log:
            result=subprocess.run([str(exe),'--config_file='+str(folder/'receiver.conf'),'--log_dir='+str(folder),'--keyboard=true'],
                                  cwd=folder,env=native_receiver.environment(exe),stdin=subprocess.DEVNULL,stdout=log,
                                  stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW,timeout=1200)
        elapsed=time.perf_counter()-start
        result.check_returncode()
    finally:
        stop.set()
        for t,sock in zip(threads,sockets):
            t.join()
            sock.close()
    return summarize(folder,elapsed,*sets)


def compare(exe, config, out, endpoint):
    payload=json.dumps(dict(executable=str(exe),config_mode='original',original_config=str(config))).encode()
    request=urllib.request.Request(endpoint+'/api/start',data=payload,headers={'Content-Type':'application/json'})
    start=time.perf_counter()
    with urllib.request.urlopen(request,timeout=30) as res:
        meta=json.load(res)
    gui=Path(meta['output'])
    for _ in range(4800):
        if (gui/'snapshot.json').is_file():
            break
        time.sleep(.25)
    elapsed=time.perf_counter()-start
    snap=json.loads((gui/'snapshot.json').read_text(encoding='utf8'))
    if snap['meta']['status']!='completed':
        raise RuntimeError(str(gui))
    def rows(name):
        return (json.loads(l) for l in (gui/name).read_text(encoding='utf8').splitlines())
    a=summarize(gui,elapsed,{prn(r) for r in rows('acquisitions.jsonl')},
                {sv for signal in snap['stages']['signals'] for sv in signal['valid_tracking']})
    b=raw_cli(exe,gui/'receiver.conf',out)
    assert a['config_sha256']==b['config_sha256']
    return dict(workbench=a,command_line=b)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--exe',type=Path,required=True)
    p.add_argument('--endpoint',help='running workbench URL (including the frozen application)')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('configs',type=Path,nargs='+')
    args=p.parse_args()
    root=args.output.resolve()
    root.mkdir(parents=True,exist_ok=False)
    http=None
    endpoint=args.endpoint
    if not endpoint:
        server.RUNS=root/'workbench'
        http=server.LocalServer(('127.0.0.1',0),server.Handler)
        threading.Thread(target=http.serve_forever,daemon=True).start()
        endpoint='http://127.0.0.1:'+str(http.server_port)
    try:
        for config in args.configs:
            name=config.stem
            if (root/(name+'.json')).exists():
                raise ValueError('每个用例需要独立的配置文件名')
            print('Starting '+name,flush=True)
            result=compare(args.exe.resolve(),config.resolve(),root/('cli-'+name),endpoint)
            (root/(name+'.json')).write_text(json.dumps(result,indent=2),encoding='utf8')
            print(name,result['workbench']['elapsed_s'], result['command_line']['elapsed_s'],flush=True)
    finally:
        if http:
            http.shutdown()
            http.server_close()


if __name__=='__main__':
    main()
