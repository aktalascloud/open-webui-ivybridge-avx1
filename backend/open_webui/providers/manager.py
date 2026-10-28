"""A single, account-backed DeepSeek provider inside OWUI.

The public API has one latest-model alias. Account credentials stay encrypted
under DATA_DIR and are never OpenAI connection keys or process environment.
"""
import asyncio
import csv
import hashlib
import hmac
import importlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import threading
import time

from .provider_crypto import read_private,write_private

MODEL_ID='deepseek-latest'
MODEL_NAME='DeepSeek (latest web model)'
PACKAGE=Path(__file__).resolve().parent

def atomic_json(path,value):
    path=Path(path);temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');temporary.replace(path)


class ProviderManager:
    def __init__(self,root):
        self.root=Path(root).resolve();self.lock=threading.RLock();self.protocol=None

    def config(self,*,create=False):
        path=self.root/'service-config.dpapi'
        if path.exists():return read_private(path)
        if not create:return None
        if os.name!='nt':raise RuntimeError('Local browser account integration requires Windows')
        if (self.root/'accounts.json').exists():raise RuntimeError('Existing account store has no matching encryption identity')
        self.root.mkdir(parents=True,exist_ok=True)
        sid=list(csv.reader(subprocess.check_output(['whoami.exe','/user','/fo','csv','/nh'],text=True).splitlines()))[-1][-1]
        if not sid.startswith('S-1-'):raise RuntimeError('Windows profile identity unavailable')
        subprocess.run(['icacls.exe',str(self.root),'/inheritance:r','/grant:r','*'+sid+':(OI)(CI)F','*S-1-5-18:(OI)(CI)F'],
            check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        from cryptography.fernet import Fernet
        value={'api_key':'owui-dsw-'+secrets.token_urlsafe(32),'admin_password':secrets.token_urlsafe(32),
               'encryption_key':Fernet.generate_key().decode(),'browser_consent':False}
        write_private(path,value);return value

    def initialize(self):
        with self.lock:
            if self.protocol is not None:return self.protocol
            config=self.config(create=True)
            from .vendor.dsw2api import managed_env
            managed_env.configure({'MODEL_NAME':MODEL_ID,'MODEL_ROUTES':'','MODE':'auto','THINKING':'auto','SEARCH':'auto',
                'HOST':'127.0.0.1','PORT':'8080','ENABLE_RATE_LIMIT':'false','ALLOW_UNAUTHENTICATED_API':'false',
                'DEEPSEEK_ADMIN_PASSWORD':config['admin_password'],'API_KEYS':config['api_key'],
                'ACCOUNT_STORE_PATH':str(self.root/'accounts.json'),'API_KEY_STORE_PATH':str(self.root/'api-keys.sqlite3'),
                'DEEPSEEK_ENCRYPTION_KEY':config['encryption_key'],'DEEPSEEK_JITTER_SECS':'0','LOG_LEVEL':'WARNING',
                'LOG_FORMAT':'json','ALLOWED_ORIGINS':'','DISABLE_AUTO_RECOVER':'true'})
            # The embedded protocol has no reason to retain a standalone stats
            # sampler. No account discovery, model probes or remote login runs.
            from .vendor.dsw2api import stats_history
            original_sampler=stats_history.start_sampler
            stats_history.start_sampler=lambda *_:None
            try:self.protocol=importlib.import_module('.vendor.dsw2api.server',__package__)
            finally:stats_history.start_sampler=original_sampler
            return self.protocol

    def status(self):
        config=self.config();connected=False;accounts=0
        if self.protocol is not None:
            rows=self.protocol.get_pool().get_all()
            accounts=len(rows);connected=any(row.get('state')!='error' for row in rows)
        elif config and (self.root/'accounts.json').exists():
            # Loading the provider's own encrypted store does not contact DS.
            self.initialize();return self.status()
        flow={}
        path=self.root/'login-flow.json'
        if path.exists():
            data=json.loads(path.read_text('utf-8'))
            flow={'stage':data.get('stage'),'expires':data.get('expires'),'browser':data.get('browser')}
        return {'provider':'dsw2api','installed':config is not None,'connected':connected,'accounts':accounts,
                'model':{'id':MODEL_ID,'name':MODEL_NAME},'browser_consent':bool(config and config.get('browser_consent')),
                'login':flow,'local_usage_quotas':False,'upstream_limits':'controlled by DeepSeek; no bypass or older-model fallback'}

    def setup(self):
        self.initialize();return self.status()

    def connection(self,port):
        self.initialize();config=self.config()
        return {'url':f'http://127.0.0.1:{int(port)}/dsw2api/v1','key':config['api_key'],
                'provider':'dsw2api','prefix_id':'DSW2API','model_ids':[], 'status':self.status()}

    def begin_login(self,user_id,port,*,consent=False):
        with self.lock:
            self.initialize();config=self.config()
            if not consent and not config.get('browser_consent'):raise PermissionError('Explicit browser connector consent required')
            connector=PACKAGE/'browser_connector';target=self.root/'browser-connector'
            target.mkdir(exist_ok=True)
            for source in connector.iterdir():
                if source.is_file():shutil.copyfile(source,target/source.name)
            nonce=secrets.token_hex(32)
            flow={'hash':hashlib.sha256(nonce.encode()).hexdigest(),'user_id':user_id,
                  'expires':time.time()+600,'stage':'opening_browser'}
            atomic_json(self.root/'login-flow.json',flow)
            from .browser import open_login
            try:browser=open_login(self.root,nonce,int(port),consent=True)
            except Exception:
                flow['stage']='browser_unavailable';atomic_json(self.root/'login-flow.json',flow);raise
            config['browser_consent']=True;write_private(self.root/'service-config.dpapi',config)
            flow.update(stage='awaiting_login',browser=browser['browser'],pid=browser['pid'])
            atomic_json(self.root/'login-flow.json',flow)
            return self.status()

    def complete_login(self,state,token,cookies):
        if not isinstance(state,str) or len(state)!=64 or not isinstance(token,str) or not 20<=len(token)<=16384 or '\r' in token or '\n' in token:
            raise PermissionError('Invalid account handoff')
        if not isinstance(cookies,str) or not cookies or len(cookies)>65536 or '\r' in cookies or '\n' in cookies:
            raise PermissionError('Invalid account handoff')
        with self.lock:
            path=self.root/'login-flow.json';flow=json.loads(path.read_text('utf-8')) if path.exists() else {}
            if flow.get('expires',0)<time.time() or not hmac.compare_digest(flow.get('hash',''),hashlib.sha256(state.encode()).hexdigest()):
                raise PermissionError('Expired or invalid account handoff')
            credential_hash=hashlib.sha256((token+'\0'+cookies).encode()).hexdigest()
            if flow.get('stage')=='connected':
                if hmac.compare_digest(flow.get('credential_hash',''),credential_hash):return {'connected':True}
                raise PermissionError('Account handoff already consumed')
            service=self.initialize();pool=service.get_pool()
            # Validate the captured session through the provider's real session
            # endpoint, not merely the presence of an Authorization header.
            adapter=service.DeepSeekAdapter(token=token,cookies=cookies)
            adapter.create_session()
            if pool.stats().get('busy',0):raise RuntimeError('Wait for the active provider request before changing account')
            account=pool.add(token=token,cookies=cookies,email='DeepSeek')
            for previous in pool.get_all():
                if previous['id']!=account.id:pool.remove_by_id(previous['id'])
            flow.update(stage='connected',credential_hash=credential_hash,account_id=account.id)
            atomic_json(path,flow)
            return {'connected':True}


_manager=None
def manager():
    global _manager
    if _manager is None:
        from open_webui.env import DATA_DIR
        _manager=ProviderManager(Path(DATA_DIR)/'managed-providers/dsw2api')
    return _manager


class InferenceApplication:
    """Expose inference only; upstream standalone administration stays private."""
    async def __call__(self,scope,receive,send):
        from starlette.responses import JSONResponse
        if scope['type']!='http':return
        path=scope.get('path','')
        root_path=scope.get('root_path','')
        if root_path and path.startswith(root_path):path=path[len(root_path):] or '/'
        allowed={'/v1/models','/v1/chat/completions','/v1/responses','/v1/messages','/v1/messages/count_tokens'}
        if path not in allowed and not path.startswith('/v1/responses/'):
            return await JSONResponse({'detail':'Not found'},status_code=404)(scope,receive,send)
        instance=manager()
        config=instance.config()
        if config is None:
            return await JSONResponse({'error':{'message':'Set up DSW2API in OWUI Connections first','type':'provider_unavailable'}},status_code=503)(scope,receive,send)
        authorization=dict(scope.get('headers',[])).get(b'authorization',b'')
        if not hmac.compare_digest(authorization,('Bearer '+config['api_key']).encode()):
            return await JSONResponse({'error':{'message':'Unauthorized','type':'authentication_error'}},status_code=401)(scope,receive,send)
        try:service=await asyncio.to_thread(instance.initialize)
        except Exception:return await JSONResponse({'error':{'message':'DSW2API is not ready','type':'provider_unavailable'}},status_code=503)(scope,receive,send)
        if scope['method']=='GET' and path=='/v1/models':
            headers=dict(scope.get('headers',[]));expected=('Bearer '+instance.config()['api_key']).encode()
            if not hmac.compare_digest(headers.get(b'authorization',b''),expected):
                return await JSONResponse({'error':{'message':'Unauthorized'}},status_code=401)(scope,receive,send)
            return await JSONResponse({'object':'list','data':[{'id':MODEL_ID,'object':'model','owned_by':'dsw2api','name':MODEL_NAME}]})(scope,receive,send)
        if scope['method']=='POST':
            body=bytearray()
            while True:
                message=await receive()
                if message['type']=='http.disconnect':return
                body.extend(message.get('body',b''))
                if len(body)>40*1024*1024:return await JSONResponse({'error':{'message':'Request body too large'}},status_code=413)(scope,receive,send)
                if not message.get('more_body'):break
            try:payload=json.loads(body)
            except Exception:return await JSONResponse({'error':{'message':'Invalid JSON'}},status_code=400)(scope,receive,send)
            if payload.get('model') not in (None,MODEL_ID):
                return await JSONResponse({'error':{'message':'Only deepseek-latest is available; no model fallback','type':'invalid_request_error'}},status_code=400)(scope,receive,send)
            first=True
            async def replay():
                nonlocal first
                if first:first=False;return {'type':'http.request','body':bytes(body),'more_body':False}
                return await receive()
            return await service.app({**scope,'root_path':'','path':path},replay,send)
        return await service.app({**scope,'root_path':'','path':path},receive,send)

inference_app=InferenceApplication()
