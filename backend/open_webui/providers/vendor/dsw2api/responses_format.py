"""Responses wire models and Item conversion, independent of HTTP/execution."""
from copy import deepcopy
import time
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .chat_types import ChatResult
from .image_inputs import normalize_images
from .responses_errors import ResponseError
from .responses_compat import normalize_client_options
from .responses_tools import normalize_tools, validate_choice, validate_call_batch, pending_calls, json_arguments
from .token_counter import count_text


def identifier(prefix):
    return prefix + '_' + uuid.uuid4().hex


class ResponsesRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    input: str | list[dict]
    model: str | None = None
    instructions: str | None = None
    previous_response_id: str | None = None
    store: bool = True
    stream: bool = False
    tools: list[dict] = Field(default_factory=list)
    tool_choice: str | dict = 'auto'
    parallel_tool_calls: bool = False
    metadata: dict[str, str] = Field(default_factory=dict)
    reasoning: dict | None = None
    text: dict | None = None
    include: list[str] = Field(default_factory=list)
    background: bool = False
    conversation: str | dict | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    truncation: str = 'disabled'

    @model_validator(mode='before')
    @classmethod
    def nullable_defaults(cls, value):
        if not isinstance(value, dict): return value
        value = normalize_client_options(value)
        for name, default in {'metadata': {}, 'tools': [], 'include': [], 'tool_choice':'auto',
                'parallel_tool_calls':False, 'background':False, 'truncation':'disabled'}.items():
            if name in value and value[name] is None: value[name] = deepcopy(default)
        return value

    @model_validator(mode='after')
    def supported(self):
        unsupported = {'background': self.background, 'conversation': self.conversation,
            'max_output_tokens': self.max_output_tokens,
            'temperature': self.temperature, 'top_p': self.top_p}
        for name, value in unsupported.items():
            if value is not None and value is not False:
                raise ResponseError(f'{name} is not supported by this upstream', param=name)
        if self.reasoning not in (None, {}):
            raise ResponseError('Native reasoning effort/summary controls are not supported; use server THINKING policy', param='reasoning')
        if self.text not in (None, {}, {'format': {'type': 'text'}}):
            raise ResponseError('Only plain text output is supported', param='text')
        if self.include:
            raise ResponseError('Unsupported include value', param='include')
        if self.truncation != 'disabled':
            raise ResponseError('Automatic truncation is not supported', param='truncation')
        if len(self.metadata) > 16 or any(len(k) > 64 or len(v) > 512 for k, v in self.metadata.items()):
            raise ResponseError('metadata exceeds supported limits', param='metadata')
        self.tools = normalize_tools(self.tools)
        validate_choice(self.tools, self.tool_choice)
        return self

    def chat_tools(self):
        return [{'type': 'function', 'function': {'name': t['name'], 'description': t.get('description', ''),
                 'parameters': t['parameters']}} for t in self.tools]

    def chat_choice(self):
        if isinstance(self.tool_choice, dict): return {'type': 'function', 'function': {'name': self.tool_choice['name']}}
        return self.tool_choice


def normalize_input(request: ResponsesRequest, history: list[dict]):
    items = [{'role': 'user', 'content': request.input}] if isinstance(request.input, str) else request.input
    if not items: raise ResponseError('input must contain at least one item', param='input')
    known, resolved = {}, set()
    for message in history:
        for call in message.get('tool_calls', []): known[call['id']] = call['function']['name']
        if message.get('role') == 'tool': resolved.add(message.get('tool_call_id'))
    messages = []
    def content_parts(value):
        if isinstance(value, str): return value
        if not isinstance(value, list): raise ResponseError('Message content must be a string or content array')
        parts = []
        for part in value:
            if not isinstance(part, dict): raise ResponseError('Invalid content part')
            kind = part.get('type')
            if kind in ('input_text', 'output_text') and isinstance(part.get('text'), str):
                parts.append({'type': 'text', 'text': part['text']})
            elif kind == 'input_image' and isinstance(part.get('image_url'), str) and not part.get('file_id'):
                parts.append({'type': 'image_url', 'image_url': {'url': part['image_url']}})
            else: raise ResponseError('Unsupported content part; use input_text/input_image', param='input')
        return parts
    for item_index, item in enumerate(items):
        kind = item.get('type', 'message')
        if kind == 'message':
            role = item.get('role')
            if role not in ('system', 'developer', 'user', 'assistant'): raise ResponseError('Unsupported input role')
            messages.append({'role': role, 'content': content_parts(item.get('content'))})
        elif kind == 'function_call':
            call_id, name, arguments = item.get('call_id'), item.get('name'), item.get('arguments')
            if not all(isinstance(x, str) and x for x in (call_id, name, arguments)) or call_id in known:
                raise ResponseError('Invalid or duplicate function call', param=f'input[{item_index}].call_id')
            try: json_arguments(arguments)
            except ValueError: raise ResponseError('Function call arguments must be JSON') from None
            known[call_id] = name
            messages.append({'role': 'assistant', 'content': '', 'tool_calls': [
                {'id': call_id, 'type': 'function', 'function': {'name': name, 'arguments': arguments}}]})
        elif kind == 'function_call_output':
            call_id = item.get('call_id')
            if not isinstance(call_id, str) or call_id not in known or call_id in resolved:
                raise ResponseError('Function output does not match an unresolved call_id', param=f'input[{item_index}].call_id')
            resolved.add(call_id)
            messages.append({'role': 'tool', 'tool_call_id': call_id, 'content': content_parts(item.get('output'))})
        elif kind == 'reasoning':
            if item.get('encrypted_content'):
                raise ResponseError('Encrypted reasoning state is not supported')
            # Public reasoning is presentation, not an opaque model-state token.
        else: raise ResponseError('Unsupported input Item type', param='input')
    if pending_calls(history + messages):
        raise ResponseError('All pending function results are required before generation', param='input')
    roles = [m['role'] for m in messages]
    # Function outputs may carry screenshots, while other unsupported roles may not.
    for m in messages:
        if m['role'] == 'tool': m['role'] = 'user'
    normalized, attachments = normalize_images(messages, 'openai')
    for message, role in zip(normalized, roles):
        message['role'] = role
        text = str(message.get('content', ''))
        message['_image_digests'] = [a.asset.digest for a in attachments if a.marker in text]
    return normalized, attachments


def validate_calls(request, calls, *, complete=True):
    validate_call_batch(request.tools, request.tool_choice, calls,
                        parallel=request.parallel_tool_calls, complete=complete)


def output_items(result: ChatResult):
    output = []
    if result.reasoning:
        output.append({'id': identifier('rs'), 'type': 'reasoning', 'status': 'completed', 'summary': [],
                       'content': [{'type': 'reasoning_text', 'text': result.reasoning}]})
    if result.text:
        output.append({'id': identifier('msg'), 'type': 'message', 'role': 'assistant', 'status': 'completed',
                       'content': [{'type': 'output_text', 'text': result.text, 'annotations': [], 'logprobs': []}]})
    for call in result.calls:
        output.append({'id': identifier('fc'), 'type': 'function_call', 'call_id': call['id'],
                       'name': call['function']['name'], 'arguments': call['function']['arguments'], 'status': 'completed'})
    return output


def history_output(output):
    messages = []
    for item in output:
        if item['type'] == 'message':
            messages.append({'role': 'assistant', 'content': ''.join(p['text'] for p in item['content'])})
        elif item['type'] == 'function_call':
            messages.append({'role': 'assistant', 'content': '', 'tool_calls': [{'id': item['call_id'], 'type': 'function',
                'function': {'name': item['name'], 'arguments': item['arguments']}}]})
    return messages


def response_object(request, response_id, model, output, prompt, status='completed', created_at=None):
    reasoning = ''.join(p['text'] for item in output if item['type'] == 'reasoning' for p in item.get('content', []))
    visible = ''.join(p['text'] for item in output if item['type'] == 'message' for p in item['content'])
    arguments = ''.join(i['arguments'] for i in output if i['type'] == 'function_call')
    incoming, outgoing = count_text(prompt), count_text(reasoning + visible + arguments)
    return {'id': response_id, 'object': 'response', 'created_at': created_at or time.time(),
        'completed_at': time.time() if status == 'completed' else None, 'status': status, 'error': None,
        'incomplete_details': None, 'model': model, 'output': deepcopy(output), 'instructions': request.instructions,
        'parallel_tool_calls': request.parallel_tool_calls, 'tool_choice': request.tool_choice, 'tools': request.tools,
        'store': request.store, 'previous_response_id': request.previous_response_id, 'metadata': request.metadata,
        'reasoning': None, 'text': {'format': {'type': 'text'}}, 'max_output_tokens': None,
        'temperature': None, 'top_p': None, 'truncation': 'disabled',
        'usage': {'input_tokens': incoming, 'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0},
                  'output_tokens': outgoing, 'output_tokens_details': {'reasoning_tokens': count_text(reasoning)},
                  'total_tokens': incoming + outgoing} if status == 'completed' else None}
