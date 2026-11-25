"""Exercise a native real-int16 fixture and verify the bytes after its file-source valve."""
import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_receiver
import signals


def region_hash(path, start, size):
    with path.open('rb') as stream:
        stream.seek(start)
        h=hashlib.sha256()
        while size:
            buf=stream.read(min(1024*1024,size))
            if not buf:
                raise EOFError(path)
            h.update(buf)
            size-=len(buf)
        return h.hexdigest()


def check(exe, fixture, output, name, params, offset, count):
    directory=output/name
    directory.mkdir(parents=True,exist_ok=False)
    options=signals.parse(fixture.read_text(encoding='utf-8-sig'))
    source=Path(options['SignalSource.filename'])
    options.update({'SignalSource.dump':'true','SignalSource.dump_filename':'./valve-output.bin'},**params)
    (directory/'receiver.conf').write_text('[GNSS-SDR]\n'+''.join(f'{k}={v}\n' for k,v in options.items()),encoding='utf8')
    with (directory/'receiver.log').open('wb') as log:
        run=subprocess.run(native_receiver.command(exe,directory),cwd=directory,env=native_receiver.environment(exe),
                           stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                           creationflags=subprocess.CREATE_NO_WINDOW,timeout=35)
    run.check_returncode()
    native=next(directory.glob('gnss-sdr.*.log')).read_text(encoding='utf8',errors='replace')
    assert re.findall(r'Stopping receiver, (\d+) samples processed',native)==[str(count)],name
    capture=directory/'valve-output.bin'
    assert capture.stat().st_size==count*2,(name,capture.stat().st_size,count*2)
    assert region_hash(capture,0,count*2)==region_hash(source,offset*2,count*2),name
    print(name,count,'items, output matches input',flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--exe',required=True,type=Path)
    p.add_argument('--fixture',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    options=signals.parse(args.fixture.read_text(encoding='utf-8-sig'))
    assert options['SignalSource.item_type']=='short' and options['SignalSource.repeat']=='false'
    source=Path(options['SignalSource.filename'])
    total=source.stat().st_size//2
    rate=int(options['SignalSource.sampling_frequency'])
    for name,params,offset,count in [
        ('exact',{'SignalSource.samples':total},0,total),
        ('implicit',{'SignalSource.samples':0},0,total),
        ('oversized',{'SignalSource.samples':total+1},0,total),
        ('partial',{'SignalSource.samples':total//2},0,total//2),
        ('offset',{'SignalSource.header_size':3,'SignalSource.seconds_to_skip':.125,'SignalSource.samples':total},
         3+rate//8,total-3-rate//8)]:
        check(args.exe.resolve(),args.fixture,args.output.resolve(),name,params,offset,count)


if __name__=='__main__':
    main()
