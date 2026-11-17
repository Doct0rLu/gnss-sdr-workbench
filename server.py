"""Local GNSS-SDR workbench. Python 3.11+; portable builds include numerical dependencies."""
from __future__ import annotations
import argparse, collections, hashlib, json, math, os, re, socket, struct, subprocess, threading, time, uuid, sys
import diagnostics
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

RESOURCES = Path(__file__).resolve().parent
HERE = Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else RESOURCES
RUNS = HERE / 'runs'
LOCK = threading.RLock()

def write_json(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)

def varint(data, pos):
    value = 0
    for shift in range(0, 70, 7):
        b = data[pos]; pos += 1; value |= (b & 127) << shift
        if b < 128: return value, pos
    raise ValueError('invalid protobuf varint')

def fields(data):
    pos = 0
    while pos < len(data):
        tag, pos = varint(data, pos); wire = tag & 7; field = tag >> 3
        if not field: raise ValueError('invalid protobuf field')
        if wire == 0: value, pos = varint(data, pos)
        elif wire == 1: value = struct.unpack_from('<d', data, pos)[0]; pos += 8
        elif wire == 2:
            size, pos = varint(data, pos)
            if size > len(data)-pos: raise ValueError('truncated protobuf')
            value = data[pos:pos+size]; pos += size
        elif wire == 5: value = struct.unpack_from('<f', data, pos)[0]; pos += 4
        else: raise ValueError('unsupported protobuf wire')
        yield field, value

def decode(data):
    """Read Observables/GnssSynchro using upstream BSD schema; ignore new fields."""
    for field, payload in fields(data):
        if field != 1 or not isinstance(payload, bytes): continue
        f = dict(fields(payload)); fs = f.get(10, 0)
        def number(n):
            v = f.get(n, 0)
            return v if isinstance(v, (int, float)) and math.isfinite(v) else None
        yield dict(channel=f.get(4, 0), prn=f.get(3, 0),
                   system=f.get(1, b'').decode('utf-8', 'replace'), signal=f.get(2, b'').decode('utf-8', 'replace'),
                   t=f.get(17, 0)/fs if fs > 0 else None,
                   cn0=number(13), doppler=number(14), i=number(11), q=number(12),
                   valid=bool(f.get(18, 0)), word=bool(f.get(20, 0)),
                   acquired=bool(f.get(9, 0)), slip=bool(f.get(27, 0)),
                   acq_samples=f.get(7,0), acq_doppler=number(6), acq_delay=number(5),
                   pseudorange=number(22) if f.get(24) else None)

def classify(text):
    level = 'INFO'
    if re.search(r'(^E\d{4}|error|fatal|exception|failed to|not found)', text, re.I): level = 'ERROR'
    elif re.search(r'(^W\d{4}|warning|loss of lock|lost lock)', text, re.I): level = 'WARN'
    m = re.search(r'(?:channel|ch)[\s:=#]*(\d+)', text, re.I)
    channel = int(m[1]) if m else None
    module = 'tracking' if re.search(r'track|lock', text, re.I) else 'acquisition' if re.search(r'acqui', text, re.I) else 'pvt' if re.search(r'position|latitude|longitude|pvt', text, re.I) else 'receiver'
    return level, module, channel

class Run:
    def __init__(self, path, meta):
        self.path, self.meta = path, meta
        self.logs = collections.deque(maxlen=3000)
        self.channels = {}; self.history = {}; self.events = collections.deque(maxlen=300)
        self.positions = collections.deque(maxlen=2400)
        self.acquisitions = collections.deque(maxlen=500)
        self.seq = 0; self.udp = 0; self.decode_errors = 0; self.proc = None; self.sock = None
        self.signal_time = 0; self.last_packet = None
        self.log_signal_time=0
        self.log_sink=None
    def event(self,row):
        self.events.append(row)
        if self.path.is_dir():
            with (self.path/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    def log(self, text):
        text = re.sub(r'\x1b\[[0-9;]*m','',text)
        level, module, ch = classify(text)
        with LOCK:
            tick=re.search(r'Current receiver time: (?:(\d+) min )?(\d+) s',text)
            if tick:self.log_signal_time=int(tick[1] or 0)*60+int(tick[2])
            event_time=self.log_signal_time
            if re.search(r'Tracking of .*started',text):
                prn=re.search(r'PRN (\d+)',text)
                prior=next((a for a in reversed(self.acquisitions) if a['channel']==ch and prn and a['prn']==int(prn[1])),None)
                if prior:event_time=prior['t']
            position = re.search(r'Position at (.+?) UTC using (\d+) observations is Lat = ([\d.+-]+).*?Long = ([\d.+-]+).*?Height = ([\d.+-]+)',text)
            if position:
                row = dict(t=self.signal_time,utc=position[1],observations=int(position[2]),lat=float(position[3]),lon=float(position[4]),height=float(position[5]))
                self.positions.append(row)
                if self.path.is_dir():
                    with (self.path/'positions.jsonl').open('a',encoding='utf-8') as out: out.write(json.dumps(row)+'\n')
            self.seq += 1
            row = dict(seq=self.seq, wall=time.time(), level=level, module=module, channel=ch, text=text[:4000],t=event_time)
            self.logs.append(row)
            if self.log_sink:self.log_sink.write(json.dumps(row,ensure_ascii=False)+'\n')
            if level != 'INFO' or re.search(r'acquisition|tracking.*started|synchronization locked|extended correlator|position at|interrupt|stopp|quit', text, re.I):
                self.event(dict(row))
    def sample(self, row, persist=None):
        ch = row['channel']; t = row['t']
        if ch < 0 or ch > 127 or t is None: return
        old = self.channels.get(ch)
        row['received_wall'] = time.time()
        self.channels[ch] = row; self.signal_time = max(self.signal_time, t)
        if row.get('slip') and (not old or not old.get('slip')):
            self.event(dict(t=t,wall=time.time(),level='WARN',module='tracking',channel=ch,text='载波周跳'))
        if old and old['prn'] == row['prn'] and old['valid'] != row['valid']:
            event = dict(t=t, wall=time.time(), level='INFO' if row['valid'] else 'WARN', module='tracking', channel=ch, text='符号输出恢复有效' if row['valid'] else '符号输出转为无效')
            self.event(event)
        hist = self.history.setdefault(ch, collections.deque(maxlen=2400))
        if not hist or t-hist[-1]['t'] >= .2 or row['prn'] != hist[-1]['prn']:
            hist.append(row)
            if persist:
                persist.write(json.dumps(row, ensure_ascii=False, allow_nan=False)+'\n')
    def snapshot(self, after=0):
        with LOCK:
            end = self.meta.get('ended', time.time())
            return dict(meta=dict(self.meta), wall_elapsed=max(0,end-self.meta['started']), signal_time=self.signal_time,
                        channels=list(self.channels.values()), history={str(k):list(v) for k,v in self.history.items()},
                        events=list(self.events), logs=[r for r in self.logs if r['seq']>after][-600:],
                        log_seq=self.seq, log_gap=bool(after and (self.seq-after>600 or self.logs and after < self.logs[0]['seq']-1)), udp=self.udp,
                        decode_errors=self.decode_errors, last_packet=self.last_packet, positions=list(self.positions),acquisitions=list(self.acquisitions))

def signal_contract(options):
    signal=options.get('Channel.signal','1C').strip()
    if signal not in ('1C','B3'):raise ValueError('工作台当前开放 GPS 1C 与 BDS B3 的监测适配')
    count=int(options.get(f'Channels_{signal}.count','12'))
    return signal,count


class Workbench:
    def __init__(self):
        self.active = None
        self.restarting=False
        self.settings = json.loads((HERE/'local.json').read_text(encoding='utf-8')) if (HERE/'local.json').exists() else {}
    def defaults(self):
        bundled=HERE/'receiver/bin/gnss-sdr.exe'
        exe=self.settings.get('executable','')
        if not Path(exe).is_file() and bundled.is_file():exe=str(bundled)
        return dict(executable=exe, iq=self.settings.get('iq',''), duration=self.settings.get('duration',20),capture_channel=self.settings.get('capture_channel',0),
                    config=self.settings.get('config',(RESOURCES/'templates/gps-l1.conf').read_text(encoding='utf-8')))
    def validate(self, data):
        exe = Path(data.get('executable','')); iq = Path(data.get('iq',''))
        if not exe.is_file() or exe.suffix.lower() != '.exe': raise ValueError('请选择存在的接收机 .exe 文件')
        if not iq.is_file(): raise ValueError('IQ 文件不存在')
        duration = float(data.get('duration',20))
        if not math.isfinite(duration) or duration <= 0 or duration > 3600: raise ValueError('信号时长需在 0 到 3600 秒之间')
        config = data.get('config','')
        if '[GNSS-SDR]' not in config: raise ValueError('配置缺少 [GNSS-SDR] 段')
        options = dict(re.findall(r'^\s*([^#;\s=]+)\s*=\s*([^\r\n;#]+)',config,re.M))
        # v0.1 has a deliberately explicit input contract; other formats need adapters.
        if options.get('SignalSource.item_type','').strip() != 'ibyte': raise ValueError('本版仅支持 signed int8 I/Q（ibyte）')
        if options.get('SignalSource.implementation','').strip() != 'File_Signal_Source': raise ValueError('本版仅支持 File_Signal_Source')
        signal,count=signal_contract(options)
        if not 1<=count<=128 or not 0<=int(data.get('capture_channel',0))<count:raise ValueError('捕获通道编号超出配置范围')
        if not 1<=int(options.get('Channels.in_acquisition','1'))<=count:raise ValueError('并行捕获通道数应在 1 到总通道数之间')
        for key in (f'Tracking_{signal}.pll_bw_hz',f'Tracking_{signal}.dll_bw_hz',f'Acquisition_{signal}.doppler_step',f'Acquisition_{signal}.doppler_max'):
            if key in options:
                value=float(options[key])
                if not math.isfinite(value) or value<=0:raise ValueError(key+' 应为正数')
        fs = float(options.get('SignalSource.sampling_frequency',0))
        if not math.isfinite(fs) or fs <= 0: raise ValueError('输入采样率无效')
        if float(options.get('SignalSource.seconds_to_skip',0)) != 0 or float(options.get('SignalSource.header_size',0)) != 0:
            raise ValueError('本版时间轴从文件起点计算，请移除跳过时长和文件头设置')
        if iq.stat().st_size < int(duration*fs)*2: raise ValueError('IQ 文件长度不足以覆盖请求的信号时长')
        for key,value in options.items():
            if key.endswith(('dump_filename','output_path')) and value.strip() not in ('.','./') and (Path(value.strip()).is_absolute() or '..' in Path(value.strip()).parts):
                raise ValueError('输出路径必须位于本次实验目录内：'+key)
        return exe.resolve(), iq.resolve(), duration, fs
    def start(self, data, restarting=False):
        with LOCK:
            if self.restarting and not restarting:raise ValueError('接收机正在重启')
            if self.active and self.active.proc and self.active.proc.poll() is None: raise ValueError('已有接收机正在运行')
            exe, iq, duration, fs = self.validate(data)
            capture_channel=int(data.get('capture_channel',0))
            options=dict(re.findall(r'^\s*([^#;\s=]+)\s*=\s*([^\r\n;#]+)',data['config'],re.M))
            signal,configured_channels=signal_contract(options)
            if not 0<=capture_channel<configured_channels:raise ValueError('捕获通道编号超出配置范围')
            sock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM); sock.bind(('127.0.0.1',0)); sock.settimeout(.3)
            acq_sock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM);acq_sock.bind(('127.0.0.1',0));acq_sock.settimeout(.3)
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,4*1024*1024)
            run_id = time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
            path = RUNS/run_id; path.mkdir(parents=True)
            config = data['config']
            overrides = {'SignalSource.filename':iq.as_posix(),'SignalSource.samples':str(int(duration*fs)*2),
                         'SignalSource.repeat':'false','TrackingMonitor.enable_monitor':'true',
                         'TrackingMonitor.enable_protobuf':'true','TrackingMonitor.client_addresses':'127.0.0.1',
                         'TrackingMonitor.udp_port':str(sock.getsockname()[1]),'TrackingMonitor.decimation_factor':'10',
                         'AcquisitionMonitor.enable_monitor':'true','AcquisitionMonitor.enable_protobuf':'true','AcquisitionMonitor.client_addresses':'127.0.0.1','AcquisitionMonitor.udp_port':str(acq_sock.getsockname()[1]),
                         f'Acquisition_{signal}.dump':'true' if data.get('capture_enabled',True) else 'false',f'Acquisition_{signal}.dump_channel':str(capture_channel),f'Acquisition_{signal}.dump_filename':'./acquisition',
                         'PVT.output_path':'.','PVT.nmea_dump_filename':'./solution.nmea'}
            for k,v in overrides.items():
                config = re.sub(r'^\s*'+re.escape(k)+r'\s*=.*(?:\n|$)','',config,flags=re.M)
                config += '\n'+k+'='+v
            (path/'receiver.conf').write_text(config+'\n',encoding='utf-8')
            env = dict(os.environ)
            system = Path(env.get('SystemRoot','C:/Windows'))
            dll_dirs = self.settings.get('dll_dirs',[])
            env['PATH'] = os.pathsep.join([str(exe.parent),*dll_dirs,str(system/'System32'),str(system)])
            command = [str(exe),'--config_file='+str(path/'receiver.conf'),'--log_dir='+str(path),'--keyboard=true']
            with exe.open('rb') as binary:
                executable_hash = hashlib.file_digest(binary,'sha256').hexdigest()
            meta = dict(id=run_id,status='starting',started=time.time(),exe=str(exe),iq=str(iq),duration=duration,fs=fs,
                        exe_sha256=executable_hash,
                        config_sha256=hashlib.sha256((path/'receiver.conf').read_bytes()).hexdigest(),iq_bytes=iq.stat().st_size,
                        iq_mtime_ns=iq.stat().st_mtime_ns,output=str(path),command=command,source=str(data.get('source_label','真实 IQ / 独立接收机进程'))[:120],
                        monitor='TrackingMonitor / UDP Protobuf',version='0.3.1',tracking_port=sock.getsockname()[1],acquisition_port=acq_sock.getsockname()[1],capture_channel=capture_channel,configured_channels=configured_channels,signal=signal,signal_label='BDS · B3I' if signal=='B3' else 'GPS · L1 C/A')
            run = Run(path,meta); run.sock = sock; self.active = run
            try:
                if getattr(sys,'frozen',False):
                    import ctypes
                    ctypes.windll.kernel32.SetDllDirectoryW(None)
                try:
                    run.proc = subprocess.Popen(command,cwd=path,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                                stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                finally:
                    if getattr(sys,'frozen',False):ctypes.windll.kernel32.SetDllDirectoryW(str(sys._MEIPASS))
                meta.update(status='running',pid=run.proc.pid)
            except Exception as exc:
                sock.close();acq_sock.close(); meta.update(status='failed',error=str(exc),ended=time.time()); write_json(path/'manifest.json',meta); raise ValueError(str(exc))
            write_json(path/'manifest.json',meta)
            run.listener = threading.Thread(target=self.listen,args=(run,),daemon=True)
            run.listener.start()
            run.acq_listener=threading.Thread(target=self.listen_acquisition,args=(run,acq_sock),daemon=True);run.acq_listener.start()
            threading.Thread(target=self.consume,args=(run,),daemon=True).start()
            return meta
    def listen_acquisition(self,run,sock):
        fs=float(diagnostics.settings(run.path)['GNSS-SDR.internal_fs_sps'])
        with (run.path/'acquisitions.jsonl').open('w',encoding='utf-8') as out:
            while run.proc.poll() is None:
                try:
                    data,_=sock.recvfrom(65535)
                    for row in decode(data):
                        row['t']=row['acq_samples']/fs
                        with LOCK:
                            run.acquisitions.append(row)
                            run.event(dict(t=row['t'],wall=time.time(),level='INFO',module='acquisition',channel=row['channel'],text=f"{row['system'] or '?'}{row['prn']:02} 捕获成功 · {row['acq_doppler']:.0f} Hz"))
                        out.write(json.dumps(row)+'\n');out.flush()
                except socket.timeout:continue
                except (ValueError,IndexError,struct.error):continue
        sock.close()
    def listen(self, run):
        with (run.path/'telemetry.jsonl').open('w',encoding='utf-8',buffering=1) as out:
            while run.proc.poll() is None:
                try:
                    payload,_ = run.sock.recvfrom(65535)
                    with LOCK:
                        run.udp += 1; run.last_packet = time.time()
                        for row in decode(payload): run.sample(row,out)
                except socket.timeout: continue
                except (ValueError,IndexError,struct.error,UnicodeError): run.decode_errors += 1
                except OSError: break
        run.sock.close()
    def consume(self,run):
        with (run.path/'receiver.log').open('wb') as raw, (run.path/'logs.jsonl').open('w',encoding='utf-8',buffering=1) as structured:
            run.log_sink=structured
            # Read bounded chunks even if the receiver writes a huge line.
            while True:
                line = run.proc.stdout.readline(16384)
                if not line: break
                raw.write(line); raw.flush(); run.log(line.decode('utf-8','replace').rstrip())
            run.log_sink=None
        code = run.proc.wait()
        run.listener.join(timeout=2)
        run.acq_listener.join(timeout=2)
        with LOCK:
            stopped = run.meta['status'] == 'stopping'
            run.meta.update(status='stopped' if stopped and code == 0 else 'completed' if code == 0 else 'failed',exit_code=code,ended=time.time())
            write_json(run.path/'manifest.json',run.meta)
            write_json(run.path/'snapshot.json',run.snapshot())
    def stop(self):
        with LOCK:
            run = self.active
            if not run or not run.proc or run.proc.poll() is not None: raise ValueError('没有正在运行的接收机')
            run.proc.stdin.write(b'q\n'); run.proc.stdin.flush()
            run.meta['status']='stopping'; write_json(run.path/'manifest.json',run.meta)
            return {'status':'stopping'}
    def restart(self,data):
        self.validate(data)
        with LOCK:
            if self.restarting:raise ValueError('接收机正在重启')
            self.restarting=True
            previous=self.active
        try:
            if previous and previous.proc and previous.proc.poll() is None:self.stop()
            deadline=time.monotonic()+30
            while previous and previous.meta['status'] in ('starting','running','stopping'):
                if time.monotonic()>deadline:raise ValueError('仍在等待当前接收机收尾，请稍后重启')
                time.sleep(.1)
            meta=self.start(data,restarting=True)
            meta['restarted_from']=previous.meta['id'] if previous else None
            write_json(self.active.path/'manifest.json',meta)
            return meta
        finally:
            with LOCK:self.restarting=False
    def history(self):
        rows=[]
        for p in sorted(RUNS.glob('*/manifest.json'),reverse=True)[:100]:
            try: rows.append(json.loads(p.read_text(encoding='utf-8')))
            except (ValueError,OSError): pass
        return rows

APP = Workbench()
class LocalServer(ThreadingHTTPServer):
    allow_reuse_address=False
    def server_bind(self):
        if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send(self,data,status=200,ctype='application/json; charset=utf-8'):
        body=json.dumps(data,ensure_ascii=False,allow_nan=False).encode() if not isinstance(data,bytes) else data
        self.send_response(status); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(body)
    def valid_host(self):
        return self.headers.get('Host','') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')
    def do_GET(self):
        if not self.valid_host(): return self.send({'error':'invalid host'},403)
        u=urlparse(self.path); q=parse_qs(u.query)
        try:
            if u.path=='/api/defaults': return self.send(APP.defaults())
            if u.path=='/api/history': return self.send(APP.history())
            if u.path=='/api/raw-iq':
                rid=q.get('run',[''])[0];t=float(q.get('t',['0'])[0]);count=int(q.get('count',['8192'])[0])
                if not re.fullmatch(r'[0-9-]+[a-f0-9]{6}',rid) or not math.isfinite(t) or not 0<=t<=3600 or not 1<=count<=1000000:raise ValueError('IQ 切片范围无效')
                meta=json.loads((RUNS/rid/'manifest.json').read_text(encoding='utf-8'))
                with Path(meta['iq']).open('rb') as f:f.seek(int(t*meta['fs'])*2);payload=f.read(count*2)
                return self.send(payload,ctype='application/octet-stream')
            if u.path=='/api/inspect':
                rid=q.get('run',[''])[0]
                if not re.fullmatch(r'[0-9-]+[a-f0-9]{6}',rid):raise ValueError('请选择实验')
                path=RUNS/rid;kind=q.get('kind',['files'])[0]
                if kind=='timeline':return self.send(diagnostics.timeline(path))
                if kind in ('logs','events'):
                    start=float(q.get('start',['0'])[0]);end=float(q.get('end',['3600'])[0])
                    if not all(math.isfinite(v) for v in (start,end)) or not 0<=start<=end<=3601:raise ValueError('时间范围无效')
                    channel=int(q['channel'][0]) if 'channel' in q else None
                    if channel is not None and not 0<=channel<128:raise ValueError('通道无效')
                    rows=diagnostics.time_rows(path,kind+'.jsonl',start,end,2000 if kind=='events' else 600,tail=True,channel=channel)
                    if not rows and not (path/(kind+'.jsonl')).exists():
                        source=json.loads((path/'snapshot.json').read_text(encoding='utf-8'))
                        rows=[r for r in source.get(kind,[]) if start<=r.get('t',0)<=end]
                    return self.send(rows)
                if kind=='files':return self.send(diagnostics.files(path))
                if kind=='tracking':
                    start=float(q.get('start',['0'])[0]);end=float(q.get('end',['3600'])[0]);ch=int(q.get('channel',['0'])[0])
                    if not all(math.isfinite(x) for x in [start,end]) or not 0<=start<end<=3601 or not 0<=ch<128:raise ValueError('时间范围或通道无效')
                    return self.send(diagnostics.tracking(path,ch,start,end))
                if kind=='acquisition':
                    ch=int(q['channel'][0]) if 'channel' in q else None;at=float(q['t'][0]) if 't' in q else None
                    if ch is not None and not 0<=ch<128 or at is not None and (not math.isfinite(at) or not 0<=at<=3600):raise ValueError('捕获时间或通道无效')
                    return self.send(diagnostics.acquisition(path,q.get('file',[''])[0],ch,at))
                if kind=='iq':
                    t=float(q.get('t',['0'])[0])
                    if not math.isfinite(t) or not 0<=t<=3600:raise ValueError('时间无效')
                    return self.send(diagnostics.iq(path,t))
                if kind=='sky':return self.send(diagnostics.sky(path))
                raise ValueError('未知数据类型')
            if u.path=='/api/state':
                selected=q.get('run',[''])[0]
                if selected and (not APP.active or APP.active.meta['id']!=selected):
                    if not re.fullmatch(r'[0-9-]+[a-f0-9]{6}',selected): raise ValueError('无效实验编号')
                    p=RUNS/selected/'snapshot.json'
                    if not p.exists(): raise ValueError('实验未完整收尾，无可回看快照；原始输出仍保留')
                    return self.send(json.loads(p.read_text(encoding='utf-8')))
                return self.send(APP.active.snapshot(int(q.get('after',['0'])[0])) if APP.active else None)
            if u.path=='/api/file':
                run=q.get('run',[''])[0]; name=q.get('name',['receiver.log'])[0]
                if not re.fullmatch(r'[0-9-]+[a-f0-9]{6}',run): raise ValueError('文件不允许访问')
                p=diagnostics.safe_file(RUNS/run,name)
                if not p.is_file(): raise ValueError('结果文件尚未生成')
                # Stream exports; never read an unlimited raw log into RAM.
                remaining=p.stat().st_size
                self.send_response(200); self.send_header('Content-Type','application/octet-stream'); self.send_header('Content-Length',str(remaining)); self.send_header('Content-Disposition','attachment; filename="'+name+'"'); self.end_headers()
                with p.open('rb') as f:
                    while remaining:
                        chunk=f.read(min(65536,remaining))
                        if not chunk: break
                        self.wfile.write(chunk); remaining-=len(chunk)
                return
            if u.path in ('/','/app.js','/style.css','/debug.js','/debug.css','/replay.js','/replay-model.js','/replay.css'):
                p=RESOURCES/'web'/('index.html' if u.path=='/' else u.path[1:])
                return self.send(p.read_bytes(),ctype={'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8'}[p.suffix[1:]])
            return self.send({'error':'not found'},404)
        except (BrokenPipeError,ConnectionResetError): pass
        except (ValueError,OSError,ImportError,KeyError) as exc: self.send({'error':str(exc)},400)
    def do_POST(self):
        origin=self.headers.get('Origin')
        if not self.valid_host() or origin not in (None,'http://'+self.headers['Host']): return self.send({'error':'origin denied'},403)
        try:
            size=int(self.headers.get('Content-Length',0))
            if size>100000: raise ValueError('请求过大')
            data=json.loads(self.rfile.read(size) or b'{}')
            if self.path=='/api/browse':
                kind=data.get('kind')
                if kind not in ('exe','iq','config'):raise ValueError('文件类型无效')
                command=[sys.executable,'--pick-file',kind] if getattr(sys,'frozen',False) else [sys.executable,str(RESOURCES/'picker.py'),kind]
                r=subprocess.run(command,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=180)
                if r.returncode:raise ValueError('文件选择器未能打开')
                value=json.loads(r.stdout)
                if kind=='config' and value['path']:
                    p=Path(value['path'])
                    if p.stat().st_size>100000:raise ValueError('配置文件过大')
                    value['config']=p.read_text(encoding='utf-8-sig')
                return self.send(value)
            if self.path=='/api/settings':
                APP.validate(data);APP.settings.update(data);write_json(HERE/'local.json',APP.settings);return self.send({'saved':True})
            if self.path=='/api/start': return self.send(APP.start(data))
            if self.path=='/api/restart': return self.send(APP.restart(data))
            if self.path=='/api/validate':
                APP.validate(data); return self.send({'valid':True})
            if self.path=='/api/stop': return self.send(APP.stop())
            self.send({'error':'not found'},404)
        except (ValueError,OSError,KeyError,TypeError) as exc: self.send({'error':str(exc)},400)

def main():
    if len(sys.argv)==3 and sys.argv[1]=='--pick-file':
        import runpy
        sys.argv=[str(RESOURCES/'picker.py'),sys.argv[2]]
        runpy.run_path(str(RESOURCES/'picker.py'),run_name='__main__');return
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8765); parser.add_argument('--open',action='store_true'); args=parser.parse_args()
    RUNS.mkdir(exist_ok=True)
    server=LocalServer(('127.0.0.1',args.port),Handler)
    print(f'GNSS-SDR Workbench http://127.0.0.1:{args.port}',flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{args.port}')
    try: server.serve_forever()
    except KeyboardInterrupt:
        if APP.active and APP.active.proc and APP.active.proc.poll() is None:
            APP.stop()
            try: APP.active.proc.wait(timeout=30)
            except subprocess.TimeoutExpired: print('Receiver still stopping; process was not killed.',flush=True)
    finally: server.server_close()

if __name__=='__main__': main()
