"""Free-model allowlist and actual outbound identity isolation; offline only."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace as NS
from fastapi import HTTPException
from test_daily_20261030 import load

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('free_llm_policy', ROOT/'backend/open_webui/utils/free_llm.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class FreeLLM(unittest.IsolatedAsyncioTestCase):
    def test_only_three_reviewed_models_and_no_paid_or_credential_fallback(self):
        cfg={'provider':'freellm','auth_type':'none'}
        models=[m['id'] for m in policy.CATALOG['models']]
        self.assertEqual(len(set(models)),3)
        self.assertEqual(len({m['vendor'] for m in policy.CATALOG['models']}),3)
        for model in models:policy.check_free_llm_request(cfg,policy.CATALOG['base_url'],'',model)
        for override in ({'auth_type':'session'},{'headers':{'Authorization':'secret'}},
                         {'forward_cookies':True},{'azure':True},{'api_type':'responses'}):
            with self.assertRaises(HTTPException):policy.check_free_llm_request({**cfg,**override},policy.CATALOG['base_url'])
        for url,key,model in [('http://127.0.0.1/v1','',models[0]),
                              (policy.CATALOG['base_url'],'secret',models[0]),
                              (policy.CATALOG['base_url'],'','paid/model')]:
            with self.assertRaises(HTTPException):policy.check_free_llm_request(cfg,url,key,model)
        policy.check_free_llm_request({'provider':'other'},'http://local','unchanged','other-model')

    def test_private_routing_identity_is_not_part_of_the_cloud_payload(self):
        body={'model':policy.CATALOG['models'][0]['id'],'messages':[{'role':'user','content':'fixture'}],
              'user':'private-user','metadata':{'chat_id':'private-chat'},'temperature':.6}
        before=copy.deepcopy(body)
        clean=policy.prepare_free_llm_payload({'provider':'freellm','auth_type':'none'},policy.CATALOG['base_url'],'',body)
        self.assertNotIn('user',clean);self.assertNotIn('metadata',clean)
        self.assertEqual(clean['messages'],body['messages']);self.assertEqual(clean['temperature'],.6)
        self.assertEqual(body,before)
        self.assertIs(policy.prepare_free_llm_payload({'provider':'other'},'local','key',body),body)

    async def test_actual_header_builder_never_reads_or_forwards_private_identity(self):
        scope={'ENABLE_FORWARD_USER_INFO_HEADERS':True,
               'get_custom_headers':AsyncMock(side_effect=AssertionError('Private headers evaluated')),
               'get_system_oauth_token':AsyncMock(side_effect=AssertionError('OAuth evaluated'))}
        load('utils/headers.py',['get_headers_and_cookies'],scope)
        request=NS(cookies={'private':'cookie'},state=NS(token=NS(credentials='private-session')))
        user=NS(id='private-user',email='private@example.invalid',name='Private',role='admin')
        config={'provider':'freellm','auth_type':'none'};before=copy.deepcopy(config)
        with patch.dict(sys.modules,{'open_webui.utils.free_llm':policy}):
            headers,cookies=await scope['get_headers_and_cookies'](request,policy.CATALOG['base_url'],'',config,{'chat_id':'private-chat'},user=user)
        self.assertEqual(headers,{'Content-Type':'application/json'});self.assertEqual(cookies,{})
        self.assertEqual(config,before)
        scope['get_custom_headers'].assert_not_awaited();scope['get_system_oauth_token'].assert_not_awaited()


if __name__=='__main__':unittest.main()
