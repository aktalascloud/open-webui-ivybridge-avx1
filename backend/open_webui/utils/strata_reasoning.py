"""Explicit, opt-in author-template controls at the provider boundary.

No template text is bundled. Control tags use the existing template interface;
only an outgoing copy changes, after the user's original chat text is stored.
"""
import re
from .mnemosyne_reasoning import reason_auto_pick


def adaptive_reasoning_mode(text: str, supported_modes) -> str | None:
    # Normalize domain words for the English upstream task map. The user's text
    # is never translated or changed by this normalization; only the score input.
    words = []
    for pattern, equivalents in (
        (r'\bошиб\w*', 'bug'), (r'\bисправ\w*', 'fix'),
        (r'\bкод\w*', 'code'), (r'\bпарсер\w*', 'parser'),
        (r'\bрефактор\w*', 'refactor'), (r'\bпрограмм\w*', 'programming'),
        (r'\bисслед\w*', 'research'), (r'\bисточник\w*', 'sources'),
        (r'\bпроцитир\w*', 'cite'), (r'\bстат(?:ья|ьи|ью|ей|ьям|ьями|ьях)\b', 'papers'),
        (r'\bобъясн\w*', 'explain'), (r'\bнаучи\w*', 'teach'),
        (r'\bшут\w*', 'joke'), (r'\bсмешн\w*', 'funny'),
    ):
        if re.search(pattern, text.lower()): words.append(equivalents)
    picked = reason_auto_pick(text + ' ' + ' '.join(words))
    mode = picked.partition('+')[0] if picked else None
    supported = {value for value in supported_modes or [] if isinstance(value, str)}
    return mode if mode in supported else None


def apply_strata_reasoning_profile(payload: dict, author_template: bool = False, supported_modes=None) -> dict:
    if '_strata_reasoning_mode' not in payload:
        return payload
    result = dict(payload)
    mode = result.pop('_strata_reasoning_mode')
    tags = {'none': 'ioff', 'low': 'low', 'medium': 'medium',
            'high': 'off', 'xhigh': 'off', 'ultra': 'ultra', 'adaptive': None}
    if not author_template or not isinstance(mode, str) or mode not in tags or not isinstance(payload.get('messages'), list):
        return result
    for index in range(len(payload['messages']) - 1, -1, -1):
        message = payload['messages'][index]
        if not isinstance(message, dict) or message.get('role') != 'user':
            continue
        content = message.get('content')
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = '\n'.join(p.get('text', '') for p in content
                             if isinstance(p, dict) and isinstance(p.get('text'), str))
        else:
            return result
        # A manually supplied author control retains its existing precedence.
        if re.search(r'\{REASON:[A-Za-z0-9_]+\}', text):
            return result
        tag = adaptive_reasoning_mode(text, supported_modes) if mode == 'adaptive' else tags[mode]
        if not tag:return result
        prefix = '{REASON:' + tag + '}\n'
        outgoing = prefix + content if isinstance(content, str) else [{'type': 'text', 'text': prefix}, *content]
        result['messages'] = [*payload['messages']]
        result['messages'][index] = {**message, 'content': outgoing}
        break
    return result
