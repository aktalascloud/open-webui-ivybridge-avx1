from fastapi import HTTPException, Request
from cryptography.fernet import InvalidToken
from open_webui.utils.auth import create_token, decode_token, get_optional_verified_user_from_request


def browser_ticket(server_id, user_id, chat_id, session, headers=None, cookies=None, *, owner_token, resource='browser'):
    from open_webui.utils.oauth import encrypt_data

    relay = encrypt_data(
        {
            'authorization': (headers or {}).get('Authorization'),
            'cookies': cookies or {},
            'owner_token': owner_token,
            'capability': session['token'],
        }
    )
    return create_token(
        {
            'purpose': 'terminal-browser',
            'server': server_id,
            'user': user_id,
            'chat': chat_id,
            'session': session['id'],
            'mode': session.get('mode', 'proxy'),
            'resource': resource,
            'model': (headers or {}).get('X-Terminal-Model-Id'),
            'relay': relay,
        },
    )


async def browser_access(server_id, sid, ticket, request):
    data = decode_token(ticket)
    if (
        not data
        or data.get('purpose') != 'terminal-browser'
        or data.get('server') != server_id
        or data.get('session') != sid
        or data.get('mode') not in ('proxy', 'chrome')
    ):
        raise HTTPException(401, 'Browser session expired')
    from open_webui.utils.oauth import decrypt_data

    try:
        relay = decrypt_data(data['relay'])
        owner_token = relay.pop('owner_token')
        capability = relay.pop('capability')
        if not isinstance(capability, str) or (not capability and data.get('resource') != 'files'):
            raise ValueError('Missing browser capability')
        if not isinstance(owner_token, str) or not owner_token:
            raise ValueError('Missing browser owner credential')
        # Reuse revocation and endpoint policy; never relay the owner credential upstream.
        auth_scope = {**request.scope, 'type': 'http', 'method': request.scope.get('method', 'GET'),
                      'headers': [(b'authorization', f'Bearer {owner_token}'.encode('latin-1'))], 'state': {}}
        user = await get_optional_verified_user_from_request(Request(auth_scope))
    except (InvalidToken, ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(401, 'Browser session expired') from None
    if user is None or user.id != data.get('user'):
        raise HTTPException(401, 'Browser session expired')
    data['relay'] = relay
    data['capability'] = capability
    return user, data
