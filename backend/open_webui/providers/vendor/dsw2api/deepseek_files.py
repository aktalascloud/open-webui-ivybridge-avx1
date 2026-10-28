"""DeepSeek file protocol only: authenticated upload, processing and errors."""
from __future__ import annotations

from . import managed_env


import os
import time

from curl_cffi import CurlMime
from curl_cffi.requests.exceptions import RequestException

from .image_inputs import ImageAsset, ImageError

BASE_URL = 'https://chat.deepseek.com'


class DeepSeekFilesClient:
    def __init__(self, transport, pow_headers, base_headers):
        self.transport = transport
        self.pow_headers = pow_headers
        self.base_headers = base_headers
        try:
            self.timeout = max(1, float(managed_env.get('IMAGE_PROCESSING_TIMEOUT', '60')))
        except ValueError:
            self.timeout = 60

    @staticmethod
    def _body(response):
        if response.status_code == 429:
            raise ImageError('Upstream file service rate limited the request', 429)
        if response.status_code != 200:
            raise ImageError('Upstream file service returned an HTTP error', 502)
        try:
            body = response.json()
            data = body.get('data') or {}
            if body.get('code') != 0 or data.get('biz_code', 0) != 0:
                raise ImageError('Upstream file service rejected the request', 502)
            biz = data['biz_data']
            if not isinstance(biz, dict):
                raise ValueError()
            return biz
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ImageError('Invalid upstream file response', 502) from None

    def upload(self, asset: ImageAsset, *, thinking: bool, model_type: str) -> str:
        mime = CurlMime()
        try:
            headers = self.pow_headers('/api/v0/file/upload_file', include_hif=False)
            headers = {k: v for k, v in headers.items() if k.lower() != 'content-type'}
            headers.update({'X-File-Size': str(len(asset.data)), 'X-Model-Type': model_type,
                            'X-Thinking-Enabled': '1' if thinking else '0'})
            extension = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}[asset.mime]
            mime.addpart('file', content_type=asset.mime, filename=f'image-{asset.digest[:12]}.{extension}', data=asset.data)
            response = self.transport.post(BASE_URL + '/api/v0/file/upload_file',
                                           headers=headers, multipart=mime, timeout=self.timeout)
            body = self._body(response)
            file_id = body.get('id')
            if not isinstance(file_id, str) or not file_id:
                raise ImageError('Upstream upload returned no file ID', 502)
            return file_id
        except RequestException:
            raise ImageError('Unable to upload image to upstream', 502) from None
        finally:
            mime.close()

    def wait_ready(self, file_ids: list[str]) -> None:
        if not file_ids:
            return
        expected = set(file_ids)
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                response = self.transport.get(BASE_URL + '/api/v0/file/fetch_files',
                    headers=self.base_headers, params=[('file_ids', fid) for fid in dict.fromkeys(file_ids)],
                    timeout=max(0.1, deadline - time.monotonic()))
                files = self._body(response).get('files')
                if (not isinstance(files, list)
                        or not all(isinstance(x, dict) and isinstance(x.get('id'), str) for x in files)
                        or {x['id'] for x in files} != expected):
                    raise ImageError('Upstream file processing response omitted requested files', 502)
                for item in files:
                    if item.get('error_code') or item.get('status') not in ('PENDING', 'PARSING', 'SUCCESS'):
                        raise ImageError('Upstream rejected or failed to process an image', 502)
                    if item.get('audit_result') in ('fail', 'reject', 'block'):
                        raise ImageError('Upstream image audit rejected the image', 502)
                if all(item['status'] == 'SUCCESS' for item in files):
                    return
            except RequestException:
                raise ImageError('Unable to query upstream image processing', 502) from None
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        raise ImageError('Upstream image processing timed out', 504)
