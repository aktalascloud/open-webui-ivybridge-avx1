"""Anonymous, fixed free catalog. No credentials, account or paid fallback."""
import json
from pathlib import Path
from fastapi import HTTPException

CATALOG = json.loads(Path(__file__).with_name('free_llm_catalog.json').read_text('utf-8'))


def check_free_llm_request(config, url, key=None, model=None):
    if config.get('provider') != 'freellm':
        return
    if (url.rstrip('/') != CATALOG['base_url'] or key
            or config.get('auth_type') != 'none' or config.get('headers')
            or config.get('forward_cookies') or config.get('azure')
            or config.get('api_type')):
        raise HTTPException(400, 'FreeLLM requires its anonymous gateway profile without credentials or custom headers')
    if model is not None and model not in {row['id'] for row in CATALOG['models']}:
        raise HTTPException(400, 'This model is not in the reviewed FreeLLM catalog')


def prepare_free_llm_payload(config, url, key, payload):
    check_free_llm_request(config, url, key, payload.get('model'))
    if config.get('provider') != 'freellm':
        return payload
    return {name: value for name, value in payload.items() if name not in {'user', 'metadata'}}
