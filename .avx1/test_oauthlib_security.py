"""Synthetic device-code rejection and authorized-scope regressions for4.0.1."""
import unittest
from unittest.mock import Mock
from oauthlib.common import Request
from oauthlib.oauth2.rfc8628.grant_types.device_code import DeviceCodeGrant
from oauthlib.oauth2.rfc6749.errors import InvalidRequestError, InvalidGrantError


class DeviceCodeSecurity(unittest.TestCase):
    def request(self, code='fixture'):
        return Request('https://fixture.invalid/token',http_method='POST',
                       body='grant_type=urn:ietf:params:oauth:grant-type:device_code&client_id=fixture&device_code='+code)

    def test_missing_and_bogus_codes_are_rejected(self):
        validator=Mock();validator.validate_device_code.return_value=None
        grant=DeviceCodeGrant(validator)
        with self.assertRaises(InvalidRequestError):grant.validate_device_code(self.request(''))
        validator.validate_device_code.assert_not_called()
        with self.assertRaises(InvalidGrantError):grant.validate_device_code(self.request('bogus'))

    def test_validation_populates_authorized_scopes_before_scope_checks(self):
        validator=Mock();grant=DeviceCodeGrant(validator)
        def authorize(client,code,request):
            request.user='synthetic-user';request.scopes=['authorized-scope']
            return grant.DEVICE_CODE_AUTHORIZED
        validator.validate_device_code.side_effect=authorize
        grant.validate_client_authentication=Mock();grant.validate_grant_type=Mock()
        seen=[];grant.validate_scopes=lambda request:seen.append(request.scopes)
        grant.validate_token_request(self.request())
        self.assertEqual(seen,[['authorized-scope']])


if __name__=='__main__':unittest.main()
