"""Targeted gates for reviewed KB, tool-image, auth and embedding changes."""
import ast
import asyncio
import copy
import logging
from pathlib import Path
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock
import uuid
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import HTTPException,status,Response
from pydantic import BaseModel,ConfigDict
from sqlalchemy import create_engine,Column,Text,Integer,JSON,select
from sqlalchemy.orm import declarative_base,Session

ROOT=Path(__file__).resolve().parents[1]/'backend/open_webui'
def functions(path,names,scope,owner=None):
    tree=ast.parse((ROOT/path).read_text('utf-8'))
    nodes=tree.body if owner is None else next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==owner).body
    chosen=[copy.deepcopy(n) for n in nodes if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
    assert {n.name for n in chosen}==set(names)
    for n in chosen:n.decorator_list=[]
    future=ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future,*chosen],type_ignores=[])),str(path),'exec'),scope)
    return scope

class ToolImages(unittest.TestCase):
    def test_disabled_vision_strips_only_tool_images_without_mutating_saved_output(self):
        f=functions('utils/middleware.py',['strip_tool_images'],{})['strip_tool_images']
        original=[{'type':'function_call_output','call_id':'call1','output':[{'type':'input_image','image_url':'data:image/png;base64,fixture'},{'type':'input_text','text':'keep'}]}]
        before=copy.deepcopy(original);result=f(original,{'info':{'meta':{'capabilities':{'vision':False}}}})
        self.assertEqual(original,before);self.assertEqual(result[0]['call_id'],'call1')
        self.assertEqual(result[0]['output'],[{'type':'input_text','text':'\n[image]'},{'type':'input_text','text':'keep'}])
        self.assertIs(f(original,{}),original)
    def test_text_null_outputs_and_null_metadata_remain_valid(self):
        f=functions('utils/middleware.py',['strip_tool_images'],{})['strip_tool_images']
        rows=[{'type':'function_call_output','output':'plain text'},{'type':'function_call_output','output':None},{'type':'message','content':'keep'}]
        self.assertEqual(f(rows,{'info':{'meta':{'capabilities':{'vision':False}}}}),rows)
        self.assertIs(f(rows,{'info':None}),rows)

class KnowledgeProjection(unittest.IsolatedAsyncioTestCase):
    async def test_metadata_query_does_not_select_extracted_text(self):
        Base=declarative_base()
        class File(Base):
            __tablename__='file';id=Column(Text,primary_key=True);user_id=Column(Text);hash=Column(Text);filename=Column(Text);path=Column(Text);meta=Column(JSON);created_at=Column(Integer);updated_at=Column(Integer);data=Column(JSON)
        class KnowledgeFile(Base):
            __tablename__='knowledge_file';id=Column(Integer,primary_key=True);file_id=Column(Text);knowledge_id=Column(Text);directory_id=Column(Text)
        class DTO(BaseModel):
            model_config=ConfigDict(from_attributes=True)
            id:str;user_id:str;hash:str;filename:str;path:str;meta:dict;created_at:int;updated_at:int;data:dict|None=None
        engine=create_engine('sqlite://');Base.metadata.create_all(engine);queries=[]
        with Session(engine) as database:
            database.add(File(id='f',user_id='u',hash='h',filename='document.txt',path='/fixture',meta={'size':4},created_at=1,updated_at=2,data={'content':'x'*1000000}))
            database.add(KnowledgeFile(file_id='f',knowledge_id='kb',directory_id='dir'));database.commit()
            class AsyncDB:
                async def execute(self,query):queries.append(str(query));return database.execute(query)
            @asynccontextmanager
            async def context(_):yield AsyncDB()
            scope={'get_async_db_context':context,'select':select,'File':File,'KnowledgeFile':KnowledgeFile,'FileModel':DTO}
            f=functions('models/knowledge.py',['get_files_with_directory_ids'],scope,'KnowledgeTable')['get_files_with_directory_ids']
            rows=await f(None,'kb')
            self.assertEqual(len(rows),1);self.assertEqual(rows[0][0].filename,'document.txt');self.assertEqual(rows[0][1],'dir')
            self.assertIsNone(rows[0][0].data);self.assertNotIn('file.data',queries[0])
        engine.dispose()

class AdminKeyRoutes(unittest.IsolatedAsyncioTestCase):
    def fixture(self,enabled=True,permission=True,target='owner'):
        users=NS(get_user_by_id=AsyncMock(return_value=NS(id=target,role='user')),get_first_user=AsyncMock(return_value=NS(id='owner')),
                 update_user_api_key_by_id=AsyncMock(),delete_user_api_key_by_id=AsyncMock())
        scope={'Depends':lambda _:None,'get_admin_user':object(),'get_async_session':object(),'HTTPException':HTTPException,'status':status,
               'Users':users,'Config':NS(get=AsyncMock(side_effect=lambda key:enabled if key=='auth.enable_api_keys' else {})),
               'has_permission':AsyncMock(return_value=permission),'create_api_key':lambda:'fixture-new-key','publish_event':AsyncMock(),
               'EVENTS':NS(AUTH_API_KEY_CREATED='created',AUTH_API_KEY_DELETED='deleted'),
               'ERROR_MESSAGES':NS(USER_NOT_FOUND='missing',ACTION_PROHIBITED='denied',API_KEY_CREATION_NOT_ALLOWED='disabled')}
        functions('routers/users.py',['rotate_user_api_key_by_id','delete_user_api_key_by_id'],scope)
        tree=ast.parse((ROOT/'routers/users.py').read_text('utf-8'))
        for node in tree.body:
            if isinstance(node,ast.AsyncFunctionDef) and node.name in ('rotate_user_api_key_by_id','delete_user_api_key_by_id'):
                self.assertTrue(any(isinstance(x,ast.Call) and isinstance(x.func,ast.Name) and x.func.id=='Depends' and isinstance(x.args[0],ast.Name) and x.args[0].id=='get_admin_user' for x in node.args.defaults))
        return scope,users
    async def test_another_admin_cannot_rotate_first_owner(self):
        s,u=self.fixture()
        with self.assertRaises(HTTPException) as error:await s['rotate_user_api_key_by_id'](None,Response(),'owner',session_user=NS(id='other'),db=None)
        self.assertEqual(error.exception.status_code,403);u.update_user_api_key_by_id.assert_not_awaited()
    async def test_owner_rotation_no_store_and_disabled_creation(self):
        s,u=self.fixture();response=Response();result=await s['rotate_user_api_key_by_id'](None,response,'owner',session_user=NS(id='owner'),db=None)
        self.assertEqual(result,{'api_key':'fixture-new-key'});self.assertEqual(response.headers['Cache-Control'],'no-store')
        s,u=self.fixture(enabled=False)
        with self.assertRaises(HTTPException):await s['rotate_user_api_key_by_id'](None,Response(),'owner',session_user=NS(id='owner'),db=None)
        u.update_user_api_key_by_id.assert_not_awaited()
    async def test_revocation_stays_available_when_creation_disabled(self):
        s,u=self.fixture(enabled=False,permission=False,target='member')
        self.assertTrue(await s['delete_user_api_key_by_id'](None,'member',session_user=NS(id='owner'),db=None));u.delete_user_api_key_by_id.assert_awaited_once_with('member',db=None)

class EmbeddingBuffers(unittest.TestCase):
    def exercise(self,fail=False,add=False):
        loop=asyncio.new_event_loop();thread=threading.Thread(target=loop.run_forever,daemon=True);thread.start()
        calls=[];inserted=[];deleted=[]
        async def embedding(texts,**kwargs):
            calls.append(texts)
            if fail and len(calls)==2:raise RuntimeError('synthetic provider failure')
            return [[1,2] for _ in texts]
        client=NS(has_collection=lambda **_:False,insert=lambda **kwargs:inserted.extend(kwargs['items']),
                  delete=lambda **kwargs:deleted.append(('ids',kwargs['ids'])),delete_collection=lambda **_:deleted.append(('collection',None)))
        log=logging.getLogger('silent-embedding-fixture');log.disabled=True
        scope={'log':log,'sanitize_text_for_db':lambda s:s,'get_vector_db_client':lambda:client,'get_embedding_function':lambda *a,**k:embedding,
               'RAG_EMBEDDING_BUFFER_SIZE':3,'RAG_EMBEDDING_TIMEOUT':5,'asyncio':asyncio,'time':time,'uuid':uuid}
        f=functions('routers/retrieval.py',['save_docs_to_vector_db'],scope)['save_docs_to_vector_db']
        config={'rag.embedding_engine':'openai','rag.embedding_model':'fixture','rag.openai.api_base_url':'http://fixture.invalid',
                'rag.openai.api_key':'fixture','rag.embedding_batch_size':2,'rag.embedding_content_prefix':'','rag.embedding_concurrent_requests':1,'rag.enable_async_embedding':True}
        request=NS(app=NS(state=NS(ef=None,main_loop=loop)));docs=[NS(page_content='chunk'+str(i),metadata={'position':i}) for i in range(5)]
        try:
            if fail:
                with self.assertRaisesRegex(RuntimeError,'synthetic'):f(request,docs,'fixture',config,split=False,add=add)
            else:self.assertTrue(f(request,docs,'fixture',config,split=False))
            return calls,inserted,deleted
        finally:loop.call_soon_threadsafe(loop.stop);thread.join();loop.close()
    def test_buffered_batches_keep_all_text_and_metadata_in_order(self):
        calls,items,deleted=self.exercise();self.assertEqual(list(map(len,calls)),[4,1]);self.assertEqual([x['metadata']['position'] for x in items],list(range(5)));self.assertEqual(deleted,[])
    def test_partial_failure_rolls_back_only_new_items_or_new_collection(self):
        for add in (True,False):
            calls,items,deleted=self.exercise(fail=True,add=add)
            self.assertEqual(len(items),4);self.assertEqual(deleted[0][0],'ids' if add else 'collection')
            if add:self.assertEqual(set(deleted[0][1]),{x['id'] for x in items})

if __name__=='__main__':unittest.main()
