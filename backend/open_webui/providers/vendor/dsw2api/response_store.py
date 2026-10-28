"""Bounded caller-scoped immutable response deltas; no images or credentials."""

from . import managed_env

from collections import OrderedDict
import json
import os
import threading
import time

from .responses_errors import ResponseError


def setting(name, default):
    try: return max(1, int(managed_env.get(name, default)))
    except ValueError: return default


class ResponseStore:
    def __init__(self, ttl=None, max_records=None, max_bytes=None, per_caller=None,
                 max_depth=None, max_history_bytes=None, clock=time.monotonic):
        self.ttl = ttl if ttl is not None else setting('RESPONSES_TTL', 1800)
        self.max_records = max_records if max_records is not None else setting('RESPONSES_MAX_RECORDS', 1000)
        self.max_bytes = max_bytes if max_bytes is not None else setting('RESPONSES_MAX_BYTES', 32 * 1024 * 1024)
        self.per_caller = per_caller if per_caller is not None else setting('RESPONSES_PER_CALLER', 100)
        self.max_depth = max_depth if max_depth is not None else setting('RESPONSES_MAX_DEPTH', 128)
        self.max_history_bytes = max_history_bytes if max_history_bytes is not None else setting('RESPONSES_MAX_HISTORY_BYTES', 4 * 1024 * 1024)
        self.clock, self._lock = clock, threading.RLock()
        self._records, self._bytes = OrderedDict(), 0

    def _remove(self, key):
        record = self._records.pop(key)
        self._bytes -= len(record[1])

    def _sweep(self):
        now = self.clock()
        for key, (expires, _) in list(self._records.items()):
            if expires <= now: self._remove(key)

    def get(self, scope, response_id):
        with self._lock:
            self._sweep()
            item = self._records.get((scope, response_id))
            if item is None:
                raise ResponseError('Response not found, expired, deleted or not accessible', 404, 'response_not_found', 'previous_response_id')
            return json.loads(item[1])

    def put(self, scope, response, parent, delta, account_id, fingerprint, files):
        if response.get('status') != 'completed':
            raise ResponseError('Only completed responses can be stored')
        value = {'response': response, 'parent': parent, 'delta': delta, 'account_id': account_id,
                 'fingerprint': fingerprint, 'files': files}
        raw = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
        delta_bytes = len(json.dumps(delta, ensure_ascii=False).encode())
        if len(raw) > self.max_bytes:
            raise ResponseError('Response exceeds the configured storage byte limit', 413)
        with self._lock:
            self._sweep()
            self.history(scope, parent, extra_depth=1, extra_bytes=delta_bytes)
            key = (scope, response['id'])
            if key in self._records: raise ResponseError('Response IDs are immutable', 409)
            owned = [k for k in self._records if k[0] == scope]
            while len(owned) >= self.per_caller:
                self._remove(owned.pop(0))
            while self._records and (len(self._records) >= self.max_records or self._bytes + len(raw) > self.max_bytes):
                self._remove(next(iter(self._records)))
            # Never publish a child whose parent was evicted to make room.
            if parent:
                try: self.history(scope, parent, extra_depth=1, extra_bytes=delta_bytes)
                except ResponseError:
                    raise ResponseError('Parent history evicted by storage limits; resend complete input', 409, 'response_context_unavailable') from None
            self._records[key] = (self.clock() + self.ttl, raw)
            self._bytes += len(raw)

    def history(self, scope, response_id, *, extra_depth=0, extra_bytes=0):
        with self._lock:
            chain, seen, size = [], set(), extra_bytes
            if size > self.max_history_bytes or extra_depth > self.max_depth:
                raise ResponseError('Response history exceeds configured limits', 413)
            while response_id:
                if response_id in seen or len(chain) + extra_depth >= self.max_depth:
                    raise ResponseError('Response history exceeds the configured depth', 413)
                seen.add(response_id)
                record = self.get(scope, response_id)
                delta = record['delta']
                size += len(json.dumps(delta, ensure_ascii=False).encode())
                if size > self.max_history_bytes:
                    raise ResponseError('Response history exceeds the configured byte limit', 413)
                chain.append(delta); response_id = record['parent']
            return [m for part in reversed(chain) for m in part]

    def delete(self, scope, response_id):
        with self._lock:
            self.get(scope, response_id)
            self._remove((scope, response_id))
        return {'id': response_id, 'object': 'response', 'deleted': True}
