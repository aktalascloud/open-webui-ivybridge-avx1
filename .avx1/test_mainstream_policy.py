"""Offline regressions for mainstream browser and subagent trust boundaries."""
import ast
import copy
import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.security.utils import get_authorization_scheme_param
import jwt
from starlette.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[1] / 'backend/open_webui'


def load(path, names, scope):
    tree = ast.parse((ROOT / path).read_text('utf-8'))
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in names]
    assert len(nodes) == len(names)
    for node in nodes:
        node.decorator_list = []
    future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[])), path, 'exec'), scope)
    return scope


class SubagentPolicy(unittest.IsolatedAsyncioTestCase):
    def policy(self, configured):
        models = [{'id': 'a', 'name': 'A'}, {'id': 'b', 'name': 'B'}, {'id': 'private'}]
        return load('utils/subagents.py', {'get_subagent_models', 'subagent_request_params'}, {
            'Config': NS(get=AsyncMock(return_value=configured)),
            'get_all_models': AsyncMock(return_value=models),
            'get_filtered_models': AsyncMock(return_value=models[:2]),
        })

    async def test_old_call_keeps_admin_policy_and_user_acl(self):
        scope = self.policy([{'id': 'a'}, {'id': 'private'}, {'id': 'missing'}])
        result = await scope['get_subagent_models'](None, NS(id='user'))
        self.assertEqual([m['id'] for m in result], ['a'])

    async def test_card_can_only_narrow_admin_list(self):
        scope = self.policy([{'id': 'a'}, {'id': 'b'}])
        card = {'info': {'meta': {'subagents': {'model_ids': ['b', 'private']}}}}
        before = copy.deepcopy(card)
        result = await scope['get_subagent_models'](None, NS(id='user'), card)
        self.assertEqual([m['id'] for m in result], ['b'])
        self.assertEqual(card, before)

    async def test_card_cannot_expand_or_enable_an_empty_admin_list(self):
        for configured in ([], [{'id': 'a'}]):
            scope = self.policy(configured)
            card = {'info': {'meta': {'subagents': {'model_ids': ['b']}}}}
            self.assertEqual(await scope['get_subagent_models'](None, NS(id='user'), card), [])

    async def test_explicit_empty_card_disables_other_models(self):
        scope = self.policy([{'id': 'a'}])
        self.assertEqual(await scope['get_subagent_models'](None, NS(id='user'), {'info': {'meta': {'subagents': {'model_ids': []}}}}), [])

    def test_different_model_does_not_inherit_author_modes(self):
        scope = self.policy([])
        params = {'reasoning_effort': 'ultra', 'temperature': 0.7}
        self.assertEqual(scope['subagent_request_params']('parent', 'child', params), {})
        same = scope['subagent_request_params']('parent', 'parent', params)
        self.assertEqual(same, params)
        self.assertIsNot(same, params)


class BrowserOwner(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = NS(id='owner', role='user')
        self.users = {'owner': self.user, 'other': NS(id='other', role='user')}
        self.revoked = set()
        self.api_keys = {'sk-synthetic-owner': self.user}
        self.redis = object()
        self.path = '/api/v1/terminals/server/browser/view/session/ticket/page'
        self.allowed_api_paths = {self.path}
        self.last_api_path = None
        self.last_api_method = None
        async def valid(decoded, redis):
            self.assertIs(redis, self.redis)
            return decoded.get('jti') not in self.revoked
        async def by_key(request, key):
            self.last_api_path = request.url.path
            self.last_api_method = request.method
            if key not in self.api_keys or request.url.path not in self.allowed_api_paths:
                raise HTTPException(401)
            return self.api_keys[key]
        self.scope = {'jwt': jwt, 'uuid': uuid, 'datetime': datetime, 'UTC': timezone.utc,
                      'SESSION_SECRET': 'synthetic-browser-signing-key-' * 3, 'ALGORITHM': 'HS256',
                      'log': Mock(), 'HTTPException': HTTPException, 'Request': Request,
                      'HTTPAuthorizationCredentials': HTTPAuthorizationCredentials,
                      'get_authorization_scheme_param': get_authorization_scheme_param,
                      'is_valid_token': valid, 'get_current_user_by_api_key': by_key,
                      'Users': NS(get_user_by_id=AsyncMock(side_effect=lambda identity: self.users.get(identity))),
                      'VERIFIED_USER_ROLES': {'user', 'admin'}, 'InvalidToken': InvalidToken}
        load('utils/auth.py', {'create_token', 'decode_token', 'get_http_authorization_cred', 'get_verified_user_by_token', 'get_optional_verified_user_from_request'}, self.scope)
        load('utils/browser.py', {'browser_ticket', 'browser_access'}, self.scope)
        fernet = Fernet(Fernet.generate_key())
        oauth = ModuleType('open_webui.utils.oauth')
        oauth.encrypt_data = lambda data: fernet.encrypt(json.dumps(data).encode()).decode()
        oauth.decrypt_data = lambda data: json.loads(fernet.decrypt(data.encode()))
        self.modules = patch.dict(sys.modules, {'open_webui.utils.oauth': oauth})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def parent(self, identity='owner', expired=False):
        return self.scope['create_token']({'id': identity}, expires_delta=timedelta(seconds=-1 if expired else 3600))

    def ticket(self, parent, identity='owner'):
        return self.scope['browser_ticket']('server', identity, 'chat', {'id': 'session', 'token': 'synthetic-capability'},
                                            {'Authorization': 'Bearer synthetic-terminal-key'}, {'cookie': 'synthetic-cookie'}, owner_token=parent)

    def context(self, websocket=False):
        return NS(scope={'type': 'websocket' if websocket else 'http', 'method': 'GET', 'scheme': 'http',
                         'server': ('127.0.0.1', 8080), 'path': self.path, 'query_string': b'', 'headers': [],
                         'app': NS(state=NS(redis=self.redis)), 'state': {}})

    async def access(self, ticket, websocket=False):
        return await self.scope['browser_access']('server', 'session', ticket, self.context(websocket))

    async def test_parent_secret_is_encrypted_and_not_forwarded(self):
        parent = self.parent()
        ticket = self.ticket(parent)
        decoded = self.scope['decode_token'](ticket)
        self.assertNotIn(parent, json.dumps(decoded))
        self.assertNotIn('synthetic-terminal-key', json.dumps(decoded))
        self.assertNotIn('synthetic-capability', json.dumps(decoded))
        user, data = await self.access(ticket)
        self.assertEqual(user.id, 'owner')
        self.assertNotIn('owner_token', data['relay'])
        self.assertNotIn('capability', data['relay'])
        self.assertEqual(data['capability'], 'synthetic-capability')
        self.assertEqual(data['relay']['authorization'], 'Bearer synthetic-terminal-key')

    async def test_expired_parent_is_rejected_even_when_ticket_is_signed(self):
        with self.assertRaises(HTTPException) as error:
            await self.access(self.ticket(self.parent(expired=True)))
        self.assertEqual(error.exception.status_code, 401)

    async def test_revocation_is_rechecked_on_http_and_websocket(self):
        parent = self.parent()
        ticket = self.ticket(parent)
        await self.access(ticket)
        self.revoked.add(self.scope['decode_token'](parent)['jti'])
        for websocket in (False, True):
            with self.assertRaises(HTTPException):
                await self.access(ticket, websocket)

    async def test_api_key_rotation_and_endpoint_policy_are_rechecked(self):
        ticket = self.ticket('sk-synthetic-owner')
        await self.access(ticket, True)
        self.assertEqual(self.last_api_path, self.path)
        self.assertEqual(self.last_api_method, 'GET')
        self.allowed_api_paths.clear()
        with self.assertRaises(HTTPException):
            await self.access(ticket)
        self.allowed_api_paths.add(self.path)
        self.api_keys.clear()
        with self.assertRaises(HTTPException):
            await self.access(ticket)

    async def test_http_method_is_preserved_for_central_key_policy(self):
        request = self.context()
        request.scope['method'] = 'POST'
        await self.scope['browser_access']('server', 'session', self.ticket('sk-synthetic-owner'), request)
        self.assertEqual(self.last_api_method, 'POST')

    async def test_wrong_owner_and_unverified_role_are_rejected(self):
        with self.assertRaises(HTTPException):
            await self.access(self.ticket(self.parent('other')))
        self.users['owner'] = NS(id='owner', role='pending')
        with self.assertRaises(HTTPException):
            await self.access(self.ticket(self.parent()))

    async def test_purpose_server_session_cipher_and_old_tickets_fail_closed(self):
        ticket = self.ticket(self.parent())
        base = self.scope['decode_token'](ticket)
        for field, value in [('purpose', 'wrong'), ('server', 'other'), ('session', 'other'), ('relay', 'invalid'), ('mode', 'invalid')]:
            payload = {**base, field: value}
            with self.subTest(field=field), self.assertRaises(HTTPException):
                await self.access(self.scope['create_token'](payload))
        from open_webui.utils.oauth import encrypt_data
        with self.assertRaises(HTTPException):
            await self.access(self.scope['create_token']({**base, 'relay': encrypt_data({'cookies': {}})}))


class BrowserMode(unittest.IsolatedAsyncioTestCase):
    def route_scope(self, mode):
        self.connection = Mock()
        class Context:
            def __init__(self, value): self.value = value
            async def __aenter__(self): return self.value
            async def __aexit__(self, *args): return False
        def connect(*args, **kwargs):
            self.connection(*args, **kwargs)
            return Context(object())
        client = NS(ws_connect=connect)
        data = {'mode': mode, 'relay': {'authorization': 'Bearer synthetic-terminal-key'},
                'capability': 'synthetic-capability', 'chat': 'chat'}
        self.proxy = AsyncMock(return_value='response')
        return load('routers/terminals.py', {'browser_http', 'browser_ws'}, {
            'HTTPException': HTTPException, 'browser_access': AsyncMock(return_value=(NS(id='owner'), data)),
            'proxy_terminal': self.proxy, 'Config': NS(get=AsyncMock(return_value=[{'id': 'server'}])),
            'ENABLE_TOOL_SERVERS': True, 'has_connection_access': AsyncMock(return_value=True),
            'terminal_context_available': lambda *a: True, 'terminal_context_id': lambda *a: None,
            'terminal_context_config': lambda *a: {}, 'get_terminal_server_url': lambda *a: 'http://127.0.0.1:1',
            'quote': quote, 'AIOHTTP_CLIENT_SESSION_SSL': True, 'TERMINAL_CONTEXT_HEADER': 'context',
            'aiohttp': NS(ClientSession=lambda **k: Context(client), WSServerHandshakeError=type('HandshakeError', (Exception,), {})),
            'asyncio': asyncio, 'suppress': suppress, 'log': Mock(),
            'relay_from_browser': AsyncMock(), 'relay_to_browser': AsyncMock(), 'watch_access': AsyncMock(),
        })

    async def test_proxy_ticket_cannot_upgrade_to_chrome_and_reverse(self):
        for mode, kind in [('proxy', 'stream'), ('proxy', 'vnc'), ('chrome', 'ws')]:
            with self.subTest(mode=mode, kind=kind):
                scope = self.route_scope(mode)
                ws = NS(close=AsyncMock(), accept=AsyncMock())
                await scope['browser_ws'](ws, 'server', 'session', 'ticket', kind)
                ws.accept.assert_not_awaited()
                ws.close.assert_awaited_once_with(code=4001)
                self.connection.assert_not_called()

    async def test_each_authorized_websocket_mode_still_connects(self):
        for mode, kind in [('proxy', 'ws'), ('chrome', 'stream'), ('chrome', 'vnc')]:
            with self.subTest(mode=mode, kind=kind):
                scope = self.route_scope(mode)
                ws = NS(close=AsyncMock(), accept=AsyncMock())
                await scope['browser_ws'](ws, 'server', 'session', 'ticket', kind)
                ws.accept.assert_awaited_once()
                self.connection.assert_called_once()
                self.assertEqual(self.connection.call_args.kwargs['headers']['Authorization'], 'Bearer synthetic-terminal-key')

    async def test_http_view_is_proxy_only(self):
        for mode in ('proxy', 'chrome'):
            scope = self.route_scope(mode)
            request = NS(state=NS(), scope={'path_params': {}})
            if mode == 'chrome':
                with self.assertRaises(HTTPException):
                    await scope['browser_http'](request, 'server', 'session', 'ticket', 'frame/page')
                self.proxy.assert_not_awaited()
            else:
                self.assertEqual(await scope['browser_http'](request, 'server', 'session', 'ticket', 'frame/page'), 'response')
                self.proxy.assert_awaited_once()


class BrowserCors(unittest.IsolatedAsyncioTestCase):
    async def test_opaque_view_origin_does_not_relax_normal_api_cors(self):
        scope = load('utils/asgi_middleware.py', {'BrowserCORSMiddleware'}, {'CORSMiddleware': CORSMiddleware, 're': re})
        seen = []
        async def app(request, receive, send):
            seen.append(request['path'])
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b''})
        middleware = scope['BrowserCORSMiddleware'](app, allow_origins=['https://approved.example'])
        for path, expected in [('/api/v1/terminals/server/browser/view/session/ticket/page', 200), ('/api/v1/users', 400)]:
            sent = []
            request = {'type': 'http', 'method': 'OPTIONS', 'path': path, 'headers': [(b'origin', b'null'), (b'access-control-request-method', b'GET')]}
            await middleware(request, AsyncMock(), AsyncMock(side_effect=sent.append))
            self.assertEqual(sent[0]['status'], expected)
        self.assertEqual(seen, ['/api/v1/terminals/server/browser/view/session/ticket/page'])


if __name__ == '__main__':
    unittest.main()
