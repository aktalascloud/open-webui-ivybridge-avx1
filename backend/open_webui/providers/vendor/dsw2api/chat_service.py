"""Shared prompt and upstream execution; no HTTP or output-protocol imports."""
from contextlib import closing

from .chat_types import ChatEvent, ChatResult
from .tool_dsml import build_dsml_tool_prompt, format_tool_calls_for_prompt, parse_dsml_tool_calls
from .tool_sieve import StreamSieve
from .turn_preparation import prepare_turn


class ChatService:
    prepare = staticmethod(prepare_turn)

    @staticmethod
    def build_prompt(messages, tools=None, tool_choice=None, *, tool_result_limit=1000):
        def text(content):
            if isinstance(content, str): return content
            return ' '.join(p.get('text', '') for p in content or [] if p.get('type') == 'text' and p.get('text'))
        parts, injected = [], False
        tool_prompt = build_dsml_tool_prompt(tools, tool_choice) if tools else None
        for message in messages:
            role = message['role']; value = text(message.get('content'))
            if role in ('system', 'developer'):
                if tool_prompt and not injected:
                    value = value + '\n\n' + tool_prompt if value else tool_prompt
                    injected = True
                if value: parts.append('System: ' + value)
            elif role == 'user':
                parts.append('User: ' + value)
            elif role == 'assistant':
                dsml = format_tool_calls_for_prompt(message.get('tool_calls')) if message.get('tool_calls') else ''
                value = ' '.join(p for p in (value, dsml) if p)
                if value: parts.append('Assistant: ' + value)
            elif role == 'tool':
                call = message.get('tool_call_id')
                parts.append((f'Tool result (call_id={call}):' if call else 'Tool result:') + ' ' +
                             (value if tool_result_limit is None else value[:tool_result_limit]))
        if tool_prompt and not any(m['role'] in ('system', 'developer') for m in messages):
            parts.insert(0, 'System: ' + tool_prompt)
        return '\n'.join(parts)

    @staticmethod
    def invoke(acquired, turn, options, ready):
        return acquired.adapter.chat(turn.session_id, turn.prompt, parent_message_id=acquired.parent_message_id,
                                     ready_out=ready, **options, **turn.completion_options())

    @staticmethod
    def tokens(acquired, turn, options, ready):
        return acquired.adapter.chat_stream(turn.session_id, turn.prompt, parent_message_id=acquired.parent_message_id,
                                            ready_out=ready, **options, **turn.completion_options())

    @classmethod
    def result(cls, acquired, turn, options, tool_names, ready):
        text, reasoning = cls.invoke(acquired, turn, options, ready)
        calls, cleaned = parse_dsml_tool_calls(text, tool_names)
        return ChatResult(cleaned if calls else text, reasoning, calls)

    @classmethod
    def events(cls, acquired, turn, options, tool_names, ready, *, batch_tools=False, on_token=None):
        sieve = StreamSieve(parse_fn=lambda text: parse_dsml_tool_calls(text, tool_names))
        def converted(events):
            for event in events:
                if event.type == 'text' and event.data: yield ChatEvent('text', event.data)
                elif event.type == 'tool_calls':
                    if batch_tools: yield ChatEvent('tools', calls=event.data)
                    else:
                        for call in event.data: yield ChatEvent('tool', call=call)
        with closing(cls.tokens(acquired, turn, options, ready)) as source:
            for token in source:
                if on_token is not None:
                    try: on_token()
                    except Exception: pass
                if isinstance(token, dict):
                    if token.get('__type') == 'status' and token.get('status') == 'FINISHED': break
                    if token.get('__type') == 'thinking' and token.get('content'):
                        yield ChatEvent('reasoning', token['content'])
                    continue
                yield from converted(sieve.feed(token))
            yield from converted(sieve.flush())
