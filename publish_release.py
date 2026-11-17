"""Publish the reviewed source and prebuilt assets to the authenticated user's GitHub."""
import argparse,json,os,shutil,subprocess,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def main():
    p=argparse.ArgumentParser();p.add_argument('--name',default='gnss-sdr-workbench');a=p.parse_args()
    gh=shutil.which('gh') or str(ROOT/'.build-tools/bin/gh.exe')
    env=dict(os.environ)
    if not env.get('HTTPS_PROXY'):
        proxy=urllib.request.getproxies().get('https')
        if proxy:env['HTTPS_PROXY']=proxy
    def run(args,capture=False):return subprocess.run(args,cwd=ROOT,env=env,check=True,text=True,encoding="utf-8",capture_output=capture)
    run([gh,'auth','status'])
    owner=run([gh,'api','user','--jq','.login'],True).stdout.strip();repo=owner+'/'+a.name
    files=[ROOT/'release'/name for name in ['GNSS-SDR-Workbench-v0.3.2-win-x64.zip','GNSS-SDR-Workbench-v0.3.2-source.zip','GNSS-SDR-receiver-corresponding-source.zip','SHA256SUMS.txt']]
    if not all(p.is_file() for p in files):raise SystemExit('Build and verify all release assets first')
    if run(['git','status','--porcelain'],True).stdout.strip():raise SystemExit('Commit reviewed source changes before publishing')
    # Credentials stay in gh's credential store. Configure only this repository.
    run(['git','config','--local','credential.helper',''])
    run(['git','config','--local','--add','credential.helper','!"'+str(Path(gh).resolve()).replace('\\','/')+'" auth git-credential'])
    remotes=run(['git','remote'],True).stdout.split()
    if 'origin' not in remotes:run([gh,'repo','create',repo,'--public','--description','Local GNSS-SDR debugging workbench for Windows: live channel/loop monitoring and linked event replay.','--source','.','--remote','origin','--push'])
    else:
        origin=run(['git','remote','get-url','origin'],True).stdout.strip()
        if origin not in ('https://github.com/'+repo+'.git','https://github.com/'+repo,'git@github.com:'+repo+'.git'):raise SystemExit('origin differs from the selected repository')
        run(['git','push','-u','origin','main'])
    run([gh,'release','create','v0.3.2',*[str(p) for p in files],'--repo',repo,'--target','main','--title','v0.3.2 — Windows x64 portable workbench','--notes-file','RELEASE-NOTES.md'])
    print(run([gh,'release','view','v0.3.2','--repo',repo,'--json','url,assets'],True).stdout)
if __name__=='__main__':main()
