"""Model-independent entry point for the repository's pinned build recipe."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
def run(*args,capture=False):
    result=subprocess.run([str(a) for a in args],cwd=ROOT,check=True,text=True,
        stdout=subprocess.PIPE if capture else None,encoding='utf-8')
    return result.stdout.strip() if capture else None

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['status','build','local'],nargs='?',default='status')
    args=parser.parse_args()
    project=json.loads((ROOT/'.avx1/project.json').read_text('utf-8'))
    git=shutil.which('git')
    if not git:raise RuntimeError('Install Git and retry; no LLM is required')
    source=run(git,'rev-parse','HEAD',capture=True)
    dirty=bool(run(git,'status','--porcelain',capture=True))
    if args.command=='status':
        print(json.dumps({'project':project['id'],'source':source,'clean':not dirty,
            'model_required':False,'recipe':'.avx1/build.py','pins':'.avx1/toolchains.json'}));return
    if dirty:raise RuntimeError('Commit/review source changes before building')
    day=dt.datetime.now(dt.timezone(dt.timedelta(hours=6))).strftime('%Y%m%d')
    if args.command=='local':
        os.environ.update(BUILD_CHANNEL='latest',BUILD_DAY=day)
        run(sys.executable,ROOT/'.avx1/build.py');return
    gh=shutil.which('gh')
    if not gh:raise RuntimeError('Install GitHub CLI and run gh auth login once; do not put a token in this project')
    remote=run(gh,'api','repos/'+project['repository']+'/git/ref/heads/avx1','--jq','.object.sha',capture=True)
    if remote!=source:raise RuntimeError('Published avx1 differs from this source; review and push the exact commit first')
    run(gh,'workflow','run','avx1-build.yml','--repo',project['repository'],'--ref','avx1','-f','day='+day)
    print('Build dispatched for '+source+'. The workflow performs checks and produces one verified candidate.')

if __name__=='__main__':main()
