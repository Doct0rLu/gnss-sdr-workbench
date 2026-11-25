"""Local GNSS-SDR workbench. Python 3.11+; portable builds include numerical dependencies."""
from __future__ import annotations
import argparse, collections, hashlib, json, math, os, re, socket, struct, subprocess, threading, time, uuid, sys
import diagnostics
import linux_receiver
import signal_input
import signals
import picker
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
        self.identities = {r['channel']: r for r in meta.get('channel_map', [])}
        self.native_log_offsets = {}
        self.progress = {}
        for row in self.identities.values():
            stats = self.progress.setdefault(row['signal'], dict(label=row['label'], channels=0,
                                             acquired=set(), tracking=set(), decoded=set()))
            stats['channels'] += 1

    def record_stage(self, channel, prn, stage):
        row = self.identities.get(channel)
        if row and prn > 0:
            self.progress[row['signal']][stage].add(f"{row['system']}{prn:02d}")

    def read_b1c_ephemeris_events(self):
        # Native log records are serialized even when simultaneous stdout messages interleave.
        for path in self.path.glob('gnss-sdr.*.log'):
            try:
                with path.open('rb') as stream:
                    stream.seek(self.native_log_offsets.get(path,0))
                    for line in stream:
                        if not line.endswith(b'\n'):
                            break
                        self.native_log_offsets[path]=stream.tell()
                        if b'B-CNAV1 ephemeris from PRN' not in line:
                            continue
                        event=re.search(rb'New BeiDou B-CNAV1 ephemeris from PRN (\d+) in channel (\d+)\b',line)
                        if event:
                            self.record_stage(int(event[2]),int(event[1]),'decoded')
            except (FileNotFoundError, PermissionError):
                continue

    def stage_summary(self):
        if '1D' in self.progress:
            self.read_b1c_ephemeris_events()
        rows = [dict(signal=sid, **{k:sorted(v) if isinstance(v,set) else v for k,v in stats.items()})
                for sid,stats in self.progress.items()]
        return dict(signals=rows, pvt=diagnostics.pvt_satellites(self.path))

    def event(self,row):
        self.events.append(row)
        if self.path.is_dir():
            with (self.path/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    def log(self, text):
        text = re.sub(r'\x1b\[[0-9;]*m','',text)
        level, module, ch = classify(text)
        with LOCK:
            if self.meta.get('backend')=='upstream-linux':
                marker=re.fullmatch(r'WORKBENCH_(QEMU|RECEIVER)_PID=(\d+)',text)
                if marker:self.meta[marker[1].lower()+'_pid']=int(marker[2])
            tick=re.search(r'Current receiver time: (?:(\d+) min )?(\d+) s',text)
            if tick:self.log_signal_time=int(tick[1] or 0)*60+int(tick[2])
            event_time=self.log_signal_time
            if re.search(r'Tracking of .*started',text):
                prn=re.search(r'PRN (\d+)',text)
                prior=next((a for a in reversed(self.acquisitions) if a['channel']==ch and prn and a['prn']==int(prn[1])),None)
                if prior:event_time=prior['t']
            message = re.search(r'New .+?(?:message received|ephemeris) in channel (\d+)\b.*?\bPRN (\d+)', text, re.I)
            if message:
                self.record_stage(int(message[1]), int(message[2]), 'decoded')
            started = re.search(r'Tracking of .*?started on channel (\d+) for satellite .*?PRN (\d+)', text)
            if started:
                self.record_stage(int(started[1]), int(started[2]), 'tracking')
            position = re.search(r'Position at (.+?) UTC using (\d+) observations is Lat = ([\d.+-]+).*?Long = ([\d.+-]+).*?Height = ([\d.+-]+)',text)
            first = re.search(r'First position fix at (.+?) UTC is Lat = ([\d.+-]+).*?Long = ([\d.+-]+).*?Height = ([\d.+-]+)', text)
            if position or first:
                entry = position or first
                offset = 1 if position else 0
                row = dict(t=self.signal_time or self.log_signal_time,utc=entry[1],
                           observations=int(position[2]) if position else None,first_fix=bool(first),
                           lat=float(entry[2+offset]),lon=float(entry[3+offset]),height=float(entry[4+offset]))
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
        if row.get('valid'):
            self.record_stage(ch, row['prn'], 'tracking')
        if row.get('word'):
            self.record_stage(ch, row['prn'], 'decoded')
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
            return dict(meta=dict(self.meta), nmea=diagnostics.solution_file(self.path).name, stages=self.stage_summary(), wall_elapsed=max(0,end-self.meta['started']), signal_time=self.signal_time,
                        channels=list(self.channels.values()), history={str(k):list(v) for k,v in self.history.items()},
                        events=list(self.events), logs=[r for r in self.logs if r['seq']>after][-600:],
                        log_seq=self.seq, log_gap=bool(after and (self.seq-after>600 or self.logs and after < self.logs[0]['seq']-1)), udp=self.udp,
                        decode_errors=self.decode_errors, last_packet=self.last_packet, positions=list(self.positions),acquisitions=list(self.acquisitions))

def signal_contract(options):
    rows=signals.channels(options)
    return rows[0]['signal'],len(rows)



class Workbench:
    def __init__(self):
        self.active = None
        self.restarting=False
        self.settings = json.loads((HERE/'local.json').read_text(encoding='utf-8')) if (HERE/'local.json').exists() else {}
    def defaults(self):
        linux = linux_receiver.runtime(HERE)
        bundled=HERE/'receiver/bin/gnss-sdr.exe'
        exe=self.settings.get('executable','')
        if not Path(exe).is_file() and bundled.is_file():exe=str(bundled)
        examples = linux/'linux/conf' if linux else None
        return dict(executable=linux_receiver.LABEL if linux else exe, upstream=bool(linux),
                    upstream_examples=[dict(label=p.relative_to(examples).as_posix(),path=str(p))
                                       for p in sorted(examples.rglob('*.conf'))] if examples else [],
                    original_config=self.settings.get('original_config', ''),
                    config_mode=self.settings.get('config_mode','original' if linux and not self.settings else 'guided'),
                    iq=self.settings.get('iq',''), duration=self.settings.get('duration',20),inputs=self.settings.get('inputs',[]),capture_channel=self.settings.get('capture_channel',0),
                    config=self.settings.get('config',(RESOURCES/'templates/gps-l1.conf').read_text(encoding='utf-8')))
    def validate(self, data):
        exe = Path(data.get('executable','')); iq = Path(data.get('iq',''))
        linux = linux_receiver.runtime(HERE)
        if linux:
            exe = linux / 'qemu/qemu-system-x86_64.exe'
        if data.get('config_mode') == 'original':
            if not linux:
                raise ValueError('原始配置模式需要随包 Linux 接收机')
            conf = Path(data.get('original_config',''))
            if not conf.is_file():raise ValueError('请选择原始 .conf 配置文件')
            options = signals.parse(conf.read_bytes().decode('utf-8-sig'))
            entries = linux_receiver.raw_inputs(options,conf.parent,data.get('inputs',[]),data.get('iq',''))
            first = next((entry['path'] for entry in entries if entry['path']),None)
            return exe.resolve(), Path(first) if first else conf.resolve(), 0., float(options.get('GNSS-SDR.internal_fs_sps',0))
        if not exe.is_file() or exe.suffix.lower() != '.exe': raise ValueError('请选择存在的接收机 .exe 文件')
        duration = float(data.get('duration',20))
        if not math.isfinite(duration) or duration <= 0 or duration > 3600: raise ValueError('信号时长需在 0 到 3600 秒之间')
        config = data.get('config','')
        if '[GNSS-SDR]' not in config: raise ValueError('配置缺少 [GNSS-SDR] 段')
        options = dict(re.findall(r'^\s*([^#;\s=]+)\s*=\s*([^\r\n;#]+)',config,re.M))
        inputs=signal_input.sources(options,data)
        channel_map = signals.channels(options)
        for item in inputs:
            cfg=item['options'];fmt=item['layout'];source=Path(item['path']);fs=item['fs']
            if not source.is_file():raise ValueError(f"RF {item['index']} 信号文件不存在")
            signal_input.validate_chain(cfg,fmt)
            if cfg.get('SignalSource.implementation','').strip() not in ('File_Signal_Source','Multichannel_File_Signal_Source'):raise ValueError('文件实验请选择文件信号源')
            if not math.isfinite(fs) or fs<=0:raise ValueError('输入采样率无效')
            if float(cfg.get('SignalSource.seconds_to_skip',0))!=0 or float(cfg.get('SignalSource.header_size',0))!=0:raise ValueError('时间轴从文件起点计算，请移除文件头和跳过设置')
            if 'Workbench.capture_center_hz' in options:
                center = float(options['Workbench.capture_center_hz'])
                branch = {signals.CATALOG[r['signal']]['mhz'] for r in channel_map if r['rf_channel'] == item['index']}
                if len(branch) != 1 or fmt['real'] or fs != inputs[0]['fs'] or item['format'] != inputs[0]['format']:
                    raise ValueError('共享 IQ 支路需要一致的录制参数，每支路对应一个载频')
                frequency = round(next(iter(branch)) * 1e6)
                if (cfg.get('InputFilter.implementation') != 'Freq_Xlating_Fir_Filter'
                    or cfg.get('InputFilter.filter_type') != 'lowpass'
                    or float(cfg.get('InputFilter.IF', 0)) != frequency - center
                    or float(cfg.get('InputFilter.sampling_frequency', 0)) != fs
                    or cfg.get('Resampler.implementation') != 'Pass_Through'):
                    raise ValueError('共享 IQ 支路的中频或滤波配置与录制参数不一致，请重新生成配置')
                signals.check_band(frequency, center, fs, float(options['GNSS-SDR.internal_fs_sps']),
                                   float(cfg.get('InputFilter.bw', 0)), float(cfg.get('InputFilter.tw', 0)))
            if cfg.get('InputFilter.implementation') == 'Freq_Xlating_Fir_Filter' and int(cfg.get('InputFilter.decimation_factor',1)) < 1:
                raise ValueError('抽取因子应为正整数')
            output_fs=fs/float(cfg.get('InputFilter.decimation_factor',1)) if cfg.get('InputFilter.implementation')=='Freq_Xlating_Fir_Filter' else fs
            if cfg.get('Resampler.implementation','Pass_Through')=='Pass_Through' and 'GNSS-SDR.internal_fs_sps' in options and not math.isclose(output_fs,float(options['GNSS-SDR.internal_fs_sps']),rel_tol=1e-6):raise ValueError(f"RF {item['index']} 输出采样率与内部采样率不一致，请设置抽取或重采样")
            if source.stat().st_size<int(duration*fs)*fmt['sample_bytes']:raise ValueError(f"RF {item['index']} 信号文件长度不足")
        rows=signals.channels(options);count=len(rows)
        if not 1<=count<=128 or not 0<=int(data.get('capture_channel',0))<count:raise ValueError('捕获通道编号超出配置范围')
        if any(not 0<=r['rf_channel']<len(inputs) for r in rows):raise ValueError('通道的 RF_channel_ID 没有对应输入文件')
        if not 1<=int(options.get('Channels.in_acquisition','1'))<=count:raise ValueError('并行捕获通道数应在 1 到总通道数之间')
        for key,value in options.items():
            if re.match(r'(Tracking|Acquisition)_',key) and key.endswith(('.pll_bw_hz','.dll_bw_hz','.doppler_step','.doppler_max')):
                value=float(value)
                if not math.isfinite(value) or value<=0:raise ValueError(key+' 应为正数')
        iq=Path(inputs[0]['path']);fs=inputs[0]['fs']
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
            linux = linux_receiver.runtime(HERE)
            original = data.get('config_mode') == 'original'
            if original:
                conf = Path(data['original_config'])
                original_bytes = conf.read_bytes()
                options = signals.parse(original_bytes.decode('utf-8-sig'))
                inputs = linux_receiver.raw_inputs(options, conf.parent, data.get('inputs',[]), data.get('iq',''))
                try:
                    channel_map = signals.channels(options) if any(k.startswith('Channels_') for k in options) else []
                except ValueError:
                    channel_map = []
                configured_channels = len(channel_map)
                signal = channel_map[0]['signal'] if channel_map else ''
                fmt = dict(item_type=options.get('SignalSource.item_type',''), label='原始配置')
            else:
                options=dict(re.findall(r'^\s*([^#;\s=]+)\s*=\s*([^\r\n;#]+)',data['config'],re.M))
                config = data['config']
                if 'Workbench.capture_center_hz' in options and int(options.get('GNSS-SDR.num_sources',1))>1:
                    signals.synchronize_sources(options)
                    config = '[GNSS-SDR]\n'+'\n'.join(f'{k}={v}' for k,v in options.items())+'\n'
                signal,configured_channels=signal_contract(options)
                inputs=signal_input.sources(options,data);channel_map=signals.channels(options)
                fmt=inputs[0]['layout']
                if not 0<=capture_channel<configured_channels:raise ValueError('捕获通道编号超出配置范围')
            sock, trk_relay = linux_receiver.monitor_endpoint(options,'Tracking',1236,original)
            acq_sock, acq_relay = linux_receiver.monitor_endpoint(options,'Acquisition',1235,original)
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,4*1024*1024)
            run_id = time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
            path = RUNS/run_id; path.mkdir(parents=True)
            if original:
                (path/'receiver.conf').write_bytes(original_bytes)
            else:
                monitor_host = '10.0.2.2' if linux else '127.0.0.1'
                overrides = {'TrackingMonitor.enable_monitor':'true',
                             'TrackingMonitor.enable_protobuf':'true','TrackingMonitor.client_addresses':monitor_host,
                             'TrackingMonitor.udp_port':str(sock.getsockname()[1]),'TrackingMonitor.decimation_factor':'10',
                             'AcquisitionMonitor.enable_monitor':'true','AcquisitionMonitor.enable_protobuf':'true','AcquisitionMonitor.client_addresses':monitor_host,'AcquisitionMonitor.udp_port':str(acq_sock.getsockname()[1]),
                             f'Acquisition_{signal}.dump':'true' if data.get('capture_enabled',True) else 'false',f'Acquisition_{signal}.dump_channel':str(capture_channel),f'Acquisition_{signal}.dump_filename':'./acquisition',
                             'PVT.output_path':'.','PVT.nmea_dump_filename':'./solution.nmea'}
                for index,item in enumerate(inputs):
                    src=Path(item['path']);role=item['role']
                    samples=signal_input.source_count(item['layout'],duration,item['fs'],src.stat().st_size)
                    previous=int(overrides.get(role+'.samples',samples))
                    overrides.update({item['filename_key']:f'/mnt/host/input/{index}' if linux else src.as_posix(),role+'.samples':str(min(previous,samples)),
                                      role+'.repeat':'false'})
                for row in channel_map:
                    sid=row['signal'];ch=row['channel']
                    acq=signals.role(options,'Acquisition',sid,ch);trk=signals.role(options,'Tracking',sid,ch)
                    overrides.update({acq+'.dump':'true' if data.get('capture_enabled',True) and ch==capture_channel else 'false',acq+'.dump_channel':str(capture_channel),acq+'.dump_filename':'./acquisition_'+sid,
                        trk+'.dump':'true',trk+'.dump_mat':'false',trk+'.dump_filename':options.get(trk+'.dump_filename','./tracking_'+sid+'_ch_')})
                # Signal-wide acquisition role may be shared: apply selected channel last.
                chosen=channel_map[capture_channel];acq=signals.role(options,'Acquisition',chosen['signal'],capture_channel)
                overrides[acq+'.dump']='true' if data.get('capture_enabled',True) else 'false'
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
                        iq_mtime_ns=iq.stat().st_mtime_ns,output=str(path),command=command,input_format=fmt['item_type'],input_label=fmt['label'],source=str(data.get('source_label','本地信号 / 独立接收机进程'))[:120],
                        monitor='TrackingMonitor / UDP Protobuf',version='0.4.3',tracking_port=sock.getsockname()[1],acquisition_port=acq_sock.getsockname()[1],capture_channel=capture_channel,configured_channels=configured_channels,signal=signal,signal_label=' + '.join(dict.fromkeys(r['label'] for r in channel_map)),signals=list(dict.fromkeys(r['signal'] for r in channel_map)),channel_map=channel_map,inputs=[{k:v for k,v in item.items() if k not in ('layout','options')} for item in inputs])
            if linux:
                command = [sys.executable] + ([] if getattr(sys, 'frozen', False) else [str(RESOURCES/'server.py')])
                command += ['--guest-run', str(linux), str(path)]
                env = dict(os.environ)
                meta.update(command=command, backend='upstream-linux', upstream_commit=linux_receiver.COMMIT,
                            exe='/usr/bin/gnss-sdr', qemu_sha256=executable_hash, config_mode='original' if original else 'guided',
                            exe_sha256=(linux/'linux/receiver.sha256').read_text(encoding='ascii').split()[0],
                            version='0.5.0')
                write_json(path/'guest-job.json', dict(inputs=meta['inputs'],original=original,
                           relays=[r for r in (trk_relay,acq_relay) if r]))
            run = Run(path,meta); run.sock = sock; self.active = run
            if options.get('Workbench.replay_profile') == 'm1':
                satellites = [options.get(f"Channel{row['channel']}.satellite",'').strip() for row in channel_map]
                assigned = sum(value.isdecimal() and value.strip('0') != '' for value in satellites)
                meta['profile_label'] = 'M1 实验 · ' + (f'{assigned} 个指定 PRN 通道' if assigned else '盲搜')
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
        fs=float(diagnostics.settings(run.path).get('GNSS-SDR.internal_fs_sps',0))
        with (run.path/'acquisitions.jsonl').open('w',encoding='utf-8') as out:
            while run.proc.poll() is None:
                try:
                    data,_=sock.recvfrom(65535)
                    for row in decode(data):
                        if fs <= 0:continue
                        row['t']=row['acq_samples']/fs
                        with LOCK:
                            run.record_stage(row['channel'], row['prn'], 'acquired')
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
            if u.path=='/api/signals':return self.send(list(signals.CATALOG.values()))
            if u.path=='/api/defaults': return self.send(APP.defaults())
            if u.path=='/api/history': return self.send(APP.history())
            if u.path in ('/api/raw-iq','/api/raw-input'):
                rid=q.get('run',[''])[0];t=float(q.get('t',['0'])[0]);count=int(q.get('count',['8192'])[0])
                if not re.fullmatch(r'[0-9-]+[a-f0-9]{6}',rid) or not math.isfinite(t) or not 0<=t<=3600 or not 1<=count<=1000000:raise ValueError('信号切片范围无效')
                meta=json.loads((RUNS/rid/'manifest.json').read_text(encoding='utf-8'))
                rf=int(q.get('rf',['0'])[0]);item,fmt=diagnostics.input_source(RUNS/rid,rf);width=fmt['sample_bytes']
                with Path(item['path']).open('rb') as f:f.seek(item.get('byte_offset',0)+int(t*item['fs'])*width);payload=f.read(count*width)
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
                    return self.send(diagnostics.iq(path,t,int(q.get('rf',['0'])[0])))
                if kind=='sky':return self.send(diagnostics.sky(path,q.get('utc',[None])[0]))
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
            if self.path=='/api/template':
                profile = data.get('profile','standard')
                ids = data.get('signals', [])
                if profile == 'm1':
                    if data.get('shared') is not None or data.get('b1c_profile','narrow') != 'narrow':
                        raise ValueError('M1 单频预设使用一份以载频为中心的 24 MS/s IQ 录制')
                    if len(ids)==3 and set(ids)==set(signals.M1_CROSS_SIGNALS):
                        config = signals.m1_cross_template(int(data.get('count',9)), data.get('prns'))
                    elif len(ids)==1:
                        config = signals.m1_template(ids[0], int(data['count']) if 'count' in data else None, data.get('prns',''))
                    else:
                        raise ValueError('请选择对应的 M1 实验预设')
                elif profile == 'standard':
                    config = signals.template(ids,int(data.get('count',8)),data.get('fs'),data.get('shared'),data.get('b1c_profile','narrow'))
                else:
                    raise ValueError('未知接收参数预设')
                return self.send({'config':config})
            if self.path=='/api/browse':
                kind=data.get('kind')
                if kind not in ('exe','iq','config'):raise ValueError('文件类型无效')
                command=[sys.executable,'--pick-file',kind] if getattr(sys,'frozen',False) else [sys.executable,str(RESOURCES/'picker.py'),kind]
                r=subprocess.run(command,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=180)
                if r.returncode:
                    log=HERE/'logs/file-picker.log';log.parent.mkdir(exist_ok=True)
                    with log.open('ab') as out:out.write(r.stderr[-16384:]+b'\n')
                    raise ValueError('文件选择器启动失败，详细信息见 logs/file-picker.log')
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
        except subprocess.TimeoutExpired:self.send({'error':'文件选择超时，请重试'},400)
        except (ValueError,OSError,KeyError,TypeError) as exc: self.send({'error':str(exc)},400)

def main():
    if len(sys.argv)==4 and sys.argv[1]=='--guest-run':
        raise SystemExit(linux_receiver.launch(sys.argv[2], sys.argv[3]))
    if len(sys.argv)==3 and sys.argv[1]=='--pick-file':
        print(json.dumps(picker.choose_file(sys.argv[2]),ensure_ascii=True));return
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--open',action='store_true')
    parser.add_argument('--receiver-config',type=Path)
    parser.add_argument('--input',type=Path,action='append',default=[])
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.receiver_config:
        if not sys.stdout.isatty():sys.stdout.reconfigure(encoding='utf-8')
        base=linux_receiver.runtime(HERE)
        if not base:parser.error('此命令需要便携 Linux 接收机')
        source=args.receiver_config.resolve()
        contents=source.read_bytes()
        options=signals.parse(contents.decode('utf-8-sig'))
        inputs=linux_receiver.raw_inputs(options,source.parent,[dict(path=str(p)) for p in args.input],'')
        path=(args.output or (RUNS/('cli-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]))).resolve()
        path.mkdir(parents=True,exist_ok=False)
        (path/'receiver.conf').write_bytes(contents)
        write_json(path/'guest-job.json',dict(inputs=inputs,original=True))
        print('GNSS-SDR '+linux_receiver.COMMIT[:7]+' · '+str(path),flush=True)
        raise SystemExit(linux_receiver.launch(base,path))
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
