"""Boot the packaged UI in Chromium against an isolated, offline backend."""
import json
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
from common import ROOT,WORK

parser=argparse.ArgumentParser()
parser.add_argument('--check-bundle-only',action='store_true')
parser.add_argument('--frontend',type=Path,default=ROOT/'build')
args=parser.parse_args()
# The previous regression resolved Svelte's server context into the client bundle.
maps=list((args.frontend/'_app/immutable').rglob('*.js.map'))
if not maps:raise RuntimeError('Browser sourcemaps missing from the test input')
for mapping in maps:
    data=json.loads(mapping.read_text('utf-8'))
    if any('/svelte/src/internal/server/context.js' in source.replace('\\','/') for source in data.get('sources',[])):
        raise RuntimeError('Svelte server context was included in the browser bundle')
if args.check_bundle_only:
    print('CLIENT_BUNDLE_USES_NO_SVELTE_SERVER_CONTEXT')
    raise SystemExit(0)

subprocess.run([sys.executable,'-m','pip','install','playwright>=1.58,<2'],check=True)
subprocess.run([sys.executable,'-m','playwright','install','chromium'],check=True)
from playwright.sync_api import sync_playwright
with socket.socket() as probe:
    probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
environment=dict(os.environ,DATA_DIR=str(WORK/'browser-smoke-data'),WEBUI_SECRET_KEY='ci-local-browser-fixture-key',
    OFFLINE_MODE='true',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',ENABLE_VERSION_UPDATE_CHECK='false',
    RAG_EMBEDDING_ENGINE='openai',RAG_OPENAI_API_BASE_URL='http://127.0.0.1:1/v1',
    RAG_OPENAI_API_KEY='ci-fixture-no-network',RAG_EMBEDDING_MODEL_AUTO_UPDATE='false',WHISPER_MODEL_AUTO_UPDATE='false')
launcher="import site,sys;site.addsitedir(sys.argv[1]);sys.path.insert(0,sys.argv[1]);sys.argv=['open-webui','serve','--host','127.0.0.1','--port',sys.argv[2]];from open_webui import app;app()"
log=(WORK/'browser-smoke-server.log').open('w',encoding='utf-8')
process=subprocess.Popen([sys.executable,'-c',launcher,str(WORK/'audit-packages'),str(port)],env=environment,stdout=log,stderr=log)
try:
    deadline=time.monotonic()+240
    while True:
        if process.poll() is not None:raise RuntimeError('Browser test backend exited; inspect the CI-only smoke log')
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=2) as response:
                if json.load(response).get('status') is True:break
        except Exception:pass
        if time.monotonic()>deadline:raise RuntimeError('Browser test backend startup timed out')
        time.sleep(1)
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True)
        page=browser.new_page()
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{port}',wait_until='domcontentloaded')
        page.locator('input[type="email"],input[type="password"]').first.wait_for(state='visible',timeout=45000)
        if errors:raise RuntimeError('Packaged frontend JavaScript failed: '+errors[0])
        browser.close()
    print('CHROMIUM_PACKAGED_LOGIN_RENDERED_NO_PAGE_ERRORS')
except Exception:
    log.flush()
    print((WORK/'browser-smoke-server.log').read_text('utf-8',errors='replace')[-6000:])
    raise
finally:
    process.terminate()
    try:process.wait(timeout=20)
    except subprocess.TimeoutExpired:process.kill();process.wait()
    log.close()
