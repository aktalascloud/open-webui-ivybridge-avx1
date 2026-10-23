"""Check the SDK symbols and call signatures actually used by the OWUI client."""
import argparse
import ast
import inspect
import json
from pathlib import Path

from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from mcp.types import ElicitRequestFormParams, ElicitResult

parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);args=parser.parse_args()
bindings={'ClientSession':ClientSession,'OAuthClientProvider':OAuthClientProvider,'streamablehttp_client':streamablehttp_client}
checked=[]
for relative in ('utils/mcp/client.py','utils/oauth.py'):
    tree=ast.parse((args.source/relative).read_text('utf-8'))
    for node in ast.walk(tree):
        if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Name) or node.func.id not in bindings:continue
        if any(isinstance(value,ast.Starred) for value in node.args) or any(item.arg is None for item in node.keywords):
            raise RuntimeError('MCP call argument expansion requires a new compatibility review')
        inspect.signature(bindings[node.func.id]).bind(*[object() for _ in node.args],**{item.arg:object() for item in node.keywords})
        checked.append({'symbol':node.func.id,'source':relative})
if not any(item['symbol']=='ClientSession' for item in checked):raise RuntimeError('MCP client session call was not checked')
print(json.dumps({'mcp_symbols':'imported','calls_checked':checked}))
