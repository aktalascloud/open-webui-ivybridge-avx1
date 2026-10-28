"""Bounded request-local diagnostic projection with a field allowlist."""
import threading
import time

from .execution_observer import Observation
from .logger import get_logger

_STAGES = {'history_replay','account_wait','session_create','image_upload','image_processing',
           'generation','storage','first_upstream_event','first_output_text','request'}
_COUNTS = {'image_count','image_bytes','history_bytes','history_messages','call_count','output_items'}
_CODES = {'invalid_request_error','invalid_api_key','permission_denied','rate_limit_exceeded',
          'service_unavailable','server_error','image_parse_error','response_not_found','response_context_unavailable'}
_LOG = get_logger('responses')


class RequestTrace:
    def __init__(self, request_id, *, clock=time.monotonic, emit=None):
        self.id, self.clock, self.started = request_id, clock, clock()
        self.response_id, self.seen, self.done = None, set(), False
        self.lock = threading.RLock()
        self.emit = emit or (lambda row: _LOG.info('responses_execution', extra=row))

    def bind(self, response_id):
        with self.lock: self.response_id = response_id

    def observe(self, observation):
        with self.lock:
            if self.done or observation.stage not in _STAGES or observation.status not in ('completed','failed','cancelled'): return
            row = {'request_id':self.id, 'stage':observation.stage,
                   'elapsed_ms':round(max(0,observation.elapsed_ms),3), 'status':observation.status}
            if self.response_id: row['response_id'] = self.response_id
            row.update({k:v for k,v in observation.counts.items() if k in _COUNTS and type(v) is int and v >= 0})
            try: self.emit(row)
            except Exception: pass

    def first(self, stage):
        with self.lock:
            if stage in self.seen or stage not in ('first_upstream_event','first_output_text'): return
            self.seen.add(stage)
            self.observe(Observation(stage,(self.clock()-self.started)*1000,'completed',{}))

    def finish(self, status, code=None):
        with self.lock:
            if self.done: return
            if code is not None:
                # Code values are derived from our classifier, not exception text.
                safe_code = code if code in _CODES else 'server_error'
                observation = Observation('request',(self.clock()-self.started)*1000,status,{})
                original_emit = self.emit
                self.emit = lambda row: original_emit({**row,'error_code':safe_code})
                try: self.observe(observation)
                finally: self.emit = original_emit
            else: self.observe(Observation('request',(self.clock()-self.started)*1000,status,{}))
            self.done = True
