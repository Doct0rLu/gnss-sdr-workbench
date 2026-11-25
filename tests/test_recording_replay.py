import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import diagnostics
import server
import signal_input
import signals


class RecordingReplayTests(unittest.TestCase):
    def test_two_synchronized_files_keep_distinct_paths(self):
        cfg=signals.parse(signals.template(['1C','1D','B1'],3,separate={'rate_hz':24000000,'format':'ibyte'}))
        cfg['SignalSource0.filename']='L1.iq'
        cfg['SignalSource1.filename']='B1I.iq'
        signals.synchronize_sources(cfg)
        self.assertEqual(cfg['SignalSource.implementation'],'Multichannel_File_Signal_Source')
        self.assertEqual([Path(x['path']).name for x in signal_input.sources(cfg)],['L1.iq','B1I.iq'])

    def test_separate_recording_uses_physical_input_rate(self):
        cfg=signals.parse(signals.template(['1C','1D'],12,separate={'rate_hz':24000000,'format':'ibyte'}))
        self.assertEqual(cfg['SignalSource.sampling_frequency'],'24000000')
        self.assertEqual(cfg['InputFilter.decimation_factor'],'3')
        self.assertEqual(cfg['GNSS-SDR.internal_fs_sps'],'8000000')
        self.assertEqual(len(signal_input.sources(cfg)),1)
        self.assertNotIn('Workbench.capture_center_hz',cfg)
        with tempfile.TemporaryDirectory() as folder:
            iq=Path(folder)/'m1.iq'
            iq.write_bytes(b'0123')
            Path(str(iq)+'.json').write_text(json.dumps(dict(bytes=4,datatype='ci8',config=dict(sample_rate_hz=24000000))))
            self.assertEqual(signal_input.recording_metadata(iq)['rate_hz'],24000000)
            exe=Path(folder)/'receiver.exe';exe.touch()
            data=dict(iq=str(iq),executable=str(exe),config=signals.template(['1C','1D']))
            with self.assertRaisesRegex(ValueError,'24 MS/s'):server.Workbench().validate(data)

    def test_startup_events_without_a_snapshot(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(server,'RUNS',Path(folder)):
            run='20261125-164107-6141be'
            (Path(folder)/run).mkdir()
            http=server.LocalServer(('127.0.0.1',0),server.Handler)
            t=threading.Thread(target=http.serve_forever);t.start()
            try:
                for kind in ('events','logs'):
                    with urllib.request.urlopen(f'http://127.0.0.1:{http.server_port}/api/inspect?run={run}&kind={kind}') as r:
                        self.assertEqual(json.load(r),[])
            finally:http.shutdown();t.join();http.server_close()

    def test_sky_reassignment_and_lock_loss_at_cursor(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            (path/'manifest.json').write_text(json.dumps(dict(channel_map=[dict(channel=1,signal='1D',system='C')])))
            events=[(.1,'C24 捕获成功'),(.15,'Tracking of B1C started on channel 1 for satellite PRN 24'),
                    (2,'Loss of lock in channel 1, satellite PRN 24'),(4,'C33 捕获成功')]
            (path/'events.jsonl').write_text(''.join(json.dumps(dict(t=t,channel=1,text=msg))+'\n' for t,msg in events))
            self.assertEqual(diagnostics.sky_at(path,0),[])
            self.assertEqual(diagnostics.sky_at(path,1)[0]['status'],'跟踪中')
            self.assertEqual(diagnostics.sky_at(path,3)[0]['status'],'已失锁')
            self.assertEqual(diagnostics.sky_at(path,4)[0]['prn'],33)
