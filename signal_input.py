"""File sample layout shared by validation, receiver configuration and inspection."""
import math
from pathlib import Path
FORMATS = {
    'byte': dict(label='实数 · int8', dtype='i1', components=1, scalar_bytes=1, source_items=1, adapter='Pass_Through', filter_type='byte'),
    'short': dict(label='实数 · int16 LE', dtype='<i2', components=1, scalar_bytes=2, source_items=1, adapter='Pass_Through', filter_type='short'),
    'float': dict(label='实数 · float32 LE', dtype='<f4', components=1, scalar_bytes=4, source_items=1, adapter='Pass_Through', filter_type='float'),
    'ibyte': dict(label='IQ · int8', dtype='i1', components=2, scalar_bytes=1, source_items=2, adapter='Ibyte_To_Complex', filter_type='gr_complex'),
    'ishort': dict(label='IQ · int16 LE', dtype='<i2', components=2, scalar_bytes=2, source_items=2, adapter='Ishort_To_Complex', filter_type='gr_complex'),
    'gr_complex': dict(label='IQ · float32 LE', dtype='<f4', components=2, scalar_bytes=4, source_items=1, adapter='Pass_Through', filter_type='gr_complex'),
}

def layout(options):
    item_type=options.get('SignalSource.item_type','ibyte').strip()
    if item_type not in FORMATS:raise ValueError('请选择实数或 IQ 的 int8、int16、float32 输入格式')
    result=dict(FORMATS[item_type],item_type=item_type)
    result['sample_bytes']=result['scalar_bytes']*result['components']
    result['real']=result['components']==1
    return result

def validate_chain(options, fmt):
    # Explicitly configured mismatches otherwise fail later in GNU Radio's flowgraph.
    for key,expected in [('DataTypeAdapter.implementation',fmt['adapter']),('InputFilter.input_item_type',fmt['filter_type'])]:
        if key in options and options[key].strip()!=expected:raise ValueError(f'{fmt["label"]} 需要 {key}={expected}')
    if fmt['real'] and options.get('InputFilter.implementation','').strip()!='Freq_Xlating_Fir_Filter':
        raise ValueError('实数输入请选择 Freq_Xlating_Fir_Filter，并填写录制信号的中频')
    if fmt['adapter']=='Pass_Through' and options.get('DataTypeAdapter.item_type','gr_complex').strip()!=fmt['filter_type']:
        raise ValueError(f'DataTypeAdapter.item_type 应为 {fmt["filter_type"]}')

def source_count(fmt, duration, fs, file_bytes, *, full_int16_eof=False):
    # Match FileSourceBase's 100 ms tail so DSP blocks can finish before EOF.
    # Its byte-based limit only handles int8 correctly; apply it in sample units.
    available=file_bytes//fmt['sample_bytes']
    if full_int16_eof and fmt['item_type']=='short':
        return min(int(duration*fs),available)
    samples=min(int(duration*fs),max(1,available-math.ceil(.1*fs)))
    return samples*fmt['source_items']

def sources(options, data=None):
    data=data or {}
    count=int(options.get('GNSS-SDR.num_sources',options.get('Receiver.sources_count',1)))
    synchronized = options.get('SignalSource.implementation')=='Multichannel_File_Signal_Source'
    if synchronized:
        channels = int(options.get('SignalSource.RF_channels',1))
        if count!=1 or channels!=int(options.get('SignalSource.total_channels',1)):
            raise ValueError('多通道文件源需要一个源，RF_channels 与 total_channels 应相同')
        count = channels
    if not 1<=count<=32:raise ValueError('RF 输入数需在 1–32 之间')
    result=[]
    for n in range(count):
        suffix=str(n) if count>1 else '';role='SignalSource' if synchronized else 'SignalSource'+suffix
        flat={}
        for base in ('SignalSource','SignalConditioner','DataTypeAdapter','InputFilter','Resampler'):
            prefix=role if base=='SignalSource' else base+suffix
            for k,v in options.items():
                if k.startswith(prefix+'.'):flat[base+k[len(prefix):]]=v
        supplied=data.get('inputs',[])
        filename=supplied[n].get('path','') if n<len(supplied) else ''
        filename_key=role+'.filename'+(str(n) if synchronized else '')
        filename=filename or (data.get('iq','') if n==0 else '') or options.get(filename_key,'')
        if 'Workbench.capture_center_hz' in options:
            first_key='SignalSource.filename0' if synchronized else ('SignalSource0' if count>1 else 'SignalSource')+'.filename'
            filename=data.get('iq') or (supplied[0].get('path') if supplied else '') or options.get(first_key,'')
        fmt=layout(flat);fs=float(flat.get('SignalSource.sampling_frequency',0))
        result.append(dict(index=n,role=role,filename_key=filename_key,path=str(Path(filename).resolve()),fs=fs,format=fmt['item_type'],label=fmt['label'],options=flat,layout=fmt))
    return result
