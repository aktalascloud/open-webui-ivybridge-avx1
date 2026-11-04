"""Synthetic gates for upstream compaction, OAuth and bounded file reads."""
import ast
import asyncio
import copy
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1] / 'backend/open_webui'


def load(path, names, scope):
    tree = ast.parse((ROOT / path).read_text('utf-8'))
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    assert {n.name for n in nodes} == names
    future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[])), path, 'exec'), scope)
    return scope


class UpstreamChecks(unittest.IsolatedAsyncioTestCase):
    def test_numbered_read_is_bounded_and_resumable(self):
        fn = load('tools/builtin.py', {'_numbered_lines_within_cap'}, {'VIEW_FILE_MAX_CHARS': 12})['_numbered_lines_within_cap']
        text, end = fn(['abcd', 'efgh', 'ijkl'], 0, 3)
        self.assertLessEqual(len(text), 12)
        self.assertEqual((text, end), ('1: abcd', 1))
        text, end = fn(['x' * 100], 0, 1)
        self.assertEqual((len(text), end), (12, 1))

    def test_pkce_rejects_plain_and_keeps_timeout(self):
        fn = load('config.py', {'oauth_client_kwargs'}, {})['oauth_client_kwargs']
        self.assertEqual(fn('openid', '10', 'S256'), {'scope': 'openid', 'timeout': 10, 'code_challenge_method': 'S256'})
        with self.assertRaises(ValueError):
            fn('openid', 10, 'plain')

    async def test_summary_preserves_tools_and_original_payload(self):
        await self.summary_case(False)

    async def test_tool_summary_response_falls_back_without_replaying_tools(self):
        await self.summary_case(True)

    async def summary_case(self, fallback):
        module = ModuleType('open_webui.utils.chat')
        module.generate_chat_completion = AsyncMock(side_effect=[
            {'choices': [{'message': {'tool_calls': [{'id': 'unexpected'}]}}]} if fallback else
            {'choices': [{'message': {'content': 'summary'}}]},
            {'choices': [{'message': {'content': 'fallback summary'}}]},
        ])
        async def identity(value, user):
            return value
        scope = load('utils/context_compaction.py', {'_generate_summary', '_message_prefix', '_response_text'}, {
            'copy': copy, 'JSONCodec': json, 'JSONResponse': type('UnusedResponse', (), {}),
            'Config': NS(get_many=AsyncMock(return_value={})),
            'DEFAULT_CONTEXT_COMPACTION_PROMPT': 'Summarize',
            'get_content_from_message': lambda m: m.get('content', ''),
            'get_last_user_message': lambda messages: 'question',
            'replace_prompt_variable': lambda text, _: text,
            'replace_messages_variable': lambda text, *args: text,
            'prompt_variables_template': lambda text, _: text,
            'prompt_template': identity,
            'apply_params_to_form_data': lambda payload, *args: payload,
        })
        messages = [{'role': 'user', 'content': 'old'}, {'role': 'user', 'content': 'unique recent'}]
        form = {'messages': messages, 'tools': [{'type': 'function', 'function': {'name': 'lookup'}}], 'tool_choice': 'required'}
        before = copy.deepcopy(form)
        with patch.dict(sys.modules, {'open_webui.utils.chat': module}):
            result = await scope['_generate_summary'](NS(state=NS()), form, NS(), 'm', {'m': {}}, messages[:1], messages[1:], None, 'summary', True)
        self.assertEqual(form, before)
        calls = module.generate_chat_completion.call_args_list
        self.assertEqual(calls[0].kwargs['form_data']['tools'], form['tools'])
        self.assertNotIn('tool_choice', calls[0].kwargs['form_data'])
        self.assertTrue(calls[0].kwargs['bypass_system_prompt'])
        self.assertEqual(result, 'fallback summary' if fallback else 'summary')
        self.assertEqual(len(calls), 2 if fallback else 1)
        if fallback:
            self.assertNotIn('tools', calls[1].kwargs['form_data'])


if __name__ == '__main__':
    unittest.main()
