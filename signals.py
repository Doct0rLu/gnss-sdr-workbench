"""Signal identities and channel order from the bundled GNSS-SDR block factory."""
import math
import re

from signal_input import FORMATS

# Keep factory order: absolute channel IDs depend on it, not configuration order.
_ROWS = [
 ('1C','G','GPS L1 C/A',1575.42,'GPS_L1_CA_PCPS_Acquisition','GPS_L1_CA_DLL_PLL_Tracking','GPS_L1_CA_Telemetry_Decoder',4e6),
 ('1S','G','GPS L1C',1575.42,'GPS_L1C_PCPS_Ambiguous_Acquisition','GPS_L1C_DLL_PLL_VEML_Tracking','GPS_L1C_Telemetry_Decoder',4e6),
 ('2S','G','GPS L2C (M)',1227.60,'GPS_L2_M_PCPS_Acquisition','GPS_L2_M_DLL_PLL_Tracking','GPS_L2C_Telemetry_Decoder',4e6),
 ('L5','G','GPS L5',1176.45,'GPS_L5i_PCPS_Acquisition','GPS_L5_DLL_PLL_Tracking','GPS_L5_Telemetry_Decoder',24e6),
 ('1B','E','Galileo E1 B/C',1575.42,'Galileo_E1_PCPS_Ambiguous_Acquisition','Galileo_E1_DLL_PLL_VEML_Tracking','Galileo_E1B_Telemetry_Decoder',4e6),
 ('5X','E','Galileo E5a',1176.45,'Galileo_E5a_Pcps_Acquisition','Galileo_E5a_DLL_PLL_Tracking','Galileo_E5a_Telemetry_Decoder',24e6),
 ('E6','E','Galileo E6 B/C',1278.75,'Galileo_E6_PCPS_Acquisition','Galileo_E6_DLL_PLL_Tracking','Galileo_E6_Telemetry_Decoder',24e6),
 ('1G','R','GLONASS L1 C/A',1602.0,'GLONASS_L1_CA_PCPS_Acquisition','GLONASS_L1_CA_DLL_PLL_Tracking','GLONASS_L1_CA_Telemetry_Decoder',8e6),
 ('2G','R','GLONASS L2 C/A',1246.0,'GLONASS_L2_CA_PCPS_Acquisition','GLONASS_L2_CA_DLL_PLL_Tracking','GLONASS_L2_CA_Telemetry_Decoder',8e6),
 ('B1','C','北斗 B1I',1561.098,'BEIDOU_B1I_PCPS_Acquisition','BEIDOU_B1I_DLL_PLL_Tracking','BEIDOU_B1I_Telemetry_Decoder',4e6),
 ('1D','C','北斗 B1C',1575.42,'BEIDOU_B1C_PCPS_Ambiguous_Acquisition','BEIDOU_B1C_DLL_PLL_VEML_Tracking','BEIDOU_B1C_Telemetry_Decoder',8e6),
 ('5D','C','北斗 B2a',1176.45,'BEIDOU_B2A_PCPS_Acquisition','BEIDOU_B2A_DLL_PLL_Tracking','BEIDOU_B2A_Telemetry_Decoder',24e6),
 ('B3','C','北斗 B3I',1268.52,'BEIDOU_B3I_PCPS_Acquisition','BEIDOU_B3I_DLL_PLL_Tracking','BEIDOU_B3I_Telemetry_Decoder',24e6),
 ('7X','E','Galileo E5b',1207.14,'Galileo_E5b_PCPS_Acquisition','Galileo_E5b_DLL_PLL_Tracking','Galileo_E5b_Telemetry_Decoder',24e6),
 ('J1','J','QZSS L1 C/A',1575.42,'QZSS_L1_PCPS_Acquisition','QZSS_L1_CA_DLL_PLL_Tracking','QZSS_L1_Telemetry_Decoder',4e6),
 ('J5','J','QZSS L5',1176.45,'QZSS_L5i_PCPS_Acquisition','QZSS_L5_DLL_PLL_Tracking','QZSS_L5_Telemetry_Decoder',24e6),
 ('S1','S','SBAS L1',1575.42,'SBAS_L1_PCPS_Acquisition','SBAS_L1_DLL_PLL_Tracking','SBAS_L1_Telemetry_Decoder',4e6),
]
CATALOG={r[0]:dict(zip(('id','system','label','mhz','acquisition','tracking','telemetry','fs'),r)) for r in _ROWS}
for sid,item in CATALOG.items():
    item['purpose']='增强电文 / SBAS 校正' if sid=='S1' else 'E6 导航电文 / HAS 改正' if sid=='E6' else '观测量与 PVT'
    item['frequency_step_mhz']=.5625 if sid=='1G' else .4375 if sid=='2G' else 0

def parse(text):
    return dict(re.findall(r'^\s*([^#;\s=]+)\s*=\s*([^\r\n;#]+)',text,re.M))

def channels(cfg):
    unknown=[k for k in cfg if re.fullmatch(r'Channels_\w+\.count',k) and k[9:-6] not in CATALOG and int(cfg[k])]
    if unknown:raise ValueError('接收机没有该信号标识：'+', '.join(unknown))
    groups=[(sid,int(cfg.get('Channels_'+sid+'.count',0))) for sid in CATALOG]
    # Compatibility for early workbench configurations without a channel count.
    if not any(n for _,n in groups) and not any(k.startswith('Channels_') for k in cfg):
        sid=cfg.get('Channel.signal','1C').strip()
        if sid not in CATALOG:raise ValueError('未知信号标识：'+sid)
        groups=[(sid,12)]
    result=[]
    for sid,count in groups:
        if count<0:raise ValueError('通道数不能为负数')
        if len(result)+count>128:raise ValueError('总通道数需在 1–128 之间')
        for _ in range(count):
            ch=len(result);rf=int(cfg.get(f'Channel{ch}.RF_channel_ID',cfg.get(f'Channels_{sid}.RF_channel_ID',0)))
            result.append(dict(channel=ch,signal=sid,rf_channel=rf,system=CATALOG[sid]['system'],label=CATALOG[sid]['label']))
    if not result:raise ValueError('请至少启用一个信号通道')
    return result

def channel(cfg,ch):
    return next((r for r in channels(cfg) if r['channel']==ch),dict(channel=ch,signal=cfg.get('Channel.signal','1C'),system='?',rf_channel=0))

def role(cfg,base,sid,ch):
    # The native factory accepts per-channel roles, with the signal-wide fallback.
    specific=f'{base}_{sid}{ch}'
    return specific if specific+'.implementation' in cfg else f'{base}_{sid}'

def branch_bandwidth(ids, wide_b1c, single_frequency):
    # One-sided low-pass cutoff and transition width in Hz.
    if set(ids)=={'2S'}:
        return 1_500_000, 500_000
    if any(CATALOG[s]['fs'] >= 24e6 for s in ids) or ('1D' in ids and wide_b1c):
        return 10_300_000, 900_000
    if any(s in ('1G', '2G') for s in ids):
        return 4_600_000, 900_000
    if single_frequency and '1D' in ids:
        return 3_000_000, 750_000
    return 2_600_000, 1_200_000


def check_band(frequency, center, rate, internal, cutoff, transition):
    if not all(math.isfinite(v) and v > 0 for v in (frequency, center, rate, internal, cutoff, transition)):
        raise ValueError('采集中心、采样率、低通带宽和过渡带必须为正数')
    offset = frequency - center
    if abs(offset) + cutoff + transition > rate / 2:
        raise ValueError(f'{frequency / 1e6:g} MHz 支路超出录制带宽（IF {offset / 1e6:+g} MHz，低通和过渡带 {(cutoff + transition) / 1e6:g} MHz）')
    if cutoff + transition > internal / 2:
        raise ValueError('抽取后采样率不足以容纳支路低通和过渡带')


def lowpass(cfg, suffix, rate, offset, cutoff, transition, factor):
    values = dict(implementation='Freq_Xlating_Fir_Filter', IF=offset,
                  sampling_frequency=rate, filter_type='lowpass', bw=cutoff, tw=transition,
                  decimation_factor=factor, input_item_type='gr_complex',
                  output_item_type='gr_complex', taps_item_type='float')
    cfg.update({f'InputFilter{suffix}.{key}': value for key, value in values.items()})


def synchronize_sources(cfg):
    """Give matched file streams one sample counter and one end-of-input event."""
    count = int(cfg.get('GNSS-SDR.num_sources',1))
    if count < 2:
        return
    if 'Workbench.capture_center_hz' not in cfg:
        if cfg.get('Workbench.synchronized_files') != 'true':
            return
        # The native multi-channel file source shares every input option except filename.
        streams=[{k.split('.',1)[1]:v for k,v in cfg.items() if k.startswith(f'SignalSource{n}.') and not k.endswith('.filename')} for n in range(count)]
        if any(stream!=streams[0] for stream in streams[1:]):return
    source = {}
    for n in range(count):
        prefix = f'SignalSource{n}.'
        for key in [key for key in cfg if key.startswith(prefix)]:
            option = key[len(prefix):]
            value = cfg.pop(key)
            if option == 'filename':
                source[f'SignalSource.filename{n}'] = value
            elif n == 0:
                source['SignalSource.' + option] = value
    cfg.update(source)
    cfg.update({'GNSS-SDR.num_sources':1, 'SignalSource.implementation':'Multichannel_File_Signal_Source',
                'SignalSource.RF_channels':count, 'SignalSource.total_channels':count})


def template(ids, count=8, fs=None, shared=None, b1c_profile='narrow', separate=None):
    ids=list(dict.fromkeys(ids))
    if not ids or any(s not in CATALOG for s in ids):raise ValueError('请选择信号')
    if not 1<=int(count)<=128 or len(ids)*int(count)>128:raise ValueError('总通道数需在 1–128 之间')
    if b1c_profile not in ('narrow', 'wide'):
        raise ValueError('请选择 B1C 接收模式')
    wide = '1D' in ids and b1c_profile == 'wide'
    frequencies = list(dict.fromkeys(CATALOG[s]['mhz'] for s in ids))
    multi = len(frequencies) > 1
    bands = [branch_bandwidth([s for s in ids if CATALOG[s]['mhz'] == freq], wide, not multi)
             for freq in frequencies]
    rate = int(fs or max(24e6 if wide else 0, *(CATALOG[s]['fs'] for s in ids)))
    fmt = 'ibyte'
    factor = 1
    cfg = {}
    if separate is not None:
        if shared is not None:
            raise ValueError('请选择一种录制方式')
        target = rate
        rate = int(separate['rate_hz'])
        fmt = separate['format']
        if not 0 < rate <= 2_147_483_647 or fmt not in FORMATS or FORMATS[fmt]['components'] != 2:
            raise ValueError('请填写录制采样率并选择 IQ 格式')
        if rate < target:
            raise ValueError(f'当前信号接收配置需要至少 {target/1e6:g} MS/s')
        factor = max(n for n in range(1, rate // target + 1) if rate % n == 0)
        if multi:cfg['Workbench.synchronized_files']='true'
    if shared is not None:
        center = float(shared.get('center_mhz', 0)) * 1e6
        rate = int(shared.get('rate_hz', 0))
        fmt = shared.get('format', 'ibyte')
        if fmt not in FORMATS or FORMATS[fmt]['components'] != 2:
            raise ValueError('共享宽带文件请选择 IQ 格式')
        minimum = max(2 * (bw + tw) for bw, tw in bands)
        if fs is not None:
            internal = int(fs)
            if internal <= 0 or rate < internal or rate % internal:
                raise ValueError('输入采样率应为内部采样率的整数倍')
            factor = rate // internal
        else:
            # Prefer an integral output rate and the largest alias-free decimation.
            if not 0 < rate <= 2_147_483_647:
                raise ValueError('采样率超出接收机范围')
            factor = max(n for n in range(1, max(1, rate // minimum) + 1) if rate % n == 0)
        cfg['Workbench.capture_center_hz'] = round(center) if math.isfinite(center) else 0
    internal = rate // factor
    if rate <= 0 or (wide and internal < 22_400_000):
        raise ValueError('宽带 QMBOC 配置需要至少 22.4 MS/s' if wide else '采样率无效')
    cfg.update({'GNSS-SDR.internal_fs_sps':internal,'GNSS-SDR.use_acquisition_resampler':'false','ControlThread.wait_for_flowgraph':'false'})
    if multi:cfg['GNSS-SDR.num_sources']=len(frequencies)
    for n,freq in enumerate(frequencies):
        suffix=str(n) if multi else '';src='SignalSource'+suffix
        cfg.update({src+'.implementation':'File_Signal_Source',src+'.filename':('INPUT-IQ.bin' if shared is not None else f'INPUT-RF{n}.bin'),src+'.item_type':fmt,src+'.sampling_frequency':rate,src+'.samples':0,src+'.repeat':'false',src+'.enable_throttle_control':'false',
          'SignalConditioner'+suffix+'.implementation':'Signal_Conditioner','DataTypeAdapter'+suffix+'.implementation':FORMATS[fmt]['adapter'],'InputFilter'+suffix+'.implementation':'Pass_Through','InputFilter'+suffix+'.IF':0,'InputFilter'+suffix+'.input_item_type':'gr_complex','Resampler'+suffix+'.implementation':'Pass_Through'})
        frequency = round(freq * 1e6)
        if shared is not None:
            center = cfg['Workbench.capture_center_hz']
            cutoff, transition = bands[n]
            check_band(frequency, center, rate, internal, cutoff, transition)
            lowpass(cfg, suffix, rate, frequency - center, cutoff, transition, factor)
        elif ('1D' in ids and freq == CATALOG['1D']['mhz']) or factor > 1:
            cutoff, transition = bands[n]
            if factor > 1 and cutoff + transition > internal/2:
                cutoff, transition = int(.38*internal), int(.1*internal)
            check_band(frequency, frequency, rate, internal, cutoff, transition)
            lowpass(cfg, suffix, rate, 0, cutoff, transition, factor)
    for sid in ids:
        cfg['Channels_'+sid+'.count']=int(count);cfg['Channels_'+sid+'.RF_channel_ID']=frequencies.index(CATALOG[sid]['mhz'])
        item=CATALOG[sid]
        for base,key in [('Acquisition','acquisition'),('Tracking','tracking'),('TelemetryDecoder','telemetry')]:cfg[f'{base}_{sid}.implementation']=item[key]
        for key,value in {'item_type':'gr_complex','doppler_max':10000,'doppler_step':500,'pfa':.0001,'blocking':'true','coherent_integration_time_ms':20 if sid=='2S' else 4 if sid=='1B' else 10 if sid in ('1S','1D') else 1}.items():cfg[f'Acquisition_{sid}.'+key]=value
        for key,value in {'item_type':'gr_complex','pll_bw_hz':35,'dll_bw_hz':2,'dump':'true','dump_mat':'false','dump_filename':f'./tracking_{sid}_ch_'}.items():cfg[f'Tracking_{sid}.'+key]=value
        if sid in ('1S','1D'):cfg[f'Acquisition_{sid}.acquire_pilot']='true';cfg[f'Tracking_{sid}.track_pilot']='true'
    if '2S' in ids:
        cfg.update({'Acquisition_2S.doppler_max':5000, 'Acquisition_2S.doppler_step':25,
                    'Acquisition_2S.pfa':0.001, 'Tracking_2S.pll_bw_hz':6, 'Tracking_2S.dll_bw_hz':0.2,
                    'Tracking_2S.pll_bw_narrow_hz':3, 'Tracking_2S.dll_bw_narrow_hz':0.15})
    if '1D' in ids:
        replica = 'true' if wide else 'false'
        cfg.update({'Acquisition_1D.qmboc': replica, 'Tracking_1D.qmboc': replica,
                    'Acquisition_1D.doppler_step': 50, 'Acquisition_1D.doppler_max': 4500})
        loops = dict(pll_bw_hz=10, dll_bw_hz=0.5, pll_bw_narrow_hz=5, dll_bw_narrow_hz=0.2,
                     pll_filter_order=2, early_late_space_chips=0.15, very_early_late_space_chips=0.5,
                     cn0_min=20, bit_synchronization_time_limit_s=90, extend_correlation_symbols=1)
        cfg.update({f'Tracking_1D.{key}': value for key, value in loops.items()})
    cfg.update({'Channels.in_acquisition':min(6 if '1D' in ids else 2,len(ids)*int(count)),'Channel.signal':ids[0],'Observables.implementation':'Hybrid_Observables','PVT.implementation':'RTKLIB_PVT','PVT.positioning_mode':'Single','PVT.output_rate_ms':100,'PVT.display_rate_ms':1000,'PVT.output_enabled':'true','PVT.output_path':'.','PVT.nmea_dump_filename':'./solution.nmea','PVT.flag_nmea_tty_port':'false','PVT.flag_rtcm_tty_port':'false','PVT.flag_rtcm_server':'false'})
    if shared is not None:synchronize_sources(cfg)
    return '[GNSS-SDR]\n'+'\n'.join(f'{k}={v}' for k,v in cfg.items())+'\n'

def parse_prns(sid, prns):
    if not isinstance(prns, str):
        raise ValueError('PRN 请用空格或逗号分隔')
    tokens = prns.strip()
    satellites = []
    if tokens:
        maximum = 63 if CATALOG[sid]['system'] == 'C' else 32
        for token in re.split(r'[，,\s]+', tokens):
            if not token.isascii() or not token.isdecimal() or not 1 <= int(token) <= maximum:
                raise ValueError(f'PRN 应为 1–{maximum} 的整数')
            satellites.append(int(token))
        if len(set(satellites)) != len(satellites):
            raise ValueError('PRN 列表中有重复卫星')
    return satellites


def m1_template(sid, count=None, prns=''):
    """M1 single-band replay with optional assignments from the current recording."""
    if sid not in ('1D', '2S', 'L5'):
        raise ValueError('M1 单频预设支持 B1C、L2C 和 L5')
    satellites = parse_prns(sid, prns)
    if count is None:
        count = 12 if sid == '2S' else 9
    if satellites:
        count = len(satellites)

    rate = 24_000_000
    internal = {'1D':8_000_000, '2S':4_000_000, 'L5':rate}[sid]
    cfg = parse(template([sid], count, internal))
    cfg['Workbench.replay_profile'] = 'm1'
    cfg['SignalSource.sampling_frequency'] = rate
    if sid == '1D':
        lowpass(cfg, '', rate, 0, 3_000_000, 750_000, 3)
        cfg.update({'Tracking_1D.b1c_data_prompt_scale':4.0, 'Tracking_1D.b1c_pilot_prompt_scale':1.0,
                    'Channels.in_acquisition':min(9, count)})
    elif sid == '2S':
        lowpass(cfg, '', rate, 0, 1_500_000, 500_000, 6)
    else:
        cfg.update({'Acquisition_L5.doppler_max':6500, 'Acquisition_L5.doppler_step':250,
                    'Acquisition_L5.pfa':0.01, 'Acquisition_L5.max_dwells':4, 'Acquisition_L5.acquire_pilot':'false',
                    'Tracking_L5.track_pilot':'false', 'Tracking_L5.pll_bw_hz':12, 'Tracking_L5.dll_bw_hz':0.5,
                    'Tracking_L5.pll_bw_narrow_hz':5, 'Tracking_L5.dll_bw_narrow_hz':0.2})
    if sid in ('2S','L5'):
        cfg.update({'PVT.elevation_mask':5, 'PVT.iono_model':'OFF', 'PVT.trop_model':'OFF'})
    for channel_id, prn in enumerate(satellites):
        cfg[f'Channel{channel_id}.satellite'] = prn
    return '[GNSS-SDR]\n' + '\n'.join(f'{k}={v}' for k,v in cfg.items()) + '\n'

M1_CROSS_SIGNALS = ('1C','1D','B1')


def m1_cross_template(count=9, prns=None):
    """Centered 24 MS/s M1 recording spanning L1 and B1I, with user-selected PRNs."""
    prns = {} if prns is None else prns
    if not isinstance(prns,dict) or set(prns).difference(M1_CROSS_SIGNALS):
        raise ValueError('请按 L1 C/A、B1C 和 B1I 分别填写 PRN')
    pins = {sid:parse_prns(sid,prns.get(sid,'')) for sid in M1_CROSS_SIGNALS}
    shared = dict(center_mhz=1568.259, rate_hz=24_000_000, format='ibyte')
    cfg = parse(template(M1_CROSS_SIGNALS,1,shared=shared))
    cfg['Workbench.replay_profile'] = 'm1'
    if not 1 <= count <= 128:
        raise ValueError('通道数需在 1–128 之间')
    for sid, assigned in pins.items():
        cfg[f'Channels_{sid}.count'] = len(assigned) or count
    mapping = channels(cfg)
    cfg['Channels.in_acquisition'] = min(8,len(mapping))
    for sid in ('1C','B1'):
        cfg.update({f'Acquisition_{sid}.doppler_max':6000, f'Acquisition_{sid}.doppler_step':250})
    cfg.update({'Acquisition_1D.doppler_step':100, 'Tracking_1D.b1c_data_prompt_scale':4.0,
                'Tracking_1D.b1c_pilot_prompt_scale':1.0, 'PVT.elevation_mask':5,
                'PVT.iono_model':'OFF', 'PVT.trop_model':'OFF'})
    for sid, assigned in pins.items():
        group = [row['channel'] for row in mapping if row['signal']==sid]
        for channel_id, prn in zip(group,assigned):
            cfg[f'Channel{channel_id}.satellite'] = prn
    return '[GNSS-SDR]\n'+'\n'.join(f'{k}={v}' for k,v in cfg.items())+'\n'
