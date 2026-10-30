"""Offline gates for the embedded latest-only provider and account handoff."""
import asyncio
import importlib
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock,patch

_auth_directory=tempfile.TemporaryDirectory(prefix='owui-provider-auth-fixture-')
os.environ['DATA_DIR']=_auth_directory.name
os.environ['LOCALAPPDATA']=_auth_directory.name
os.environ['STATIC_DIR']=str(Path(_auth_directory.name)/'static')
# Unit tests load the wheel from pip --target. Its installed BASE_DIR does
# not contain the repository's frontend assets; use the real fixture source.
os.environ['FRONTEND_BUILD_DIR']=str(Path(__file__).resolve().parents[1]/'static')
os.environ.setdefault('WEBUI_SECRET_KEY','fixture-'+'x'*32)
os.environ.setdefault('OFFLINE_MODE','true')
os.environ.setdefault('HF_HUB_OFFLINE','1')

from fastapi import FastAPI,Request
from fastapi.testclient import TestClient
from open_webui.providers import manager as managed
from open_webui.providers import browser
from open_webui.routers import local_providers as routes
from open_webui.utils.auth import get_current_user


class ProviderGates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='owui-provider-fixture-')
        cls.bridge_patch=patch('open_webui.providers.browser_bridge.install',return_value={'status':'fixture','extension_id':'jaljomgoclehkemckjhifflhmlllfopc'})
        cls.bridge_patch.start()
        cls.instance=managed.ProviderManager(cls.directory.name)
        before=dict(os.environ)
        cls.service=cls.instance.initialize()
        assert before==dict(os.environ),'Provider changed the hosting process environment'
        managed._manager=cls.instance
        cls.app=FastAPI()
        @cls.app.middleware('http')
        async def context(request,call_next):
            request.state.auth_type=request.headers.get('x-fixture-auth','jwt')
            request.state.claims={'typ':'session'}
            return await call_next(request)
        async def actor(request:Request):
            return SimpleNamespace(id='fixture-admin',role=request.headers.get('x-fixture-role','admin'))
        cls.app.dependency_overrides[get_current_user]=actor
        cls.app.include_router(routes.router,prefix='/api/v1/local-providers')
        cls.app.mount('/dsw2api',managed.inference_app)
        cls.client=TestClient(cls.app,client=('127.0.0.1',50000))
        cls.identity=json.loads((managed.PACKAGE/'browser_connector/identity.json').read_text('utf-8'))['extension_id']

    @classmethod
    def tearDownClass(cls):
        cls.bridge_patch.stop()
        cls.client.close();cls.directory.cleanup()

    def tearDown(self):
        for account in self.service.get_pool().get_all():self.service.get_pool().remove_by_id(account['id'])
        (self.instance.root/'login-flow.json').unlink(missing_ok=True)
        config=self.instance.config();config['browser_consent']=False
        config.pop('vendor_restriction',None)
        managed.write_private(self.instance.root/'service-config.dpapi',config)

    def begin(self):
        with patch.object(browser,'open_login',return_value={'browser':'Brave','pid':1234}) as launch:
            self.instance.begin_login('fixture-admin',8080,consent=True)
            return launch.call_args.args[1]

    def headers(self,**more):
        return {'X-OWUI-Connector':self.identity,'Origin':'chrome-extension://'+self.identity,**more}

    def plaintext(self,state):return {'state':state,'token':'synthetic-token-'+'x'*32,'cookies':'fixture_session='+'y'*24}

    def payload(self,state):
        import base64
        from open_webui.providers.provider_crypto import seal_browser_payload
        data={**self.plaintext(state),'origin':'https://chat.deepseek.com','nonce':base64.b64encode(b'c'*32).decode()}
        return {'state':state,'protected_session':seal_browser_payload(data,'owui-dsw-session-v2',state)}

    def check_payload(self,state):
        import base64
        from open_webui.providers.provider_crypto import seal_browser_payload
        return {'state':state,'challenge':seal_browser_payload({'nonce':base64.b64encode(b'p'*32).decode()},'owui-dsw-check-v2',state)}

    def test_status_has_no_credentials_and_no_local_usage_quota(self):
        config=self.instance.config();body=json.dumps(self.instance.status())
        self.assertFalse(self.instance.status()['local_usage_quotas'])
        for name in ['api_key','admin_password','encryption_key']:self.assertNotIn(config[name],body)

    def test_provider_configuration_is_not_an_environment_secret(self):
        config=self.instance.config()
        self.assertNotEqual(os.environ.get('DEEPSEEK_ADMIN_PASSWORD'),config['admin_password'])
        self.assertNotEqual(os.environ.get('DEEPSEEK_ENCRYPTION_KEY'),config['encryption_key'])
        self.assertNotEqual(os.environ.get('ACCOUNT_STORE_PATH'),str(self.instance.root/'accounts.json'))
        self.assertTrue(self.service.crypto_is_enabled())
        self.assertFalse(self.service.RATE_LIMITER.enabled)

    def test_model_list_has_exactly_one_latest_alias(self):
        config=self.instance.config()
        response=self.client.get('/dsw2api/v1/models',headers={'Authorization':'Bearer '+config['api_key']})
        self.assertEqual(response.status_code,200)
        self.assertEqual([row['id'] for row in response.json()['data']],['deepseek-latest'])

    def test_unknown_key_and_standalone_admin_are_rejected(self):
        self.assertEqual(self.client.get('/dsw2api/v1/models',headers={'Authorization':'Bearer wrong'}).status_code,401)
        self.assertEqual(self.client.get('/dsw2api/admin/api/accounts').status_code,404)

    def test_older_model_never_silently_falls_back(self):
        config=self.instance.config()
        response=self.client.post('/dsw2api/v1/chat/completions',headers={'Authorization':'Bearer '+config['api_key']},
            json={'model':'deepseek-v3','messages':[{'role':'user','content':'fixture'}]})
        self.assertEqual(response.status_code,400)

    def test_full_thinking_is_default_and_request_hint_does_not_leak(self):
        module=importlib.import_module('open_webui.providers.vendor.dsw2api.managed_env')
        self.assertTrue(self.service._responses_controls('deepseek-latest')['thinking_enabled'])
        token=module.request_thinking.set(False)
        try:self.assertFalse(self.service._responses_controls('deepseek-latest')['thinking_enabled'])
        finally:module.request_thinking.reset(token)
        self.assertTrue(self.service._responses_controls('deepseek-latest')['thinking_enabled'])

    def test_regular_user_cannot_provision_or_get_local_key(self):
        response=self.client.post('/api/v1/local-providers/dsw2api/setup',headers={'X-Fixture-Role':'user'})
        self.assertIn(response.status_code,[401,403])

    def test_admin_api_key_cannot_launch_human_browser(self):
        with patch.object(browser,'open_login') as launch:
            response=self.client.post('/api/v1/local-providers/dsw2api/browser/login',
                headers={'X-Fixture-Auth':'api_key'},json={'consent':True})
            self.assertEqual(response.status_code,403);launch.assert_not_called()

    def test_consent_is_required_before_browser_launch(self):
        with patch.object(browser,'open_login') as launch:
            response=self.client.post('/api/v1/local-providers/dsw2api/browser/login',json={'consent':False})
            self.assertEqual(response.status_code,403);launch.assert_not_called()

    def test_old_isolated_profile_consent_cannot_authorize_regular_profile(self):
        config=self.instance.config();config['browser_consent']=True;config.pop('browser_consent_scope',None)
        managed.write_private(self.instance.root/'service-config.dpapi',config)
        with patch.object(browser,'open_login') as launch:
            with self.assertRaises(PermissionError):self.instance.begin_login('fixture-admin',8080,consent=False)
            launch.assert_not_called()

    def test_explicit_login_keeps_only_hash_and_uses_installed_browser(self):
        state=self.begin();flow=(self.instance.root/'login-flow.json').read_text('utf-8')
        self.assertNotIn(state,flow);self.assertEqual(self.instance.status()['login']['browser'],'Brave')

    def test_browser_uses_existing_default_profile_without_automation_flags(self):
        (self.instance.root/'browser-connector').mkdir(exist_ok=True)
        (self.instance.root/'browser-connector/manifest.json').write_text('{}')
        with patch.object(browser,'default_browser',return_value=Path('C:/fixture/brave.exe')),patch.object(browser.subprocess,'Popen',return_value=SimpleNamespace(pid=99)) as start:
            browser.open_login(self.instance.root,'a'*64,8080,consent=True)
            args=start.call_args.args[0]
            self.assertEqual(len(args),2)
            self.assertEqual(Path(args[0]),Path('C:/fixture/brave.exe'))
            self.assertTrue(args[1].startswith('https://chat.deepseek.com/#owui-dsw2api='))
            self.assertFalse(any('user-data-dir' in value or 'load-extension' in value for value in args))
            self.assertFalse(any('remote-debugging' in value or 'enable-automation' in value or 'ignore-certificate' in value for value in args))

    def test_wrong_origin_never_imports_an_account(self):
        state=self.begin()
        with patch.object(self.service.DeepSeekAdapter,'create_session') as validate:
            response=self.client.post('/api/v1/local-providers/dsw2api/browser/callback',headers=self.headers(Origin='https://evil.invalid'),json=self.payload(state))
            self.assertEqual(response.status_code,403);validate.assert_not_called()

    def test_shared_extension_checks_permission_before_session_capture(self):
        state=self.begin()
        with patch.object(routes.Users,'get_user_by_id',AsyncMock(return_value=SimpleNamespace(role='admin'))):
            result=self.client.post('/api/v1/local-providers/dsw2api/browser/check',headers=self.headers(),json=self.check_payload(state))
            self.assertEqual(result.status_code,200);self.assertTrue(result.json()['ok'])
            result=self.client.post('/api/v1/local-providers/dsw2api/browser/check',headers=self.headers(),json=self.check_payload('f'*64))
            self.assertEqual(result.status_code,401)
        with patch.object(routes.Users,'get_user_by_id',AsyncMock(return_value=SimpleNamespace(role='user'))):
            result=self.client.post('/api/v1/local-providers/dsw2api/browser/check',headers=self.headers(),json=self.check_payload(state))
            self.assertEqual(result.status_code,401)

    def test_native_thinking_and_search_defaults_and_explicit_overrides(self):
        from open_webui.providers.vendor.dsw2api.model_router import RouteDecision
        self.assertEqual(self.service.resolve_model_controls(RouteDecision()),('default',True,True))
        self.assertEqual(self.service.resolve_model_controls(RouteDecision(),False,False),('default',False,False))
        async def echo(scope,receive,send):
            from starlette.responses import JSONResponse
            decision=self.service.resolve_model_controls(RouteDecision())
            await JSONResponse({'thinking':decision[1],'search':decision[2]})(scope,receive,send)
        headers={'Authorization':'Bearer '+self.instance.config()['api_key']}
        with patch.object(self.service,'app',echo):
            for payload,expected in [({'model':'deepseek-latest'},{'thinking':True,'search':True}),
                                     ({'model':'deepseek-latest','reasoning_effort':'none','search_enabled':False},{'thinking':False,'search':False}),
                                     ({'model':'deepseek-latest'},{'thinking':True,'search':True})]:
                result=self.client.post('/dsw2api/v1/chat/completions',headers=headers,json=payload)
                self.assertEqual(result.json(),expected)
    def test_nonce_expiry_and_revoked_actor_block_handoff(self):
        state=self.begin();path=self.instance.root/'login-flow.json';flow=json.loads(path.read_text());flow['expires']=time.time()-1;managed.atomic_json(path,flow)
        with patch.object(routes.Users,'get_user_by_id',AsyncMock(return_value=SimpleNamespace(role='admin'))),patch.object(self.service.DeepSeekAdapter,'create_session') as validate:
            response=self.client.post('/api/v1/local-providers/dsw2api/browser/callback',headers=self.headers(),json=self.payload(state))
            self.assertEqual(response.status_code,401);validate.assert_not_called()
        state=self.begin()
        with patch.object(routes.Users,'get_user_by_id',AsyncMock(return_value=SimpleNamespace(role='user'))):
            response=self.client.post('/api/v1/local-providers/dsw2api/browser/callback',headers=self.headers(),json=self.payload(state))
            self.assertEqual(response.status_code,401)

    def test_validated_session_is_encrypted_and_exact_retry_is_idempotent(self):
        state=self.begin();payload=self.payload(state)
        with patch.object(routes.Users,'get_user_by_id',AsyncMock(return_value=SimpleNamespace(role='admin'))),patch.object(self.service.DeepSeekAdapter,'create_session',return_value='fixture-session') as validate:
            for _ in range(2):
                response=self.client.post('/api/v1/local-providers/dsw2api/browser/callback',headers=self.headers(),json=payload)
                self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(validate.call_count,1)
        self.assertEqual(len(self.service.get_pool().get_all()),1)
        stored=(self.instance.root/'accounts.json').read_text('utf-8')
        self.assertNotIn(self.plaintext(state)['token'],stored);self.assertNotIn(self.plaintext(state)['cookies'],stored)
        altered={**self.plaintext(state),'token':'different-token-'+'z'*32}
        with self.assertRaises(PermissionError):self.instance.complete_login(**altered)

    def test_failed_session_validation_does_not_persist_credentials(self):
        state=self.begin()
        with patch.object(self.service.DeepSeekAdapter,'create_session',side_effect=RuntimeError('fixture failed')):
            with self.assertRaises(RuntimeError):self.instance.complete_login(**self.plaintext(state))
        self.assertEqual(self.service.get_pool().get_all(),[])

    def test_pow_jit_uses_the_runtime_cpu_without_serializing_native_code(self):
        module=importlib.import_module('open_webui.providers.vendor.dsw2api.adapter')
        solver=module._WASMSolver()
        self.assertIsNotNone(solver.store)

    def test_audit_retains_metadata_without_capturing_account_or_setup_bodies(self):
        from open_webui.utils.audit import AuditLoggingMiddleware,AuditLevel
        @asynccontextmanager
        async def context(_):yield SimpleNamespace()
        async def exercise(path):
            received=[];sent=[]
            async def app(scope,receive,send):
                received.append((await receive())['body'])
                await send({'type':'http.response.start','status':200,'headers':[]})
                await send({'type':'http.response.body','body':b'fixture-private-response'})
            middleware=AuditLoggingMiddleware(app,audit_level=AuditLevel.REQUEST_RESPONSE)
            async def receive():return {'type':'http.request','body':b'fixture-private-account','more_body':False}
            async def send(message):sent.append(message)
            scope={'type':'http','http_version':'1.1','method':'POST','scheme':'http','path':path,'root_path':'','query_string':b'',
                   'headers':[(b'host',b'127.0.0.1:8080')],'client':('127.0.0.1',50000),'server':('127.0.0.1',8080),'state':{'token':'fixture-only'}}
            audit_module=importlib.import_module('open_webui.utils.audit')
            with patch.object(audit_module,'AUDIT_LOG_LEVEL','REQUEST_RESPONSE'),patch.object(middleware,'_audit_context',context),patch.object(middleware,'_capture_request',AsyncMock()) as request_capture,patch.object(middleware,'_capture_response',AsyncMock()) as response_capture:
                await middleware(scope,receive,send)
                request_capture.assert_not_awaited()
                self.assertEqual([c.args[0]['type'] for c in response_capture.await_args_list],['http.response.start'])
            self.assertEqual(received,[b'fixture-private-account']);self.assertEqual(sent[-1]['body'],b'fixture-private-response')
        for path in ['/api/v1/local-providers/dsw2api/setup','/api/v1/local-providers/dsw2api/browser/callback',
                     '/api/v1/users/fixture-user/api_key/rotate','/api/v1/users/fixture-user/api_key']:
            asyncio.run(exercise(path))

    def test_rejected_pow_challenge_is_typed_auth_error(self):
        adapter_module=importlib.import_module('open_webui.providers.vendor.dsw2api.adapter')
        response=SimpleNamespace(status_code=200,headers={},json=lambda:{'code':40003},raise_for_status=lambda:None)
        fake=SimpleNamespace(_client=SimpleNamespace(post=lambda *args,**kwargs:response),_base_headers={},_detect_waf_challenge=lambda *args:None)
        with self.assertRaises(adapter_module.SessionAuthorizationError):adapter_module.DeepSeekAdapter._get_challenge(fake)

    def test_managed_transient_and_auth_states_are_distinct_without_replay(self):
        auth=importlib.import_module('open_webui.providers.vendor.dsw2api.adapter').SessionAuthorizationError
        pool=self.service.get_pool();acct=pool.add('fixture-token-'+'t'*32,'session=fixture-state','fixture')
        pool.mark_request_error(acct,RuntimeError('fixture transport failure'))
        self.assertEqual(acct.state,'idle')
        pool.mark_request_error(acct,auth())
        self.assertTrue(acct.authorization_required);self.assertEqual(acct.state,'error')
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as caught:self.service._acquire()
        self.assertEqual(caught.exception.status_code,401)
        self.assertEqual(caught.exception.detail['code'],'deepseek_session_expired')
        same=pool.reconnect_verified(acct.token,acct.cookies)
        self.assertIs(same,acct);self.assertFalse(acct.authorization_required);self.assertEqual(acct.state,'idle')

    def test_provider_restriction_cannot_be_cleared_by_reconnect(self):
        adapter_module=importlib.import_module('open_webui.providers.vendor.dsw2api.adapter')
        pool=self.service.get_pool();acct=pool.add('fixture-token-'+'b'*32,'session=fixture-blocked','fixture')
        pool.mark_request_error(acct,adapter_module.UserMutedError('fixture account restricted'))
        self.assertTrue(acct.vendor_blocked)
        with self.assertRaises(PermissionError):pool.reconnect_verified(acct.token,acct.cookies)
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as caught:self.service._acquire()
        self.assertEqual(caught.exception.status_code,403)

    def test_detected_vendor_restriction_survives_restart_without_probes(self):
        adapter=importlib.import_module('open_webui.providers.vendor.dsw2api.adapter')
        pool=self.service.get_pool();acct=pool.add('fixture-token-'+'p'*32,'session=fixture-persist','fixture')
        pool.mark_request_error(acct,adapter.UserMutedError('synthetic provider restriction'))
        ciphertext=pool._store_path.read_text('utf-8')
        self.assertNotIn(acct.token,ciphertext);self.assertNotIn(acct.cookies,ciphertext)
        restarted=type(pool)();rows=restarted.get_all()
        self.assertEqual(len(rows),1);self.assertTrue(rows[0]['vendor_blocked'])
        self.assertEqual(rows[0]['state'],'error')
        with self.assertRaises(PermissionError):restarted.reconnect_verified(acct.token,acct.cookies)

    def test_expired_authorization_survives_restart_until_explicit_verified_reconnect(self):
        adapter=importlib.import_module('open_webui.providers.vendor.dsw2api.adapter')
        pool=self.service.get_pool();acct=pool.add('fixture-token-'+'a'*32,'session=fixture-expired','fixture')
        pool.mark_request_error(acct,adapter.SessionAuthorizationError())
        restarted=type(pool)();self.assertTrue(restarted.get_all()[0]['authorization_required'])
        restarted.reconnect_verified(acct.token,acct.cookies)
        again=type(pool)();self.assertEqual(again.get_all()[0]['state'],'idle')
        self.assertFalse(again.get_all()[0]['authorization_required'])

    def test_reported_vendor_block_gates_inference_and_login_without_probes(self):
        pool=self.service.get_pool();pool.add('fixture-token-'+'g'*32,'session=fixture-guard','fixture')
        config=self.instance.config();config['vendor_restriction']={'active':True,'until_utc':time.time()+3600,'display_until':'fixture deadline'}
        managed.write_private(self.instance.root/'service-config.dpapi',config)
        with patch.object(self.service.DeepSeekAdapter,'create_session',side_effect=AssertionError('No vendor calls')) as create:
            status=self.instance.status();self.assertTrue(status['connected']);self.assertTrue(status['vendor_blocked']);self.assertFalse(status['inference_verified'])
            r=self.client.post('/dsw2api/v1/chat/completions',headers={'Authorization':'Bearer '+config['api_key']},json={'model':'deepseek-latest','messages':[{'role':'user','content':'fixture only'}]})
            self.assertEqual(r.status_code,403);self.assertEqual(r.json()['error']['code'],'deepseek_account_restricted')
            r=self.client.post('/api/v1/local-providers/dsw2api/browser/login',json={'consent':True})
            self.assertEqual(r.status_code,403);create.assert_not_called()

    def test_queued_client_disconnect_sends_no_vendor_post(self):
        import subprocess,sys
        module=managed.PACKAGE/'vendor/dsw2api/browser_session_lease.py'
        child=subprocess.Popen([sys.executable,'-B','-c',"import runpy,sys;d=runpy.run_path(sys.argv[1]);h=d['acquire_browser_session_lease'](enabled=True);print('acquired',flush=True);sys.stdin.readline();h.release()",str(module)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'acquired')
            pool=self.service.get_pool();acct=pool.add('fixture-token-'+'q'*32,'session=fixture-queued','fixture')
            config=self.instance.config()
            async def run():
                incoming=asyncio.Queue();sent=[]
                await incoming.put({'type':'http.request','body':json.dumps({'model':'deepseek-latest','messages':[{'role':'user','content':'fixture queued'}],'stream':True}).encode(),'more_body':False})
                async def receive():return await incoming.get()
                async def send(m):sent.append(m)
                scope={'type':'http','http_version':'1.1','method':'POST','scheme':'http','path':'/v1/chat/completions','root_path':'','query_string':b'','headers':[(b'host',b'127.0.0.1:8080'),(b'authorization',('Bearer '+config['api_key']).encode())],'client':('127.0.0.1',50000),'server':('127.0.0.1',8080)}
                request=asyncio.create_task(managed.inference_app(scope,receive,send))
                await asyncio.sleep(.2)
                await incoming.put({'type':'http.disconnect'})
                try:await asyncio.wait_for(request,15)
                except asyncio.CancelledError:pass
            with patch.object(self.service.DeepSeekAdapter,'create_session',side_effect=AssertionError('Queued request must not send')) as create:
                asyncio.run(run());create.assert_not_called()
            self.assertEqual(acct.state,'idle')
        finally:
            if child.poll() is None:
                child.stdin.write('\n');child.stdin.flush()
            child.communicate(timeout=10)

    def test_response_continuation_holds_and_releases_shared_lease_once(self):
        from unittest.mock import Mock
        pool=self.service.get_pool();acct=pool.add('fixture-token-'+'r'*32,'session=fixture-responses','fixture');acct._adapter=SimpleNamespace()
        lease=SimpleNamespace(release=Mock())
        with patch.object(self.service,'acquire_browser_session_lease',return_value=lease):
            acquired=self.service._acquire_response({'account_id':acct.id})
            self.assertEqual(acct.state,'busy');lease.release.assert_not_called()
            acquired.release();acquired.release()
        self.assertEqual(acct.state,'idle');lease.release.assert_called_once()

    def test_response_constructor_failure_releases_account_and_queue(self):
        from unittest.mock import Mock
        pool=self.service.get_pool();acct=pool.add('fixture-token-'+'f'*32,'session=fixture-failure','fixture')
        lease=SimpleNamespace(release=Mock())
        with patch.object(self.service,'acquire_browser_session_lease',return_value=lease),patch.object(self.service,'AcquiredAccount',side_effect=RuntimeError('fixture constructor')):
            with self.assertRaises(RuntimeError):self.service._acquire_response({'account_id':acct.id})
        self.assertEqual(acct.state,'idle');lease.release.assert_called_once()

    def test_stream_closes_before_account_lease_is_released(self):
        async def run():
            events=[];started=asyncio.Event()
            async def stream():
                try:
                    yield b'data: fixture\n\n'
                    await asyncio.sleep(10)
                finally:events.append('closed')
            acquired=SimpleNamespace(release=lambda:events.append('released'))
            response=self.service._AccountStreamingResponse(acquired,stream(),media_type='text/event-stream')
            async def receive():await started.wait();return {'type':'http.disconnect'}
            async def send(message):
                if message['type']=='http.response.body':started.set();await asyncio.sleep(.2)
            scope={'type':'http','http_version':'1.1','method':'POST','path':'/fixture','headers':[],'asgi':{'version':'3.0','spec_version':'2.3'}}
            await asyncio.wait_for(response(scope,receive,send),3)
            self.assertEqual(events,['closed','released'])
        asyncio.run(run())

    def test_plaintext_handoff_is_rejected_before_vendor_validation(self):
        state=self.begin()
        with patch.object(routes.Users,'get_user_by_id',AsyncMock(return_value=SimpleNamespace(role='admin'))),patch.object(self.service.DeepSeekAdapter,'create_session') as create:
            result=self.client.post('/api/v1/local-providers/dsw2api/browser/callback',headers=self.headers(),json=self.plaintext(state))
            self.assertEqual(result.status_code,422);create.assert_not_called()

    def test_protected_handoff_is_bound_to_nonce_and_purpose(self):
        from open_webui.providers.provider_crypto import seal_browser_payload
        import base64
        state=self.begin()
        data={'nonce':base64.b64encode(b'n'*32).decode(),'origin':'https://chat.deepseek.com','token':self.plaintext(state)['token'],'cookies':self.plaintext(state)['cookies']}
        with patch.object(routes.Users,'get_user_by_id',AsyncMock(return_value=SimpleNamespace(role='admin'))),patch.object(self.service.DeepSeekAdapter,'create_session') as create:
            for purpose,binding in [('wrong-purpose',state),('owui-dsw-session-v2','f'*64)]:
                payload={'state':state,'protected_session':seal_browser_payload(data,purpose,binding)}
                result=self.client.post('/api/v1/local-providers/dsw2api/browser/callback',headers=self.headers(),json=payload)
                self.assertEqual(result.status_code,401)
            create.assert_not_called()

if __name__=='__main__':unittest.main()
