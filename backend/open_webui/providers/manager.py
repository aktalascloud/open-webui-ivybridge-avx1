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
                'LOG_FORMAT':'json','ALLOWED_ORIGINS':'','DISABLE_AUTO_RECOVER':'true',
                'DEEPSEEK_MAX_CONCURRENCY':'1','DEEPSEEK_SHARED_BROWSER_LEASE':'1',
                'DEEPSEEK_DISABLE_AUTO_REPLAY':'1',
                'RECOVER_MANAGED_REQUEST_FAILURES':'1'})
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
        restriction = (config or {}).get('vendor_restriction') or {}
        restricted = bool(restriction.get('active')) and (not restriction.get('until_utc') or time.time()<restriction['until_utc'])
        rows = self.protocol.get_pool().get_all() if self.protocol is not None else []
        return {'provider':'dsw2api','installed':config is not None,'connected':bool(accounts),'accounts':accounts,
                'inference_verified':False,'vendor_blocked':restricted or any(row.get('vendor_blocked') for row in rows),
                'restriction_until':restriction.get('display_until') if restricted else None,
                'authorization_required':any(row.get('authorization_required') or '40003' in row.get('last_error','') for row in rows),
                'model':{'id':MODEL_ID,'name':MODEL_NAME},'browser_consent':bool(config and config.get('browser_consent') and config.get('browser_consent_scope')=='shared-native-v1'),
                'login':flow,'local_usage_quotas':False,'upstream_limits':'controlled by DeepSeek; no bypass or older-model fallback'}

    def setup(self):
        self.initialize();return self.status()

    def connection(self,port):
        self.initialize();config=self.config()
        from .browser_bridge import install
        bridge=install()
        return {'url':f'http://127.0.0.1:{int(port)}/dsw2api/v1','key':config['api_key'],
                'provider':'dsw2api','prefix_id':'DSW2API','model_ids':[], 'status':self.status(),
                'browser_extension':bridge}

    def begin_login(self,user_id,port,*,consent=False):
        with self.lock:
            self.initialize();config=self.config()
            if self.status().get('vendor_blocked'):
                raise PermissionError('DeepSeek restricted this account; reconnecting does not remove the restriction')
            if not consent and not (config.get('browser_consent') and config.get('browser_consent_scope')=='shared-native-v1'):
                raise PermissionError('Explicit shared browser connector consent required')
            from .browser_bridge import install
            install()
            nonce=secrets.token_hex(32)
            flow={'hash':hashlib.sha256(nonce.encode()).hexdigest(),'user_id':user_id,
                  'expires':time.time()+600,'stage':'opening_browser'}
            atomic_json(self.root/'login-flow.json',flow)
            from .browser import open_login
            try:browser=open_login(self.root,nonce,int(port),consent=True)
            except Exception:
                flow['stage']='browser_unavailable';atomic_json(self.root/'login-flow.json',flow);raise
            config['browser_consent']=True;config['browser_consent_scope']='shared-native-v1'
            write_private(self.root/'service-config.dpapi',config)
            flow.update(stage='awaiting_login',browser=browser['browser'],pid=browser['pid'])
            atomic_json(self.root/'login-flow.json',flow)
            return self.status()

    def validate_login_state(self,state):
        if not isinstance(state,str) or len(state)!=64:raise PermissionError('Invalid account handoff')
        with self.lock:
            path=self.root/'login-flow.json'
            flow=json.loads(path.read_text('utf-8')) if path.exists() else {}
            if (flow.get('expires',0)<time.time() or flow.get('stage') not in {'opening_browser','awaiting_login'}
                or not hmac.compare_digest(flow.get('hash',''),hashlib.sha256(state.encode()).hexdigest())):
                raise PermissionError('Expired or consumed account handoff')
            return {'user_id':flow['user_id'],'expires':flow['expires']}

    def complete_login(self,state,token,cookies):
        if not isinstance(state,str) or len(state)!=64 or not isinstance(token,str) or not 20<=len(token)<=16384 or '\r' in token or '\n' in token:
            raise PermissionError('Invalid account handoff')
        if not isinstance(cookies,str) or not cookies or len(cookies)>65536 or '\r' in cookies or '\n' in cookies:
            raise PermissionError('Invalid account handoff')
        with self.lock:
            if self.status().get('vendor_blocked'):
                raise PermissionError('DeepSeek restricted this account; no authentication probe was sent')
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
            from .vendor.dsw2api.browser_session_lease import acquire_browser_session_lease
            with_lease=acquire_browser_session_lease(enabled=True)
            try: adapter.create_session()
            finally: with_lease.release()
            if pool.stats().get('busy',0):raise RuntimeError('Wait for the active provider request before changing account')
            account=pool.reconnect_verified(token,cookies) or pool.add(token=token,cookies=cookies,email='DeepSeek')
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
        restriction=config.get('vendor_restriction') or {}
        if scope['method']=='POST' and path in {'/v1/chat/completions','/v1/messages','/v1/responses'} and restriction.get('active') and (not restriction.get('until_utc') or time.time()<restriction['until_utc']):
            return await JSONResponse({'error':{'message':'DeepSeek restricted the account; reconnecting does not remove the provider restriction.',
                'type':'permission_error','code':'deepseek_account_restricted'}},status_code=403)(scope,receive,send)
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
            if not isinstance(payload,dict):
                return await JSONResponse({'error':{'message':'A JSON object is required'}},status_code=400)(scope,receive,send)
            if payload.get('model') not in (None,MODEL_ID):
                return await JSONResponse({'error':{'message':'Only deepseek-latest is available; no model fallback','type':'invalid_request_error'}},status_code=400)(scope,receive,send)
            effort=payload.get('reasoning_effort')
            if effort is None and isinstance(payload.get('reasoning'),dict):effort=payload['reasoning'].get('effort')
            if effort is not None and (not isinstance(effort,str) or effort not in {'none','disabled','off','minimal','low','medium','high','xhigh','max'}):
                return await JSONResponse({'error':{'message':'Unsupported reasoning control for DeepSeek web'}},status_code=400)(scope,receive,send)
            from .vendor.dsw2api import managed_env
            thinking=effort not in {'none','disabled','off'}
            if 'search_enabled' in payload and type(payload['search_enabled']) is not bool:
                return await JSONResponse({'error':{'message':'search_enabled must be a boolean'}},status_code=400)(scope,receive,send)
            context_token=managed_env.request_thinking.set(thinking)
            search_token=managed_env.request_search.set(payload.get('search_enabled',True))
            from .vendor.dsw2api.chat_runtime import REQUEST_CANCEL
            cancelled=threading.Event()
            cancel_token=REQUEST_CANCEL.set(cancelled)
            incoming=asyncio.Queue(maxsize=2)
            async def monitor_disconnect():
                while True:
                    message=await receive()
                    if message['type']=='http.disconnect':cancelled.set()
                    await incoming.put(message)
                    if message['type']=='http.disconnect':return
                    await asyncio.sleep(0)
            monitor=asyncio.create_task(monitor_disconnect())
            first=True
            async def replay():
                nonlocal first
                if first:first=False;return {'type':'http.request','body':bytes(body),'more_body':False}
                return await incoming.get()
            try:return await service.app({**scope,'root_path':'','path':path},replay,send)
            finally:
                cancelled.set();monitor.cancel()
                await asyncio.gather(monitor,return_exceptions=True)
                REQUEST_CANCEL.reset(cancel_token)
                managed_env.request_thinking.reset(context_token)
                managed_env.request_search.reset(search_token)
        return await service.app({**scope,'root_path':'','path':path},receive,send)

inference_app=InferenceApplication()
