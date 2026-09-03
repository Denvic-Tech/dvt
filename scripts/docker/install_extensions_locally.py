"""
Устанавливает расширения из дистрибьютора локально для тестов.

Получает список расширений через API дистрибьютора, скачивает zip-архивы,
распаковывает и устанавливает Python-зависимости.

НЕ использует БД — чистая файловая система. Не импортирует src.* во избежание
циклических импортов.

Использование:
    python scripts/docker/install_extensions_locally.py
    python scripts/docker/install_extensions_locally.py -e "Bitrix24 Connector"
    python scripts/docker/install_extensions_locally.py --target-dir ./extensions --dvt-channel dev
"""

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

try:
    from scripts.docker.test_runner import PROJECT_DIR
except ModuleNotFoundError:
    from test_runner import PROJECT_DIR  # type: ignore[no-redef]

os.chdir(PROJECT_DIR)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Устанавливает расширения из дистрибьютора локально (без БД)."
    )
    parser.add_argument(
        "-e",
        "--extension",
        default=None,
        help="Имя конкретного расширения для установки (если не указано — все).",
    )
    parser.add_argument(
        "--distributor-url",
        default="https://extensions.distribution.denvic.tech",
        help="URL дистрибьютора расширений (по умолчанию 'https://extensions.distribution.denvic.tech').",
    )
    parser.add_argument(
        "--target-dir",
        default=None,
        help="Директория для установки (по умолчанию EXTENSIONS_VOLUME_PATH или ./extensions).",
    )
    parser.add_argument(
        "--dvt-version",
        default=None,
        help="Версия DVT для фильтрации совместимых расширений (по умолчанию из pyproject.toml).",
    )
    parser.add_argument(
        "--dvt-channel",
        default=None,
        choices=("dev", "prod"),
        help="Канал: dev (все версии) или prod (только stable). По умолчанию DVT_EXTENSION_CHANNEL или dev.",
    )
    parser.add_argument(
        "--extension-version",
        default=None,
        help="Конкретная версия расширения для установки (если не указана — latest compatible).",
    )
    parser.add_argument(
        "--no-deps",
        action="store_true",
        help="Не устанавливать Python-зависимости.",
    )
    parser.add_argument(
        "--deps-only",
        action="store_true",
        help="Только установить Python-зависимости для уже присутствующих расширений (без скачивания).",
    )
    return parser.parse_args(argv)


def resolve_distributor_url(cli_url: str | None) -> str:
    if cli_url:
        return cli_url
    url = os.getenv("EXTENSIONS_DISTRIBUTOR_URL")
    if not url:
        print(
            "Ошибка: не указан URL дистрибьютора (EXTENSIONS_DISTRIBUTOR_URL).",
            file=sys.stderr,
        )
        sys.exit(2)
    return url


def resolve_target_dir(cli_dir: str | None) -> Path:
    if cli_dir:
        return Path(cli_dir).resolve()
    return Path(os.getenv("EXTENSIONS_VOLUME_PATH", PROJECT_DIR / "extensions")).resolve()


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _encode_url(url: str) -> str:
    """Экранирует пробелы и спецсимволы в path-части URL."""
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/%")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def _http_download(url: str, dest: Path) -> None:
    req = urllib.request.Request(_encode_url(url))
    with urllib.request.urlopen(req, timeout=120) as resp:
        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > 200 * 1024 * 1024:
            raise ValueError("Archive too large (>200 MB)")
        downloaded = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
        print(f"    Скачано {downloaded / 1024 / 1024:.1f} MB")


def _get_dvt_version() -> str:
    """Читает версию DVT из pyproject.toml."""
    pyproject = PROJECT_DIR / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        version = (data.get("project") or {}).get("version")
        if version:
            return version
    except Exception:
        pass
    return "0.0.0"


def fetch_extension_list(
    distributor_url: str,
    dvt_version: str | None = None,
    dvt_channel: str | None = None,
) -> list[dict]:
    params = {}
    if dvt_version:
        params["dvt_version"] = dvt_version
    if dvt_channel:
        params["dvt_channel"] = dvt_channel
    list_url = distributor_url.rstrip("/") + "/extensions"
    if params:
        list_url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    payload = _http_get_json(list_url)
    if not isinstance(payload, dict):
        raise TypeError("Дистрибьютор вернул не JSON-объект")
    raw = payload.get("extensions")
    if not isinstance(raw, list):
        raise TypeError("Поле 'extensions' не является списком")
    return [e for e in raw if isinstance(e, dict)]


def fetch_extension_versions(
    distributor_url: str,
    name: str,
    dvt_version: str | None = None,
    dvt_channel: str | None = None,
) -> list[dict]:
    params = {}
    if dvt_version:
        params["dvt_version"] = dvt_version
    if dvt_channel:
        params["dvt_channel"] = dvt_channel
    versions_url = distributor_url.rstrip("/") + f"/extensions/{urllib.parse.quote(name, safe='')}/versions"
    if params:
        versions_url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    payload = _http_get_json(versions_url)
    if not isinstance(payload, dict):
        raise TypeError(f"Дистрибьютор вернул не JSON-объект для '{name}'")
    raw = payload.get("versions")
    if not isinstance(raw, list):
        raise TypeError(f"Поле 'versions' не является списком для '{name}'")
    return [v for v in raw if isinstance(v, dict)]


def resolve_download_url(
    distributor_url: str,
    name: str,
    dvt_version: str | None,
    dvt_channel: str | None,
    requested_version: str | None,
    latest_compatible_version: str | None,
) -> str | None:
    """Получает download_url через /extensions/{name}/versions."""
    versions = fetch_extension_versions(distributor_url, name, dvt_version, dvt_channel)
    if not versions:
        return None

    if requested_version:
        target = next((v for v in versions if v.get("version") == requested_version), None)
        if target is None:
            print(
                f"    Версия '{requested_version}' не найдена для '{name}'.",
                file=sys.stderr,
            )
            return None
    elif latest_compatible_version:
        target = next(
            (v for v in versions if v.get("version") == latest_compatible_version), None
        )
        if target is None:
            target = versions[0]
    else:
        target = versions[0]

    return target.get("download_url") if target else None


# ── Установка одного расширения (без src.*) ──────────────────────────────

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


def _extract_zip(zf: zipfile.ZipFile, target: Path) -> Path:
    """Распаковывает zip с защитой от zip-slip, возвращает реальный корень."""
    for member in zf.infolist():
        member_path = target / member.filename
        if not str(member_path.resolve()).startswith(str(target.resolve())):
            raise ValueError(f"Unsafe archive content: {member.filename}")
    zf.extractall(target)
    items = list(target.iterdir())
    if len(items) == 1 and items[0].is_dir():
        return items[0]
    return target


def _run_pip(requirements: list[str]) -> None:
    print(f"    pip install {' '.join(requirements)}")
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *requirements],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(stderr or "pip install failed")
    print("    pip install OK")


def _load_dependencies(install_root: Path) -> list[str]:
    """Читает [project].dependencies из pyproject.toml."""
    pyproject = install_root / "pyproject.toml"
    if not pyproject.exists():
        return []
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    deps = (data.get("project") or {}).get("dependencies") or []
    if not isinstance(deps, list):
        return []
    return [d for d in deps if isinstance(d, str) and d.strip()]


def install_one(download_url: str, install_root: Path, *, install_deps: bool = True) -> None:
    """Скачивает и распаковывает одно расширение в install_root."""
    if install_root.exists():
        _remove_readonly(install_root)

    install_root.parent.mkdir(parents=True, exist_ok=True)

    tmp_zip: Path | None = None
    try:
        tmp_fd, tmp_name = tempfile.mkstemp(suffix=".zip")
        os.close(tmp_fd)
        tmp_zip = Path(tmp_name)
        _http_download(download_url, tmp_zip)

        with tempfile.TemporaryDirectory(prefix="ext-install-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            with zipfile.ZipFile(tmp_zip, "r") as zf:
                source = _extract_zip(zf, tmp_path)
            shutil.move(str(source), str(install_root))
    finally:
        if tmp_zip and tmp_zip.exists():
            try:
                tmp_zip.unlink(missing_ok=True)
            except Exception:
                pass

    if install_deps:
        requirements = _load_dependencies(install_root)
        if requirements:
            _run_pip(requirements)


def install_deps_only(target_dir: Path, extension_name: str | None = None) -> None:
    """Устанавливает только Python-зависимости для уже присутствующих расширений."""
    if not target_dir.is_dir():
        print(f"Директория не существует: {target_dir}")
        return

    if extension_name:
        entries = [target_dir / extension_name]
        if not entries[0].is_dir():
            print(f"Расширение '{extension_name}' не найдено в {target_dir}.", file=sys.stderr)
            sys.exit(1)
    else:
        entries = sorted(e for e in target_dir.iterdir() if e.is_dir())

    if not entries:
        print(f"Нет расширений в {target_dir}.")
        return

    print(f"Устанавливаю зависимости для {len(entries)} расширений ...")
    for idx, install_root in enumerate(entries, 1):
        name = install_root.name
        print(f"  [{idx}/{len(entries)}] {name} ...")
        try:
            requirements = _load_dependencies(install_root)
            if requirements:
                _run_pip(requirements)
            else:
                print("    Нет зависимостей.")
        except Exception as exc:
            print(f"  [{idx}/{len(entries)}] {name}: ОШИБКА — {exc}", file=sys.stderr)
            continue


# ── main ──────────────────────────────────────────────────────────────────

def run(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    target_dir = resolve_target_dir(args.target_dir)

    if args.deps_only:
        install_deps_only(target_dir, args.extension)
        print("Готово.")
        return

    target_dir.mkdir(parents=True, exist_ok=True)
    distributor_url = resolve_distributor_url(args.distributor_url)

    dvt_version = args.dvt_version or _get_dvt_version()
    dvt_channel = args.dvt_channel or os.getenv("DVT_EXTENSION_CHANNEL", "dev")

    print(f"Запрашиваю список расширений с {distributor_url} ...")
    print(f"  dvt_version={dvt_version}, dvt_channel={dvt_channel}")
    try:
        all_extensions = fetch_extension_list(
            distributor_url, dvt_version=dvt_version, dvt_channel=dvt_channel
        )
    except Exception as exc:
        print(f"Ошибка при запросе к дистрибьютору: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.extension:
        all_extensions = [e for e in all_extensions if e.get("name") == args.extension]
        if not all_extensions:
            print(f"Расширение '{args.extension}' не найдено в дистрибьюторе.", file=sys.stderr)
            sys.exit(1)

    print(f"Найдено расширений для установки: {len(all_extensions)}")

    for idx, item in enumerate(all_extensions, 1):
        name = item.get("name", f"unknown-{idx}")
        latest_compat = item.get("latest_compatible_version")

        download_url = resolve_download_url(
            distributor_url,
            name,
            dvt_version=dvt_version,
            dvt_channel=dvt_channel,
            requested_version=args.extension_version,
            latest_compatible_version=latest_compat,
        )

        if not download_url:
            print(f"  [{idx}/{len(all_extensions)}] {name}: пропущено (нет download_url)")
            continue

        install_root = target_dir / name
        print(f"  [{idx}/{len(all_extensions)}] Устанавливаю {name}")
        print(f"    URL: {download_url}")
        print(f"    Путь: {install_root}")

        try:
            install_one(download_url, install_root, install_deps=not args.no_deps)
            print(f"  [{idx}/{len(all_extensions)}] {name}: OK")
        except Exception as exc:
            print(f"  [{idx}/{len(all_extensions)}] {name}: ОШИБКА — {exc}", file=sys.stderr)
            try:
                if install_root.exists():
                    _remove_readonly(install_root)
            except Exception:
                pass
            continue

    print("Готово.")


if __name__ == "__main__":
    run()
