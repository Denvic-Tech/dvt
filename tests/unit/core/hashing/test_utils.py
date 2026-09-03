import numpy as np
import pandas as pd
import pytest

from core.hashing.hasher import _new_hasher
from core.hashing.utils import _finalize, _to_bytes_fast, _update_many


def test_new_hasher_digest_length():
    hasher = _new_hasher()
    hasher.update(b"payload")
    digest = _finalize(hasher)

    assert isinstance(digest, bytes)
    assert len(digest) == 32


def test_to_bytes_fast_handles_common_types():
    ts = pd.Timestamp("2024-01-01T12:00:00")
    dt64 = np.datetime64("2024-01-01")

    assert _to_bytes_fast("text") == b"text"
    assert _to_bytes_fast(b"data") == b"data"
    assert _to_bytes_fast(bytearray(b"data")) == b"data"
    assert _to_bytes_fast(memoryview(b"data")) == b"data"
    assert _to_bytes_fast(ts).startswith(b"2024-01-01")
    assert _to_bytes_fast(dt64).startswith(b"2024-01-01")


def test_to_bytes_fast_raises_for_unserializable():
    class Unserializable:
        pass

    with pytest.raises(TypeError) as exc_info:
        _to_bytes_fast(Unserializable())

    message = str(exc_info.value)
    assert "obj:" in message
    assert "Unserializable" in message


def test_update_many_accumulates_bytes():
    hasher = _new_hasher()
    _update_many(hasher, [b"alpha", b"beta"])
    digest = _finalize(hasher)

    hasher_manual = _new_hasher()
    hasher_manual.update(b"alpha")
    hasher_manual.update(b"beta")
    digest_manual = _finalize(hasher_manual)

    assert digest == digest_manual
