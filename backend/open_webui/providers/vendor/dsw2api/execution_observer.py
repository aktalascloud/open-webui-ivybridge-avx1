"""Optional protocol-neutral timing; observations never own business resources."""
from contextlib import contextmanager
from dataclasses import dataclass
import time


@dataclass(frozen=True)
class Observation:
    stage: str
    elapsed_ms: float
    status: str
    counts: dict[str, int]


@contextmanager
def phase(observer, stage, *, clock=time.monotonic, **counts):
    started, status = clock(), 'completed'
    try:
        yield
    except BaseException as error:
        status = 'failed' if isinstance(error, Exception) else 'cancelled'
        raise
    finally:
        if observer is not None:
            try: observer(Observation(stage, (clock() - started) * 1000, status, counts))
            except Exception: pass
