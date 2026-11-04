"""Exercise actual Responses-to-OpenAI adapter functions with synthetic events."""
import ast
import asyncio
import json
from pathlib import Path
import time
import unittest
import uuid
from typing import AsyncIterator

ROOT=Path(__file__).resolve().parents[1]/'backend/open_webui'
scope={'JSONCodec':json,'time':time,'uuid':uuid,'uuid4':uuid.uuid4,'AsyncIterator':AsyncIterator}
def load(path,names):
    tree=ast.parse((ROOT/path).read_text('utf-8'))
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
    assert len(nodes)==len(names)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),scope)
load(Path('utils/misc.py'),{'chat_completion_template','chat_completion_message_template','chat_completion_chunk_template'})
load(Path('utils/response.py'),{'usage_counter','normalize_usage','get_responses_finish_reason','convert_responses_usage_to_chat_completions','convert_responses_stream_to_chat_completions'})
load(Path('routers/openai.py'),{'convert_responses_result'})

class ResponsesClients(unittest.IsolatedAsyncioTestCase):
    async def test_stream_tool_arguments_usage_and_length(self):
        events=[{'type':'response.created','response':{'model':'fixture'}},
            {'type':'response.output_item.added','output_index':3,'item':{'type':'function_call','call_id':'call1','name':'lookup','arguments':''}},
            {'type':'response.function_call_arguments.delta','output_index':3,'delta':'{"x":1}'},
            {'type':'response.incomplete','response':{'incomplete_details':{'reason':'max_output_tokens'},'usage':{'input_tokens':7,'output_tokens':3}}}]
        async def stream():
            for event in events:yield 'data: '+json.dumps(event)+'\n\n'
        output=[line async for line in scope['convert_responses_stream_to_chat_completions'](stream())]
        chunks=[json.loads(line[6:]) for line in output if line.startswith('data: {')]
        self.assertEqual(chunks[0]['choices'][0]['delta']['tool_calls'][0]['id'],'call1')
        self.assertEqual(chunks[1]['choices'][0]['delta']['tool_calls'][0]['index'],0)
        self.assertEqual(chunks[-1]['usage']['prompt_tokens'],7)
        self.assertEqual(chunks[-1]['choices'][0]['finish_reason'],'length')
        self.assertEqual(output[-1],'data: [DONE]\n\n')
    async def test_chat_completion_passes_through(self):
        value='data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
        async def stream():yield value
        self.assertEqual([x async for x in scope['convert_responses_stream_to_chat_completions'](stream())],[value])
    def test_nonstream_usage_and_filter_reason(self):
        result=scope['convert_responses_result']({'model':'fixture','status':'incomplete','incomplete_details':{'reason':'content_filter'},'usage':{'input_tokens':8,'output_tokens':0},'output':[]})
        self.assertEqual(result['usage']['prompt_tokens'],8)
        self.assertEqual(result['usage']['completion_tokens'],0)
        self.assertEqual(result['choices'][0]['finish_reason'],'content_filter')
        self.assertIsInstance(result['created'],int)

if __name__=='__main__':unittest.main()
