"""Compile the minimal Windows CLR host; no separate browser or Node runtime."""
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
CONNECTOR=ROOT/'backend/open_webui/providers/browser_connector'

def build(destination=None,*,test=False):
    source=CONNECTOR/'native/Host.cs'
    target=Path(destination) if destination else CONNECTOR/'native/owui-native-host.exe'
    target.parent.mkdir(parents=True,exist_ok=True)
    compiler=Path(os.environ.get('SystemRoot','C:/Windows'))/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    args=[str(compiler),'/nologo','/target:exe','/platform:x64','/optimize+','/debug-',
          '/reference:System.Web.Extensions.dll','/reference:System.Security.dll','/out:'+str(target),str(source)]
    if test:args.insert(1,'/define:BRIDGE_TEST')
    subprocess.run(args,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    return target

if __name__=='__main__':build()
