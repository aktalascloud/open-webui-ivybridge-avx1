"""Run actual patched function bodies with synthetic RPC/permission boundaries."""
import ast
import copy
import json
from pathlib import Path
import types
import unittest
from unittest.mock import AsyncMock
ROOT=Path(__file__).resolve().parents[1]/'backend/open_webui'

def function(path,name,namespace,legacy=False):
    tree=ast.parse((ROOT/path).read_text('utf-8'))
    node=copy.deepcopy(next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name==name))
    node.decorator_list=[];node.returns=None
    for arg in [*node.args.posonlyargs,*node.args.args,*node.args.kwonlyargs]:arg.annotation=None
    if legacy:
        factory=ast.FunctionDef(name='factory',args=ast.arguments(posonlyargs=[],args=[],kwonlyargs=[],kw_defaults=[],defaults=[]),
            body=[ast.Assign(targets=[ast.Name(id='skip_files',ctx=ast.Store())],value=ast.Constant(False)),node,ast.Return(ast.Name(id=name,ctx=ast.Load()))],decorator_list=[])
        module=ast.Module(body=[factory],type_ignores=[])
    else:module=ast.Module(body=[node],type_ignores=[])
    exec(compile(ast.fix_missing_locations(module),str(path),'exec'),namespace)
    return namespace['factory']() if legacy else namespace[name]

class AgentPRs(unittest.IsolatedAsyncioTestCase):
    async def native(self,kind,params,spec):
        captured=[]
        async def target(**kwargs):captured.append(kwargs);return 'ok'
        async def update(function,extra_params):return function
        space={'resolve_tool_call':lambda *_:None,'JSONCodec':json,'ast':ast,'log':types.SimpleNamespace(debug=lambda *_:None),
               'is_saved_chat_id':lambda _:True,'get_updated_tool_function':update}
        call=function(Path('utils/middleware.py'),'execute_tool_call',space)
        tool={'type':kind,'callable':target,'spec':{'parameters':spec}}
        result=await call({'messages':[]},{'tools':{'demo':tool}},None,{'function':{'name':'demo','arguments':json.dumps(params)}})
        self.assertEqual(result[1],'ok');return captured[0]

    async def test_native_mcp_alternative_schema_keeps_arguments(self):
        params=await self.native('mcp',{'query':'kept'},{'anyOf':[{'properties':{'query':{'type':'string'}}}]})
        self.assertEqual(params,{'query':'kept'})

    async def test_native_functions_still_remove_unlisted_arguments(self):
        params=await self.native('function',{'query':'kept','unlisted':'drop'},{'properties':{'query':{}}})
        self.assertEqual(params,{'query':'kept'})

    async def test_legacy_mcp_and_function_boundaries(self):
        for kind,expected in [('mcp',{'query':'kept','other':1}),('function',{'query':'kept'})]:
            captured=[]
            async def target(**kwargs):captured.append(kwargs);return 'ok'
            async def result(*args):return args[2],[],[]
            space={'tools':{'demo':{'type':kind,'callable':target,'spec':{'parameters':{'properties':{'query':{}}}}}},
                'log':types.SimpleNamespace(debug=lambda *_:None,warning=lambda *_:None),'process_tool_result':result,
                'request':None,'metadata':{},'user':None,'event_emitter':None,'sources':[]}
            call=function(Path('utils/middleware.py'),'tool_call_handler',space,legacy=True)
            await call({'name':'demo','parameters':{'query':'kept','other':1}})
            self.assertEqual(captured,[expected])

    async def test_mcp_errors_are_plain_readable_text(self):
        for content,expected in [([{'type':'text','text':'Permission denied'},{'type':'image','data':'synthetic'}],'Permission denied'),([], 'MCP tool call returned an error.')]:
            reply=types.SimpleNamespace(isError=True,model_dump=lambda **_: {'content':content})
            session=types.SimpleNamespace(call_tool=AsyncMock(return_value=reply))
            call=function(Path('utils/mcp/client.py'),'call_tool',{'AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER':None,'JSONCodec':json})
            with self.assertRaisesRegex(Exception,expected):await call(types.SimpleNamespace(session=session),'demo',{})

    async def test_mcp_success_content_remains_unchanged(self):
        content=[{'type':'text','text':'[1, 2]'}]
        reply=types.SimpleNamespace(isError=False,model_dump=lambda **_: {'content':content,'structuredContent':{'result':[1,2]}})
        call=function(Path('utils/mcp/client.py'),'call_tool',{'AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER':None,'JSONCodec':json})
        result=await call(types.SimpleNamespace(session=types.SimpleNamespace(call_tool=AsyncMock(return_value=reply))),'demo',{})
        self.assertEqual(result,content)

    async def test_api_sharing_permission_and_admin_behavior(self):
        grants=[{'principal_type':'user','principal_id':'synthetic-other','permission':'read'}]
        for role,allowed,expected in [('user',False,[]),('user',True,grants),('admin',False,grants)]:
            permission=AsyncMock(side_effect=lambda uid,key,defaults,db=None:allowed if key=='sharing.tools' else True)
            space={'has_anyone_read_access_grant':lambda _:False,'has_public_read_access_grant':lambda _:False,
                   'has_public_write_access_grant':lambda _:False,'has_user_access_grant':lambda _:True,'has_permission':permission}
            call=function(Path('utils/access_control/__init__.py'),'filter_allowed_access_grants',space)
            result=await call({},'synthetic-user',role,grants,'sharing.public_tools',sharing_permission_key='sharing.tools')
            self.assertEqual(result,expected)
            if role=='admin':permission.assert_not_awaited()

    async def test_legacy_positional_database_parameter_stays_compatible(self):
        call=function(Path('utils/access_control/__init__.py'),'filter_allowed_access_grants',{})
        self.assertEqual(await call({},'synthetic','user',[],'sharing.public_tools',None,object()),[])

if __name__=='__main__':unittest.main()
