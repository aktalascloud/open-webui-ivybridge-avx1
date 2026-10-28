"""HTTP boundary for image errors and bounded JSON request buffering."""
from starlette.responses import JSONResponse

from .image_inputs import ImageError, ImageLimits


def image_error_response(path: str, error: ImageError):
    kind = 'invalid_request_error' if error.status < 500 else 'api_error'
    if error.status == 429:
        kind = 'rate_limit_error'
    payload = {'error': {'type': kind, 'message': str(error)}}
    if path == '/v1/messages':
        payload['type'] = 'error'
    return JSONResponse(payload, status_code=error.status)


class ImageBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] != 'http' or path not in ('/v1/chat/completions', '/v1/messages', '/v1/responses'):
            return await self.app(scope, receive, send)
        limit = ImageLimits.from_env().max_request_bytes
        error = ImageError('JSON request exceeds byte limit', 413)
        headers = dict(scope.get('headers', []))
        try:
            declared = int(headers.get(b'content-length', b'0'))
        except ValueError:
            declared = 0
        if declared > limit:
            return await image_error_response(path, error)(scope, receive, send)
        messages, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            size += len(message.get('body', b''))
            if size > limit:
                return await image_error_response(path, error)(scope, receive, send)
            messages.append(message)
            if not message.get('more_body', False):
                break
        iterator = iter(messages)
        async def replay():
            try:
                return next(iterator)
            except StopIteration:
                return await receive()
        await self.app(scope, replay, send)
