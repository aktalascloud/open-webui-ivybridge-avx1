"""Responses HTTP adapter. Runtime ownership is injected by the application."""
from contextlib import aclosing
import json
import time

from fastapi import APIRouter, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .chat_service import ChatService
from .chat_types import ChatEvent
from .chat_runtime import AccountStreamingResponse, iterate_upstream, prepare_account, thread_step
from .image_inputs import ImageLimits
from .responses_errors import ResponseError, classify_error, validation_error
from .responses_format import (ResponsesRequest, normalize_input, identifier, validate_calls,
                              output_items, history_output, response_object)
from .responses_stream import ResponseStream
from .responses_observability import RequestTrace
from .execution_observer import phase


public_error = classify_error


def create_responses_router(*, store, acquire, authenticate, scope, controls, model, mark_error, record):
    router = APIRouter()

    async def dispatch(request, operation, trace=None):
        try:
            headers = authenticate(request)
            return await operation(headers)
        except Exception as error:
            error = public_error(error)
            if trace is not None: trace.finish('failed',error.code)
            return JSONResponse(error.payload(), status_code=error.status)

    @router.get('/v1/responses/{response_id}')
    async def retrieve(response_id: str, request: Request):
        async def operation(headers):
            return JSONResponse(store().get(scope(request), response_id)['response'], headers=headers)
        return await dispatch(request, operation)

    @router.delete('/v1/responses/{response_id}')
    async def delete(response_id: str, request: Request):
        async def operation(headers):
            return JSONResponse(store().delete(scope(request), response_id), headers=headers)
        return await dispatch(request, operation)

    @router.post('/v1/responses')
    async def create(request: Request):
        trace = RequestTrace(identifier('req'))
        async def operation(headers):
            try: req = ResponsesRequest.model_validate(await request.json())
            except ValidationError as error: raise validation_error(error) from None
            except ValueError: raise ResponseError('Invalid JSON request', param='input') from None
            caller, memory = scope(request), store()
            with phase(trace.observe, 'history_replay'):
                parent = memory.get(caller, req.previous_response_id) if req.previous_response_id else None
                history = memory.history(caller, req.previous_response_id) if parent else []
                delta, attachments = await run_in_threadpool(normalize_input, req, history)
            messages = history + delta
            if len(json.dumps(messages, ensure_ascii=False).encode()) > memory.max_history_bytes:
                raise ResponseError('Response history exceeds the configured byte limit', 413)
            digests = [d for message in messages for d in message.get('_image_digests', [])]
            if len(digests) > ImageLimits.from_env().max_images:
                raise ResponseError('Too many images in reconstructed history; resend a shorter history', 413)
            prompt_messages = ([{'role':'system','content':req.instructions}] if req.instructions else []) + messages
            if req.tools and req.tool_choice != 'none':
                prompt_messages = [{'role':'system','content':
                    ('You may call multiple functions, at most 64. ' if req.parallel_tool_calls else 'Call at most one function. ')
                    + 'Function parameter JSON schemas:\n' + json.dumps(req.tools, ensure_ascii=False)}] + prompt_messages
            prompt = ChatService.build_prompt(prompt_messages, req.chat_tools(), req.chat_choice(), tool_result_limit=None)
            options = controls(req.model)
            def prepare(acquired):
                if parent:
                    if acquired.acct.id != parent['account_id'] or acquired.credential_fingerprint != parent['fingerprint']:
                        raise ResponseError('Response account credentials changed; resend complete input and images', 409, 'response_context_unavailable')
                    acquired.seed_image_files(parent['files'])
                return ChatService.prepare(acquired, prompt, attachments, thinking=options['thinking_enabled'],
                    model_type=options['model_type'], replay_digests=digests, observer=trace.observe)
            def acquire_observed():
                with phase(trace.observe, 'account_wait'): return acquire(parent)
            acquired, turn = await prepare_account(acquire_observed, prepare, mark_error)
            response_id, created, started = identifier('resp'), time.time(), time.monotonic()
            trace.bind(response_id)
            ready, names = {}, [t['name'] for t in req.tools]
            def save(response):
                if req.store:
                    with phase(trace.observe, 'storage', output_items=len(response['output'])):
                        memory.put(caller, response, req.previous_response_id, delta + history_output(response['output']),
                                   acquired.acct.id, acquired.credential_fingerprint, acquired.prepared_image_files)
            if not req.stream:
                try:
                    with phase(trace.observe, 'generation'):
                        result = await thread_step(ChatService.result, acquired, turn, options, names, ready)
                    validate_calls(req, result.calls)
                    response = response_object(req, response_id, model(), output_items(result), prompt, created_at=created)
                    save(response)
                    record((time.monotonic() - started) * 1000, True)
                    trace.finish('completed')
                    return JSONResponse(response, headers=headers)
                except Exception as error:
                    record((time.monotonic() - started) * 1000, False)
                    trace.finish('failed', classify_error(error).code)
                    raise
                finally:
                    acquired.release()
                    trace.finish('cancelled')
            async def events():
                wire, calls = ResponseStream(req, response_id, model(), prompt, created), []
                try:
                    for frame in wire.start(): yield frame
                    with phase(trace.observe, 'generation'):
                        async with aclosing(iterate_upstream(ChatService.events(acquired, turn, options, names, ready,
                                batch_tools=True, on_token=lambda:trace.first('first_upstream_event')))) as source:
                            async for event in source:
                                if event.kind == 'tools':
                                    calls.extend(event.calls)
                                    validate_calls(req, calls, complete=False)
                                    for call in event.calls:
                                        for frame in wire.consume(ChatEvent('tool', call=call)): yield frame
                                else:
                                    if event.kind == 'text': trace.first('first_output_text')
                                    for frame in wire.consume(event): yield frame
                    validate_calls(req, calls)
                    for frame in wire.close_active(): yield frame
                    response = wire.response()
                    save(response)
                    record((time.monotonic() - started) * 1000, True)
                    trace.finish('completed')
                    yield wire.emit('response.completed', response=response)
                except Exception as error:
                    record((time.monotonic() - started) * 1000, False)
                    trace.finish('failed', classify_error(error).code)
                    yield wire.fail(public_error(error))
                finally:
                    acquired.release()
                    trace.finish('cancelled')
            return AccountStreamingResponse(acquired, events(), media_type='text/event-stream',
                headers={'Cache-Control':'no-cache', **headers}, on_close=lambda:trace.finish('cancelled'))
        try:
            result = await dispatch(request, operation, trace)
            if not isinstance(result, AccountStreamingResponse):
                trace.finish('failed' if result.status_code >= 400 else 'completed')
            return result
        except BaseException:
            trace.finish('cancelled')
            raise

    return router
