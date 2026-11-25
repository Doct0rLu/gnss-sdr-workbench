"""Collect acquisition, tracking and CNAV evidence from l5_repeat.py runs."""
import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter,defaultdict
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import diagnostics
import signals


def json_lines(path):
    with path.open(encoding='utf8') as stream:
        for line in stream:
            yield json.loads(line)


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def read_run(folder, page_file=None):
    cfg=signals.parse((folder/'receiver.conf').read_text(encoding='utf8'))
    channels={int(cfg[f'Channel{i}.satellite']):i for i in range(int(cfg['Channels_L5.count']))}
    xml=folder/'gps_cnav_ephemeris.xml'
    eph={int(x.text) for x in ET.parse(xml).findall('.//item/second/PRN')} if xml.is_file() else set()
    native=next(folder.glob('gnss-sdr.*.log')).read_text(encoding='utf8',errors='replace')
    log=(folder/'receiver.log').read_text(encoding='utf8',errors='replace')
    valid={row['prn'] for row in json_lines(folder/'telemetry.jsonl') if row['valid']}
    if (folder/'snapshot.json').is_file():
        snap=json.loads((folder/'snapshot.json').read_text(encoding='utf8'))
        valid={int(sv[1:]) for row in snap['stages']['signals'] for sv in row['valid_tracking']}
    acquired=defaultdict(list)
    for r in json_lines(folder/'acquisitions.jsonl'):
        acquired[r['prn']].append([r['acq_samples'],r['acq_delay'],r['acq_doppler']])
    total=Counter(int(prn) for prn in re.findall(r'Successful acquisition in channel \d+ for satellite G (\d+)\b',native))
    rows={}
    for prn,ch in channels.items():
        assert total[prn]==len(acquired[prn]),(folder.name,prn,'AcquisitionMonitor/log count mismatch')
        t=folder/(cfg['Tracking_L5.dump_filename']+str(ch)+'.dat')
        with t.open('rb') as f:
            first=diagnostics.RECORD.unpack(f.read(diagnostics.RECORD.size))
            f.seek(-diagnostics.RECORD.size,2)
            last=diagnostics.RECORD.unpack(f.read(diagnostics.RECORD.size))
        assert first[21]==prn and last[21]==prn
        sync=re.findall(rf'Successful frame synchronization in channel {ch} .*?GPS PRN 0*{prn}\b.*?at sample_counter=(\d+)',native)
        rows[prn]=dict(first_or_reacquisition=sorted(acquired[prn]),tracking_first=first[7],tracking_last=last[7],
                       tracking_rows=t.stat().st_size//diagnostics.RECORD.size,valid_symbol=prn in valid,
                       loss_of_lock=len(re.findall(rf'Loss of lock in channel {ch}, satellite GPS PRN 0*{prn}\b',native)),
                       secondary_locks=len(re.findall(rf'secondary code locked in channel {ch} for satellite GPS PRN 0*{prn}\b',native)),
                       frame_decoder_symbol_counters=list(map(int,sync)),ephemeris=prn in eph)
    if page_file and page_file.is_file():
        for row in rows.values():
            row['pages']=[]
        for page in json_lines(page_file):
            assert page['page_prn']==page['prn']
            rows[page['prn']]['pages'].append([page['tow'],page['mt']])
    fix=re.search(r'First position fix at (.+?) UTC',log)
    return dict(prns=rows,first_fix_utc=fix[1] if fix else None,config_sha256=sha(folder/'receiver.conf'),
                nmea_sha256=sha(folder/'solution.nmea'),ephemeris_xml_sha256=sha(xml) if eph else None)


def analyze(root):
    folders=sorted(p for p in root.glob('??-*') if p.is_dir())
    digests=json.loads((root/'digests.json').read_text())
    runs={p.name:read_run(p,p.with_suffix('.pages.jsonl')) for p in folders}
    assert all(r['config_sha256']==digests['config'] for r in runs.values())
    return dict(digests=digests,runs=runs)


def tracking_prefixes(root):
    folders=sorted(p for p in root.glob('??-*') if p.is_dir())
    cfg=signals.parse((folders[0]/'receiver.conf').read_text(encoding='utf8'))
    out={}
    for ch in range(int(cfg['Channels_L5.count'])):
        name=cfg['Tracking_L5.dump_filename']+str(ch)+'.dat'
        blobs=[(p/name).read_bytes() for p in folders]
        shortest=min(map(len,blobs))
        assert all(len(b)%diagnostics.RECORD.size==0 for b in blobs)
        out[cfg[f'Channel{ch}.satellite']]=dict(common_region_equal=len({b[:shortest] for b in blobs})==1,
               rows_by_run={p.name:len(b)//diagnostics.RECORD.size for p,b in zip(folders,blobs)})
    return out


def main():
    p=argparse.ArgumentParser()
    p.add_argument('root',type=Path)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    result={case:analyze(args.root/case) for case in ('baseline','deterministic','pages')}
    result['deterministic']['tracking_prefixes']=tracking_prefixes(args.root/'deterministic')
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


if __name__=='__main__':
    main()
