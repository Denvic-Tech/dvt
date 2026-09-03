from src.logger import logger

import config


def get_version_from_pyproject() -> str | None:
    """
    Получает версию проекта из файла 'pyproject.toml'.
    """
    import tomli

    try:
        with open(config.PROJECT.PYPROJECT_TOML, "rb") as f:
            data = tomli.load(f)
        version = data.get("project", {}).get("version")
        if version:
            return version
        else:
            logger.error("Версия не найдена в 'pyproject.toml'")
            return None
    except FileNotFoundError:
        logger.error("Файл 'pyproject.toml' не найден")
        return None
    except tomli.TOMLDecodeError as e:
        logger.error(f"Неверный формат 'pyproject.toml': {e}")
        return None
    except Exception as e:
        logger.error(f"Ошибка при чтении 'pyproject.toml': {e}")
        return None
