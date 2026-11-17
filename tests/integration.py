"""Real receiver smoke test. Requires configured local.json and running server."""
import json,time,urllib.request,urllib.error,hashlib
from pathlib import Path
BASE='http://127.0.0.1:8765'
def api(path,data=None):
    req=urllib.request.Request(BASE+path,json.dumps(data).encode() if data is not None else None,{'Content-Type':'application/json'})
    return json.load(urllib.request.urlopen(req))
def await_end(timeout=60):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        s=api('/api/state')
        if s['meta']['status'] not in ('running','starting','stopping'): return s
        time.sleep(.2)
    raise AssertionError('receiver timeout; left running for inspection')
def main():
    results={}
    cfg=api('/api/defaults');cfg['duration']=60
    meta=api('/api/start',cfg);s=await_end()
    assert s['meta']['status']=='completed',s['meta']
    assert s['udp']>100 and s['decode_errors']==0 and s['signal_time']>59
    assert len(s['channels'])>=4 and len(s['positions'])>0
    p=Path(meta['output']);assert (p/'receiver.log').stat().st_size>0
    assert hashlib.sha256((p/'receiver.conf').read_bytes()).hexdigest()==meta['config_sha256']
    assert len((p/'telemetry.jsonl').read_text().splitlines())>100
    results['real_60s']={k:s[k] for k in ['signal_time','wall_elapsed','udp','decode_errors']}
    results['real_60s'].update(id=meta['id'],channels=len(s['channels']),positions=len(s['positions']),exit_code=s['meta']['exit_code'])
    cfg['duration']=30;cfg['config']=cfg['config'].replace('SignalSource.enable_throttle_control=false','SignalSource.enable_throttle_control=true')
    m=api('/api/start',cfg)
    try: api('/api/start',cfg);raise AssertionError('concurrent receiver allowed')
    except urllib.error.HTTPError as exc: assert exc.code==400
    time.sleep(3);api('/api/stop',{});st=await_end(30)
    assert st['meta']['status']=='stopped' and st['meta']['exit_code']==0,st['meta']
    assert 'Quit keystroke' in (Path(m['output'])/'receiver.log').read_text(encoding='utf-8')
    results['graceful_stop']=dict(id=m['id'],status=st['meta']['status'],exit_code=st['meta']['exit_code'],wall_elapsed=st['wall_elapsed'])
    for change in [dict(iq='missing'),dict(duration=999999),dict(config='invalid')]:
        try: api('/api/validate',cfg|change);raise AssertionError('invalid input allowed')
        except urllib.error.HTTPError as exc: assert exc.code==400
    results['input_errors']='passed'
    old=api('/api/state?run='+meta['id']);assert old['meta']['id']==meta['id'] and old['udp']>100
    results['history_replay']='passed'
    out=Path(__file__).resolve().parents[1]/'verification';out.mkdir(exist_ok=True)
    (out/'integration.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results,indent=2))
if __name__=='__main__': main()
