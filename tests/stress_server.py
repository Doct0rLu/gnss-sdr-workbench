"""Explicit test-only source; no IQ/receiver data. Serves on separate port."""
import sys,time,threading,tempfile
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

tmp=tempfile.TemporaryDirectory(prefix='gnss-workbench-stress-')
run=server.Run(Path(tmp.name),dict(id='00000000-000000-aaaaaa',status='running',started=time.time(),duration=60,
                                 fs=18000000,output=tmp.name,source='测试数据 · 高频日志压力检查',version='test'))
server.APP.active=run
def flood():
    for batch in range(1200):
        for n in range(1000): run.log(f'tracking channel {n%12} stress sample {batch*1000+n}')
        time.sleep(.05)
threading.Thread(target=flood,daemon=True).start()
print('TEST ONLY http://127.0.0.1:8766',flush=True)
ThreadingHTTPServer(('127.0.0.1',8766),server.Handler).serve_forever()
