import os
import socket
import uuid
from functools import lru_cache

_INTERNAL_WORKER_ID_ENV = "_DVT_TASK_WORKER_ID"


def initialize_worker_id() -> str:
    """Create an ID for one task-worker main process.

    The value is deliberately overwritten on every worker start: it is an
    internal, process-scoped identity rather than user configuration. Celery
    child processes inherit it from their parent through the environment.
    """
    worker_id = f"task-worker-{socket.gethostname()}-{uuid.uuid4().hex}"
    os.environ[_INTERNAL_WORKER_ID_ENV] = worker_id
    get_worker_id.cache_clear()
    return worker_id


@lru_cache(maxsize=1)
def get_worker_id() -> str:
    return os.getenv(_INTERNAL_WORKER_ID_ENV, f"task-worker-{socket.gethostname()}")
