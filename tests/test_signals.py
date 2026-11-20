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

if __name__=='__main__':unittest.main()
