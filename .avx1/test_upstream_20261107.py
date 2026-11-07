"""Synthetic native-login and tool-approval boundaries; no agents or providers started."""
import ast
import base64
import hashlib
import hmac
import json
from pathlib import Path
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock
from urllib.parse import urlsplit
from uuid import UUID
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, ValidationError

ROOT=Path(__file__).resolve().parents[1]/'backend/open_webui'


def load(path,names,scope):
    nodes=[n for n in ast.parse((ROOT/path).read_text('utf-8')).body
           if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name in names]
    assert {n.name for n in nodes}==names
    for n in nodes:n.decorator_list=[]
    future=ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future,*nodes],type_ignores=[])),path,'exec'),scope)
    return scope


class UpstreamBoundaries(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_auto_preserves_ask_and_invalid_modes_fail(self):
        s=load('utils/tool_permissions.py',{'resolve_tool_approval_mode'},
               {'Config':NS(get_many=AsyncMock(return_value={'chat.tool_permissions.enable':True,'chat.tool_permissions.auto.enable':False})),
                'HTTPException':HTTPException})
        self.assertEqual(await s['resolve_tool_approval_mode']('auto'),'ask')
        self.assertEqual(await s['resolve_tool_approval_mode']('ask'),'ask')
        with self.assertRaises(HTTPException):await s['resolve_tool_approval_mode']('unknown')
        with self.assertRaises(HTTPException):await s['resolve_tool_approval_mode']('auto',is_channel_chat=True)

    async def test_changed_approved_call_always_requires_fresh_human_approval(self):
        post=AsyncMock(side_effect=AssertionError('no provider request'))
        s=load('utils/tool_permissions.py',{'requires_tool_approval','tool_permission_fingerprint'},
               {'hashlib':hashlib,'JSONCodec':json,'post_decisions':post})
        call={'name':'write','approved':True,'approval_fingerprint':'old'}
        self.assertTrue(await s['requires_tool_approval']({}, {'params':{'tool_approval_mode':'auto'}},call,{'type':'builtin','spec':{}},{'path':'fixture'}))
        self.assertEqual(call['permission_review']['reason'],'call_changed');post.assert_not_awaited()

    def test_native_login_callback_accepts_only_exact_loopback_without_credentials(self):
        scope={'BaseModel':BaseModel,'ConfigDict':ConfigDict,'Field':Field,'field_validator':field_validator,'urlsplit':urlsplit}
        s=load('routers/sessions.py',{'SessionForm','AuthorizationRequest'},scope)
        args={'name':'synthetic','state':'s'*32,'code_challenge':'c'*43}
        s['AuthorizationRequest'](**args,redirect_uri='http://127.0.0.1:1234/callback')
        for url in ['https://example.invalid/callback','http://localhost:1234/callback','http://user@127.0.0.1:1234/','http://127.0.0.1:1234/?q=x','http://127.0.0.1:1234/#x']:
            with self.assertRaises(ValidationError):s['AuthorizationRequest'](**args,redirect_uri=url)

    async def exchange_case(self,wrong_owner):
        sid=UUID('12345678-1234-1234-1234-123456789abc');verifier='v'*43;code='synthetic-code'
        authorization={'code_hash':hashlib.sha256(code.encode()).hexdigest(),'redirect_uri':'http://127.0.0.1:1234/callback',
                       'code_challenge':base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()}
        row=NS(user_id='owner',refresh_token_id=None,data={'authorization':authorization},expires_at=time.time()+600,id=str(sid))
        sessions=NS(get=AsyncMock(return_value=row),change=AsyncMock(return_value=False))
        proof=AsyncMock(return_value={});credentials=Mock();columns=MagicMock();columns.expires_at.__gt__.return_value=True
        s=load('routers/sessions.py',{'exchange','digest','challenge'},
               {'hashlib':hashlib,'base64':base64,'hmac':hmac,'time':time,'AuthSessions':sessions,'AuthSession':columns,
                'decode_token':lambda _: {'typ':'session_code','sid':str(sid),'id':'intruder' if wrong_owner else 'owner'},
                'HTTPException':HTTPException,'verify_proof':proof,'idle_expiry':AsyncMock(return_value=int(time.time())+600),
                'throttle':AsyncMock(),'uuid4':lambda:'next-id','credentials':credentials})
        with self.assertRaises(HTTPException) as failure:
            await s['exchange'](NS(session_id=sid,code=code,code_verifier=verifier,redirect_uri=authorization['redirect_uri']),NS())
        self.assertEqual(failure.exception.status_code,401);credentials.assert_not_called()
        if wrong_owner:sessions.change.assert_not_awaited();proof.assert_not_awaited()
        else:sessions.change.assert_awaited_once()

    async def test_native_exchange_rejects_other_owner(self):await self.exchange_case(True)
    async def test_native_exchange_rejects_already_consumed_atomic_claim(self):await self.exchange_case(False)


if __name__=='__main__':unittest.main()
