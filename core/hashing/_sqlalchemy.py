from sqlalchemy import Engine

from .hasher import _new_hasher
from .utils import _update_many, _to_bytes_fast, _finalize


def _get_sa_engine_hash(engine: Engine) -> bytes:
    hasher = _new_hasher()

    url_str = engine.url.render_as_string(hide_password=False)

    payload = {
        "url": url_str,
        "dialect": getattr(engine.dialect, "name", None),
        "driver": getattr(engine.dialect, "driver", None),
        "pool": engine.pool.__class__.__name__ if getattr(engine, "pool", None) else None,
        "exec_opts": dict(getattr(engine, "_execution_options", {}) or {}),
    }
    _update_many(hasher, [_to_bytes_fast(payload)])
    return _finalize(hasher)
