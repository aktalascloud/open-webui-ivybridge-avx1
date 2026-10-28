"""Target the new note migration/concurrency, attachment ACL and URL boundary."""
import ast
import copy
from html import escape
import json
import logging
from pathlib import Path
import re
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
import uuid
import markdown
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]/'backend/open_webui'

def load(path,names,space):
    tree=ast.parse((ROOT/path).read_text('utf-8'))
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name in names]
    assert {n.name for n in nodes}==set(names)
    future=ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future,*nodes],type_ignores=[])),str(path),'exec'),space)
    return space

class DailyRegressions(unittest.IsolatedAsyncioTestCase):
    def notes(self):
        names=['NotePageConflict','order_pages','subtree_ids','page_paths','get_content_files','migrate_page_files',
               'get_note_files','normalize_pages','get_page','document_page','apply_page_operation','update_page_content']
        return load('models/notes.py',names,dict(deepcopy=copy.deepcopy,json=json,re=re,uuid=uuid,
            markdown=markdown,BeautifulSoup=BeautifulSoup,escape=escape,time=time))

    def test_legacy_content_and_versions_migrate_without_mutating_original(self):
        s=self.notes();data={'content':{'md':'Original','html':'','json':None},'versions':[{'md':'Earlier'}]}
        frozen=copy.deepcopy(data);value=s['normalize_pages'](data,'Title')
        self.assertEqual(data,frozen);self.assertEqual(value['pages'][0]['content']['md'],'Original')
        self.assertEqual(value['pages'][0]['versions'],[{'md':'Earlier'}])
        self.assertEqual(s['normalize_pages'](value),value)

    def test_file_migration_and_html_reference_boundaries(self):
        s=self.notes();value=s['normalize_pages']({'content':{'md':'Original'},'files':[{'id':'file-1','name':'A.pdf'}]})
        self.assertEqual({f['id'] for f in s['get_note_files'](value)},{'file-1'})
        self.assertEqual(s['get_content_files']({'html':'<a href="https://example.com/api/v1/files/foreign/content">x</a>'}),[])
        self.assertEqual(s['get_content_files']({'json':{'type':'fileAttachment','attrs':{'id':'../foreign'}}}),[])

    def test_cycle_and_duplicate_pages_rejected(self):
        s=self.notes()
        for pages in [[{'id':'x','parent_id':'x'}],[{'id':'main'},{'id':'main'}]]:
            with self.assertRaises(ValueError):s['order_pages'](pages)

    def test_stale_generation_document_rejected(self):
        s=self.notes();data=s['normalize_pages']({'content':{'md':'A'}})
        data['pages'][0]['generation']=1
        for identifier in ['note:n','note:n:page:main:0']:
            with self.assertRaises(s['NotePageConflict']):s['document_page'](data,identifier)
        self.assertEqual(s['document_page'](data,'note:n:page:main:1')['id'],'main')

    def test_revisions_prevent_lost_updates_and_require_page_selection(self):
        s=self.notes();data=s['normalize_pages']({'content':{'md':'A'}})
        newer=s['update_page_content'](data,'main',{'content':{'md':'B'}},revision=0)
        self.assertEqual(s['get_page'](newer,'main')['content']['md'],'B')
        with self.assertRaises(s['NotePageConflict']):s['update_page_content'](newer,'main',{'content':{'md':'C'}},revision=0)
        op=SimpleNamespace(action='create',new_id=str(uuid.uuid4()),parent_id=None,title='Second',revision=0)
        pages=s['apply_page_operation'](newer,op)
        with self.assertRaises(s['NotePageConflict']):s['get_page'](pages)
        op=SimpleNamespace(action='delete',page_id='main',revision=1)
        with self.assertRaises(ValueError):s['apply_page_operation'](pages,op)

    async def test_new_note_attachment_requires_read_access(self):
        s=self.notes();groups=SimpleNamespace(get_groups_by_member_id=AsyncMock(return_value=[]))
        access=AsyncMock(return_value=False)
        s.update(Groups=groups,has_access_to_file=access)
        load('utils/access_control/files.py',['get_note_file_ids','has_access_to_note_files'],s)
        user=SimpleNamespace(id='editor',role='user')
        self.assertFalse(await s['has_access_to_note_files'](None,[{'type':'file','id':'foreign-file'}],user))
        access.assert_awaited_once()
        access.reset_mock()
        existing=SimpleNamespace(data=s['normalize_pages']({'content':{'html':'<a href="/api/v1/files/existing/content">A</a>'}}))
        self.assertTrue(await s['has_access_to_note_files'](existing,[{'type':'file','id':'existing'}],user))
        access.assert_not_awaited()

    def test_compressed_remote_bodies_rejected(self):
        s=load('retrieval/web/utils.py',['is_identity_encoding','assert_identity_encoding'],
               {'log':logging.getLogger('fixture'),'ERROR_MESSAGES':SimpleNamespace(COMPRESSED_RESPONSE='blocked')})
        for headers in [[],['identity'],['Identity','']]:s['assert_identity_encoding'](headers)
        for headers in [['gzip'],['br'],['identity','deflate'],['gzip, identity']]:
            with self.assertRaises(ValueError):s['assert_identity_encoding'](headers)

if __name__=='__main__':unittest.main()
