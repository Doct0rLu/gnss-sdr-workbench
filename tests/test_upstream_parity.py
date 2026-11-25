from pathlib import Path
import tempfile
import unittest

import diagnostics
import linux_receiver
import server


def sentence(body):
    checksum = 0
    for byte in body.encode('ascii'):
        checksum ^= byte
    return f'${body}*{checksum:02X}\n'


class UpstreamParityTests(unittest.TestCase):
    def test_sky_epoch_retains_both_prn_08_across_midnight(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            lines = ['GPRMC,235959.00,A,,,,,,,151221', 'GPGGA,235959.00',
                     'GPGSV,1,1,01,08,11,123,40', 'BDGSV,1,1,01,08,22,234,41',
                     'GPRMC,000001.00,A,,,,,,,161221', 'GPGGA,000001.00',
                     'BDGSV,1,1,01,25,33,345,42']
            (path/'solution.nmea').write_text(''.join(map(sentence,lines)),encoding='ascii')
            before = diagnostics.sky(path,'2021-Dec-15 23:59:59.000000')
            self.assertEqual({(s['system'],s['prn']) for s in before},{('G',8),('C',8)})
            self.assertEqual([s['prn'] for s in diagnostics.sky(path)],[25])
            self.assertEqual(diagnostics.sky(path,'2021-Dec-15 23:59:58.000000'),[])

    def test_first_fix_before_periodic_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = server.Run(Path(tmp),{})
            run.log('Current receiver time: 27 s')
            run.log('First position fix at 2021-Dec-15 03:06:00.120000 UTC is Lat = 40.01 [deg], Long = -105.244 [deg], Height = 1620.91 [m], with GDOP = 4.44803')
            run.log('Position at 2021-Dec-15 03:06:01.000000 UTC using 6 observations is Lat = 40.009969 [deg], Long = -105.244312 [deg], Height = 1618.95 [m]')
            self.assertTrue(run.positions[0]['first_fix'])
            self.assertIsNone(run.positions[0]['observations'])
            self.assertEqual(run.positions[0]['t'],27)
            self.assertEqual(run.positions[1]['observations'],6)

    def test_native_input_mapping_keeps_file_bytes_and_sample_offsets(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            src=base/'采样.iq'
            src.write_bytes(bytes(range(32)))
            options={'SignalSource.filename':'/recordings/input.iq','SignalSource.implementation':'File_Signal_Source',
                     'SignalSource.item_type':'ishort','SignalSource.sampling_frequency':'4',
                     'SignalSource.header_size':'2','SignalSource.seconds_to_skip':'0.5'}
            row=linux_receiver.raw_inputs(options,base,[dict(path=str(src))],'')[0]
            self.assertEqual(row['guest_name'],'/recordings/input.iq')
            self.assertTrue(src.samefile(row['path']))
            self.assertEqual(row['byte_offset'],12)
            self.assertEqual(src.read_bytes(),bytes(range(32)))
