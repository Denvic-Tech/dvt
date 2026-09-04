import sys
import time
import tracemalloc
import threading
import contextvars
import inspect
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, List

try:
    from src.logger import logger as default_logger
except ImportError:
    import logging

    logging.basicConfig(level=logging.INFO)
    default_logger = logging.getLogger("cascade_profiler")

try:
    import psutil  # опционально для настоящего RSS
except ImportError:
    psutil = None


# ────────────────────────────────────────────────────────────────────────────────
# Структуры данных
# ────────────────────────────────────────────────────────────────────────────────

@dataclass
class _CallRecord:
    module: str
    qualname: str
    depth: int
    start_wall_ns: int
    start_cpu_ns: int
    start_heap_bytes: int
    start_heap_peak: int
    start_rss_bytes: Optional[int] = None


@dataclass
class FunctionStats:
    module: str
    qualname: str
    count: int = 0
    total_wall_ns: int = 0
    total_cpu_ns: int = 0
    max_wall_ns: int = 0
    max_cpu_ns: int = 0
    total_heap_delta: int = 0  # суммарный чистый рост heap по tracemalloc
    max_heap_delta: int = 0
    total_rss_delta: int = 0  # суммарный чистый рост RSS (если psutil включён)
    max_rss_delta: int = 0

    def update(self, wall_ns: int, cpu_ns: int, heap_delta: int, rss_delta: int):
        self.count += 1
        self.total_wall_ns += wall_ns
        self.total_cpu_ns += cpu_ns
        self.max_wall_ns = max(self.max_wall_ns, wall_ns)
        self.max_cpu_ns = max(self.max_cpu_ns, cpu_ns)
        self.total_heap_delta += max(0, heap_delta)
        self.max_heap_delta = max(self.max_heap_delta, heap_delta)
        self.total_rss_delta += max(0, rss_delta)
        self.max_rss_delta = max(self.max_rss_delta, rss_delta)


# ────────────────────────────────────────────────────────────────────────────────
# Контекст-менеджер профилирования
# ────────────────────────────────────────────────────────────────────────────────

class CascadeProfiler:
    """
    Каскадный профилировщик вызовов внутри with-блока.
    - Фильтр по модулям: include_modules=('src.',), exclude_modules=()
    - Логи: log_calls=True (вход/выход), log_args=False (показать типы локалей)
    - Потоки: profile_threads=False (для новых потоков через threading.setprofile)
    - Память: tracemalloc (всегда), psutil RSS при use_psutil_rss=True
    """

    LOGGING_MODULE_PREFIXES = ("logging", "loguru", "src.logger")
    LOGGING_FILENAME_MARKERS = ("site-packages/loguru", "logging/__init__.py")

    def __init__(
            self,
            *,
            include_modules: Tuple[str, ...] = ("",),
            exclude_modules: Tuple[str, ...] = (),
            log_calls: bool = True,
            log_args: bool = False,
            profile_threads: bool = False,
            use_psutil_rss: bool = False,
            logger=default_logger,
            exclude_self: bool = True,
    ):
        self.include_modules = include_modules
        self.exclude_modules = exclude_modules
        self.log_calls = log_calls
        self.log_args = log_args
        self.profile_threads = profile_threads
        self.use_psutil_rss = use_psutil_rss and (psutil is not None)
        self.logger = logger

        self._calls: Dict[int, _CallRecord] = {}
        self._stats: Dict[Tuple[str, str], FunctionStats] = {}
        self._lock = threading.RLock()
        self._orig_prof = None
        self._orig_thread_prof = None
        self._had_tracemalloc = False
        self._proc = psutil.Process() if self.use_psutil_rss else None
        self._suspend: contextvars.ContextVar[bool] = contextvars.ContextVar("prof_suspended", default=False)
        self._depth_local = threading.local()
        self._depth_local.depth = 0
        self._self_module = __name__ if exclude_self else None

    # ── infra ───────────────────────────────────────────────────────────────────

    def __enter__(self):
        self._had_tracemalloc = tracemalloc.is_tracing()
        if not self._had_tracemalloc:
            tracemalloc.start()

        self._orig_prof = sys.getprofile()
        sys.setprofile(self._callback)

        if self.profile_threads:
            # В 3.10 это затронет только новые потоки; в 3.12+ есть *_all_threads
            self._orig_thread_prof = getattr(threading, "getprofile", lambda: None)()
            threading.setprofile(self._callback)

        return self

    def __exit__(self, exc_type, exc, tb):
        sys.setprofile(self._orig_prof)
        if self.profile_threads:
            threading.setprofile(self._orig_thread_prof)
        if not self._had_tracemalloc:
            tracemalloc.stop()

    # ── публичные методы ────────────────────────────────────────────────────────

    def results(self, sort_by: str = "total_wall_ns", top: Optional[int] = None) -> List[FunctionStats]:
        with self._lock:
            arr = list(self._stats.values())
        arr.sort(key=lambda s: getattr(s, sort_by), reverse=True)
        return arr[:top] if top is not None else arr

    def report(self, sort_by: str = "total_wall_ns", top: int = 50) -> str:
        header = f"{'Function':60} {'calls':>7} {'tot_wall[s]':>12} {'tot_cpu[s]':>10} {'max_wall[s]':>11} {'heapΔ[KB]':>9} {'rssΔ[KB]':>8}"
        lines = [header, "-" * len(header)]
        for st in self.results(sort_by=sort_by, top=top):
            func = f"{st.module}.{st.qualname}"
            lines.append(
                f"{func[:60]:60} {st.count:7d} "
                f"{st.total_wall_ns / 1e9:12.6f} {st.total_cpu_ns / 1e9:10.6f} "
                f"{st.max_wall_ns / 1e9:11.6f} {st.total_heap_delta / 1024:9.0f} {st.total_rss_delta / 1024:8.0f}"
            )
        return "\n".join(lines)

    # ── хелперы ─────────────────────────────────────────────────────────────────

    def _is_logging_frame(self, frame) -> bool:
        mod = frame.f_globals.get("__name__", "")
        if any(mod.startswith(p) for p in self.LOGGING_MODULE_PREFIXES):
            return True
        filename = frame.f_code.co_filename.replace("\\", "/")
        return any(marker in filename for marker in self.LOGGING_FILENAME_MARKERS)

    def _module_allowed(self, module: str, frame=None) -> bool:
        if frame is not None and self._is_logging_frame(frame):
            return False
        if self._self_module and module.startswith(self._self_module):
            return False
        if self.exclude_modules and any(module.startswith(p) for p in self.exclude_modules):
            return False
        if not self.include_modules:
            return True
        return any(module.startswith(p) for p in self.include_modules)

    @staticmethod
    def _qualname_from_frame(frame) -> str:
        name = frame.f_code.co_name
        if name == "<module>":
            return name
        cls = None
        if "self" in frame.f_locals:
            try:
                cls = frame.f_locals["self"].__class__.__name__
            except Exception:
                cls = None
        return f"{cls}.{name}" if cls else name

    # ── профильный коллбек ─────────────────────────────────────────────────────

    def _callback(self, frame, event, arg):
        # не реэнтримся (логгер тоже вызывает функции)
        if self._suspend.get():
            return

        module = frame.f_globals.get("__name__", "")
        if not self._module_allowed(module, frame):
            return

        token = self._suspend.set(True)
        try:
            if event == "call":

                qual = self._qualname_from_frame(frame)
                if qual == "<module>":
                    return

                # глубина стека (для красоты)
                try:
                    self._depth_local.depth += 1
                except Exception:
                    self._depth_local.depth = 1
                depth = self._depth_local.depth

                wall = time.perf_counter_ns()
                cpu = time.process_time_ns()
                current, peak = tracemalloc.get_traced_memory()
                rss = self._proc.memory_info().rss if self._proc else None

                with self._lock:
                    self._calls[id(frame)] = _CallRecord(
                        module=module,
                        qualname=qual,
                        depth=depth,
                        start_wall_ns=wall,
                        start_cpu_ns=cpu,
                        start_heap_bytes=current,
                        start_heap_peak=peak,
                        start_rss_bytes=rss,
                    )

                if self.log_calls:
                    if self.log_args:
                        # бережно показываем только типы первых локалей (чтобы не спамить гигантскими структурами)
                        try:
                            args_info = inspect.getargvalues(frame)
                            locals_preview = {k: type(v).__name__ for k, v in list(args_info.locals.items())[:5]}
                        except Exception:
                            locals_preview = {}
                        self.logger.debug(f"[CALL] {module}.{qual} depth={depth} locals~={locals_preview}")
                    else:
                        self.logger.debug(f"[CALL] {module}.{qual} depth={depth}")

            elif event in ("return", "exception"):
                key = id(frame)
                with self._lock:
                    rec = self._calls.pop(key, None)

                # уменьшаем глубину
                try:
                    self._depth_local.depth = max(0, self._depth_local.depth - 1)
                except Exception:
                    self._depth_local.depth = 0

                if rec is None:
                    return

                wall_end = time.perf_counter_ns()
                cpu_end = time.process_time_ns()
                current, peak = tracemalloc.get_traced_memory()
                rss_end = self._proc.memory_info().rss if self._proc else None

                wall_ns = wall_end - rec.start_wall_ns
                cpu_ns = cpu_end - rec.start_cpu_ns
                heap_delta = current - rec.start_heap_bytes
                rss_delta = (rss_end - rec.start_rss_bytes) if (
                            rss_end is not None and rec.start_rss_bytes is not None) else 0

                key_stats = (rec.module, rec.qualname)
                with self._lock:
                    st = self._stats.get(key_stats)
                    if st is None:
                        st = FunctionStats(module=rec.module, qualname=rec.qualname)
                        self._stats[key_stats] = st
                    st.update(wall_ns, cpu_ns, heap_delta, rss_delta)

                if self.log_calls:
                    if event == "exception":
                        exc_type = type(arg).__name__ if arg else "Exception"
                        self.logger.debug(
                            f"[EXC ] {rec.module}.{rec.qualname} wall={wall_ns / 1e9:.6f}s "
                            f"cpu={cpu_ns / 1e9:.6f}s heapΔ={heap_delta / 1024:.0f}KB rssΔ={rss_delta / 1024:.0f}KB -> {exc_type}"
                        )
                    else:
                        self.logger.debug(
                            f"[RET ] {rec.module}.{rec.qualname} wall={wall_ns / 1e9:.6f}s "
                            f"cpu={cpu_ns / 1e9:.6f}s heapΔ={heap_delta / 1024:.0f}KB rssΔ={rss_delta / 1024:.0f}KB"
                        )
        finally:
            try:
                self._suspend.reset(token)
            except Exception:
                pass
