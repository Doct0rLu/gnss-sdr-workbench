import json,time,urllib.request,urllib.error
from pathlib import Path
B='http://127.0.0.1:8765'
def api(route,data=None):
    return json.load(urllib.request.urlopen(urllib.request.Request(B+route,json.dumps(data).encode() if data is not None else None,{'Content-Type':'application/json'})))
cfg=api('/api/defaults');cfg['duration']=30;cfg['capture_channel']=0
cfg['config']=cfg['config'].replace('SignalSource.enable_throttle_control=false','SignalSource.enable_throttle_control=true')
old=api('/api/start',cfg);time.sleep(1)
bad=cfg|{'duration':999999}
try:api('/api/restart',bad);raise AssertionError('invalid restart')
except urllib.error.HTTPError as e:assert e.code==400
assert api('/api/state')['meta']['id']==old['id']
cfg['config']=cfg['config'].replace('SignalSource.enable_throttle_control=true','SignalSource.enable_throttle_control=false').replace('Tracking_1C.pll_bw_hz=40','Tracking_1C.pll_bw_hz=35')
new=api('/api/restart',cfg)
assert new['id']!=old['id'] and new['restarted_from']==old['id']
old_snapshot=api('/api/state?run='+old['id']);assert old_snapshot['meta']['status']=='stopped'
deadline=time.monotonic()+45
while time.monotonic()<deadline:
    s=api('/api/state')
    if s['meta']['status'] not in ('running','stopping','starting'):break
    time.sleep(.2)
assert s['meta']['status']=='completed'
assert 'Tracking_1C.pll_bw_hz=35' in (Path(new['output'])/'receiver.conf').read_text(encoding='utf-8')
prefix='/api/inspect?run='+new['id']+'&kind='
trk=api(prefix+'tracking&channel=0&start=0&end=30');assert len(trk['rows'])>10 and len(trk['rows'])<=1600
assert all(0<=r['t']<30 for r in trk['rows'])
acq=api(prefix+'acquisition');assert acq['frame'] and acq['frame']['peak']>0
assert abs(max(acq['frame']['profile'])-1)<1e-6
for frame in acq['files']:assert api(prefix+'acquisition&file='+frame['name'])['frame']
iq=api(prefix+'iq&t=1');assert iq['samples']==8192 and len(iq['spectrum'])==512
sky=api(prefix+'sky');assert len(sky)>=4
files=api(prefix+'files');assert any(f['name'].endswith('.mat') for f in files)
with urllib.request.urlopen(B+'/api/file?run='+new['id']+'&name=tracking_ch_0.dat') as response:assert response.status==200 and len(response.read(112))==112
result=dict(old_run=old['id'],new_run=new['id'],restart='passed',config_change='passed',invalid_restart='rejected_before_stop',status=s['meta']['status'],signal_time=s['signal_time'],acquisition_successes=len(s['acquisitions']),capture_frames=len(acq['files']),tracking_records=trk['records'],slice_points=len(trk['rows']),sky_satellites=len(sky),input_complex_samples=iq['samples'],files=len(files))
out=Path(__file__).resolve().parents[1]/'verification/integration-v02.json';out.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
