"""Offline regressions for new MCP app authorization, KB limits and tool rounds."""
import ast
import asyncio
import copy
import hmac
import json
from pathlib import Path
import re
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator, ValidationError
from typing import Literal

ROOT = Path(__file__).resolve().parents[1] / 'backend/open_webui'


def load(path, names, scope):
    tree = ast.parse((ROOT / path).read_text('utf-8'))
    chosen = [copy.deepcopy(n) for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    assert {n.name for n in chosen} == set(names)
    for node in chosen:
        node.decorator_list = []
    future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future, *chosen], type_ignores=[])), path, 'exec'), scope)
    return scope


class MCPApps(unittest.IsolatedAsyncioTestCase):
    def fixture(self, binding=True, app_visible=True):
        definitions = {'origin': {'name': 'origin', '_meta': {'ui': {'resourceUri': 'ui://fixture'}}},
                       'action': {'name': 'action', '_meta': {'ui': {'visibility': ['app'] if app_visible else ['model']}}}}
        client = NS(tool_definitions=definitions, disconnect=AsyncMock(), call_tool_raw=AsyncMock(return_value={'content': []}),
                    read_resource=AsyncMock(return_value={'contents': []}))
        scope = {'BaseModel': BaseModel, 'ConfigDict': ConfigDict, 'Field': Field, 'model_validator': model_validator,
                 'Literal': Literal, 'Depends': lambda _: None, 'get_verified_user': object(),
                 'HTTPException': HTTPException, 'asyncio': asyncio,
                 'verify_app_binding': lambda *args: binding,
                 'connect_mcp_server': AsyncMock(return_value=(client, []))}
        load('utils/mcp/apps.py', ['ui_metadata', 'ui_resource_uri'], scope)
        load('utils/mcp/client.py', ['tool_visible_to'], scope)
        load('routers/tools.py', ['MCPAppRPCForm', 'mcp_app_rpc'], scope)
        scope['MCPAppRPCForm'].model_rebuild(_types_namespace=scope)
        return scope, client

    def form(self, scope, **values):
        return scope['MCPAppRPCForm'](tool_name='origin', binding='a' * 64,
                                    method='tools/call', params={'name': 'action', 'arguments': {}}, **values)

    async def test_bad_binding_never_opens_mcp_connection(self):
        s, client = self.fixture(binding=False)
        with self.assertRaises(HTTPException) as error:
            await s['mcp_app_rpc'](None, 'server:mcp:fixture', self.form(s), NS(id='viewer'))
        self.assertEqual(error.exception.status_code, 403)
        s['connect_mcp_server'].assert_not_awaited()
        client.call_tool_raw.assert_not_awaited()

    async def test_app_cannot_call_model_only_tool_and_connection_closes(self):
        s, client = self.fixture(app_visible=False)
        with self.assertRaises(HTTPException) as error:
            await s['mcp_app_rpc'](None, 'server:mcp:fixture', self.form(s), NS(id='viewer'))
        self.assertEqual(error.exception.status_code, 403)
        client.call_tool_raw.assert_not_awaited()
        client.disconnect.assert_awaited_once()

    async def test_allowed_call_uses_current_user_once(self):
        s, client = self.fixture()
        user = NS(id='viewer')
        await s['mcp_app_rpc'](None, 'server:mcp:fixture', self.form(s), user)
        s['connect_mcp_server'].assert_awaited_once_with(None, 'fixture', user, {})
        client.call_tool_raw.assert_awaited_once_with('action', {})
        client.disconnect.assert_awaited_once()

    async def test_failed_uncertain_call_is_not_replayed(self):
        s, client = self.fixture()
        s['log'] = NS(warning=lambda *args: None)
        client.call_tool_raw.side_effect = RuntimeError('synthetic uncertain outcome')
        with self.assertRaises(HTTPException) as error:
            await s['mcp_app_rpc'](None, 'server:mcp:fixture', self.form(s), NS(id='viewer'))
        self.assertEqual(error.exception.status_code, 502)
        self.assertEqual(client.call_tool_raw.await_count, 1)
        client.disconnect.assert_awaited_once()

    def test_form_rejects_arbitrary_rpc_and_extra_arguments(self):
        s, _ = self.fixture()
        for method, params in [('shell/exec', {}), ('tools/call', {'name': 'action', 'shell': 'bad'}), ('resources/read', {'uri': 42})]:
            with self.assertRaises(ValidationError):
                s['MCPAppRPCForm'](tool_name='origin', binding='a'*64, method=method, params=params)

    def test_csp_injection_and_cross_tool_binding_rejected(self):
        s = {'hmac': hmac, 'JSONCodec': json, 'WEBUI_SECRET_KEY': 'synthetic',
             '_DOMAIN': re.compile(r'(?:https?|wss?)://(?:\*\.)?(?:[a-zA-Z0-9.-]+|\[[a-fA-F0-9:]+\])(?::[0-9]{1,5})?')}
        load('utils/mcp/apps.py', ['app_csp', 'app_binding', 'verify_app_binding'], s)
        token = s['app_binding']('server1', 'tool1')
        self.assertFalse(s['verify_app_binding']('server2', 'tool1', token))
        self.assertFalse(s['verify_app_binding']('server1', 'tool2', token))
        for domain in ["https://example.org; script-src *", 'javascript:alert(1)', 'https://example.org/path']:
            with self.assertRaises(ValueError):
                s['app_csp']({'csp': {'connectDomains': [domain]}})
        self.assertIn("connect-src 'none'", s['app_csp']({}))


class KnowledgeLimits(unittest.IsolatedAsyncioTestCase):
    async def test_pending_uploads_count_and_existing_files_are_excluded(self):
        config = NS(get=AsyncMock(return_value=None))
        knowledge = NS(get_knowledge_by_id=AsyncMock(return_value=NS(meta={})),
                       get_file_limits=AsyncMock(return_value={'max_file_count': 2, 'max_file_size': None}),
                       get_file_count_by_id=AsyncMock(return_value=2))
        s = {'Config': config, 'Knowledges': knowledge, 'HTTPException': HTTPException}
        load('routers/knowledge.py', ['check_knowledge_upload_limits'], s)
        with self.assertRaises(HTTPException) as error:
            await s['check_knowledge_upload_limits']('kb', 1, exclude_file_ids=['already-pending'])
        self.assertEqual(error.exception.status_code, 400)
        knowledge.get_file_count_by_id.assert_awaited_once_with('kb', include_pending=True, exclude_file_ids=['already-pending'], db=None)

    async def test_oversized_file_rejected_before_embedding(self):
        s = {'Config': NS(get=AsyncMock(return_value=None)), 'HTTPException': HTTPException,
             'ERROR_MESSAGES': NS(FILE_TOO_LARGE=lambda **_: 'too large'),
             'Knowledges': NS(get_knowledge_by_id=AsyncMock(return_value=NS(meta={})),
                             get_file_limits=AsyncMock(return_value={'max_file_count': None, 'max_file_size': 1}))}
        load('routers/knowledge.py', ['check_knowledge_upload_limits'], s)
        with self.assertRaises(HTTPException) as error:
            await s['check_knowledge_upload_limits']('kb', 1, file_size=1024*1024+1)
        self.assertEqual(error.exception.status_code, 413)


class ToolRounds(unittest.TestCase):
    def test_reused_call_id_does_not_merge_separate_rounds(self):
        s = load('utils/session_records.py', ['normalize_tool_output', 'pair_results'], {})
        rows = [{'type': 'function_call', 'call_id': 'same', 'status': 'completed'},
                {'type': 'function_call_output', 'call_id': 'same', 'output': 'first', 'duration': 1},
                {'type': 'function_call', 'call_id': 'same', 'status': 'rejected'},
                {'type': 'function_call_output', 'call_id': 'same', 'output': 'second', 'duration': 2}]
        before = copy.deepcopy(rows)
        result = s['normalize_tool_output'](rows)
        self.assertEqual(rows, before)
        self.assertEqual(len(result), 4)
        self.assertEqual(result[0]['duration'], 1)
        self.assertEqual(result[2]['duration'], 2)
        self.assertEqual(result[2]['status'], 'rejected')


if __name__ == '__main__':
    unittest.main()
