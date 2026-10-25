"""Check actual MCP 2 imports, constructor signatures and wire aliases."""
import argparse
import ast
import inspect
import importlib
import json
from pathlib import Path

parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);args=parser.parse_args()
bindings={}
checked=[]
for relative in ('utils/mcp/client.py','utils/oauth.py'):
    tree=ast.parse((args.source/relative).read_text('utf-8'))
    for node in ast.walk(tree):
        if isinstance(node,ast.ImportFrom) and (node.module or '').startswith('mcp'):
            module=importlib.import_module(node.module)
            for alias in node.names:bindings[alias.asname or alias.name]=getattr(module,alias.name)
    for node in ast.walk(tree):
        if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Name) or node.func.id not in bindings:continue
        if any(isinstance(value,ast.Starred) for value in node.args) or any(item.arg is None for item in node.keywords):
            raise RuntimeError('MCP call argument expansion requires a new compatibility review')
        inspect.signature(bindings[node.func.id]).bind(*[object() for _ in node.args],**{item.arg:object() for item in node.keywords})
        checked.append({'symbol':node.func.id,'source':relative})
if not {'Client','streamable_http_client'}.issubset({item['symbol'] for item in checked}):
    raise RuntimeError('MCP transport/client constructor was not checked')
from mcp.types import CallToolResult,TextContent,Tool
reply=CallToolResult(content=[TextContent(type='text',text='synthetic')],isError=True)
assert reply.is_error and reply.model_dump(mode='json',by_alias=True)['isError'] is True
tool=Tool(name='synthetic',inputSchema={'type':'object','properties':{}})
assert tool.input_schema=={'type':'object','properties':{}}
print(json.dumps({'mcp_symbols':'imported','calls_checked':checked,'wire_aliases':'passed'}))
