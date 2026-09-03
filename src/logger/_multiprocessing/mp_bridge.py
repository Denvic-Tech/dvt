import traceback
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

MP_LOG_BRIDGE_EXTRA_KEY = "_from_mp_bridge"


@dataclass
class MpLogRecord:
    time_iso: str
    level: str
    message: str
    name: str
    module: str
    function: str
    line: int
    extra: Dict[str, Any]
    exception: Optional[str] = None
    exception_type: Optional[str] = None
    exception_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _safe_extra(d: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in d.items():
        try:
            if isinstance(v, (str, int, float, bool)) or v is None:
                out[k] = v
            elif isinstance(v, (list, dict, tuple)):
                out[k] = str(v)
            else:
                out[k] = str(v)
        except Exception:
            out[k] = "<unserializable>"
    return out


def reduce_loguru_message(message) -> MpLogRecord:
    r = message.record
    exc = r.get("exception")
    extra = _safe_extra(r.get("extra", {}))
    exception_type = None
    exception_text = None

    if extra.get("traceback_str"):
        exception_text = str(extra["traceback_str"])
    elif exc:
        try:
            exception_type = exc.type.__name__ if exc.type else None
            exception_text = "".join(traceback.format_exception(exc.type, exc.value, exc.traceback))
        except Exception:
            exception_text = str(exc)

    return MpLogRecord(
        time_iso=r["time"].isoformat(),
        level=r["level"].name,
        message=r["message"],
        name=r["name"],
        module=r["module"],
        function=r["function"],
        line=r["line"],
        extra=extra,
        exception=str(exc) if exc else None,
        exception_type=exception_type,
        exception_text=exception_text,
    )
