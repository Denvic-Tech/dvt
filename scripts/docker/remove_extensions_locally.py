"""
Удаляет расширения из локальной файловой системы.

НЕ использует БД — чистая файловая система. Не импортирует src.* во избежание
циклических импортов.

Использование:
    python scripts/docker/remove_extensions_locally.py
    python scripts/docker/remove_extensions_locally.py -e "Bitrix24 Connector"
    python scripts/docker/remove_extensions_locally.py --target-dir ./extensions
"""

import argparse
import os
import shutil
import stat
import sys
from pathlib import Path

try:
    from scripts.docker.test_runner import PROJECT_DIR
except ModuleNotFoundError:
    from test_runner import PROJECT_DIR  # type: ignore[no-redef]

os.chdir(PROJECT_DIR)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Удаляет расширения из локальной файловой системы (без БД)."
    )
    parser.add_argument(
        "-e",
        "--extension",
        default=None,
        help="Имя конкретного расширения для удаления (если не указано — все).",
    )
    parser.add_argument(
        "--target-dir",
        default=None,
        help="Директория с расширениями (по умолчанию EXTENSIONS_VOLUME_PATH или ./extensions).",
    )
    return parser.parse_args(argv)


def resolve_target_dir(cli_dir: str | None) -> Path:
    if cli_dir:
        return Path(cli_dir).resolve()
    return Path(os.getenv("EXTENSIONS_VOLUME_PATH", PROJECT_DIR / "extensions")).resolve()


def _remove_readonly(path: Path) -> None:
    """Удаляет директорию, снимая readonly-флаги при необходимости."""

    def _on_error(func, exc_path, exc_info):
        err = exc_info[1] if isinstance(exc_info, tuple) else exc_info
        if not isinstance(err, PermissionError):
            raise err
        p = Path(exc_path)
        if not p.exists():
            raise err
        os.chmod(p, os.stat(p).st_mode | stat.S_IWRITE)
        func(exc_path)

    shutil.rmtree(path, onerror=_on_error)


def remove_one(install_root: Path) -> None:
    """Удаляет одно расширение."""
    if not install_root.exists():
        print(f"    Пропущено (не существует): {install_root}")
        return
    _remove_readonly(install_root)
    print(f"    Удалено: {install_root}")


def run_main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    target_dir = resolve_target_dir(args.target_dir)

    if not target_dir.is_dir():
        print(f"Директория не существует: {target_dir}")
        return

    if args.extension:
        install_root = target_dir / args.extension
        if not install_root.is_dir():
            print(f"Расширение '{args.extension}' не найдено в {target_dir}.", file=sys.stderr)
            sys.exit(1)
        print(f"Удаляю {args.extension} ...")
        remove_one(install_root)
    else:
        entries = sorted(e for e in target_dir.iterdir() if e.is_dir())
        if not entries:
            print(f"Нет расширений в {target_dir}.")
            return

        print(f"Найдено расширений для удаления: {len(entries)}")
        for idx, entry in enumerate(entries, 1):
            print(f"  [{idx}/{len(entries)}] Удаляю {entry.name} ...")
            try:
                remove_one(entry)
                print(f"  [{idx}/{len(entries)}] {entry.name}: OK")
            except Exception as exc:
                print(f"  [{idx}/{len(entries)}] {entry.name}: ОШИБКА — {exc}", file=sys.stderr)

    print("Готово.")


if __name__ == "__main__":
    run_main()
