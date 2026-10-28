"""Bounded image decoding and credential-free, DNS-pinned HTTP downloads."""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import http.client
from io import BytesIO
import ipaddress
import re
import socket
import ssl
import time
import threading
from urllib.parse import urljoin, urlsplit
import warnings

from PIL import Image, UnidentifiedImageError

from .image_inputs import ImageAsset, ImageError, ImageLimits

MIMES = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}
_DNS_SLOTS = threading.BoundedSemaphore(4)


def _resolve(host, port, timeout):
    """Bound caller waiting and orphaned resolver work when OS DNS stalls."""
    deadline = time.monotonic() + timeout
    slots = _DNS_SLOTS
    if not slots.acquire(timeout=max(0, timeout)):
        raise ImageError('Image DNS resolution timed out')
    done, result = threading.Event(), []
    def worker():
        try:
            result.append(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
        except OSError:
            result.append(None)
        finally:
            slots.release()
            done.set()
    try:
        threading.Thread(target=worker, daemon=True, name='image-dns').start()
    except BaseException:
        slots.release()
        raise
    if not done.wait(max(0, deadline - time.monotonic())):
        raise ImageError('Image DNS resolution timed out')
    if not result or result[0] is None:
        raise ImageError('Unable to resolve image hostname')
    return result[0]


@dataclass(frozen=True)
class PublicTarget:
    host: str
    port: int
    address: str
    path: str
    secure: bool


def public_target(url: str, timeout: float = 15) -> PublicTarget:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
        host = parsed.hostname.encode('idna').decode('ascii')
        if any(c.isspace() or ord(c) < 32 for c in url):
            raise ValueError()
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        if port not in (80, 443):
            raise ValueError()
        addresses = _resolve(host, port, timeout)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError()
        return PublicTarget(host, port, addresses[0][4][0],
                            (parsed.path or '/') + ('?' + parsed.query if parsed.query else ''),
                            parsed.scheme == 'https')
    except (ValueError, UnicodeError, OSError):
        raise ImageError('Image URL must resolve exclusively to public HTTP(S) addresses on port 80 or 443') from None


def _open(target: PublicTarget, timeout: float):
    """Connect to the checked address, retaining hostname for Host and TLS SNI."""
    connection = http.client.HTTPConnection(target.host, target.port, timeout=timeout)
    sock = None
    try:
        sock = socket.create_connection((target.address, target.port), timeout=timeout)
        if target.secure:
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=target.host)
        connection.sock = sock
        connection.request('GET', target.path, headers={'Accept': 'image/*', 'Accept-Encoding': 'identity', 'User-Agent': 'DeepSeek-Image-Proxy/1.0'})
        response = connection.getresponse()
        connection._image_socket = sock
        return connection, response
    except BaseException:
        if sock is not None:
            sock.close()
        connection.close()
        raise


def download_image(url: str, limits: ImageLimits) -> bytes:
    deadline = time.monotonic() + limits.download_timeout
    try:
        for _ in range(4):
            target = public_target(url, max(0, deadline - time.monotonic()))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            conn, response = _open(target, remaining)
            try:
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader('Location')
                    if not location:
                        raise ImageError('Image redirect has no location')
                    url = urljoin(url, location)
                    continue
                if response.status != 200:
                    raise ImageError('Image URL returned an unsuccessful response')
                if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                    raise ImageError('Compressed HTTP image responses are unsupported')
                length = response.getheader('Content-Length')
                if length and int(length) > limits.max_bytes:
                    raise ImageError('Image download exceeds byte limit', 413)
                chunks, total = [], 0
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError()
                    read_socket = getattr(conn, '_image_socket', conn.sock)
                    if read_socket is not None:
                        read_socket.settimeout(remaining)
                    data = response.read1(min(65536, limits.max_bytes + 1 - total))
                    if not data:
                        return b''.join(chunks)
                    total += len(data)
                    if total > limits.max_bytes:
                        raise ImageError('Image download exceeds byte limit', 413)
                    chunks.append(data)
            finally:
                response.close()
                conn.close()
        raise ImageError('Too many image URL redirects')
    except ImageError:
        raise
    except (OSError, ValueError, http.client.HTTPException):
        raise ImageError('Unable to download image within configured limits') from None


def load_image(source: dict, limits: ImageLimits) -> ImageAsset:
    if not isinstance(source, dict):
        raise ImageError('Image source must be an object')
    kind, declared = source.get('type'), None
    if kind == 'url':
        url = source.get('url')
        if not isinstance(url, str) or not url:
            raise ImageError('Image source requires a nonempty url')
        if url.startswith('data:'):
            match = re.fullmatch(r'data:([^;,]+);base64,(.*)', url, re.DOTALL)
            if not match:
                raise ImageError('Image data URL must use base64 encoding')
            declared, encoded = match.groups()
            kind = 'base64'
        else:
            data = download_image(url, limits)
    elif kind == 'base64':
        declared, encoded = source.get('media_type'), source.get('data')
    else:
        raise ImageError('Unsupported image source type')
    if kind == 'base64':
        if declared not in MIMES.values():
            raise ImageError('Supported image media types: image/jpeg, image/png, image/webp', 415)
        if not isinstance(encoded, str):
            raise ImageError('Image data must be a base64 string')
        if len(encoded) > ((limits.max_bytes + 2) // 3) * 4:
            raise ImageError('Encoded image exceeds byte limit', 413)
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ImageError('Invalid base64 image data') from None
    if len(data) > limits.max_bytes:
        raise ImageError('Decoded image exceeds byte limit', 413)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                mime = MIMES.get(image.format)
                if mime is None or getattr(image, 'n_frames', 1) != 1:
                    raise ImageError('Only static JPEG, PNG and WebP images are supported', 415)
                width, height = image.size
                if width * height > limits.max_pixels:
                    raise ImageError('Image dimensions exceed pixel limit', 413)
                if declared and declared != mime:
                    raise ImageError('Declared image media type does not match its content')
                image.load()
    except ImageError:
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ImageError('Image dimensions exceed pixel limit', 413) from None
    except (UnidentifiedImageError, OSError, ValueError):
        raise ImageError('Image content is invalid or incomplete') from None
    return ImageAsset(data, mime, hashlib.sha256(data).hexdigest(), width, height)
