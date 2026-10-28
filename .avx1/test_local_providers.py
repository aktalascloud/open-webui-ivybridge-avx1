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
        cls.client.close();cls.directory.cleanup()

    def tearDown(self):
        for account in self.service.get_pool().get_all():self.service.get_pool().remove_by_id(account['id'])
        (self.instance.root/'login-flow.json').unlink(missing_ok=True)
        config=self.instance.config();config['browser_consent']=False
        managed.write_private(self.instance.root/'service-config.dpapi',config)

    def begin(self):
        with patch.object(browser,'open_login',return_value={'browser':'Brave','pid':1234}) as launch:
            self.instance.begin_login('fixture-admin',8080,consent=True)
            return launch.call_args.args[1]

    def headers(self,**more):
        return {'X-OWUI-Connector':self.identity,'Origin':'chrome-extension://'+self.identity,**more}

    def payload(self,state):return {'state':state,'token':'synthetic-token-'+'x'*32,'cookies':'fixture_session='+'y'*24}

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
            result=self.client.post('/api/v1/local-providers/dsw2api/browser/check',headers=self.headers(),json={'state':state})
            self.assertEqual(result.status_code,200);self.assertTrue(result.json()['ok'])
            result=self.client.post('/api/v1/local-providers/dsw2api/browser/check',headers=self.headers(),json={'state':'f'*64})
            self.assertEqual(result.status_code,401)
        with patch.object(routes.Users,'get_user_by_id',AsyncMock(return_value=SimpleNamespace(role='user'))):
            result=self.client.post('/api/v1/local-providers/dsw2api/browser/check',headers=self.headers(),json={'state':state})
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
        self.assertNotIn(payload['token'],stored);self.assertNotIn(payload['cookies'],stored)
        altered={**payload,'token':'different-token-'+'z'*32}
        with self.assertRaises(PermissionError):self.instance.complete_login(**altered)

    def test_failed_session_validation_does_not_persist_credentials(self):
        state=self.begin()
        with patch.object(self.service.DeepSeekAdapter,'create_session',side_effect=RuntimeError('fixture failed')):
            with self.assertRaises(RuntimeError):self.instance.complete_login(**self.payload(state))
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
        for path in ['/api/v1/local-providers/dsw2api/setup','/api/v1/local-providers/dsw2api/browser/callback']:
            asyncio.run(exercise(path))

if __name__=='__main__':unittest.main()
