"""Shared cancellation-safe worker and response lifetimes."""
import asyncio
import threading
from contextvars import ContextVar
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse
from .image_inputs import ImageError

REQUEST_CANCEL = ContextVar('owui_dsw_request_cancel', default=None)


async def prepare_account(acquire, prepare_turn, mark_error, runner=run_in_threadpool):
    # Raw Task.cancel can interrupt an await while its worker keeps running.
    # The worker owns cleanup until it atomically hands off a finished result.
    lock = threading.Lock()
    cancelled = REQUEST_CANCEL.get() or threading.Event()
    completed = []
    def prepare():
        acquired = None
        handed_off = False
        context = REQUEST_CANCEL.set(cancelled)
        try:
            if cancelled.is_set(): raise asyncio.CancelledError()
            acquired = acquire()
            if cancelled.is_set():
                return None
            turn = prepare_turn(acquired)
            with lock:
                if not cancelled.is_set():
                    completed.append(acquired)
                    handed_off = True
            return acquired, turn
        except Exception as error:
            if acquired is not None and not isinstance(error, ImageError):
                mark_error(acquired, error)
            raise
        finally:
            try:
                if acquired is not None and not handed_off: acquired.release()
            finally: REQUEST_CANCEL.reset(context)
    try:
        return await runner(prepare)
    except BaseException:
        with lock:
            cancelled.set()
            owned = completed.pop() if completed else None
        if owned is not None:
            owned.release()
        raise


async def thread_step(function, *args):
    """A cancelled reader must drain its in-flight thread before cleanup."""
    worker = asyncio.create_task(run_in_threadpool(function, *args))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not worker.cancelled():
            worker.exception()  # retrieve a failure while preserving cancellation
        raise


async def iterate_upstream(iterator):
    end = object()
    try:
        while True:
            token = await thread_step(next, iterator, end)
            if token is end:
                break
            yield token
    finally:
        close = getattr(iterator, 'close', None)
        if close is not None:
            await thread_step(close)


class AccountStreamingResponse(StreamingResponse):
    """Release even if the response is cancelled before its generator starts."""
    def __init__(self, acquired, *args, on_close=None, **kwargs):
        self.acquired = acquired
        self.on_close = on_close
        super().__init__(*args, **kwargs)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                close = getattr(self.body_iterator, 'aclose', None)
                if close is not None:
                    await close()
            finally:
                self.acquired.release()
                if self.on_close is not None:
                    try: self.on_close()
                    except Exception: pass
