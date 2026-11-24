import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import diagnostics as d
class DiagnosticsTests(unittest.TestCase):
    def test_full_l2c_search_grid_preview(self):
        import h5py
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p/'receiver.conf').write_text('[GNSS-SDR]\nGNSS-SDR.internal_fs_sps=4000000\n')
            with h5py.File(p/'acquisition_G_2S_ch_0_1_sat_3.mat','w') as f:
                f['sample_counter']=[80000]
                f['PRN']=[3]
                f['positive_acq']=[1]
                grid=f.create_dataset('acq_grid',(400,80000),dtype='f4',chunks=(1,1024))
                grid[321,73456]=12
                grid[320,73456]=3
            frame=d.acquisition(p,channel=0)['frame']
            self.assertEqual(frame['peak'],12)
            self.assertEqual(frame['delay'][80],73456)
            self.assertEqual(frame['profile'][80],1)
            self.assertEqual(frame['doppler_profile'][320],0.25)
            self.assertEqual(frame['heat'][321][73456//625],1)

    def test_dump_slice_search_and_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'receiver.conf').write_text('[GNSS-SDR]\nGNSS-SDR.internal_fs_sps=1000\n')
            with (p/'tracking_ch_0.dat').open('wb') as f:
                for n in range(10000):
                    r=[0]*24;r[7]=n;r[13]=.05;r[15]=.02;r[21]=24
                    f.write(d.RECORD.pack(*r))
            rows=d.tracking(p,0,2,8)['rows']
            self.assertLessEqual(len(rows),1600);self.assertTrue(all(2<=r['t']<8 for r in rows));self.assertEqual(rows[0]['prn'],24)
    def test_b3_tracking_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'receiver.conf').write_text('[GNSS-SDR]\nChannel.signal=B3\nGNSS-SDR.internal_fs_sps=24000000\nTracking_B3.dump_filename=./b3_tracking_ch_\n')
            row=[0]*24;row[7]=24000000;row[21]=19
            (p/'b3_tracking_ch_0.dat').write_bytes(d.RECORD.pack(*row))
            rows=d.tracking(p,0,0,2)['rows'];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['prn'],19);self.assertEqual(rows[0]['t'],1)

    def test_file_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            with self.assertRaises(ValueError):d.safe_file(p,'../outside')
    def test_bad_gsv_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'solution.nmea').write_text('$GPGSV,1,1,01,01,45,180,42*00\n')
            self.assertEqual(d.sky(p),[])

class TimeIndexTests(unittest.TestCase):
    def test_index_handles_append_nonmonotonic_time_and_partial_line(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);f=p/'logs.jsonl'
            f.write_text(''.join(json.dumps(dict(t=t,text=str(n)))+'\n' for n,t in enumerate([10,1,7,3])),encoding='utf-8')
            self.assertEqual([r['t'] for r in d.time_rows(p,'logs.jsonl',2,8)],[7,3])
            with f.open('a',encoding='utf-8') as out:out.write('{"t":4')
            self.assertEqual(len(d.time_rows(p,'logs.jsonl',2,8)),2)
            with f.open('a',encoding='utf-8') as out:out.write(',"text":"next"}\n')
            self.assertEqual([r['t'] for r in d.time_rows(p,'logs.jsonl',2,8)],[7,3,4])
    def test_capture_time_does_not_select_future_or_other_channel(self):
        import h5py,numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'receiver.conf').write_text('[GNSS-SDR]\nGNSS-SDR.internal_fs_sps=1000\n',encoding='utf-8')
            for ch,t in [(0,1),(0,3),(1,2)]:
                with h5py.File(p/f'acquisition_G_1C_ch_{ch}_{t}_sat_24.mat','w') as f:
                    for k,v in dict(sample_counter=t*1000,PRN=24,positive_acq=1).items():f[k]=np.array([v])
                    f['acq_grid']=np.array([[1.,2.],[3.,8.]])
            self.assertIsNone(d.acquisition(p,channel=0,at=.5)['frame'])
            self.assertEqual(d.acquisition(p,channel=0,at=2)['frame']['t'],1)
            self.assertEqual(d.acquisition(p,channel=1,at=2)['frame']['channel'],1)

    def test_time_index_tail_and_channel_filter(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);f=p/'events.jsonl'
            f.write_text(''.join(json.dumps(dict(t=n,channel=n%2))+'\n' for n in range(1000)),encoding='utf-8')
            rows=d.time_rows(p,'events.jsonl',0,1000,3,tail=True,channel=1)
            self.assertEqual([r['t'] for r in rows],[995,997,999])
