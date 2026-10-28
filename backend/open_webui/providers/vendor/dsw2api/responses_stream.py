"""Responses SSE state machine, fed only protocol-neutral execution events."""
from copy import deepcopy
import json

from .responses_format import identifier, response_object


class ResponseStream:
    def __init__(self, request, response_id, model, prompt, created_at):
        self.request, self.id, self.model, self.prompt, self.created = request, response_id, model, prompt, created_at
        self.output, self.active, self.sequence = [], None, 0

    def emit(self, kind, **fields):
        event = {'type': kind, 'sequence_number': self.sequence, **deepcopy(fields)}
        self.sequence += 1
        return f'event: {kind}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n'

    def response(self, status='completed'):
        return response_object(self.request, self.id, self.model, self.output, self.prompt, status, self.created)

    def start(self):
        return [self.emit('response.created', response=self.response('in_progress')),
                self.emit('response.in_progress', response=self.response('in_progress'))]

    def close_active(self):
        if self.active is None: return []
        index = self.active; item = self.output[index]; kind = item['type']; item['status'] = 'completed'
        frames = []
        if kind in ('message', 'reasoning'):
            part = item['content'][0]
            event = 'response.output_text.done' if kind == 'message' else 'response.reasoning_text.done'
            fields = dict(item_id=item['id'], output_index=index, content_index=0, text=part['text'])
            if kind == 'message': fields['logprobs'] = []
            frames += [self.emit(event, **fields), self.emit('response.content_part.done', item_id=item['id'], output_index=index, content_index=0, part=part)]
        elif kind == 'function_call':
            frames.append(self.emit('response.function_call_arguments.done', item_id=item['id'], output_index=index, arguments=item['arguments']))
        frames.append(self.emit('response.output_item.done', output_index=index, item=item))
        self.active = None
        return frames

    def consume(self, event):
        kind = {'text': 'message', 'reasoning': 'reasoning', 'tool': 'function_call'}[event.kind]
        frames = []
        if self.active is None or self.output[self.active]['type'] != kind or kind == 'function_call':
            frames += self.close_active()
            item = {'id': identifier({'message':'msg', 'reasoning':'rs', 'function_call':'fc'}[kind]), 'type': kind, 'status': 'in_progress'}
            if kind == 'message':
                item.update(role='assistant', content=[])
            elif kind == 'reasoning': item.update(summary=[], content=[])
            else:
                item.update(call_id=event.call['id'], name=event.call['function']['name'], arguments='')
            self.active = len(self.output); self.output.append(item)
            frames.append(self.emit('response.output_item.added', output_index=self.active, item=item))
            if kind in ('message', 'reasoning'):
                part = {'type': 'output_text' if kind == 'message' else 'reasoning_text', 'text': ''}
                if kind == 'message': part.update(annotations=[], logprobs=[])
                item['content'].append(part)
                frames.append(self.emit('response.content_part.added', item_id=item['id'], output_index=self.active, content_index=0, part=part))
        item = self.output[self.active]
        if kind == 'function_call':
            item['arguments'] = event.call['function']['arguments']
            frames.append(self.emit('response.function_call_arguments.delta', item_id=item['id'], output_index=self.active, delta=item['arguments']))
            frames += self.close_active()
        else:
            item['content'][0]['text'] += event.text
            fields = dict(item_id=item['id'], output_index=self.active, content_index=0, delta=event.text)
            if kind == 'message': fields['logprobs'] = []
            frames.append(self.emit('response.output_text.delta' if kind == 'message' else 'response.reasoning_text.delta', **fields))
        return frames

    def fail(self, error):
        response = self.response('failed')
        response['error'] = error.stream_payload()
        return self.emit('response.failed', response=response)
