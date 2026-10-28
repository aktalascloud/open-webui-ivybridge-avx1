"""Offline Authlib upgrade gates: signing, audience and OAuth request setup."""
import time
import unittest
from urllib.parse import parse_qs,urlsplit
from authlib.integrations.starlette_client import OAuth
from authlib.jose import JsonWebToken
from authlib.jose.errors import JoseError

class AuthlibSecurity(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        jwt=JsonWebToken(['HS256'])
        key=b'x'*32
        token=jwt.encode({'alg':'HS256'},{'sub':'fixture','aud':'intended','exp':int(time.time())+60},key)
        return jwt,key,token

    def test_valid_signed_claims(self):
        jwt,key,token=self.fixture()
        claims=jwt.decode(token,key,claims_options={'aud':{'essential':True,'value':'intended'}})
        claims.validate();self.assertEqual(claims['sub'],'fixture')

    def test_wrong_signature_rejected(self):
        jwt,key,token=self.fixture()
        with self.assertRaises(JoseError):jwt.decode(token,b'y'*32)

    def test_wrong_audience_rejected(self):
        jwt,key,token=self.fixture()
        claims=jwt.decode(token,key,claims_options={'aud':{'essential':True,'value':'other'}})
        with self.assertRaises(JoseError):claims.validate()

    def test_algorithm_allowlist_enforced(self):
        _,key,token=self.fixture()
        with self.assertRaises(JoseError):JsonWebToken(['RS256']).decode(token,key)

    async def test_starlette_oauth_authorization_request_without_network(self):
        oauth=OAuth()
        client=oauth.register('fixture',client_id='fixture',client_secret='fixture',
            authorize_url='https://example.invalid/authorize',access_token_url='https://example.invalid/token',
            client_kwargs={'scope':'openid profile email'})
        result=await client.create_authorization_url('https://callback.invalid/callback')
        url=urlsplit(result['url']);values=parse_qs(url.query)
        self.assertEqual((url.netloc,url.path),('example.invalid','/authorize'))
        self.assertEqual(values['client_id'],['fixture'])
        self.assertEqual(values['redirect_uri'],['https://callback.invalid/callback'])
        self.assertTrue(values['state']);self.assertTrue(values['nonce'])

if __name__=='__main__':unittest.main()
