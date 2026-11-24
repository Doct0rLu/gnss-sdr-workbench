import sys,unittest,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import signals,signal_input,diagnostics,server

class SignalTests(unittest.TestCase):
    def test_every_signal_template_and_native_order(self):
        self.assertEqual(len(signals.CATALOG),17)
        for sid in signals.CATALOG:
            cfg=signals.parse(signals.template([sid],1))
            self.assertEqual(signals.channels(cfg)[0]['signal'],sid)
            self.assertEqual(cfg[f'TelemetryDecoder_{sid}.implementation'],signals.CATALOG[sid]['telemetry'])
        cfg=signals.parse(signals.template(['S1','1B','1C','B3'],2))
        rows=signals.channels(cfg)
        self.assertEqual([r['signal'] for r in rows],['1C','1C','1B','1B','B3','B3','S1','S1'])
        self.assertEqual(len(signal_input.sources(cfg)),2)
        self.assertEqual([r['rf_channel'] for r in rows],[0,0,0,0,1,1,0,0])

    def test_per_channel_rf_and_role(self):
        cfg=signals.parse(signals.template(['1C','L5'],1))
        cfg['Channel1.RF_channel_ID']='0';cfg['Tracking_L51.implementation']='GPS_L5_DLL_PLL_Tracking'
        self.assertEqual(signals.channel(cfg,1)['rf_channel'],0)
        self.assertEqual(signals.role(cfg,'Tracking','L5',1),'Tracking_L51')
        with self.assertRaises(ValueError):signals.channels({'Channels_bad.count':'1'})

    def test_mixed_tracking_prefix_and_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);cfg=signals.template(['1C','1B'],1,4000000)
            (p/'receiver.conf').write_text(cfg,encoding='utf-8')
            (p/'manifest.json').write_text(json.dumps(dict(duration=3)),encoding='utf-8')
            for ch,sid in [(0,'1C'),(1,'1B')]:
                r=[0]*24;r[7]=4000000;r[21]=ch+1
                (p/f'tracking_{sid}_ch_{ch}.dat').write_bytes(diagnostics.RECORD.pack(*r))
                d=diagnostics.tracking(p,ch,0,2)
                self.assertEqual(d['signal'],sid);self.assertEqual(d['rows'][0]['t'],1)
            self.assertEqual(len(diagnostics.timeline(p)['channels']),2)

    def test_multi_source_formats_and_raw_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);a=p/'a.bin';b=p/'b.bin';a.write_bytes(b'\0'*800);b.write_bytes(b'\0'*1600)
            cfg=signals.parse(signals.template(['1C','L5'],1,100))
            cfg.update({'SignalSource1.item_type':'ishort','DataTypeAdapter1.implementation':'Ishort_To_Complex'})
            data=dict(iq=str(a),inputs=[dict(path=str(a)),dict(path=str(b))])
            items=signal_input.sources(cfg,data)
            self.assertEqual([r['layout']['sample_bytes'] for r in items],[2,4])
            (p/'manifest.json').write_text(json.dumps(dict(inputs=[{k:v for k,v in x.items() if k not in ('options','layout')} for x in items])),encoding='utf-8')
            (p/'receiver.conf').write_text('[GNSS-SDR]\n',encoding='utf-8')
            item,fmt=diagnostics.input_source(p,1)
            self.assertEqual(Path(item['path']),b.resolve());self.assertEqual(fmt['sample_bytes'],4)

    def test_shared_m1_input_and_band_edges(self):
        capture = dict(center_mhz=1568.259, rate_hz=24_000_000, format='ishort')
        ids = ['1C', 'B1', '1D']
        cfg = signals.parse(signals.template(ids, 6, shared=capture))
        self.assertEqual(cfg['GNSS-SDR.internal_fs_sps'], '8000000')
        self.assertEqual([cfg[f'Channels_{s}.RF_channel_ID'] for s in ids], ['0','1','0'])
        sources = signal_input.sources(cfg, dict(iq='shared.iq', inputs=[{}, {'path':'old.iq'}]))
        self.assertEqual(sources[0]['path'],sources[1]['path'])
        for source,offset in zip(sources,[7161000,-7161000]):
            options = source['options']
            self.assertEqual(int(options['InputFilter.IF']), offset)
            self.assertEqual(options['InputFilter.decimation_factor'],'3')
            self.assertEqual(options['InputFilter.bw'],'2600000')
            signal_input.validate_chain(options,source['layout'])
        with self.assertRaisesRegex(ValueError,'超出录制带宽'):
            signals.template(ids,shared=dict(capture,center_mhz=1575.42))
        with self.assertRaisesRegex(ValueError,'IQ 格式'):
            signals.template(ids,shared=dict(capture,format='short'))
        with self.assertRaisesRegex(ValueError,'整数倍'):
            signals.template(ids,fs=9_000_000,shared=capture)

    def test_b1c_profiles_and_shipped_templates(self):
        for profile,name in [('narrow','1D'),('wide','1D-qmboc')]:
            generated = signals.template(['1D'],8,b1c_profile=profile)
            self.assertEqual(generated,(Path(signals.__file__).parent/'templates/signals'/f'{name}.conf').read_text(encoding='utf8'))
            cfg=signals.parse(generated)
            enabled='true' if profile=='wide' else 'false'
            self.assertEqual(cfg['Acquisition_1D.qmboc'],enabled)
            self.assertEqual(cfg['Tracking_1D.qmboc'],enabled)
            if profile=='narrow':
                self.assertEqual(cfg['Tracking_1D.pll_bw_hz'],'10')
                self.assertEqual(cfg['Tracking_1D.dll_bw_narrow_hz'],'0.2')
                self.assertEqual(cfg['Acquisition_1D.doppler_step'],'50')
        with self.assertRaises(ValueError):
            signals.template(['1D'],fs=8_000_000,b1c_profile='wide')

    def test_m1_replay_profiles_and_blind_search(self):
        bands = [('1D', 8_000_000, 3, 50, 10, 0.5), ('2S', 4_000_000, 6, 25, 6, 0.2),
                 ('L5', 24_000_000, 1, 250, 12, 0.5)]
        for sid, internal, decimation, step, pll, dll in bands:
            with self.subTest(signal=sid):
                text = signals.m1_template(sid)
                shipped = Path(signals.__file__).parent / 'templates/signals' / f'm1-{sid}.conf'
                self.assertEqual(text, shipped.read_text(encoding='utf8'))
                cfg = signals.parse(text)
                self.assertFalse(any(k.endswith('.satellite') for k in cfg))
                self.assertEqual(int(cfg['GNSS-SDR.internal_fs_sps']), internal)
                self.assertEqual(int(cfg['SignalSource.sampling_frequency']), 24_000_000)
                self.assertEqual(int(cfg.get('InputFilter.decimation_factor', 1)), decimation)
                self.assertEqual(int(cfg[f'Acquisition_{sid}.doppler_step']), step)
                self.assertEqual(float(cfg[f'Tracking_{sid}.pll_bw_hz']), pll)
                self.assertEqual(float(cfg[f'Tracking_{sid}.dll_bw_hz']), dll)
                if sid in ('2S','L5'):
                    self.assertEqual(cfg['PVT.iono_model'], 'OFF')
                    self.assertEqual(cfg['PVT.trop_model'], 'OFF')
                    self.assertEqual(cfg['PVT.elevation_mask'], '5')
                self.assertEqual(len(signals.channels(cfg)), 12 if sid=='2S' else 9)
                known = signals.parse(signals.m1_template(sid, prns='7，2  6'))
                self.assertEqual(len(signals.channels(known)), 3)
                self.assertEqual([known[f'Channel{n}.satellite'] for n in range(3)], ['7','2','6'])
        self.assertNotIn('Tracking_1D.b1c_data_prompt_scale', signals.parse(signals.template(['1D'])))
        self.assertEqual(signals.parse(signals.template(['2S']))['Tracking_2S.pll_bw_hz'], '6')
        self.assertEqual(signals.parse(signals.template(['L5']))['Acquisition_L5.pfa'], '0.0001')

    def test_shared_input_synchronization_and_per_signal_assignments(self):
        cfg=signals.parse(signals.m1_cross_template(3,{'1D':'25 26','B1':'3','1C':'6 8'}))
        self.assertEqual(cfg['GNSS-SDR.num_sources'],'1')
        self.assertEqual(cfg['SignalSource.implementation'],'Multichannel_File_Signal_Source')
        self.assertEqual(cfg['SignalSource.total_channels'],cfg['SignalSource.RF_channels'])
        self.assertEqual([r['signal'] for r in signals.channels(cfg)],['1C','1C','B1','1D','1D'])
        self.assertEqual([cfg[f'Channel{n}.satellite'] for n in range(5)],['6','8','3','25','26'])
        sources=signal_input.sources(cfg,{'iq':'sample.iq','inputs':[{'path':'cached.iq'}]})
        self.assertEqual([src['filename_key'] for src in sources],['SignalSource.filename0','SignalSource.filename1'])
        self.assertEqual([src['options']['InputFilter.IF'] for src in sources],['7161000','-7161000'])
        self.assertEqual(sources[0]['path'],sources[1]['path'])
        self.assertTrue(sources[0]['path'].endswith('sample.iq'))
        self.assertFalse(any(k.endswith('.satellite') for k in signals.parse(signals.m1_cross_template())))
        with self.assertRaises(ValueError):signals.m1_cross_template(50)
        with self.assertRaises(ValueError):signals.m1_cross_template(prns={'2S':'4'})
        regular=signals.parse(signals.template(['1C','B1']))
        self.assertEqual(regular['GNSS-SDR.num_sources'],'2')
        legacy=dict(regular)
        legacy['Workbench.capture_center_hz']='1568259000'
        signals.synchronize_sources(legacy)
        self.assertEqual(int(legacy['SignalSource.total_channels']),2)
        self.assertNotIn('SignalSource0.implementation',legacy)
        self.assertIn('InputFilter1.implementation',legacy)

    def test_standard_l2c_24m_capture(self):
        cfg=signals.parse(signals.template(['2S'],12,shared=dict(rate_hz=24_000_000,center_mhz=1227.60)))
        self.assertEqual(cfg['GNSS-SDR.internal_fs_sps'],'4000000')
        self.assertEqual(cfg['InputFilter.decimation_factor'],'6')
        self.assertEqual(cfg['Acquisition_2S.doppler_step'],'25')
        self.assertNotIn('PVT.iono_model',cfg)

    def test_m1_assignment_validation(self):
        for text in ('0', '1 33', '1,1', '1,2a', '-1', '2.5'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                signals.m1_template('2S', prns=text)
        with self.assertRaises(ValueError):
            signals.m1_template('1D', prns='64')
        with self.assertRaises(ValueError):
            signals.m1_template('1C')

    def test_signal_stages_and_pvt_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            rows=signals.channels(signals.parse(signals.template(['1C','1D'],2)))
            run=server.Run(path,dict(started=0,channel_map=rows))
            run.record_stage(2,25,'acquired')
            run.log('Tracking of Beidou B1CP signal started on channel 2 for satellite Beidou PRN 25')
            run.log('Beidou B1CP secondary code locked in channel 2 for satellite Beidou PRN 25')
            stage=run.stage_summary()
            self.assertEqual(stage['signals'][1]['tracking'],['C25'])
            self.assertEqual(stage['signals'][1]['decoded'],[])
            self.assertIsNone(stage['pvt'])
            run.log('New BeiDou B-CNAV1 ephemeris in channel 2 from satellite Beidou PRN 25')
            self.assertEqual(run.stage_summary()['signals'][1]['decoded'],['C25'])
            native=path/'gnss-sdr.test.log'
            native.write_bytes(b'New BeiDou B-CNAV1 ephemeris from PRN 26 in channel 3')
            self.assertEqual(run.stage_summary()['signals'][1]['decoded'],['C25'])
            with native.open('ab') as output: output.write(b' with CN0=41 dB-Hz\n')
            self.assertEqual(run.stage_summary()['signals'][1]['decoded'],['C25','C26'])
            def sentence(body):
                checksum=0
                for c in body: checksum ^= ord(c)
                return f'${body}*{checksum:02X}\r\n'
            gsa=lambda talker,prn: sentence(talker+'GSA,A,3,'+prn+','*12+'1.6,0.8,1.4')
            (path/'solution.nmea').write_bytes((gsa('GP','01')+sentence('GPGGA,120000')+
                gsa('BD','25')+gsa('GL','66')+'$GPGSA,A,3,12,,,,,,,,,,,,0,0,0*XX\n').encode())
            self.assertEqual(run.stage_summary()['pvt'],['C25','R02'])

if __name__=='__main__':unittest.main()
