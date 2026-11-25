"""Read-only adapters for native receiver artifacts and bounded input slices."""
import bisect, datetime, json, math, re, struct, threading
import signal_input
import signals
from pathlib import Path

RECORD=struct.Struct('<7fQd11fdIQI')
_INDEX_LOCK=threading.RLock()
_CAPTURE_CACHE={}

def acquisition_index(path):
    import h5py
    fs=float(settings(path)['GNSS-SDR.internal_fs_sps'])
    rows=[]
    with _INDEX_LOCK:
        for p in path.glob('*_ch_*_sat_*.mat'):
            stat=p.stat();key=(str(p),stat.st_size,stat.st_mtime_ns)
            cached=_CAPTURE_CACHE.get(str(p))
            if cached and cached[0]==key:row=cached[1]
            else:
                try:
                    with h5py.File(p,'r') as f:
                        row=dict(name=p.name,channel=int(re.search(r'_ch_(\d+)',p.name)[1]),t=float(f['sample_counter'][()].flat[0])/fs,prn=int(f['PRN'][()].flat[0]),positive=bool(f['positive_acq'][()].flat[0]))
                    _CAPTURE_CACHE[str(p)]=(key,row)
                except (OSError,KeyError):continue # File may still be written.
            rows.append(dict(row))
        if len(_CAPTURE_CACHE)>10000:_CAPTURE_CACHE.clear()
    return sorted(rows,key=lambda r:(r['t'],r['name']))

def settings(path):
    return dict(re.findall(r'^\s*([^#;\s=]+)\s*=\s*([^\r\n;#]+)',(path/'receiver.conf').read_text(encoding='utf-8'),re.M))

def safe_file(path,name):
    p=(path/name).resolve()
    if p.parent != path.resolve() or not p.is_file(): raise ValueError('文件不存在')
    return p

def files(path):
    return [dict(name=p.name,bytes=p.stat().st_size,modified=p.stat().st_mtime) for p in sorted(path.iterdir()) if p.is_file()][:1000]

def tracking(path,ch,start,end):
    cfg=settings(path);fs=float(cfg['GNSS-SDR.internal_fs_sps'])
    sid=signals.channel(cfg,ch)['signal'];role=signals.role(cfg,'Tracking',sid,ch)
    prefix=cfg.get(role+'.dump_filename','./tracking_ch_')
    p=path/(prefix+str(ch)+'.dat')
    if not p.is_file(): return dict(rows=[],record_bytes=RECORD.size)
    safe_file(path,p.name)
    count=p.stat().st_size//RECORD.size
    # Two binary searches and at most 1600 record reads, regardless of file length.
    with p.open('rb') as f:
        def at(n):
            f.seek(n*RECORD.size);b=f.read(RECORD.size)
            return RECORD.unpack(b) if len(b)==RECORD.size else None
        def lower(t):
            lo,hi=0,count
            while lo<hi:
                mid=(lo+hi)//2;r=at(mid)
                if r is not None and r[7]/fs<t:lo=mid+1
                else:hi=mid
            return lo
        lo,hi=lower(start),lower(end)
        step=max(1,math.ceil((hi-lo)/1600));rows=[]
        for n in range(lo,hi,step):
            r=at(n)
            if r is None:break
            row=dict(t=r[7]/fs,ve=r[0],early=r[1],prompt=r[2],late=r[3],vl=r[4],i=r[5],q=r[6],phase=r[8],doppler=r[9],code_freq=r[11],pll=r[13],pll_nco=r[14],dll=r[15],dll_nco=r[16],cn0=r[17],lock=r[18],prn=r[21])
            rows.append({k:v if not isinstance(v,float) or math.isfinite(v) else None for k,v in row.items()})
    return dict(rows=rows,records=count,record_bytes=RECORD.size,file=p.name,fs=fs,**signals.channel(cfg,ch))

def acquisition(path,name='',channel=None,at=None):
    listing=acquisition_index(path)
    if channel is not None:listing=[r for r in listing if r['channel']==channel]
    if not listing:return dict(files=[],frame=None)
    eligible=[r for r in listing if at is None or r['t']<=at]
    if name:
        eligible=[r for r in eligible if r['name']==name]
    if not eligible:return dict(files=listing,frame=None)
    chosen=eligible[-1];p=safe_file(path,chosen['name'])
    if p.suffix!='.mat':raise ValueError('请选择捕获快照')
    import h5py,numpy as np
    with h5py.File(p,'r') as f:
        def scalar(k,default=0):return float(np.asarray(f[k]).flat[0]) if k in f else default
        grid=f['acq_grid'];nr,nc=grid.shape
        n=min(nr,int(scalar('doppler_num_candidates',nr)))
        if n<1 or nc<1 or nc>1_000_000 or n>4096 or n*nc>128_000_000:
            raise ValueError('捕获网格尺寸超出读取范围')
        # MAT73 stores Doppler rows by delay columns. Keep at most 1M cells in memory.
        edges=np.array_split(np.arange(nc),min(128,nc))
        starts=[part[0] for part in edges]
        pooled=np.empty((n,len(starts)))
        height=max(1,1_000_000//nc)
        peak=-math.inf
        for first in range(0,n,height):
            last=min(n,first+height)
            block=np.nan_to_num(grid[first:last,:],nan=0,posinf=0,neginf=0)
            local_row,local_col=np.unravel_index(block.argmax(),block.shape)
            candidate=float(block[local_row,local_col])
            if candidate>peak:
                peak=candidate
                row,col=first+local_row,local_col
            pooled[first:last]=np.maximum.reduceat(block,starts,axis=1)
        scale=peak or 1
        indices=np.arange(max(0,col-80),min(nc,col+81))
        profile=np.nan_to_num(grid[row,indices[0]:indices[-1]+1],nan=0,posinf=0,neginf=0)
        doppler_profile=np.nan_to_num(grid[:n,col],nan=0,posinf=0,neginf=0)
        step=scalar('doppler_step');center=scalar('doppler_center');dmax=scalar('doppler_max')
        return dict(files=listing,frame=dict(t=chosen['t'],name=p.name,channel=int(re.search(r'_ch_(\d+)',p.name)[1]),prn=scalar('PRN'),sample_counter=scalar('sample_counter'),positive=bool(scalar('positive_acq')),statistic=scalar('test_statistic'),threshold=scalar('threshold'),peak=peak,delay_samples=scalar('acq_delay_samples'),doppler_hz=scalar('acq_doppler_hz'),delay=indices.tolist(),profile=(profile/scale).tolist(),dopplers=(center-dmax+np.arange(n)*step).tolist(),doppler_profile=(doppler_profile/scale).tolist(),heat=(pooled/scale).tolist(),code_samples=nc))

def timeline(path):
    fs=float(settings(path)['GNSS-SDR.internal_fs_sps']);available=0;channels=[]
    cfg=settings(path)
    for identity in signals.channels(cfg):
        ch=identity['channel'];sid=identity['signal'];role=signals.role(cfg,'Tracking',sid,ch)
        p=path/(cfg.get(role+'.dump_filename','./tracking_ch_')+str(ch)+'.dat')
        if not p.is_file():continue
        count=p.stat().st_size//RECORD.size
        if not count:continue
        with p.open('rb') as f:f.seek((count-1)*RECORD.size);raw=f.read(RECORD.size)
        if len(raw)!=RECORD.size:continue
        last=RECORD.unpack(raw);t=last[7]/fs
        if math.isfinite(t):available=max(available,t);channels.append(dict(identity,end=t,records=count))
    captures=acquisition_index(path)
    available=max([available]+[r['t'] for r in captures])
    log=path/'logs.jsonl'
    if log.exists():
        with log.open('rb') as f:
            f.seek(max(0,log.stat().st_size-131072))
            for line in f:
                try:
                    row=json.loads(line);t=float(row.get('t',0))
                    if math.isfinite(t):available=max(available,t)
                except (ValueError,TypeError):pass
    meta=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    return dict(available=min(available,meta['duration']) if meta['duration'] > 0 else available,channels=channels,captures=captures)

_JSON_INDEX={}
def time_rows(path,name,start,end,limit=600,tail=False,channel=None):
    """Incremental block index, including min/max times for nonmonotonic records."""
    p=path/name
    if not p.exists():return []
    with _INDEX_LOCK:
        stat=p.stat();index=_JSON_INDEX.get(str(p))
        if not index or stat.st_size<index['offset']:
            index={'offset':0,'blocks':[]};_JSON_INDEX[str(p)]=index
        with p.open('rb') as f:
            f.seek(index['offset'])
            while True:
                begin=f.tell();times=[]
                for _ in range(256):
                    pos=f.tell();line=f.readline()
                    if not line or not line.endswith(b'\n'):f.seek(pos);break
                    try:
                        t=float(json.loads(line).get('t',0))
                        if math.isfinite(t):times.append(t)
                    except (ValueError,TypeError):pass
                finish=f.tell()
                if finish==begin:break
                index['blocks'].append((begin,finish,min(times,default=0),max(times,default=0)));index['offset']=finish
            rows=[]
            for begin,finish,lo,hi in (reversed(index['blocks']) if tail else index['blocks']):
                if hi<start or lo>end:continue
                f.seek(begin);block=[]
                while f.tell()<finish:
                    try:r=json.loads(f.readline())
                    except ValueError:continue
                    if start<=r.get('t',0)<=end and (channel is None or r.get('channel') in (None,channel)):block.append(r)
                for r in (reversed(block) if tail else block):
                    rows.append(r)
                    if len(rows)>=limit:return list(reversed(rows)) if tail else rows
        if len(_JSON_INDEX)>100:_JSON_INDEX.clear()
        return list(reversed(rows)) if tail else rows

def input_source(path,rf=0):
    cfg=settings(path);meta=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    items=meta.get('inputs') or [dict(path=meta['iq'],fs=meta['fs'],format=cfg.get('SignalSource.item_type','ibyte'))]
    if not 0<=rf<len(items):raise ValueError('RF 输入编号无效')
    item=items[rf]
    if not item.get('path') or not item.get('fs') or item.get('format') not in signal_input.FORMATS:
        raise ValueError('这个输入没有可预览的样本格式和采样率')
    return item,signal_input.layout({'SignalSource.item_type':item['format']})

def iq(path,t,rf=0):
    import numpy as np
    item,fmt=input_source(path,rf);fs=item['fs']
    width=fmt['sample_bytes'];source=Path(item['path'])
    if not math.isfinite(t) or t<0:raise ValueError('信号时间无效')
    # Clamp to the last complete analysis window; all offsets are in logical samples.
    begin=item.get('byte_offset',0)
    total=(source.stat().st_size-begin)//width
    offset=min(max(0,total-8192),int(t*fs))
    with source.open('rb') as f:f.seek(begin+offset*width);raw=f.read(8192*width)
    raw=raw[:len(raw)//width*width]
    a=np.frombuffer(raw,dtype=fmt['dtype']).reshape(-1,fmt['components']).astype(float)
    if len(a)<16:raise ValueError('该时间位置没有足够的信号数据')
    finite=np.isfinite(a);invalid=int(np.size(a)-finite.sum());a=np.where(finite,a,0)
    z=a[:,0] if fmt['real'] else a[:,0]+1j*a[:,1]
    # Two-sided FFT preserves the mirror spectrum of real recordings.
    spec=20*np.log10(np.maximum(np.abs(np.fft.fftshift(np.fft.fft(z*np.hanning(len(z)))))/len(z),1e-10))
    groups=np.array_split(np.arange(len(z)),min(512,len(z)))
    clipped=None
    if fmt['dtype'] in ('i1','<i2'):
        low,high=(-128,127) if fmt['dtype']=='i1' else (-32768,32767)
        clipped=float(np.mean((a<=low)|(a>=high))*100)
    return dict(rf_channel=rf,t=offset/fs,fs=fs,samples=len(z),format=fmt['item_type'],label=fmt['label'],real=fmt['real'],sample_bytes=width,
                i=a[:256,0].tolist(),q=[] if fmt['real'] else a[:256,1].tolist(),
                spectrum=[float(spec[g].max()) for g in groups],mhz=[float((g.mean()/len(z)-.5)*fs/1e6) for g in groups],
                rms=float(np.sqrt(np.mean(np.abs(z)**2))),dc_i=float(a[:,0].mean()),dc_q=None if fmt['real'] else float(a[:,1].mean()),clipped=clipped,invalid=invalid)

def solution_file(path):
    expected = path/'solution.nmea'
    if expected.exists():
        return expected
    candidates = list(path.glob('*.nmea'))
    return candidates[0] if len(candidates) == 1 else expected


def nmea_fields(raw):
    if not raw.endswith(b'\n') or not raw.startswith(b'$'):
        return []
    body, mark, checksum = raw.rstrip().partition(b'*')
    if not mark:
        return []
    check = 0
    for byte in body[1:]:
        check ^= byte
    if checksum.upper() != f'{check:02X}'.encode():
        return []
    return body[1:].decode('ascii','replace').split(',')


_SKY_INDEX = {}
_SKY_LOCK = threading.Lock()


def sky_epoch(p, utc):
    """Index complete GGA records once, including UTC day rollovers."""
    with _SKY_LOCK, p.open('rb') as stream:
        size = p.stat().st_size
        index = _SKY_INDEX.get(p)
        if index is None or size < index['read']:
            if len(_SKY_INDEX) >= 32:_SKY_INDEX.clear()
            index = _SKY_INDEX[p] = dict(read=0,day=0,clock=None,times=[],offsets=[])
        stream.seek(index['read'])
        for raw in stream:
            if not raw.endswith(b'\n'):break
            start=index['read']
            index['read']+=len(raw)
            if raw[3:6] not in (b'GGA',b'RMC'):continue
            f=nmea_fields(raw)
            if not f:continue
            if f[0].endswith('RMC') and len(f)>9:
                try:index['day']=datetime.datetime.strptime(f[9],'%d%m%y').date().toordinal();index['clock']=None
                except ValueError:pass
            elif f[0].endswith('GGA') and len(f)>1:
                try:clock=int(f[1][:2])*3600+int(f[1][2:4])*60+float(f[1][4:])
                except ValueError:continue
                if index['clock'] is not None and clock < index['clock']-43200:index['day']+=1
                index['clock']=clock
                index['times'].append(index['day']*86400+clock)
                index['offsets'].append(start)
        offsets=index['offsets']
        if not offsets:return max(0,size-131072),size
        pos=len(offsets)-1
        if utc:
            try:
                day,clock=utc.split(' ',1)
                date=datetime.datetime.strptime(day,'%Y-%b-%d').date().toordinal()
                hour,minute,second=clock.split(':')
                target=(date if index['day']>366 else index['day'])*86400+int(hour)*3600+int(minute)*60+float(second)
            except (ValueError,OverflowError):
                return 0,0
            pos=bisect.bisect_right(index['times'],target)-1
            if pos<0:return 0,0
        return offsets[pos],offsets[pos+1] if pos+1<len(offsets) else index['read']


def sky(path, utc=None):
    """GSV satellites from all talkers in one GGA epoch."""
    p=solution_file(path)
    if not p.is_file():return []
    start,end=sky_epoch(p,utc)
    satellites={}
    with p.open('rb') as stream:
        stream.seek(start)
        for raw in stream.read(end-start).splitlines(keepends=True):
            v=nmea_fields(raw)
            if not v:continue
            if v[0].endswith('GSV') and len(v) >= 4:
                talker = v[0][:2]
                if v[2] == '1':
                    satellites[talker] = {}
                rows = satellites.setdefault(talker, {})
                for i in range(4,len(v)-3,4):
                    try:
                        prn = int(v[i])
                        system = {'GP':'G','BD':'C','GB':'C','GA':'E','GL':'R','GQ':'J','QZ':'J'}.get(talker,'?')
                        if system=='G' and 33 <= prn <= 64:system,prn='S',prn+87
                        if system=='R' and 65 <= prn <= 96:prn -= 64
                        rows[(system,prn)] = dict(system=system,prn=prn,elevation=float(v[i+1]),
                                                 azimuth=float(v[i+2]),cn0=float(v[i+3]) if v[i+3] else None)
                    except ValueError:
                        continue
    return list({key:row for group in satellites.values() for key,row in group.items()}.values())

def pvt_satellites(path):
    """Satellites reported by the receiver's GSA writers for its latest GGA epoch."""
    try:
        with solution_file(path).open('rb') as stream:
            stream.seek(max(0, stream.seek(0, 2) - 8192))
            lines = stream.read().split(b'\n')[:-1]
    except (FileNotFoundError, PermissionError):
        return None
    satellites = None
    systems = {'GP':'G', 'GL':'R', 'QZ':'J', 'GA':'E', 'GB':'C', 'BD':'C'}
    for line in lines:
        body, mark, checksum = line.strip().partition(b'*')
        if not mark or not body.startswith(b'$'):
            continue
        check = 0
        for byte in body[1:]:
            check ^= byte
        if checksum.upper() != f'{check:02X}'.encode():
            continue
        fields = body[1:].decode('ascii', 'replace').split(',')
        if fields[0].endswith('GGA'):
            satellites = None
        system = systems.get(fields[0][:2])
        if not system or not fields[0].endswith('GSA') or len(fields) < 15:
            continue
        if satellites is None:
            satellites = set()
        if fields[2] not in ('2','3'):
            continue
        for field in fields[3:15]:
            if field.isdigit():
                n = int(field)
                if system == 'G' and 33 <= n <= 64:
                    satellites.add(f'S{n + 87}')
                else:
                    n = n - 64 if system == 'R' and 65 <= n <= 96 else n
                    satellites.add(f'{system}{n:02d}')
    return sorted(satellites) if satellites is not None else None
