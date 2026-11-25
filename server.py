"""Local GNSS-SDR workbench. Python 3.11+; portable builds include numerical dependencies."""
from __future__ import annotations
import argparse, collections, hashlib, json, math, os, re, socket, struct, subprocess, threading, time, uuid, sys, tempfile
import diagnostics
import native_receiver
import signal_input
import signals
import picker
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from itertools import islice
from urllib.parse import urlparse, parse_qs

RESOURCES = Path(__file__).resolve().parent
HERE = Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else RESOURCES
RUNS = HERE / 'runs'
LOCK = threading.RLock()
HISTORY_LIMIT = 2400
VERSION = '0.6.5'

def archive_roots():
    roots=[RUNS]
    if getattr(sys,'frozen',False):
        for version in ('0.6.4','0.6.3','0.6.2','0.6.1'):
            previous=HERE.parent/f'GNSS-SDR-Workbench-v{version}-win-x64'/'runs'
            if previous.is_dir() and previous!=RUNS:roots.append(previous)
    return roots

def run_path(run_id):
    if not re.fullmatch(r'[0-9]{8}-[0-9]{6}-[0-9a-f]{6}',run_id):raise ValueError('请选择实验')
    return next((p/run_id for p in archive_roots() if (p/run_id).is_dir()),RUNS/run_id)

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
        self.history_revision = 0
        self.history_tail = collections.deque(maxlen=HISTORY_LIMIT)
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
                                             acquired=set(), tracking=set(), valid_tracking=set(), decoded=set()))
            stats['channels'] += 1

    def record_stage(self, channel, prn, stage):
        row = self.identities.get(channel)
        maximum = {'G':32,'C':63,'E':36,'R':32}.get(row['system'],255) if row else 0
        if 0 < prn <= maximum:
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
    def sample(self, row):
        ch = row['channel']; t = row['t']
        if ch < 0 or ch > 127 or t is None: return
        if row.get('valid'):
            self.record_stage(ch, row['prn'], 'valid_tracking')
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
        hist = self.history.setdefault(ch, collections.deque(maxlen=HISTORY_LIMIT))
        if not hist or t-hist[-1]['t'] >= .2 or row['prn'] != hist[-1]['prn']:
            hist.append(row)
            self.history_revision += 1
            self.history_tail.append((str(ch), row))
            return row

    def history_snapshot(self, cursor):
        run_id = self.meta['id']
        update = {'history_cursor': f'{run_id}:{self.history_revision}'}
        prior_run, _, revision = cursor.partition(':')
        if prior_run == run_id and revision.isascii() and revision.isdecimal() and len(revision) <= 16:
            missing = self.history_revision - int(revision)
            if 0 <= missing <= len(self.history_tail):
                recent = list(islice(reversed(self.history_tail), missing))
                delta = {}
                for ch, row in reversed(recent):
                    delta.setdefault(ch, []).append(row)
                return update | {'history_delta': delta}
        return update | {'history': {str(ch): list(rows) for ch, rows in self.history.items()}}

    def snapshot(self, after=0, history_after=None):
        with LOCK:
            end = self.meta.get('ended', time.time())
            history = (self.history_snapshot(history_after) if history_after is not None else
                       {'history': {str(ch): list(rows) for ch, rows in self.history.items()}})
            return dict(meta=dict(self.meta), nmea=diagnostics.solution_file(self.path).name, stages=self.stage_summary(), wall_elapsed=max(0,end-self.meta['started']), signal_time=max(self.signal_time,self.log_signal_time,max((a['t'] for a in self.acquisitions),default=0)),
                        channels=list(self.channels.values()), **history,
                        events=list(self.events), logs=[r for r in self.logs if r['seq']>after][-600:],
                        log_seq=self.seq, log_gap=bool(after and (self.seq-after>600 or self.logs and after < self.logs[0]['seq']-1)), udp=self.udp,
                        decode_errors=self.decode_errors, last_packet=self.last_packet, positions=list(self.positions),acquisitions=list(self.acquisitions))

def signal_contract(options):
    rows=signals.channels(options)
    return rows[0]['signal'],len(rows)

def snapshot_channels(data, count):
    values = data.get('capture_channels', [data.get('capture_channel',0)])
    if not isinstance(values,list) or len(values)>128:
        raise ValueError('请选择有效的捕获快照通道')
    if any(isinstance(ch,bool) or not str(ch).isdigit() for ch in values):
        raise ValueError('捕获通道编号应为整数')
    selected = sorted(set(map(int,values)))
    if any(not 0<=ch<count for ch in selected):
        raise ValueError('捕获通道编号超出配置范围')
    if data.get('capture_enabled',True) and not selected:
        raise ValueError('请至少选择一个快照通道')
    return selected if data.get('capture_enabled',True) else []


def capture_overrides(options, channels, selected):
    result={}
    for row in channels:
        sid,ch=row['signal'],row['channel']
        role=signals.role(options,'Acquisition',sid,ch)
        result[role+'.dump']='false'
        if ch in selected:
            specific=f'Acquisition_{sid}{ch}'
            if role!=specific:
                prefix=role+'.'
                result.update({specific+k[len(role):]:v for k,v in options.items() if k.startswith(prefix)})
                result.setdefault(specific+'.implementation',signals.CATALOG[sid]['acquisition'])
            result.update({specific+'.dump':'true',specific+'.dump_channel':str(ch),
                           specific+'.dump_filename':'./acquisition_'+sid})
    return result



class Workbench:
    def __init__(self):
        self.active = None
        self.restarting=False
        self.settings = json.loads((HERE/'local.json').read_text(encoding='utf-8')) if (HERE/'local.json').exists() else {}
    def defaults(self):
        bundled=HERE/'receiver/bin/gnss-sdr.exe'
        exe=self.settings.get('executable','')
        if bundled.is_file() and (self.settings.get('use_bundled', True) or not Path(exe).is_file()):exe=str(bundled)
        examples = HERE/'receiver/conf'
        return dict(executable=exe, upstream=True,
                    upstream_examples=[dict(label=p.relative_to(examples).as_posix(),path=str(p))
                                       for p in sorted(examples.rglob('*.conf'))] if examples else [],
                    original_config=self.settings.get('original_config', ''),
                    config_mode=self.settings.get('config_mode','guided'),
                    iq=self.settings.get('iq',''), duration=self.settings.get('duration',20),inputs=self.settings.get('inputs',[]),capture_channel=self.settings.get('capture_channel',0),
                    capture_channels=self.settings.get('capture_channels',[self.settings.get('capture_channel',0)]),
                    capture_enabled=self.settings.get('capture_enabled',False),b1c_recovery=self.settings.get('b1c_recovery',True),
                    config=self.settings.get('config',(RESOURCES/'templates/gps-l1.conf').read_text(encoding='utf-8')))
    def validate(self, data):
        exe = Path(data.get('executable','')); iq = Path(data.get('iq',''))
        if not data.get('executable'):
            exe = HERE/'receiver/bin/gnss-sdr.exe'
        if not exe.is_file() or exe.suffix.lower() != '.exe': raise ValueError('请选择存在的接收机 .exe 文件')
        if data.get('config_mode') == 'original':
            conf = Path(data.get('original_config',''))
            if not conf.is_file():raise ValueError('请选择原始 .conf 配置文件')
            options = signals.parse(conf.read_bytes().decode('utf-8-sig'))
            entries = native_receiver.raw_inputs(options,conf.parent,data.get('inputs',[]),data.get('iq',''))
            first = next((entry['path'] for entry in entries if entry['path']),None)
            return exe.resolve(), Path(first) if first else conf.resolve(), 0., float(options.get('GNSS-SDR.internal_fs_sps',0))
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
            recording = signal_input.recording_metadata(source)
            if recording and (fs != recording['rate_hz'] or item['format'] != recording['format']):
                raise ValueError(f"RF {item['index']} 录制记录为 {recording['rate_hz']/1e6:g} MS/s、{recording['format']}。请按录制参数重新生成配置。")
            signal_input.validate_chain(cfg,fmt)
            if cfg.get('SignalSource.implementation','').strip() not in ('File_Signal_Source','Multichannel_File_Signal_Source'):raise ValueError('文件实验请选择文件信号源')
            if not math.isfinite(fs) or fs<=0:raise ValueError('输入采样率无效')
            if float(cfg.get('SignalSource.seconds_to_skip',0))!=0 or float(cfg.get('SignalSource.header_size',0))!=0:raise ValueError('时间轴从文件起点计算，请移除文件头和跳过设置')
            if 'Workbench.capture_center_hz' in options:
                center = float(options['Workbench.capture_center_hz'])
                recorded_center=recording.get('center_hz')
                if isinstance(recorded_center,(int,float)) and recorded_center>0 and center!=recorded_center:
                    raise ValueError(f'录制记录显示中心 {recorded_center/1e6:g} MHz，请更新录制中心或选择对应录制文件')
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
        snapshot_channels(data,count)
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
            capture_channels=[]
            original = data.get('config_mode') == 'original'
            if original:
                conf = Path(data['original_config'])
                original_bytes = conf.read_bytes()
                options = signals.parse(original_bytes.decode('utf-8-sig'))
                inputs = native_receiver.raw_inputs(options, conf.parent, data.get('inputs',[]), data.get('iq',''))
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
                if ('Workbench.capture_center_hz' in options or options.get('Workbench.synchronized_files')=='true') and int(options.get('GNSS-SDR.num_sources',1))>1:
                    signals.synchronize_sources(options)
                    config = '[GNSS-SDR]\n'+'\n'.join(f'{k}={v}' for k,v in options.items())+'\n'
                signal,configured_channels=signal_contract(options)
                inputs=signal_input.sources(options,data);channel_map=signals.channels(options)
                fmt=inputs[0]['layout']
                capture_channels=snapshot_channels(data,configured_channels)
                if exe == (HERE/'receiver/bin/gnss-sdr.exe').resolve():
                    if data.get('b1c_recovery') and int(options.get('Channels_1D.count',0)):
                        exe=exe.with_name('gnss-sdr-b1c.exe')
                    elif len(capture_channels)>1:
                        exe=exe.with_name('gnss-sdr-snapshots.exe')
                elif len(capture_channels)>1 and exe != (HERE/'receiver/bin/gnss-sdr-b1c.exe').resolve() and exe != (HERE/'receiver/bin/gnss-sdr-snapshots.exe').resolve():
                    raise ValueError('多通道快照需要随包接收机，请在高级选项选择 gnss-sdr.exe')
            identity = native_receiver.identity(exe,HERE)
            sock = native_receiver.monitor_socket(options,'Tracking',1236,original)
            try:
                acq_sock = native_receiver.monitor_socket(options,'Acquisition',1235,original)
            except Exception:
                sock.close()
                raise
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,4*1024*1024)
            run_id = time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
            path = RUNS/run_id; path.mkdir(parents=True)
            if original:
                native_receiver.prepare_config(original_bytes,inputs,path)
            else:
                monitor_host = '127.0.0.1'
                overrides = {'TrackingMonitor.enable_monitor':'true',
                             'TrackingMonitor.enable_protobuf':'true','TrackingMonitor.client_addresses':monitor_host,
                             'TrackingMonitor.udp_port':str(sock.getsockname()[1]),'TrackingMonitor.decimation_factor':'10',
                             'AcquisitionMonitor.enable_monitor':'true','AcquisitionMonitor.enable_protobuf':'true','AcquisitionMonitor.client_addresses':monitor_host,'AcquisitionMonitor.udp_port':str(acq_sock.getsockname()[1]),
                             'PVT.output_path':'.','PVT.nmea_dump_filename':'./solution.nmea',
                             'Observables.dump':'true','Observables.dump_mat':'false',
                             'Observables.dump_filename':'./observables.dat'}
                overrides.update(capture_overrides(options,channel_map,capture_channels))
                for index,item in enumerate(inputs):
                    src=Path(item['path']);role=item['role']
                    samples=signal_input.source_count(item['layout'],duration,item['fs'],src.stat().st_size,
                                                      full_int16_eof=identity.get('full_int16_eof',False))
                    previous=int(overrides.get(role+'.samples',samples))
                    overrides.update({item['filename_key']:src.as_posix(),role+'.samples':str(min(previous,samples)),
                                      role+'.repeat':'false'})
                for row in channel_map:
                    sid=row['signal'];ch=row['channel']
                    trk=signals.role(options,'Tracking',sid,ch)
                    overrides.update({trk+'.dump':'true',trk+'.dump_mat':'false',
                                      trk+'.dump_filename':options.get(trk+'.dump_filename','./tracking_'+sid+'_ch_')})
                for k,v in overrides.items():
                    config = re.sub(r'^\s*'+re.escape(k)+r'\s*=.*(?:\n|$)','',config,flags=re.M)
                    config += '\n'+k+'='+v
                (path/'receiver.conf').write_text(config+'\n',encoding='utf-8')
            env = native_receiver.environment(exe, self.settings.get('dll_dirs', []))
            command = native_receiver.command(exe,path)
            meta = dict(id=run_id,status='starting',started=time.time(),exe=str(exe),iq=str(iq),duration=duration,fs=fs,
                        **identity, config_mode='original' if original else 'guided',
                        config_sha256=hashlib.sha256((path/'receiver.conf').read_bytes()).hexdigest(),iq_bytes=iq.stat().st_size,
                        iq_mtime_ns=iq.stat().st_mtime_ns,output=str(path),command=command,input_format=fmt['item_type'],input_label=fmt['label'],source=str(data.get('source_label','本地信号 / 独立接收机进程'))[:120],
                        monitor='TrackingMonitor / UDP Protobuf',version=VERSION,tracking_port=native_receiver.reported_port(sock,options,'Tracking',1236,original),acquisition_port=native_receiver.reported_port(acq_sock,options,'Acquisition',1235,original),capture_channel=next(iter(capture_channels),0),capture_channels=capture_channels,configured_channels=configured_channels,signal=signal,signal_label=' + '.join(dict.fromkeys(r['label'] for r in channel_map)),signals=list(dict.fromkeys(r['signal'] for r in channel_map)),channel_map=channel_map,inputs=[{k:v for k,v in item.items() if k not in ('layout','options')} for item in inputs])
            if original:
                meta['original_config_sha256'] = hashlib.sha256(original_bytes).hexdigest()
            else:
                for entry in meta['inputs']:
                    stat=Path(entry['path']).stat()
                    entry.update(bytes=stat.st_size,mtime_ns=stat.st_mtime_ns)
            if data.get('reprocess_from'):meta['reprocess_from']=data['reprocess_from']
            run = Run(path,meta); run.sock = sock; self.active = run
            if options.get('Workbench.replay_profile') == 'm1':
                satellites = [options.get(f"Channel{row['channel']}.satellite",'').strip() for row in channel_map]
                assigned = sum(value.isdecimal() and value.strip('0') != '' for value in satellites)
                meta['profile_label'] = 'M1 实验 · ' + (f'{assigned} 个指定 PRN 通道' if assigned else '盲搜')
            try:
                with native_receiver.native_dll_search():
                    run.proc = subprocess.Popen(command,cwd=path,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                                stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
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
                    rows = []
                    try:
                        rows.extend(decode(payload))
                    except (ValueError,IndexError,struct.error,UnicodeError):
                        run.decode_errors += 1
                    with LOCK:
                        run.udp += 1; run.last_packet = time.time()
                        samples = [row for row in map(run.sample, rows) if row is not None]
                    if samples:
                        out.write(''.join(json.dumps(row, ensure_ascii=False, allow_nan=False)+'\n' for row in samples))
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
        paths=(p for root in archive_roots() for p in root.glob('*/manifest.json'))
        for p in sorted(paths,key=lambda p:p.parent.name,reverse=True)[:100]:
            try: rows.append(json.loads(p.read_text(encoding='utf-8')))
            except (ValueError,OSError): pass
        return rows

    def reprocess(self, run_id):
        path=run_path(run_id)
        meta=json.loads((path/'manifest.json').read_text(encoding='utf8'))
        if meta.get('status') not in ('completed','stopped'):
            raise ValueError('实验结束后可重算已保存的观测量')
        obs=path/'observables.dat'
        if not obs.is_file() or obs.stat().st_size==0:
            raise ValueError('这次实验没有保存伪距观测量。新版实验完成后可直接重算。')
        channels=meta.get('channel_map',[])
        if not channels or obs.stat().st_size%(56*len(channels)):
            raise ValueError('观测量文件和通道配置不匹配')
        if not any(path.glob('*ephemeris.xml')):
            raise ValueError('这次实验尚无已解星历')
        exe=HERE/'receiver/bin/gnss-sdr-pvt-replay.exe'
        if not exe.is_file():raise ValueError('找不到离线定位程序')
        cfg=signals.parse((path/'receiver.conf').read_text(encoding='utf8'))
        if cfg.get('PVT.positioning_mode','Single').strip()!='Single':
            raise ValueError('观测量直接重算目前使用单点定位，适用于 Single 实验')
        cfg={k:v for k,v in cfg.items() if k.startswith(('PVT.','Channels_','GNSS-SDR.'))}
        # Replay has no Observables block to accept a receiver-clock feedback
        # message. Let RTKLIB estimate the recorded epoch's common clock bias.
        cfg.update({'PVT.output_enabled':'true','PVT.output_path':'.','PVT.nmea_output_path':'.',
                    'PVT.nmea_dump_filename':'./recomputed.nmea','PVT.nmea_output_file_enabled':'true',
                    'PVT.enable_rx_clock_correction':'false','GNSS-SDR.deterministic':'false',
                    'PVT.max_clock_offset_ms':str(max(250,float(cfg.get('PVT.max_clock_offset_ms',40)))),
                    'PVT.enable_monitor':'false','PVT.enable_monitor_ephemeris':'false','PVT.an_output_enabled':'false',
                    'PVT.flag_nmea_tty_port':'false','PVT.flag_rtcm_tty_port':'false','PVT.flag_rtcm_server':'false'})
        for output in ('xml','rinex','gpx','geojson','kml'):
            cfg[f'PVT.{output}_output_enabled']='false'
        with tempfile.TemporaryDirectory(dir=path) as tmp:
            work=Path(tmp)
            config=work/'offline.conf'
            config.write_text('[GNSS-SDR]\n'+'\n'.join(f'{k}={v}' for k,v in cfg.items())+'\n',encoding='utf8')
            command=[str(exe),str(config),str(path),*(r['system']+r['signal'] for r in channels)]
            log=work/'recomputed.log'
            with log.open('wb') as output,native_receiver.native_dll_search():
                result=subprocess.run(command,cwd=work,stdout=output,stderr=subprocess.STDOUT,
                    env=native_receiver.environment(exe),timeout=180,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            log.replace(path/log.name)
            if result.returncode:
                raise ValueError('离线定位失败，详细信息见数据文件中的 recomputed.log')
            nmea=work/'recomputed.nmea'
            if not nmea.is_file() or not nmea.stat().st_size:
                raise ValueError('已保存的观测量未形成定位解')
            nmea.replace(path/nmea.name)
        return dict(run=run_id,rows=diagnostics.solution_track(path,'recomputed.nmea'))

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
                rf=int(q.get('rf',['0'])[0]);item,fmt=diagnostics.input_source(run_path(rid),rf);width=fmt['sample_bytes']
                with Path(item['path']).open('rb') as f:f.seek(item.get('byte_offset',0)+int(t*item['fs'])*width);payload=f.read(count*width)
                return self.send(payload,ctype='application/octet-stream')
            if u.path=='/api/inspect':
                rid=q.get('run',[''])[0]
                if not re.fullmatch(r'[0-9-]+[a-f0-9]{6}',rid):raise ValueError('请选择实验')
                path=run_path(rid);kind=q.get('kind',['files'])[0]
                if kind=='timeline':return self.send(diagnostics.timeline(path))
                if kind=='solution':
                    variant='recomputed.nmea' if q.get('offline',['0'])[0]=='1' else None
                    return self.send(diagnostics.solution_track(path,variant))
                if kind=='offline-status':
                    return self.send(dict(ready=(path/'observables.dat').is_file(),available=(path/'recomputed.nmea').is_file()))
                if kind=='sky' and 't' in q:
                    t=float(q['t'][0])
                    if not math.isfinite(t) or not 0<=t<=3601:raise ValueError('信号时刻无效')
                    return self.send(diagnostics.sky_at(path,t,reference=q.get('reference',['0'])[0]=='1'))
                if kind in ('logs','events'):
                    start=float(q.get('start',['0'])[0]);end=float(q.get('end',['3600'])[0])
                    if not all(math.isfinite(v) for v in (start,end)) or not 0<=start<=end<=3601:raise ValueError('时间范围无效')
                    channel=int(q['channel'][0]) if 'channel' in q else None
                    if channel is not None and not 0<=channel<128:raise ValueError('通道无效')
                    rows=diagnostics.time_rows(path,kind+'.jsonl',start,end,2000 if kind=='events' else 600,tail=True,channel=channel)
                    if not rows and not (path/(kind+'.jsonl')).exists() and (path/'snapshot.json').is_file():
                        source=json.loads((path/'snapshot.json').read_text(encoding='utf-8'))
                        rows=[r for r in source.get(kind,[]) if start<=r.get('t',0)<=end and (channel is None or r.get('channel') in (None,channel))]
                    return self.send(rows)
                if kind=='files':return self.send(diagnostics.files(path))
                if kind=='tracking':
                    start=float(q.get('start',['0'])[0]);end=float(q.get('end',['3600'])[0]);ch=int(q.get('channel',['0'])[0])
                    if not all(math.isfinite(x) for x in [start,end]) or not 0<=start<end<=3601 or not 0<=ch<128:raise ValueError('时间范围或通道无效')
                    return self.send(diagnostics.tracking(path,ch,start,end))
                if kind=='acquisition':
                    ch=int(q['channel'][0]) if 'channel' in q else None;at=float(q['t'][0]) if 't' in q else None
                    selected={int(x) for x in q['channels'][0].split(',')} if 'channels' in q else None
                    if selected is not None and any(not 0<=n<128 for n in selected):raise ValueError('捕获通道无效')
                    if ch is not None and not 0<=ch<128 or at is not None and (not math.isfinite(at) or not 0<=at<=3600):raise ValueError('捕获时间或通道无效')
                    return self.send(diagnostics.acquisition(path,q.get('file',[''])[0],ch,at,surface=q.get('surface',['0'])[0]=='1',channels=selected))
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
                    p=run_path(selected)/'snapshot.json'
                    if not p.exists(): raise ValueError('实验未完整收尾，无可回看快照；原始输出仍保留')
                    return self.send(json.loads(p.read_text(encoding='utf-8')))
                return self.send(APP.active.snapshot(int(q.get('after',['0'])[0]),q.get('history_after',[None])[0]) if APP.active else None)
            if u.path=='/api/file':
                run=q.get('run',[''])[0]; name=q.get('name',['receiver.log'])[0]
                if not re.fullmatch(r'[0-9-]+[a-f0-9]{6}',run): raise ValueError('文件不允许访问')
                p=diagnostics.safe_file(run_path(run),name)
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
            if u.path in ('/','/app.js','/style.css','/debug.js','/debug.css','/replay.js','/replay-model.js','/replay.css','/acquisition-surface.js'):
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
            if self.path=='/api/recording':
                return self.send(signal_input.recording_metadata(data.get('path','')))
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
                    config = signals.template(ids,int(data.get('count',8)),data.get('fs'),data.get('shared'),data.get('b1c_profile','narrow'),data.get('separate'))
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
                exe,*_ = APP.validate(data)
                bundled=HERE/'receiver/bin/gnss-sdr.exe'
                APP.settings.update(data,use_bundled=bundled.is_file() and exe.samefile(bundled))
                write_json(HERE/'local.json',APP.settings);return self.send({'saved':True})
            if self.path=='/api/start': return self.send(APP.start(data))
            if self.path=='/api/restart': return self.send(APP.restart(data))
            if self.path=='/api/reprocess':return self.send(APP.reprocess(data['run']))
            if self.path=='/api/validate':
                APP.validate(data); return self.send({'valid':True})
            if self.path=='/api/stop': return self.send(APP.stop())
            self.send({'error':'not found'},404)
        except subprocess.TimeoutExpired:self.send({'error':'文件选择超时，请重试'},400)
        except (ValueError,OSError,KeyError,TypeError) as exc: self.send({'error':str(exc)},400)

def main():
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
        exe=HERE/'receiver/bin/gnss-sdr.exe'
        native_receiver.identity(exe,HERE)
        source=args.receiver_config.resolve()
        contents=source.read_bytes()
        options=signals.parse(contents.decode('utf-8-sig'))
        inputs=native_receiver.raw_inputs(options,source.parent,[dict(path=str(p)) for p in args.input],'')
        path=(args.output or (RUNS/('cli-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]))).resolve()
        path.mkdir(parents=True,exist_ok=False)
        native_receiver.prepare_config(contents,inputs,path)
        with native_receiver.native_dll_search():
            proc=subprocess.Popen(native_receiver.command(exe,path),cwd=path,env=native_receiver.environment(exe))
        raise SystemExit(proc.wait())
    RUNS.mkdir(exist_ok=True)
    try:server=LocalServer(('127.0.0.1',args.port),Handler)
    except OSError as exc:
        if not args.open or getattr(exc,'winerror',0) not in (10013,10048):raise
        server=LocalServer(('127.0.0.1',0),Handler)
    url=f'http://127.0.0.1:{server.server_port}'
    print('GNSS-SDR Workbench '+url,flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt:
        if APP.active and APP.active.proc and APP.active.proc.poll() is None:
            APP.stop()
            try: APP.active.proc.wait(timeout=30)
            except subprocess.TimeoutExpired: print('Receiver still stopping; process was not killed.',flush=True)
    finally: server.server_close()

if __name__=='__main__': main()
