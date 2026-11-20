"""Signal identities and channel order from the bundled GNSS-SDR block factory."""
import re

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
 ('1D','C','北斗 B1C',1575.42,'BEIDOU_B1C_PCPS_Ambiguous_Acquisition','BEIDOU_B1C_DLL_PLL_VEML_Tracking','BEIDOU_B1C_Telemetry_Decoder',4e6),
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

def template(ids, count=8, fs=None):
    ids=list(dict.fromkeys(ids))
    if not ids or any(s not in CATALOG for s in ids):raise ValueError('请选择信号')
    if not 1<=int(count)<=128 or len(ids)*int(count)>128:raise ValueError('总通道数需在 1–128 之间')
    fs=int(fs or max(CATALOG[s]['fs'] for s in ids))
    if fs<=0:raise ValueError('采样率无效')
    # Same carrier uses one RF file; each other carrier receives an independent file.
    frequencies=list(dict.fromkeys(CATALOG[s]['mhz'] for s in ids));multi=len(frequencies)>1
    cfg={'GNSS-SDR.internal_fs_sps':fs,'GNSS-SDR.use_acquisition_resampler':'false','ControlThread.wait_for_flowgraph':'false'}
    if multi:cfg['GNSS-SDR.num_sources']=len(frequencies)
    for n,freq in enumerate(frequencies):
        suffix=str(n) if multi else '';src='SignalSource'+suffix
        cfg.update({src+'.implementation':'File_Signal_Source',src+'.filename':f'INPUT-RF{n}.bin',src+'.item_type':'ibyte',src+'.sampling_frequency':fs,src+'.samples':0,src+'.repeat':'false',src+'.enable_throttle_control':'false',
          'SignalConditioner'+suffix+'.implementation':'Signal_Conditioner','DataTypeAdapter'+suffix+'.implementation':'Ibyte_To_Complex','InputFilter'+suffix+'.implementation':'Pass_Through','InputFilter'+suffix+'.IF':0,'InputFilter'+suffix+'.input_item_type':'gr_complex','Resampler'+suffix+'.implementation':'Pass_Through'})
    for sid in ids:
        cfg['Channels_'+sid+'.count']=int(count);cfg['Channels_'+sid+'.RF_channel_ID']=frequencies.index(CATALOG[sid]['mhz'])
        item=CATALOG[sid]
        for base,key in [('Acquisition','acquisition'),('Tracking','tracking'),('TelemetryDecoder','telemetry')]:cfg[f'{base}_{sid}.implementation']=item[key]
        for key,value in {'item_type':'gr_complex','doppler_max':10000,'doppler_step':500,'pfa':.0001,'blocking':'true','coherent_integration_time_ms':20 if sid=='2S' else 4 if sid=='1B' else 10 if sid in ('1S','1D') else 1}.items():cfg[f'Acquisition_{sid}.'+key]=value
        for key,value in {'item_type':'gr_complex','pll_bw_hz':35,'dll_bw_hz':2,'dump':'true','dump_mat':'false','dump_filename':f'./tracking_{sid}_ch_'}.items():cfg[f'Tracking_{sid}.'+key]=value
        if sid in ('1S','1D'):cfg[f'Acquisition_{sid}.acquire_pilot']='true';cfg[f'Tracking_{sid}.track_pilot']='true'
    cfg.update({'Channels.in_acquisition':min(2,len(ids)*int(count)),'Channel.signal':ids[0],'Observables.implementation':'Hybrid_Observables','PVT.implementation':'RTKLIB_PVT','PVT.positioning_mode':'Single','PVT.output_rate_ms':100,'PVT.display_rate_ms':1000,'PVT.output_enabled':'true','PVT.output_path':'.','PVT.nmea_dump_filename':'./solution.nmea','PVT.flag_nmea_tty_port':'false','PVT.flag_rtcm_tty_port':'false','PVT.flag_rtcm_server':'false'})
    return '[GNSS-SDR]\n'+'\n'.join(f'{k}={v}' for k,v in cfg.items())+'\n'
