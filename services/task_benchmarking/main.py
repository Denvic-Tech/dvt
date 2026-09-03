from __future__ import annotations

try:
    import psutil  # noqa: F401
except ImportError as exc:
    raise SystemExit("psutil is required. Install dependencies for task_benchmarking.") from exc

from .cli import parse_args
from .patching import run_safe_compare, run_with_patches
from .runner import run_benchmark_once, run_matrix_benchmark


def main() -> int:

    options = parse_args()
    if options.matrix:
        return run_matrix_benchmark(options)
    if options.compare_candidate_python:
        return run_safe_compare(options)
    if options.validate_only or options.dry_run:
        return run_benchmark_once(options)
    if options.run_once or not options.patches:
        return run_benchmark_once(options)
    return run_with_patches(options)


if __name__ == "__main__":
    raise SystemExit(main())
