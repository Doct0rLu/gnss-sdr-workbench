import sys, unittest, tempfile, struct, time, json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

def vi(n):
    b=bytearray()
    while n>127: b.append((n&127)|128); n>>=7
    b.append(n); return bytes(b)
def integer(k,v): return vi(k<<3)+vi(v)
def double(k,v): return vi((k<<3)|1)+struct.pack('<d',v)
def blob(k,v): return vi((k<<3)|2)+vi(len(v))+v

class BackendTests(unittest.TestCase):
    def test_upstream_schema_and_defaults(self):
        msg=blob(1,b'G')+blob(2,b'1C')+integer(3,24)+integer(10,3000000)+integer(17,6000000)+double(13,47.5)+integer(18,1)
        row=list(server.decode(blob(1,msg)))[0]
        self.assertEqual((row['channel'],row['prn'],row['t'],row['cn0'],row['valid']),(0,24,2,47.5,True))
        self.assertIsNone(row['pseudorange'])
    def test_truncated_protobuf(self):
        with self.assertRaises(ValueError): list(server.decode(b'\x0a\x50a'))
    def test_log_classification_and_ansi(self):
        with tempfile.TemporaryDirectory() as d:
            r=server.Run(Path(d),{'started':time.time()})
            r.log('\x1b[32mWarning: loss of lock in channel 4\x1b[0m')
            self.assertEqual((r.logs[0]['level'],r.logs[0]['channel']),('WARN',4))
            self.assertNotIn('\x1b',r.logs[0]['text'])
    def test_event_signal_clock_ignores_stdout_arrival_time(self):
        with tempfile.TemporaryDirectory() as d:
            r=server.Run(Path(d),{'started':time.time()});r.signal_time=59
            r.acquisitions.append(dict(channel=4,prn=24,t=.25))
            r.log('Current receiver time: 1 s')
            r.log('Tracking of GPS L1 C/A signal started on channel 4 for satellite GPS PRN 24')
            self.assertEqual(r.events[-1]['t'],.25)
            r.log('Current receiver time: 1 min 2 s')
            r.log('Loss of lock in channel 4')
            self.assertEqual(r.events[-1]['t'],62)
    def test_nan_telemetry_is_not_json_nan(self):
        row=list(server.decode(blob(1,double(13,float('nan')))))[0]
        self.assertIsNone(row['cn0']);json.dumps(row,allow_nan=False)

    def test_live_history_delta_and_full_resync(self):
        with tempfile.TemporaryDirectory() as d:
            run = server.Run(Path(d), {'id': 'abc', 'started': time.time()})
            initial = run.snapshot(history_after='0')
            cursor = initial['history_cursor']
            run.sample(dict(channel=0, t=1, prn=4, valid=True))
            run.sample(dict(channel=0, t=1.1, prn=4, valid=True))
            run.sample(dict(channel=1, t=1, prn=26, valid=True))
            run.sample(dict(channel=0, t=1.1, prn=5, valid=True))
            update = run.snapshot(history_after=cursor)
            self.assertNotIn('history', update)
            self.assertEqual([row['prn'] for row in update['history_delta']['0']], [4, 5])
            self.assertEqual(update['history_delta'], run.snapshot()['history'])
            self.assertEqual(run.snapshot(history_after=update['history_cursor'])['history_delta'], {})
            self.assertEqual(run.snapshot(history_after='other:4')['history'], run.snapshot()['history'])

            for second in range(server.HISTORY_LIMIT + 1):
                run.sample(dict(channel=0, t=2+second, prn=5, valid=False))
            resynced = run.snapshot(history_after=cursor)
            self.assertNotIn('history_delta', resynced)
            self.assertEqual(len(resynced['history']['0']), server.HISTORY_LIMIT)
            self.assertEqual(resynced['history'], run.snapshot()['history'])

    def test_input_contract(self):
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'rx.exe';exe.write_bytes(b'test')
            iq=Path(d)/'iq.bin';iq.write_bytes(b'\0'*1000)
            base=dict(executable=str(exe),iq=str(iq),duration=1,config='[GNSS-SDR]\nSignalSource.implementation=File_Signal_Source\nSignalSource.item_type=ibyte\nSignalSource.sampling_frequency=100\n')
            server.APP.validate(base)
            for patch in [dict(duration=10),dict(duration=float('nan')),dict(iq='missing'),dict(config=base['config']+'PVT.dump_filename=C:/outside\n'),dict(config=base['config']+'SignalSource.seconds_to_skip=1\n')]:
                with self.assertRaises(ValueError): server.APP.validate(base|patch)
    def test_b3_channel_count_and_capture_bounds(self):
        self.assertEqual(server.signal_contract({'Channel.signal':'B3','Channels_B3.count':'14'}),('B3',14))
        with self.assertRaises(ValueError):server.signal_contract({'Channel.signal':'unsupported'})
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'rx.exe';exe.write_bytes(b'test');iq=Path(d)/'data.iq';iq.write_bytes(b'\0'*1000)
            cfg='[GNSS-SDR]\nChannel.signal=B3\nChannels_B3.count=14\nChannels.in_acquisition=2\nSignalSource.implementation=File_Signal_Source\nSignalSource.item_type=ibyte\nSignalSource.sampling_frequency=100\n'
            data=dict(executable=str(exe),iq=str(iq),duration=1,config=cfg,capture_channel=13)
            server.APP.validate(data)
            with self.assertRaises(ValueError):server.APP.validate(data|dict(capture_channel=14))

    def test_bounded_log_flood(self):
        with tempfile.TemporaryDirectory() as d:
            r=server.Run(Path(d),{'started':time.time()})
            begin=time.perf_counter()
            for n in range(100000): r.log('tracking channel 3 sample '+str(n))
            elapsed=time.perf_counter()-begin
            self.assertEqual((r.seq,len(r.logs)),(100000,3000))
            s=r.snapshot(1)
            self.assertTrue(s['log_gap']);self.assertEqual(len(s['logs']),600)
            print(f'100000 log records: {elapsed:.3f}s; retained={len(r.logs)}; response={len(json.dumps(s))} bytes')

if __name__=='__main__': unittest.main()
