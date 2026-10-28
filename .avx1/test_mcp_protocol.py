"""Exercise the shipped MCP adapter against a real SDK ASGI server, offline."""
import ast
import asyncio
import functools
import json
from pathlib import Path
import unittest
from contextlib import asynccontextmanager

import httpx2
import mcp
from mcp.server import MCPServer

SOURCE=Path(__file__).resolve().parents[1]/'backend/open_webui/utils/mcp/client.py'


def adapter():
    tree=ast.parse(SOURCE.read_text('utf-8'))
    tree.body=[node for node in tree.body if not (
        isinstance(node,ast.ImportFrom) and (node.module or '').startswith('open_webui'))]
    scope={'AIOHTTP_CLIENT_SESSION_TOOL_SERVER_SSL':True,
           'AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER':None,'MCP_INITIALIZE_TIMEOUT':5,'JSONCodec':json}
    exec(compile(tree,str(SOURCE),'exec'),scope)
    return scope


class ProtocolCompatibility(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_transport_failure_does_not_cancel_chat_or_replay(self):
        server=MCPServer('synthetic-transport-fault',log_level='ERROR')
        @server.tool()
        def echo(query:str)->str:return query
        app=server.streamable_http_app(json_response=True,stateless_http=True)
        attempts=[]
        class FaultTransport(httpx2.ASGITransport):
            async def handle_async_request(self,request):
                body=await request.aread()
                if b'tools/call' in body:
                    attempts.append(True)
                    raise httpx2.ReadError('synthetic transport EOF',request=request)
                return await super().handle_async_request(request)
        scope=adapter()
        scope['create_httpx_client']=lambda **_:httpx2.AsyncClient(transport=FaultTransport(app=app),timeout=2)
        client=scope['MCPClient']();owner=asyncio.current_task()
        async with app.router.lifespan_context(app):
            try:
                await client.connect('http://127.0.0.1:8765/mcp')
                try:await asyncio.wait_for(client.call_tool('echo',{'query':'fixture'}),5)
                except Exception:pass
                await asyncio.sleep(.05)
                self.assertEqual(owner.cancelling(),0)
                self.assertEqual(len(attempts),1,'Uncertain tool request must not be replayed')
            finally:await client.disconnect()

    def lifecycle_fixture(self,*,fail=False,opening=None,closing=None):
        scope=adapter();owners=[]
        @asynccontextmanager
        async def http_client(**_):yield object()
        class Session:
            instructions='fixture'
            async def __aenter__(self):
                owners.append(('enter',asyncio.current_task()))
                if opening:await opening.wait()
                if fail:raise ValueError('synthetic connect failure')
                return self
            async def __aexit__(self,*_):
                owners.append(('exit',asyncio.current_task()))
                if closing:await closing.wait()
        scope.update(create_httpx_client=http_client,Client=lambda *a,**k:Session(),streamable_http_client=lambda *a,**k:object())
        return scope['MCPClient'](),owners

    async def test_disconnect_from_other_task_closes_in_session_owner(self):
        client,owners=self.lifecycle_fixture()
        await client.connect('http://127.0.0.1:8765/mcp')
        await asyncio.gather(client.disconnect(),client.disconnect())
        self.assertEqual([v[0] for v in owners],['enter','exit'])
        self.assertIs(owners[0][1],owners[1][1])
        self.assertIsNone(client.client);self.assertIsNone(client.session_task)

    async def test_failed_connect_is_clean_and_keeps_original_error(self):
        client,_=self.lifecycle_fixture(fail=True)
        with self.assertRaisesRegex(ValueError,'synthetic connect failure'):
            await client.connect('http://127.0.0.1:8765/mcp')
        self.assertIsNone(client.client);self.assertIsNone(client.session_task)

    async def test_user_cancel_during_connect_propagates_without_leak(self):
        client,_=self.lifecycle_fixture(opening=asyncio.Event())
        task=asyncio.create_task(client.connect('http://127.0.0.1:8765/mcp'))
        await asyncio.sleep(.01);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertIsNone(client.client);self.assertIsNone(client.session_task)

    async def test_user_cancel_during_disconnect_is_not_suppressed(self):
        gate=asyncio.Event();client,owners=self.lifecycle_fixture(closing=gate)
        await client.connect('http://127.0.0.1:8765/mcp');session=client.session_task
        task=asyncio.create_task(client.disconnect())
        for _ in range(100):
            if len(owners)>1:break
            await asyncio.sleep(.001)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(session.done());self.assertIsNone(client.session_task)

    async def exercise(self,mode):
        server=MCPServer('synthetic-compatibility',log_level='ERROR')

        @server.tool()
        def echo(query:str)->str:
            return query

        @server.tool()
        def failure()->str:
            raise ValueError('synthetic failure')

        @server.resource('synthetic://fixture')
        def fixture()->str:
            return 'synthetic resource'

        app=server.streamable_http_app(json_response=True,stateless_http=True)
        scope=adapter()
        scope['Client']=functools.partial(mcp.Client,mode=mode)
        scope['create_httpx_client']=lambda **_:httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),timeout=5)
        client=scope['MCPClient']()
        async with app.router.lifespan_context(app):
            try:
                await client.connect('http://127.0.0.1:8765/mcp')
                tools=await client.list_tool_specs()
                self.assertIn('echo',{item['name'] for item in tools})
                content=await client.call_tool('echo',{'query':'Русский текст'})
                self.assertTrue(any(item.get('text')=='Русский текст' for item in content))
                with self.assertRaisesRegex(Exception,'Error executing tool failure'):
                    await client.call_tool('failure',{})
                resources=await client.list_resources()
                self.assertTrue(any(str(item['uri'])=='synthetic://fixture' for item in resources))
                result=await client.read_resource('synthetic://fixture')
                self.assertIn('synthetic resource',str(result))
            finally:
                await client.disconnect()
        self.assertIsNone(client.client)

    async def test_auto_discovery_and_wire_aliases(self):
        await asyncio.wait_for(self.exercise('auto'),30)

    async def test_legacy_initialize_fallback(self):
        await asyncio.wait_for(self.exercise('legacy'),30)


if __name__=='__main__':unittest.main()
