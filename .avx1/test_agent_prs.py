"""Run actual patched function bodies with synthetic RPC/permission boundaries."""
import ast
import copy
import json
import math
from pathlib import Path
import types
import time
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
               'is_saved_chat_id':lambda _:True,'get_updated_tool_function':update,'time':time}
        call=function(Path('utils/middleware.py'),'execute_tool_call',space)
        tool={'type':kind,'callable':target,'spec':{'parameters':spec}}
        result=await call({'messages':[]},{'tools':{'demo':tool}},None,{'type':'function_call','name':'demo','arguments':json.dumps(params),'call_id':'fixture-call'})
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
            reply=types.SimpleNamespace(is_error=True,model_dump=lambda **_: {'content':content})
            session=types.SimpleNamespace(call_tool=AsyncMock(return_value=reply))
            call=function(Path('utils/mcp/client.py'),'call_tool',{'AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER':None,'JSONCodec':json,'math':math})
            with self.assertRaisesRegex(Exception,expected):await call(types.SimpleNamespace(client=session),'demo',{})

    async def test_ephemeral_native_call_cannot_execute_without_explicit_approval(self):
        target=AsyncMock(return_value='must not execute')
        call=function(Path('utils/middleware.py'),'execute_tool_call',{'JSONCodec':json,'ast':ast,
                      'is_saved_chat_id':lambda _:False,'log':types.SimpleNamespace(debug=lambda *_:None)})
        metadata={'params':{'tool_approval_mode':'ask'},'tools':{'demo':{'type':'function','callable':target,'spec':{'parameters':{'properties':{}}}}}}
        result=await call({'messages':[]},metadata,None,{'type':'function_call','name':'demo','arguments':'{}'})
        self.assertIn('not approved',result[1]);target.assert_not_awaited()

    async def test_mcp_success_content_remains_unchanged(self):
        content=[{'type':'text','text':'[1, 2]'}]
        reply=types.SimpleNamespace(is_error=False,model_dump=lambda **_: {'content':content,'structuredContent':{'result':[1,2]}})
        call=function(Path('utils/mcp/client.py'),'call_tool',{'AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER':None,'JSONCodec':json,'math':math})
        rpc=AsyncMock(return_value=reply)
        result=await call(types.SimpleNamespace(client=types.SimpleNamespace(call_tool=rpc)),'demo',{})
        self.assertEqual(result,content)
        self.assertEqual(rpc.call_args.kwargs['read_timeout_seconds'],math.inf)

    def sharing(self, permissions):
        path=Path('utils/access_control/__init__.py')
        tree=ast.parse((ROOT/path).read_text('utf-8'))
        policy=next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_SHARING_PERMISSION_KEYS' for t in n.targets))
        class Denied(Exception):
            def __init__(self,status_code,detail):self.status_code=status_code;super().__init__(detail)
        space={'_SHARING_PERMISSION_KEYS':ast.literal_eval(policy),'normalize_access_grants':lambda grants:[dict(g) for g in grants],
               'strip_anyone_access_grants':lambda grants:[g for g in grants if g['principal_type']!='anyone'],
               'get_permissions':AsyncMock(return_value=permissions),'HTTPException':Denied}
        call=function(path,'filter_allowed_access_grants',space)
        return call,space,Denied

    async def test_api_sharing_permission_and_admin_behavior(self):
        grants=[{'principal_type':'user','principal_id':'synthetic-other','permission':'read'}]
        for role,allowed,expected in [('user',False,[]),('user',True,grants),('admin',False,grants)]:
            call,space,_=self.sharing({'sharing':{'tools':allowed},'access_grants':{'allow_users':True}})
            self.assertEqual(await call({},'synthetic-user',role,grants,resource_type='tool'),expected)
            if role=='admin':space['get_permissions'].assert_not_awaited()

    async def test_legacy_positional_database_parameter_stays_compatible(self):
        call,space,_=self.sharing({'sharing':{'tools':True},'access_grants':{'allow_users':True}})
        database=object();grants=[{'principal_type':'user','principal_id':'synthetic-other','permission':'read'}]
        self.assertEqual(await call({},'synthetic','user',grants,'sharing.public_tools',None,database),grants)
        self.assertIs(space['get_permissions'].call_args.kwargs['db'],database)

    async def test_public_and_group_audiences_cannot_bypass_permissions(self):
        grants=[{'principal_type':'user','principal_id':'*','permission':'read'},
                {'principal_type':'group','principal_id':'group-1','permission':'write'},
                {'principal_type':'user','principal_id':'user-1','permission':'read'}]
        call,_,_=self.sharing({'sharing':{'tools':True,'public_tools':False},'access_grants':{'allow_users':True,'allow_groups':False}})
        self.assertEqual(await call({},'synthetic','user',grants,'tool'),grants[2:])

    async def test_resource_policy_rejects_mismatch_and_unknown_type(self):
        call,_,_=self.sharing({})
        for kind,sharing in [('unknown',None),('tool','sharing.models')]:
            with self.assertRaises(ValueError):
                await call({},'synthetic','admin',[],kind,sharing_permission_key=sharing)

    async def test_unsupported_public_or_anonymous_audience_is_removed_even_for_admin(self):
        call,_,_=self.sharing({})
        grants=[{'principal_type':'anyone','principal_id':'*','permission':'read'},
                {'principal_type':'user','principal_id':'*','permission':'read'},
                {'principal_type':'user','principal_id':'user-1','permission':'read'}]
        self.assertEqual(await call({},'synthetic','admin',grants,'folder'),grants[2:])

    async def test_update_validation_denies_unauthorized_changes_instead_of_silently_stripping(self):
        call,space,Denied=self.sharing({'sharing':{'tools':False},'access_grants':{'allow_users':True}})
        validate=function(Path('utils/access_control/__init__.py'),'validate_access_grants',space)
        grants=[{'principal_type':'user','principal_id':'other','permission':'read'}]
        with self.assertRaises(Denied) as error:await validate({},'synthetic','user',grants,'tool')
        self.assertEqual(error.exception.status_code,403)
        self.assertEqual(grants[0]['principal_id'],'other')

if __name__=='__main__':unittest.main()
