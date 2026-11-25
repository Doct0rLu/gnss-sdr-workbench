import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import diagnostics, server, signal_input

class InputTests(unittest.TestCase):
    def test_real_and_complex_byte_lengths_and_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);exe=p/'rx.exe';exe.write_bytes(b'test')
            for kind,fmt in signal_input.FORMATS.items():
                with self.subTest(kind=kind):
                    source=p/'signal.bin';values=np.arange(10000*fmt['components'])%31-15
                    source.write_bytes(values.astype(fmt['dtype']).tobytes())
                    config=f'[GNSS-SDR]\nSignalSource.implementation=File_Signal_Source\nSignalSource.item_type={kind}\nSignalSource.sampling_frequency=1000\nDataTypeAdapter.implementation={fmt["adapter"]}\nDataTypeAdapter.item_type={fmt["filter_type"]}\nInputFilter.implementation=Freq_Xlating_Fir_Filter\nInputFilter.input_item_type={fmt["filter_type"]}\n'
                    (p/'receiver.conf').write_text(config,encoding='utf-8')
                    (p/'manifest.json').write_text(json.dumps(dict(iq=str(source),fs=1000)),encoding='utf-8')
                    data=dict(executable=str(exe),iq=str(source),duration=10,config=config)
                    server.APP.validate(data)
                    with self.assertRaises(ValueError):server.APP.validate(data|dict(duration=10.001))
                    d=diagnostics.iq(p,1)
                    self.assertEqual(d['t'],1)
                    self.assertEqual(d['i'][0],float(values[1000*fmt['components']]))
                    self.assertEqual(d['sample_bytes'],source.stat().st_size//10000)
                    self.assertEqual(len(d['q']),0 if fmt['components']==1 else 256)
                    self.assertEqual(d['samples'],8192);self.assertEqual(len(d['spectrum']),512)

    def test_real_fft_frequency_and_integer_rails(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);source=p/'real.bin';a=np.sin(2*np.pi*np.arange(8192)*1024/8192).astype('<f4');source.write_bytes(a.tobytes())
            (p/'receiver.conf').write_text('SignalSource.item_type=float\n',encoding='utf-8')
            (p/'manifest.json').write_text(json.dumps(dict(iq=str(source),fs=8192)),encoding='utf-8')
            d=diagnostics.iq(p,0);peaks=np.argsort(d['spectrum'])[-2:]
            self.assertTrue(all(abs(abs(d['mhz'][i])*1e6-1024)<20 for i in peaks))
            self.assertAlmostEqual(d['rms'],2**-.5,places=6);self.assertIsNone(d['clipped'])
            (p/'receiver.conf').write_text('SignalSource.item_type=short\n',encoding='utf-8')
            source.write_bytes(np.array([-32768,32767]*4096,dtype='<i2').tobytes())
            self.assertEqual(diagnostics.iq(p,0)['clipped'],100)

    def test_real_chain_mismatch(self):
        fmt=signal_input.layout({'SignalSource.item_type':'short'})
        with self.assertRaises(ValueError):signal_input.validate_chain({'DataTypeAdapter.implementation':'Ibyte_To_Complex'},fmt)

    def test_source_count_keeps_tail_in_sample_units(self):
        for kind in signal_input.FORMATS:
            fmt=signal_input.layout({'SignalSource.item_type':kind})
            self.assertEqual(signal_input.source_count(fmt,3,1000,3000*fmt['sample_bytes']),2900*fmt['source_items'])
            self.assertEqual(signal_input.source_count(fmt,2,1000,3000*fmt['sample_bytes']),2000*fmt['source_items'])

    def test_native_short_end_includes_last_whole_sample(self):
        fmt=signal_input.layout({'SignalSource.item_type':'short'})
        self.assertEqual(signal_input.source_count(fmt,3,1000,6001,full_int16_eof=True),3000)
        self.assertEqual(signal_input.source_count(fmt,2,1000,6001,full_int16_eof=True),2000)
        self.assertEqual(signal_input.source_count(fmt,3,1000,6001),2900)
        iq=signal_input.layout({'SignalSource.item_type':'ishort'})
        self.assertEqual(signal_input.source_count(iq,3,1000,12000,full_int16_eof=True),5800)

    def test_download_offsets_keep_original_bytes(self):
        import threading, urllib.request
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'20261117-000000-abcdef';run.mkdir()
            source=root/'signal.bin';source.write_bytes(bytes(range(256))*100)
            (run/'manifest.json').write_text(json.dumps(dict(iq=str(source),fs=1000)),encoding='utf-8')
            http=server.LocalServer(('127.0.0.1',0),server.Handler)
            thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            try:
                with patch.object(server,'RUNS',root):
                    for kind in signal_input.FORMATS:
                        (run/'receiver.conf').write_text('SignalSource.item_type='+kind+'\n',encoding='utf-8')
                        width=signal_input.layout({'SignalSource.item_type':kind})['sample_bytes']
                        for route in ('raw-input','raw-iq'):
                            with urllib.request.urlopen(f'http://127.0.0.1:{http.server_port}/api/{route}?run={run.name}&t=1&count=16') as r:
                                self.assertEqual(r.read(),source.read_bytes()[1000*width:1016*width])
            finally:http.shutdown();http.server_close();thread.join()

if __name__=='__main__':unittest.main()
