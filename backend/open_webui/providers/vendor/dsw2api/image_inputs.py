"""Protocol-neutral image assets, limits, and ordered content normalization."""
from __future__ import annotations

from . import managed_env


from copy import deepcopy
from dataclasses import dataclass, field
import os


class ImageError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ImageLimits:
    max_images: int = 8
    max_bytes: int = 10 * 1024 * 1024
    max_total_bytes: int = 32 * 1024 * 1024
    max_request_bytes: int = 40 * 1024 * 1024
    max_pixels: int = 25_000_000
    download_timeout: float = 15

    @classmethod
    def from_env(cls):
        defaults = cls()
        values = {}
        for name in cls.__dataclass_fields__:
            raw = managed_env.get('IMAGE_' + name.upper(), '')
            try:
                value = float(raw) if name == 'download_timeout' else int(raw)
                values[name] = value if value > 0 else getattr(defaults, name)
            except ValueError:
                values[name] = getattr(defaults, name)
        return cls(**values)


@dataclass(frozen=True)
class ImageAsset:
    data: bytes = field(repr=False)
    mime: str
    digest: str
    width: int
    height: int


@dataclass(frozen=True)
class ImageAttachment:
    marker: str
    asset: ImageAsset


def normalize_images(messages: list[dict], protocol: str,
                     limits: ImageLimits | None = None) -> tuple[list[dict], tuple[ImageAttachment, ...]]:
    """Replace supported image blocks with stable markers; never mutate input."""
    from .image_sources import load_image

    limits = limits or ImageLimits.from_env()
    normalized = deepcopy(messages)
    attachments = []
    total = 0

    def blocks(content, allowed):
        nonlocal total
        if not isinstance(content, list):
            return
        for index, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            kind = block.get('type')
            if kind in ('image', 'image_url'):
                if not allowed:
                    raise ImageError('Images are supported only in user content and user tool results')
                if len(attachments) >= limits.max_images:
                    raise ImageError('Too many images in request', 413)
                if protocol == 'openai' and kind == 'image_url':
                    value = block.get('image_url')
                    if not isinstance(value, dict):
                        raise ImageError('image_url must contain a url')
                    source = {'type': 'url', 'url': value.get('url')}
                elif protocol == 'anthropic' and kind == 'image':
                    source = block.get('source')
                else:
                    raise ImageError('Unsupported image content block for this API')
                asset = load_image(source, limits)
                total += len(asset.data)
                if total > limits.max_total_bytes:
                    raise ImageError('Total decoded image bytes exceed the request limit', 413)
                marker = f'[Attached image {len(attachments) + 1}; sha256={asset.digest}]'
                attachments.append(ImageAttachment(marker, asset))
                content[index] = {'type': 'text', 'text': marker}
            elif protocol == 'anthropic' and kind == 'tool_result':
                blocks(block.get('content'), allowed)

    for message in normalized:
        blocks(message.get('content'), message.get('role') == 'user')
    return normalized, tuple(attachments)
