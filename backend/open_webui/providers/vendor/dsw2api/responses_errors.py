"""Explicit supported-subset errors without retaining request data."""
from __future__ import annotations
from typing import TYPE_CHECKING
from .image_inputs import ImageError

if TYPE_CHECKING:
    from pydantic import ValidationError


class ResponseError(ImageError):
    def __init__(self, message, status=400, code='invalid_request_error', param=None):
        super().__init__(message, status)
        self.code, self.param = code, param

    def payload(self):
        return {'error': {'message': str(self), 'type': 'invalid_request_error' if self.status < 500 else 'server_error',
                          'code': self.code, 'param': self.param}}

    def stream_payload(self):
        code = self.code
        allowed = {'server_error', 'rate_limit_exceeded', 'invalid_prompt', 'invalid_image',
                   'invalid_image_format', 'invalid_base64_image', 'invalid_image_url', 'image_too_large',
                   'image_parse_error', 'image_content_policy_violation', 'failed_to_download_image'}
        if code not in allowed:
            code = 'invalid_prompt' if self.status < 500 else 'server_error'
        return {'code': code, 'message': str(self), 'param': self.param, 'type': self.code}


def validation_error(error: ValidationError) -> ResponseError:
    issue = error.errors(include_input=False, include_url=False)[0]
    path = ''
    for part in issue['loc']:
        if isinstance(part, int): path += f'[{part}]'
        elif part not in ('str',) and '[' not in str(part): path += ('.' if path else '') + str(part)
    return ResponseError('Invalid or unsupported request field', param=path or None)


def classify_error(error: Exception) -> ResponseError:
    # HTTP/upstream classification is an adapter; importing the error type alone
    # keeps schema policy independent of HTTP and upstream transports.
    from .adapter import RateLimitError
    from fastapi import HTTPException
    from pydantic import ValidationError
    if isinstance(error, ResponseError): return error
    if isinstance(error, ValidationError): return validation_error(error)
    if isinstance(error, RateLimitError):
        return ResponseError('Upstream rate limited the request', 429, 'rate_limit_exceeded')
    if isinstance(error, ImageError):
        return ResponseError('Image input or processing failed', error.status, 'image_parse_error', 'input')
    if isinstance(error, HTTPException):
        code, message = {401: ('invalid_api_key', 'Invalid API key'),
            403: ('permission_denied', 'Access denied'), 429: ('rate_limit_exceeded', 'Request rate limited'),
            503: ('service_unavailable', 'Service unavailable')}.get(error.status_code,
                ('invalid_request_error', 'Request rejected'))
        return ResponseError(message, error.status_code, code)
    return ResponseError('Upstream request failed', 502, 'server_error')
