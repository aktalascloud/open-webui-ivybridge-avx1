"""Consume supported client hints before protocol validation or execution.

Hints never become prompt content, caller identity, or persisted model state.
Unknown functional options remain subject to the strict Responses model.
"""
import json

from .responses_errors import ResponseError


def normalize_client_options(payload):
    value = dict(payload)
    cache_key = value.pop('prompt_cache_key', None)
    if cache_key is not None and (not isinstance(cache_key, str) or len(cache_key) > 512):
        raise ResponseError('prompt_cache_key must be a string of at most 512 characters', param='prompt_cache_key')
    metadata = value.pop('client_metadata', None)
    if metadata is not None:
        try:
            if not isinstance(metadata, dict): raise ValueError()
            encoded = json.dumps(metadata, ensure_ascii=False, allow_nan=False).encode('utf-8')
            if len(encoded) > 16384: raise ValueError()
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ResponseError('client_metadata must be a JSON object of at most 16 KiB', param='client_metadata') from None
    include = value.get('include')
    if include is not None:
        if not isinstance(include, list) or any(item != 'reasoning.encrypted_content' for item in include):
            raise ResponseError('Unsupported include value', param='include')
        # The upstream has no encrypted reasoning state; never manufacture it.
        value['include'] = []
    reasoning = value.get('reasoning')
    if isinstance(reasoning, dict):
        choices = {'effort': ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'),
                   'summary': ('auto', 'concise', 'detailed', 'none')}
        for key, hint in reasoning.items():
            if key not in choices or (hint is not None and hint not in choices[key]):
                raise ResponseError('Unsupported reasoning hint', param=f'reasoning.{key}')
        value['reasoning'] = None
    text = value.get('text')
    if isinstance(text, dict) and 'verbosity' in text:
        if text['verbosity'] not in (None, 'low', 'medium', 'high'):
            raise ResponseError('Unsupported verbosity hint', param='text.verbosity')
        value['text'] = {key: item for key, item in text.items() if key != 'verbosity'}
    return value
