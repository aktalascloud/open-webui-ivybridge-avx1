"""Exercise the shipped MCP adapter against a real SDK ASGI server, offline."""
import ast
import asyncio
import functools
import json
from pathlib import Path
import unittest

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
